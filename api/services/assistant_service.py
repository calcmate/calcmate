"""api/services/assistant_service.py — AI Assistant(운영비서) HTTP 서비스
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-ASSISTANT-02).

dashboard.py "🤖 AI Assistant" 탭(L2892-2998) 이관. 기능은 modules.ai_assistant를 그대로
재사용한다(CHAT_MODELS / chat / propose_diff / write_file / create_file / list_directory /
read_file / memory / tasks). Streamlit(로컬·무인증)에서 HTTP로 옮기면서 생기는 위험만 이
계층에서 막는다:

- 경로: modules.ai_assistant._safe()(루트 안이면 무엇이든 허용)를 HTTP에서 그대로 쓰지
  않는다. resolve_safe_path()가 절대/UNC/드라이브/ADS/.. 경로, 심볼릭 링크·정션을 통한 루트
  탈출, 민감 경로(.git, .env*, *.env, config/secrets.yaml, *secret*/*credential*/*token*,
  data/assistant/backups/**)를 요청 경로와 실제(resolve) 경로 모두에서 거부한다.
- 쓰기: preview가 준 old_sha256을 승인 요청에 다시 받아 서버가 현재 파일과 대조한다
  (클라이언트 diff/내용을 신뢰하지 않음). 덮어쓰기 백업은 기존 write_file()이 서버 고정
  경로(data/assistant/backups/)에 만든다 — 클라이언트는 백업 경로를 지정할 수 없다.
- AI context: _context_for()(키워드 시 config/config.yaml 전체 첨부)를 쓰지 않고, 파일 통계·
  최근 ERROR(민감 패턴 마스킹)·허용된 코드 파일·공개 설정 allowlist만 담은 safe context를 쓴다.
- 오류: provider 예외 원문(키/경로/스택)을 응답에 넣지 않고 고정 문구로 바꾼다.
- 대화 기록은 서버에 저장하지 않는다(요청마다 최근 10개만 사용).
"""
import hashlib
import logging
import os
import re
from pathlib import Path, PurePosixPath

from modules.config_loader import load_config

LOG = logging.getLogger(__name__)

READ_LIMIT = 8000            # dashboard.py st.code(AS.read_file(rf, 8000))
PREVIEW_OLD_LIMIT = 3000     # dashboard.py st.code(diff["old"][:3000])
MAX_MESSAGES = 10            # modules.ai_assistant.chat: messages[-10:]
MAX_CONTENT_CHARS = 200_000
QUICK_QUESTIONS = ["현재 프로젝트 분석해", "App Factory 분석해", "문제점 찾아", "개선안 제안해"]

_FORBIDDEN_PARTS = ("secret", "credential", "token")
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|AIza[0-9A-Za-z_\-]{10,}"
    r"|xox[abp]-[A-Za-z0-9\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b)")
# 공개 설정 allowlist — "config" 언급 시 config.yaml 전체 대신 이 키만 context에 넣는다.
PUBLIC_CONFIG_KEYS = ("SITE_URL", "SITE_NAME", "RUN_MODE", "ADSENSE_MODE", "DAILY_POST_COUNT",
                      "DAILY_AI_BUDGET", "MONTHLY_AI_BUDGET")
# _context_for()의 키워드 → 참고 파일(config.yaml 제외, 코드/템플릿만)
_CONTEXT_FILES = [("app factory", "modules/app_factory.py"), ("app_factory", "modules/app_factory.py"),
                  ("reviewer", "modules/calculator_reviewer.py"),
                  ("template", "templates/calculators/calculator_v1.html")]


class AssistantPathError(ValueError):
    """허용되지 않는 경로(고정 문구만 노출)."""


class AssistantStateError(ValueError):
    """파일/메모리/태스크 상태가 요청과 맞지 않음."""


class AssistantAIError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _AS():
    from modules import ai_assistant
    return ai_assistant


def _root() -> Path:
    return Path(_AS().ROOT).resolve()


# ── 경로 안전 계층 ─────────────────────────────────────────────────────────
def _forbidden_rel(rel_posix: str) -> bool:
    parts = [p for p in rel_posix.lower().split("/") if p]
    if not parts:
        return False
    if ".git" in parts:
        return True
    if rel_posix.lower() == "config/secrets.yaml":
        return True
    if parts[:3] == ["data", "assistant", "backups"]:
        return True
    for p in parts:
        if p == ".env" or p.startswith(".env.") or p.endswith(".env"):
            return True
        if any(word in p for word in _FORBIDDEN_PARTS):
            return True
    return False


def resolve_safe_path(rel: str, *, allow_root: bool = False) -> tuple:
    """요청 경로 → (실제 Path, 루트 기준 posix 상대경로). 거부 시 AssistantPathError."""
    raw = "" if rel is None else str(rel)
    s = raw.strip()
    if not s or s != raw or "\0" in s:
        if not (allow_root and s in ("", ".")):
            raise AssistantPathError("허용되지 않는 경로입니다.")
    if s.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", s) or ":" in s or os.path.isabs(s):
        raise AssistantPathError("허용되지 않는 경로입니다.")   # 절대/UNC/드라이브/ADS
    req_parts = [p for p in re.split(r"[\\/]+", s) if p not in ("", ".")]
    if any(p == ".." for p in req_parts):
        raise AssistantPathError("허용되지 않는 경로입니다.")
    req_posix = "/".join(req_parts)
    if not req_parts and not allow_root:
        raise AssistantPathError("허용되지 않는 경로입니다.")
    if _forbidden_rel(req_posix):
        raise AssistantPathError("접근이 제한된 경로입니다.")

    root = _root()
    try:
        real = (root / Path(*req_parts)).resolve() if req_parts else root
    except (OSError, RuntimeError):
        raise AssistantPathError("허용되지 않는 경로입니다.") from None
    if real != root and root not in real.parents:
        raise AssistantPathError("허용되지 않는 경로입니다.")   # 심볼릭 링크/정션 탈출
    real_posix = PurePosixPath(*real.relative_to(root).parts).as_posix() if real != root else ""
    if _forbidden_rel(real_posix):
        raise AssistantPathError("접근이 제한된 경로입니다.")
    return real, (real_posix or ".")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redact(text: str) -> str:
    return _SECRET_VALUE_RE.sub("[REDACTED]", text or "")


# ── 파일 ───────────────────────────────────────────────────────────────────
def list_files(rel: str = ".") -> dict:
    real, rel_posix = resolve_safe_path(rel, allow_root=True)
    if not real.exists():
        return {"path": rel_posix, "items": []}
    if not real.is_dir():
        raise AssistantStateError("디렉터리가 아닙니다.")
    items = []
    for it in _AS().list_directory(rel_posix):
        if _forbidden_rel(it["path"]):
            continue
        try:
            resolve_safe_path(it["path"])
        except AssistantPathError:
            continue
        items.append({"name": it["name"], "type": it["type"], "path": it["path"]})
    return {"path": rel_posix, "items": items}


def read_file(rel: str) -> dict:
    real, rel_posix = resolve_safe_path(rel)
    if not real.is_file():
        raise AssistantStateError("파일을 찾을 수 없습니다.")
    content = _AS().read_file(rel_posix, READ_LIMIT)
    return {"path": rel_posix, "content": content, "truncated": real.stat().st_size > len(content.encode("utf-8"))}


def preview_file(rel: str, content: str) -> dict:
    real, rel_posix = resolve_safe_path(rel)
    if real.exists() and not real.is_file():
        raise AssistantStateError("파일이 아닙니다.")
    d = _AS().propose_diff(rel_posix, content)
    return {"path": rel_posix, "exists": d["exists"], "old": d["old"][:PREVIEW_OLD_LIMIT],
            "old_len": d["old_len"], "new_len": d["new_len"],
            "old_sha256": _sha256(d["old"]) if d["exists"] else None}


def write_file(rel: str, content: str, expected_old_sha256: str) -> dict:
    """기존 파일 덮어쓰기(승인 후). 서버가 경로·존재·현재 내용(sha)을 다시 확인한다."""
    real, rel_posix = resolve_safe_path(rel)
    if not real.is_file():
        raise AssistantStateError("기존 파일이 없습니다 — 신규 생성을 사용하세요.")
    current = real.read_text(encoding="utf-8", errors="replace")
    if not expected_old_sha256 or _sha256(current) != expected_old_sha256:
        raise AssistantStateError("미리보기 이후 파일이 변경되었습니다. 다시 미리보기 하세요.")
    resolve_safe_path(rel_posix)                      # 쓰기 직전 재검증
    _AS().write_file(rel_posix, content)               # 원본 백업(서버 고정 경로) 후 저장
    return {"path": rel_posix, "written": True, "backed_up": True, "new_len": len(content)}


def create_file(rel: str, content: str) -> dict:
    """신규 생성(승인 후). 이미 있으면 거부 — 생성 직전 다시 확인(create_file도 재확인)."""
    real, rel_posix = resolve_safe_path(rel)
    if real.exists():
        raise AssistantStateError("이미 존재하는 파일입니다 — 덮어쓰기를 사용하세요.")
    resolve_safe_path(rel_posix)
    if real.exists():
        raise AssistantStateError("이미 존재하는 파일입니다 — 덮어쓰기를 사용하세요.")
    try:
        _AS().create_file(rel_posix, content)
    except FileExistsError:
        raise AssistantStateError("이미 존재하는 파일입니다 — 덮어쓰기를 사용하세요.") from None
    return {"path": rel_posix, "created": True, "new_len": len(content)}


# ── Memory / Task (저장 경로는 modules.ai_assistant 고정 경로) ───────────────
MEMORY_KINDS = ("rules", "todo", "dev_log")


def get_memory() -> dict:
    mem = _AS().load_memory()
    return {k: list(mem.get(k, [])) for k in MEMORY_KINDS}


def add_memory(kind: str, text: str) -> dict:
    if kind not in MEMORY_KINDS:
        raise AssistantStateError("허용되지 않는 메모리 종류입니다.")
    if not (text or "").strip():
        raise AssistantStateError("내용을 입력하세요.")
    _AS().add_memory(kind, text)
    return get_memory()


def get_tasks() -> dict:
    return {"tasks": _AS().load_tasks(), "statuses": list(_AS().TASK_STATUS)}


def add_task(title: str) -> dict:
    if not (title or "").strip():
        raise AssistantStateError("태스크 제목을 입력하세요.")
    return {"task": _AS().add_task(title), **get_tasks()}


def set_task_status(task_id: str, status: str) -> dict:
    if status not in _AS().TASK_STATUS:
        raise AssistantStateError("허용되지 않는 상태입니다.")
    if not any(t.get("id") == task_id for t in _AS().load_tasks()):
        raise AssistantStateError("태스크를 찾을 수 없습니다.")
    _AS().set_task_status(task_id, status)
    return get_tasks()


# ── Chat ───────────────────────────────────────────────────────────────────
def list_models() -> dict:
    models = [{"label": k, "provider": v[0], "model": v[1]} for k, v in _AS().CHAT_MODELS.items()]
    return {"models": models, "default": models[0]["label"] if models else None,
            "quick_questions": list(QUICK_QUESTIONS)}


def build_safe_context(last_user: str) -> str:
    """_context_for()의 안전판: 파일 통계 + 최근 ERROR(마스킹) + 키워드 코드 파일 + 공개 설정."""
    a = _AS().analyze_project()
    errors = "\n".join(_redact(l) for l in a.get("recent_errors", [])[-3:])
    ctx = f"[프로젝트 구조] 파일 {a['total_files']} · 디렉터리 {a['by_dir']}\n[최근 오류]\n{errors}"
    low = (last_user or "").lower()
    for kw, rel in _CONTEXT_FILES:
        if kw in low:
            try:
                real, rel_posix = resolve_safe_path(rel)
                if real.is_file():
                    ctx += f"\n\n[참고 파일 {rel_posix}]\n{_redact(_AS().read_file(rel_posix, 6000))}"
            except Exception:
                pass
            break
    if "config" in low:
        cfg = load_config()
        pub = {k: cfg.get(k) for k in PUBLIC_CONFIG_KEYS if cfg.get(k) not in (None, "")}
        ctx += "\n\n[공개 설정(allowlist)]\n" + "\n".join(f"{k}: {v}" for k, v in pub.items())
    return ctx


def chat(model_label: str, messages: list) -> dict:
    AS = _AS()
    if model_label not in AS.CHAT_MODELS:
        raise AssistantStateError("허용되지 않는 모델입니다.")
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages][-MAX_MESSAGES:]
    if not msgs or msgs[-1]["role"] != "user" or not msgs[-1]["content"].strip():
        raise AssistantStateError("질문을 입력하세요.")
    try:
        ctx = build_safe_context(msgs[-1]["content"])
    except Exception as e:
        LOG.warning("assistant context 생성 실패: %s", type(e).__name__)
        ctx = ""
    cfg = load_config()
    try:
        reply, model, tokens = AS.chat(cfg, model_label, msgs, context=ctx)
    except KeyError:
        LOG.warning("assistant provider 설정 누락(model=%s)", model_label)
        raise AssistantAIError("AI_NOT_CONFIGURED", "AI 제공자 설정(API 키)이 없습니다. 설정에서 확인하세요.") from None
    except Exception as e:
        LOG.warning("assistant provider 오류(model=%s): %s", model_label, type(e).__name__)
        raise AssistantAIError("AI_REQUEST_FAILED", "AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.") from None
    return {"reply": reply or "", "model": model, "tokens": int(tokens or 0)}
