"""api/services/workspace_service.py — AI Workspace HTTP 서비스
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-WORKSPACE-02).

dashboard.py "💬 AI Workspace" 탭(L2788-2858) 이관. 기능은 modules.ai_workspace를 그대로
호출한다(chat → ai_roles.make_provider → build_provider → provider.chat → BudgetTracker,
list_project_files / read_project_file / query_repo / analyze_structure /
write_workspace_file / write_project_file). modules/ai_workspace.py는 수정하지 않는다.

HTTP 경계에서만 강화한다:
- 경로: AI Assistant에서 검증한 assistant_service.resolve_safe_path(절대/UNC/드라이브/ADS/..,
  심볼릭 링크·정션 탈출, .git/.env*/*.env/config/secrets.yaml/*secret*/*credential*/*token*)를
  그대로 재사용하고(중복 구현 없음), 여기서 *api_key*/*apikey*, 서버 백업 폴더
  (data/workspace/backups/**, data/assistant/backups/**) 차단과 배포 영역
  data/workspace/_site/** 쓰기 금지만 더한다.
- context: 클라이언트가 보낸 context 문자열은 받지 않는다 — 선택값(파일/저장소/구조)으로 서버가
  만든다. 민감 파일 선택은 AI 호출 전에 거부하고, 저장소 행은 민감 컬럼을 서버에서 제거한다.
  첨부 실패 원문은 AI에 보내지 않는다(고정 placeholder). 최종 context는 8000자로 자른다.
- 프로젝트 파일 저장: 원본의 "확인 체크 → 즉시 덮어쓰기"를 preview → 승인 → 서버 SHA 재검증
  → 백업(data/workspace/backups/, write_project_file 기존 경로) → 쓰기로 강화한다.
- 샌드박스 저장: 원본 이름 정리 규칙 + 경로 검사, 기존 파일은 덮어쓰기 확인 + 백업 후에만.
- 오류: 예외 원문 대신 고정 코드/문구.
"""
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from modules.config_loader import load_config
from api.services import assistant_service as _A

LOG = logging.getLogger(__name__)

ROLES = (("orchestrator", "총괄 (GPT)"), ("code", "코드 (Claude)"), ("research", "리서치 (Gemini)"))
REPOS = ("sites", "calculators", "articles", "templates")
MAX_MESSAGES = 12            # modules.ai_workspace.chat: messages[-12:]
CONTEXT_LIMIT = 8000         # modules.ai_workspace.chat: context[:8000]
REPO_ROWS = 20               # dashboard.py: query_repo(...)[:20]
PREVIEW_OLD_LIMIT = 3000
MAX_CONTENT_CHARS = 200_000
CONTEXT_FAILED = "(컨텍스트 일부를 불러오지 못했습니다)"

_EXTRA_FORBIDDEN = ("api_key", "apikey")
_SERVER_BACKUP_DIRS = ("data/workspace/backups", "data/assistant/backups")
_SITE_DIR = "data/workspace/_site"
_SENSITIVE_COLUMN_WORDS = ("password", "passwd", "token", "secret", "api_key", "apikey", "credential",
                           "authorization", "private_key", "access_key")


class WorkspaceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _WS():
    from modules import ai_workspace
    return ai_workspace


def _not_allowed():
    return WorkspaceError("FILE_NOT_ALLOWED", "접근이 허용되지 않는 경로입니다.")


def _under(rel: str, base: str) -> bool:
    return rel == base or rel.startswith(base + "/")


def resolve_ws_path(rel: str, *, allow_root: bool = False, for_write: bool = False) -> tuple:
    """assistant_service.resolve_safe_path + Workspace 추가 규칙. 거부 시 FILE_NOT_ALLOWED."""
    try:
        real, rel_posix = _A.resolve_safe_path(rel, allow_root=allow_root)
    except _A.AssistantPathError:
        raise _not_allowed() from None
    low_req = re.sub(r"[\\/]+", "/", str(rel or "")).lower()
    low = rel_posix.lower()
    for s in (low_req, low):
        if any(w in part for part in s.split("/") for w in _EXTRA_FORBIDDEN):
            raise _not_allowed()
    if any(_under(low, d) for d in _SERVER_BACKUP_DIRS):
        raise _not_allowed()
    if for_write and _under(low, _SITE_DIR):
        raise _not_allowed()
    return real, rel_posix


def _allowed(rel: str) -> bool:
    try:
        resolve_ws_path(rel)
        return True
    except WorkspaceError:
        return False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 역할 / 컨텍스트 선택지 ───────────────────────────────────────────────────
def list_roles() -> dict:
    from modules.ai_roles import get_role
    cfg = load_config()
    out = []
    for rid, label in ROLES:
        provider, model = get_role(cfg, rid)
        out.append({"id": rid, "label": label, "provider": provider, "model": model})
    return {"roles": out, "default": ROLES[0][0], "repos": list(REPOS)}


def list_context_files() -> dict:
    """원본 '프로젝트 파일(읽기)' 선택지 — 민감/차단 경로는 목록에서 제외."""
    return {"files": [f for f in _WS().list_project_files() if _allowed(f)]}


def _filter_row(row) -> dict:
    if not isinstance(row, dict):
        return row
    out = {}
    for k, v in row.items():
        lk = str(k).lower().replace("-", "_")
        if any(w in lk for w in _SENSITIVE_COLUMN_WORDS) or lk.endswith("_key"):
            continue
        out[k] = v
    return out


def build_context(file: str = None, repo: str = None, structure: bool = False) -> str:
    """선택값으로 서버가 context를 만든다(dashboard.py L2812-2821과 같은 순서/형식)."""
    WS = _WS()
    ctx = ""
    if file:
        real, rel_posix = resolve_ws_path(file)          # 민감 파일이면 여기서 거부(AI 호출 전)
        try:
            if not real.is_file():
                raise FileNotFoundError
            ctx += f"# 파일: {rel_posix}\n{WS.read_project_file(rel_posix)}\n\n"
        except Exception as e:
            LOG.warning("workspace 파일 첨부 실패: %s", type(e).__name__)
            ctx += CONTEXT_FAILED + "\n\n"
    if repo:
        if repo not in REPOS:
            raise WorkspaceError("VALIDATION_ERROR", "허용되지 않는 데이터 종류입니다.")
        try:
            rows = [_filter_row(r) for r in (WS.query_repo(load_config(), repo) or [])[:REPO_ROWS]]
            ctx += f"# {repo} 데이터(최대 {REPO_ROWS}행)\n{str(rows)}\n\n"
        except Exception as e:
            LOG.warning("workspace 저장소 첨부 실패(%s): %s", repo, type(e).__name__)
            ctx += CONTEXT_FAILED + "\n\n"
    if structure:
        try:
            ctx += f"# 프로젝트 구조\n{WS.analyze_structure()['by_dir']}\n\n"
        except Exception as e:
            LOG.warning("workspace 구조 첨부 실패: %s", type(e).__name__)
            ctx += CONTEXT_FAILED + "\n\n"
    return ctx[:CONTEXT_LIMIT]


def chat(role: str, messages: list, file: str = None, repo: str = None, structure: bool = False) -> dict:
    if role not in dict(ROLES):
        raise WorkspaceError("VALIDATION_ERROR", "허용되지 않는 역할입니다.")
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages][-MAX_MESSAGES:]
    if not msgs or msgs[-1]["role"] != "user" or not msgs[-1]["content"].strip():
        raise WorkspaceError("VALIDATION_ERROR", "메시지를 입력하세요.")
    ctx = build_context(file, repo, structure)
    cfg = load_config()
    try:
        reply, model, tokens = _WS().chat(cfg, role, msgs, ctx)
    except KeyError:
        LOG.warning("workspace provider 설정 누락(role=%s)", role)
        raise WorkspaceError("AI_NOT_CONFIGURED", "AI 제공자 설정(API 키)이 없습니다. 설정에서 확인하세요.") from None
    except Exception as e:
        LOG.warning("workspace provider 오류(role=%s): %s", role, type(e).__name__)
        raise WorkspaceError("AI_REQUEST_FAILED", "AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.") from None
    return {"reply": reply or "", "model": model, "tokens": int(tokens or 0)}


# ── 저장 ───────────────────────────────────────────────────────────────────
def _backup(real: Path) -> str:
    """write_project_file()과 같은 서버 고정 백업 경로/이름 규칙(data/workspace/backups/<name>.<stamp>.bak)."""
    bk = Path(_WS()._root()) / "data" / "workspace" / "backups"
    bk.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    (bk / f"{real.name}.{stamp}.bak").write_text(real.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return f"data/workspace/backups/{real.name}.{stamp}.bak"


def save_sandbox(name: str, content: str, overwrite: bool = False) -> dict:
    """원본 '샌드박스 저장'(data/workspace/<정리된 이름>). 기존 파일은 overwrite 확인 + 백업 후에만."""
    if not (content or "").strip():
        raise WorkspaceError("VALIDATION_ERROR", "내용이 비어 있습니다.")
    safe = re.sub(r"[^0-9a-zA-Z._가-힣-]", "_", name or "") or "file.txt"   # write_workspace_file과 같은 규칙
    if safe.strip(".") == "":
        raise _not_allowed()
    real, rel_posix = resolve_ws_path(f"data/workspace/{safe}", for_write=True)
    if real.exists() and not real.is_file():
        raise _not_allowed()
    backup = None
    if real.exists():
        if not overwrite:
            raise WorkspaceError("FILE_CONFLICT", "같은 이름의 파일이 있습니다. 덮어쓰기를 확인하세요.")
        backup = _backup(real)
    try:
        _WS().write_workspace_file(safe, content)
    except Exception as e:
        LOG.warning("workspace 샌드박스 저장 실패: %s", type(e).__name__)
        raise WorkspaceError("FILE_WRITE_FAILED", "파일을 저장하지 못했습니다.") from None
    return {"path": rel_posix, "saved": True, "overwritten": backup is not None, "backup": backup}


def preview_project_file(rel: str, content: str) -> dict:
    real, rel_posix = resolve_ws_path(rel, for_write=True)
    if real.exists() and not real.is_file():
        raise _not_allowed()
    old = real.read_text(encoding="utf-8", errors="replace") if real.exists() else ""
    return {"path": rel_posix, "exists": real.exists(), "old": old[:PREVIEW_OLD_LIMIT], "old_len": len(old),
            "new_len": len(content), "old_sha256": _sha256(old) if real.exists() else None}


def write_project_file(rel: str, content: str, expected_old_sha256: str) -> dict:
    """승인 후 덮어쓰기. 서버가 경로·존재·현재 SHA를 다시 확인하고, 기존 write_project_file()이 백업 후 쓴다."""
    if not (content or "").strip():
        raise WorkspaceError("VALIDATION_ERROR", "내용이 비어 있습니다.")
    real, rel_posix = resolve_ws_path(rel, for_write=True)
    if not real.is_file():
        raise WorkspaceError("FILE_CONFLICT", "기존 파일이 없습니다 — 신규 생성을 사용하세요.")
    if _sha256(real.read_text(encoding="utf-8", errors="replace")) != expected_old_sha256:
        raise WorkspaceError("FILE_CONFLICT", "미리보기 이후 파일이 변경되었습니다. 다시 미리보기 하세요.")
    resolve_ws_path(rel_posix, for_write=True)
    try:
        _WS().write_project_file(rel_posix, content)     # 원본 백업(data/workspace/backups/) 후 저장
    except Exception as e:
        LOG.warning("workspace 프로젝트 파일 저장 실패: %s", type(e).__name__)
        raise WorkspaceError("FILE_WRITE_FAILED", "파일을 저장하지 못했습니다.") from None
    return {"path": rel_posix, "written": True, "backed_up": True, "new_len": len(content)}


def create_project_file(rel: str, content: str) -> dict:
    """승인 후 신규 생성. 이미 있으면 거부 — 마지막 단계는 배타적 생성('x')으로 경쟁 상태도 거부."""
    if not (content or "").strip():
        raise WorkspaceError("VALIDATION_ERROR", "내용이 비어 있습니다.")
    real, rel_posix = resolve_ws_path(rel, for_write=True)
    if real.exists():
        raise WorkspaceError("FILE_CONFLICT", "이미 존재하는 파일입니다 — 덮어쓰기를 사용하세요.")
    resolve_ws_path(rel_posix, for_write=True)
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
        resolve_ws_path(rel_posix, for_write=True)       # 상위 폴더 생성 후 재확인(링크 교체 대비)
        with open(real, "x", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        raise WorkspaceError("FILE_CONFLICT", "이미 존재하는 파일입니다 — 덮어쓰기를 사용하세요.") from None
    except WorkspaceError:
        raise
    except Exception as e:
        LOG.warning("workspace 프로젝트 파일 생성 실패: %s", type(e).__name__)
        raise WorkspaceError("FILE_WRITE_FAILED", "파일을 저장하지 못했습니다.") from None
    LOG.info("workspace 프로젝트 파일 생성: %s", rel_posix)
    return {"path": rel_posix, "created": True, "new_len": len(content)}
