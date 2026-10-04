# -*- coding: utf-8 -*-
"""
modules/ai_assistant.py — AI 운영비서 (v12 Lite, 신규)

대시보드 'AI Assistant' 탭의 백엔드. 채팅으로 프로젝트를 분석·개선·수정한다.

원칙:
- 파일 접근은 프로젝트 워크스페이스 내부로 한정(루트/OS 경로 escape 금지).
- 허용: read_file / write_file / create_file / list_directory / search_files
- 금지: delete_file / delete_directory / system command (구현하지 않음)
- 쓰기(write/create)는 UI에서 변경내용 표시 + 사용자 승인 후에만 호출(승인 게이트는 대시보드).
- write 시 원본 자동 백업(data/assistant/backups/).
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .ai_provider import build_provider
from .logger import get_logger

LOG = get_logger()
ROOT = Path(__file__).resolve().parent.parent
SKIP = (".venv", "__pycache__", ".git")
READ_EXT = {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".html", ".css", ".js", ".bat"}

# 채팅 모델 (CEO=GPT / 편집장=Claude / 실무팀=Gemini)
CHAT_MODELS = {
    "GPT (CEO/전략)":   ("openai", "gpt-4o"),
    "Claude (편집장/코드)": ("claude", "claude-sonnet-4-6"),
    "Gemini (실무팀/분석)": ("gemini", "gemini-2.5-flash"),
}

_ASSIST_DIR = ROOT / "data" / "assistant"


# ── 경로 안전장치 ─────────────────────────────────────────────────
def _safe(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError(f"워크스페이스 밖 경로 접근 금지: {rel}")
    return p


# ── 파일 시스템 (워크스페이스 한정) ───────────────────────────────
def list_directory(rel: str = ".") -> list:
    base = _safe(rel)
    if not base.exists():
        return []
    out = []
    for p in sorted(base.iterdir()):
        if p.name in SKIP:
            continue
        out.append({"name": p.name, "type": "dir" if p.is_dir() else "file",
                    "path": str(p.relative_to(ROOT)).replace("\\", "/")})
    return out


def read_file(rel: str, limit: int = 40000) -> str:
    p = _safe(rel)
    if not p.exists() or p.is_dir():
        raise FileNotFoundError(rel)
    return p.read_text(encoding="utf-8", errors="replace")[:limit]


def search_files(query: str, exts: set = None, max_hits: int = 50) -> list:
    """파일명/내용 검색. [{path, line, text}] (내용 매칭은 일부 라인만)."""
    exts = exts or READ_EXT
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(s in p.parts for s in SKIP) or p.suffix.lower() not in exts:
            continue
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if query.lower() in p.name.lower():
            hits.append({"path": rel, "line": 0, "text": "(파일명 매칭)"})
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query in line:
                    hits.append({"path": rel, "line": i, "text": line.strip()[:160]})
                    if len(hits) >= max_hits:
                        return hits
        except Exception:
            continue
        if len(hits) >= max_hits:
            break
    return hits


def _backup(p: Path):
    bk = _ASSIST_DIR / "backups"
    bk.mkdir(parents=True, exist_ok=True)
    if p.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(str(p), str(bk / f"{p.name}.{stamp}.bak"))


def create_file(rel: str, content: str) -> str:
    """신규 파일 생성(이미 있으면 거부). 승인 후 호출."""
    p = _safe(rel)
    if p.exists():
        raise FileExistsError(f"이미 존재: {rel} (write_file 사용)")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    LOG.info("[assistant] 파일 생성: %s", rel)
    return str(p)


def write_file(rel: str, content: str) -> str:
    """기존 파일 덮어쓰기(원본 백업). 승인 후 호출."""
    p = _safe(rel)
    _backup(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    LOG.info("[assistant] 파일 수정(백업됨): %s", rel)
    return str(p)


def propose_diff(rel: str, new_content: str) -> dict:
    """승인 UI용: 변경 예정 내용 + 기존 내용 미리보기."""
    p = _safe(rel)
    old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    return {"path": rel, "exists": p.exists(), "old": old, "new": new_content,
            "old_len": len(old), "new_len": len(new_content)}


# ── 메모리 (프로젝트 운영 규칙/TODO/개발기록) ─────────────────────
def _mem_path() -> Path:
    _ASSIST_DIR.mkdir(parents=True, exist_ok=True)
    return _ASSIST_DIR / "memory.json"


def load_memory() -> dict:
    p = _mem_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"rules": [], "todo": [], "dev_log": []}


def save_memory(mem: dict):
    _mem_path().write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def add_memory(kind: str, text: str):
    """kind: rules|todo|dev_log"""
    mem = load_memory()
    mem.setdefault(kind, []).append({"text": text, "at": datetime.now().isoformat()})
    save_memory(mem)


# ── 태스크 (Lite: 상태만) ─────────────────────────────────────────
TASK_STATUS = ["Pending", "Running", "Completed", "Failed"]


def _task_path() -> Path:
    _ASSIST_DIR.mkdir(parents=True, exist_ok=True)
    return _ASSIST_DIR / "tasks.json"


def load_tasks() -> list:
    p = _task_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def add_task(title: str) -> dict:
    tasks = load_tasks()
    t = {"id": datetime.now().strftime("%Y%m%d%H%M%S"), "title": title, "status": "Pending"}
    tasks.append(t)
    _task_path().write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    return t


def set_task_status(task_id: str, status: str):
    if status not in TASK_STATUS:
        return
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = status
    _task_path().write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 프로젝트 분석기 ───────────────────────────────────────────────
def analyze_project() -> dict:
    from collections import Counter
    files, by_ext, by_dir = [], Counter(), Counter()
    for p in ROOT.rglob("*"):
        if p.is_file() and not any(s in p.parts for s in SKIP) and p.suffix.lower() in READ_EXT:
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            files.append(rel)
            by_ext[p.suffix.lower()] += 1
            by_dir[rel.split("/")[0] if "/" in rel else "(root)"] += 1
    log = ROOT / "data" / "logs" / "pipeline.log"
    errors = []
    if log.exists():
        try:
            errors = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines()
                      if "[ERROR]" in l][-5:]
        except Exception:
            pass
    return {"total_files": len(files), "by_ext": dict(by_ext), "by_dir": dict(by_dir),
            "recent_errors": errors, "files": files}


def _context_for(target: str) -> str:
    """채팅 명령에 프로젝트/대상 컨텍스트 자동 주입."""
    a = analyze_project()
    ctx = (f"[프로젝트 구조] 파일 {a['total_files']} · 디렉터리 {a['by_dir']}\n"
           f"[최근 오류]\n" + "\n".join(a["recent_errors"][-3:]))
    # 특정 파일/모듈 언급 시 내용 일부 첨부
    for kw, rel in [("app factory", "modules/app_factory.py"), ("app_factory", "modules/app_factory.py"),
                    ("config", "config/config.yaml"), ("reviewer", "modules/calculator_reviewer.py"),
                    ("template", "templates/calculators/calculator_v1.html")]:
        if kw in target.lower():
            try:
                ctx += f"\n\n[참고 파일 {rel}]\n{read_file(rel, 6000)}"
            except Exception:
                pass
            break
    return ctx


# ── 채팅 ──────────────────────────────────────────────────────────
def chat(cfg: dict, model_label: str, messages: list, attach_context: bool = True,
         context: str = None) -> tuple:
    """context를 주면(HTTP API의 안전 context) _context_for() 대신 그 문자열을 쓴다.
    주지 않으면 기존 동작 그대로(dashboard.py 호출부 무변경)."""
    provider_name, model = CHAT_MODELS.get(model_label, CHAT_MODELS["GPT (CEO/전략)"])
    provider = build_provider(provider_name, cfg)
    system = ("너는 SalaryMate 운영비서다. 프로젝트 분석/코드 분석/파일 수정 제안/전략 토론/개선 제안을 한다. "
              "한국어로 간결·정확하게. 파일 수정을 제안할 때는 대상 경로와 전체 새 내용을 명확히 제시하라. "
              "직접 삭제/시스템 명령은 제안하지 마라.")
    last_user = messages[-1]["content"] if messages else ""
    if context is not None:
        ctx = context
    else:
        ctx = _context_for(last_user) if attach_context else ""
    convo = (f"[컨텍스트]\n{ctx}\n\n" if ctx else "") + \
            "\n".join(f"[{m['role']}] {m['content']}" for m in messages[-10:])
    text, tokens = provider.chat(system, convo, model, max_tokens=2500)
    try:
        from .logger import BudgetTracker
        BudgetTracker(cfg).record(model, tokens)
    except Exception:
        pass
    return text, model, tokens
