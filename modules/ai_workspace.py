# -*- coding: utf-8 -*-
"""
modules/ai_workspace.py — 대시보드 내 AI 작업공간 (v12.0)

채팅 + 안전한 프로젝트 파일 도구 + Repository/시트 조회.
- 파일 읽기/구조분석/Repository 조회: 자유
- 파일 생성: 샌드박스(data/workspace/) 기본
- 프로젝트 파일 수정: 원본 백업(data/workspace/backups/) 후 덮어쓰기 — UI에서 명시 확인 필요
모든 데이터 접근은 Repository/Adapter 경유(gspread/Drive 직접 호출 없음).
"""
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from adapters.db.factory import get_db_adapter, get_template_storage_adapter, get_calculator_storage_adapter
from .ai_roles import make_provider
from .logger import get_logger, BudgetTracker

LOG = get_logger()

SAFE_EXT = {".py", ".md", ".yaml", ".yml", ".bat", ".txt", ".json"}
SKIP_PARTS = (".venv", "__pycache__", ".git")


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


# ── 채팅 ──────────────────────────────────────────────────────────
def chat(cfg: dict, role: str, messages: list, context: str = "") -> tuple:
    """역할(총괄/코드/리서치) 모델로 응답. messages=[{role,content},...]"""
    provider, model = make_provider(cfg, role)
    system = ("너는 SalaryMate 운영센터의 AI 어시스턴트다. 한국어로 간결·정확하게 답한다. "
              "코드를 요청받으면 실행 가능한 완성 코드를 제공한다.")
    convo = ""
    if context:
        convo += f"[참고 컨텍스트]\n{context[:8000]}\n\n"
    convo += "\n".join(f"[{m['role']}] {m['content']}" for m in messages[-12:])
    text, tokens = provider.chat(system, convo, model, max_tokens=2500)
    try:
        BudgetTracker(cfg).record(model, tokens)
    except Exception as _e:
        LOG.warning("토큰 비용 기록/조회 실패: %s", _e)
    return text, model, tokens


# ── 파일 도구 ─────────────────────────────────────────────────────
def list_project_files() -> list:
    root = _root()
    out = []
    for p in root.rglob("*"):
        if p.is_file() and not any(s in p.parts for s in SKIP_PARTS):
            if p.suffix.lower() in SAFE_EXT:
                out.append(str(p.relative_to(root)).replace("\\", "/"))
    return sorted(out)


def read_project_file(rel_path: str, limit: int = 20000) -> str:
    root = _root()
    p = (root / rel_path).resolve()
    if root != p and root not in p.parents:
        raise ValueError("프로젝트 밖 경로는 읽을 수 없습니다.")
    if not p.exists():
        raise FileNotFoundError(rel_path)
    return p.read_text(encoding="utf-8", errors="replace")[:limit]


def write_workspace_file(name: str, content: str) -> str:
    ws = _root() / "data" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9a-zA-Z._가-힣-]", "_", name) or "file.txt"
    p = ws / safe
    p.write_text(content, encoding="utf-8")
    LOG.info("workspace 파일 생성: %s", p)
    return str(p)


def write_project_file(rel_path: str, content: str) -> str:
    """프로젝트 파일 덮어쓰기(원본 자동 백업). UI에서 명시 확인 후 호출."""
    root = _root()
    p = (root / rel_path).resolve()
    if root not in p.parents:
        raise ValueError("프로젝트 밖 경로는 수정할 수 없습니다.")
    bk = root / "data" / "workspace" / "backups"
    bk.mkdir(parents=True, exist_ok=True)
    if p.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        (bk / f"{p.name}.{stamp}.bak").write_text(
            p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    LOG.info("프로젝트 파일 수정(백업됨): %s", p)
    return str(p)


def analyze_structure() -> dict:
    files = list_project_files()
    by_ext = Counter(f.rsplit(".", 1)[-1] for f in files if "." in f)
    by_dir = Counter(f.split("/")[0] if "/" in f else "(root)" for f in files)
    return {"total": len(files), "by_ext": dict(by_ext), "by_dir": dict(by_dir), "files": files}


# ── Repository/시트 조회 (Adapter 경유) ───────────────────────────
def query_repo(cfg: dict, which: str) -> list:
    db = get_db_adapter(cfg)
    if which == "sites":
        from repositories.site_repository import SiteRepository
        return SiteRepository(db, cfg).get_all()
    if which == "calculators":
        from repositories.calculator_repository import CalculatorRepository
        # STEP110: calculators만 SQLite MAIN(get_calculator_storage_adapter)으로 조회한다
        # (STEP108에서 확인된 blind spot 수정 — sites/articles는 위 db(get_db_adapter)를 그대로 사용).
        return CalculatorRepository(get_calculator_storage_adapter(cfg)).get_all()
    if which == "articles":
        from repositories.article_repository import ArticleRepository
        return ArticleRepository(db).get_all()
    if which == "templates":
        from repositories.template_repository import TemplateRepository
        return TemplateRepository(get_template_storage_adapter(cfg)).get_all()
    return []
