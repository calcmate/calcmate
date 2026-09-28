"""api/services/log_service.py — 로그/파이프라인 상태 조회 서비스 (STEP 18-G).

전부 읽기 전용. dashboard.py의 "⚠️ 오류 로그" / "📡 실시간 로그" / Recent Activity 패널과
동일한 데이터 소스(로그 파일 tail, modules.dashboard_cache 경유 logs/articles 테이블,
modules.pipeline_status)를 그대로 사용한다. 로그 파일은 "rb" 모드로만 열며
쓰기/삭제/rotate를 수행하지 않는다.
"""
import re
from pathlib import Path

from modules.config_loader import load_config
from modules.dashboard_cache import read as cache_read

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PIPELINE_LOG = _PROJECT_ROOT / "data" / "logs" / "pipeline.log"

# ── 민감정보 마스킹(§17) ─────────────────────────────────────────────
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{6,}"), lambda m: "sk-****" + m.group(0)[-4:]),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"), "Bearer ****"),
    (re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[=:]\s*\S+"),
     lambda m: f"{m.group(1)}=****"),
    (re.compile(r"(?i)authorization\s*:\s*\S+"), "Authorization: ****"),
]


def mask_secrets(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _mask_row(row: dict) -> dict:
    return {k: (mask_secrets(v) if isinstance(v, str) else v) for k, v in row.items()}


def _tail_lines(path: Path, n: int = 300, blk: int = 65536) -> list:
    """dashboard.py::_tail_lines()와 동일한 방식 — 파일 끝부분 바이트만 읽기(read-only)."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - blk))
            data = f.read()
        return data.decode("utf-8", "replace").splitlines()[-n:]
    except Exception:
        return []


def get_error_logs(limit: int = 20) -> dict:
    """dashboard.py '⚠️ 오류 로그' 탭(dashboard.py:745-791)과 동일한 필터."""
    cfg = load_config()
    logs_rows = cache_read(cfg, "logs")
    errors = [r for r in logs_rows
              if "오류" in str(r.get("가동결과", "")) or str(r.get("실패모듈", "")).strip()]
    errors = errors[-limit:][::-1]

    articles_rows = cache_read(cfg, "articles")
    calc_fails = [r for r in articles_rows if str(r.get("상태값", "")).strip() == "품질보류"]
    calc_fails = calc_fails[-limit:][::-1]

    return {
        "operation_errors": [_mask_row(r) for r in errors],
        "calculator_quality_holds": [_mask_row(r) for r in calc_fails],
        "total": len(errors) + len(calc_fails),
    }


def get_recent_logs(limit: int = 20) -> dict:
    """dashboard.py render_recent_activity()(dashboard.py:480-487)와 동일: pipeline.log 최근 N줄(최신 우선)."""
    lines = _tail_lines(_PIPELINE_LOG, limit)[::-1]
    return {"lines": [mask_secrets(l) for l in lines]}


_LEVEL_SETS = {
    "all": {"error", "warn", "info", "other"},
    "error": {"error"},
    "warn_error": {"error", "warn"},
    "info": {"info"},
}


def _classify(line: str) -> str:
    if "[ERROR]" in line:
        return "error"
    if "[WARN" in line:
        return "warn"
    if "[INFO]" in line:
        return "info"
    return "other"


def get_live_logs(level: str = "all", limit: int = 300) -> dict:
    """dashboard.py '📡 실시간 로그' 탭(dashboard.py:3480-3562)과 동일한 분류/필터.
    WebSocket/SSE는 사용하지 않는다 — 매 호출마다 파일을 다시 읽어 재조회한다."""
    want = _LEVEL_SETS.get(level, _LEVEL_SETS["all"])
    lines = _tail_lines(_PIPELINE_LOG, limit)
    counts = {"error": 0, "warn": 0, "info": 0}
    for line in lines:
        lv = _classify(line)
        if lv in counts:
            counts[lv] += 1
    entries = [{"line": mask_secrets(l), "level": _classify(l)} for l in lines if _classify(l) in want]
    return {"entries": entries, "counts": counts}


def get_pipeline_status() -> dict:
    """modules.pipeline_status.get_pipeline_state()를 그대로 호출(재구현하지 않음)."""
    from modules.pipeline_status import get_pipeline_state
    cfg = load_config()
    state = dict(get_pipeline_state(cfg))
    state["last_lines"] = [mask_secrets(l) for l in state.get("last_lines", [])]
    return state
