"""api/services/dashboard_kpi_service.py — Dashboard Home/KPI 조회 서비스.

STEP P2-01: dashboard.py의 render_kpi_cards()(dashboard.py:333-378, "🏠 운영센터"
탭 최상단 5개 KPI 카드)와 동일한 계산을 재현한다. 전부 READ-ONLY이며, 기존
계산 함수를 그대로 재사용한다 — 새 계산식을 만들지 않는다.

각 KPI의 실제 데이터 source(재검색으로 확인, 추측 없음):
  1) 시스템: data/logs/health_last.json(프로젝트 루트)을 직접 읽는다. 주의 —
     이 경로는 dashboard.py의 _read_health_cache()가 읽는 경로와 동일하지만,
     실제 헬스체크 실행기(modules.utils.health_monitor.run())가 쓰는 진짜 경로는
     modules/utils/data/logs/health_last.json으로 서로 다르다(기존 Streamlit
     버그 — api/services/health_service.py:43-46의 기존 주석에서도 확인됨).
     이 STEP은 dashboard.py의 실제 동작을 그대로 재현하는 것이 목적이므로,
     "고쳐진" 경로(health_service.get_external_health_cache())가 아니라
     dashboard.py가 실제로 읽는 이 (버그가 있는) 경로를 그대로 재사용한다 —
     임의로 개선하지 않는다.
  2/3) Workflow/AI 작업: modules.pipeline_status.get_pipeline_state(cfg) —
     api/services/log_service.get_pipeline_status()(기존 GET /api/pipeline/status)
     와 완전히 동일한 함수. 새로 구현하지 않고 그대로 호출한다.
  4) 오늘(발행/생성): modules.scheduler.summarize(modules.scheduler.load_schedule(cfg))
     — scheduler_line을 지정하지 않은 "기본" 라인(기존 동작, STEP S12에서도 확인된
     대로 dashboard.py가 자동 기동하는 스레드가 없는 별개 라인)의 today_schedule.json
     을 읽는다. /api/scheduler/blog/today(블로그 전용 라인)와는 다른 데이터
     source이므로 재사용하지 않는다. "생성"은 modules.dashboard_cache.read(cfg,
     "articles", ttl=120)의 행 수(기존 캐시 프리미티브, 새로 만들지 않음).
  5) AI 비용: modules.cost_manager.status(cfg)(기존 함수, /api/costs와 동일한
     BudgetTracker.check_budget() 기반이지만 반환 형태가 달라 그대로 재사용).
"""
import json
from pathlib import Path

from modules.config_loader import load_config

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_HEALTH_CACHE_PATH = _PROJECT_ROOT / "data" / "logs" / "health_last.json"


def _system_kpi() -> dict:
    h = {}
    if _HEALTH_CACHE_PATH.exists():
        try:
            h = json.loads(_HEALTH_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            h = {}
    crit = [v for v in h.values() if isinstance(v, dict) and v.get("level") == "CRITICAL"]
    ok_c = sum(1 for v in crit if v.get("status") == "OK")
    value = "정상" if crit and ok_c == len(crit) else ("주의" if crit else "—")
    sub = f"{ok_c}/{len(crit)} OK" if crit else "헬스 미실행"
    return {"value": value, "sub": sub}


def _workflow_and_ai_kpi(ps: dict) -> tuple:
    stages = ps.get("stages", [])
    running = next((s for s in stages if s.get("status") == "running"), None)
    done = [s for s in stages if s.get("status") == "completed"]
    if running:
        wf = running.get("name", "-")
    elif ps.get("finished"):
        wf = "완료"
    elif done:
        wf = done[-1].get("name", "-")
    else:
        wf = "대기"
    ai = running.get("model", "-") if running else "대기"
    return {"value": wf, "sub": "현재 단계"}, {"value": ai, "sub": "활성 모델"}


def _today_kpi(cfg: dict) -> dict:
    try:
        import modules.scheduler as SCH
        pub = SCH.summarize(SCH.load_schedule(cfg)).get("completed", 0)
    except Exception:
        pub = "—"
    try:
        from modules.dashboard_cache import read as cache_read
        gen = len(cache_read(cfg, "articles", ttl=120))
    except Exception:
        gen = "—"
    return {"value": f"{pub}건", "sub": f"발행 / 생성 {gen}"}


def _cost_kpi(cfg: dict, ps: dict) -> dict:
    try:
        from modules import cost_manager as CM
        cs = CM.status(cfg)
        return {"value": f"${cs['used']:.2f}", "sub": f"/ ${cs['limit']} ({cs['pct']:.0f}%)"}
    except Exception:
        return {"value": f"${ps.get('cost_today', 0)}", "sub": "예산 정보"}


def get_kpi() -> dict:
    """반환: dashboard.py render_kpi_cards()의 5개 카드와 동일한 (value, sub) 쌍.
    icon/label(순수 UI 텍스트)은 프론트엔드가 담당하고, 이 함수는 계산된
    데이터만 반환한다."""
    cfg = load_config()
    from api.services.log_service import get_pipeline_status
    ps = get_pipeline_status()

    workflow, ai_task = _workflow_and_ai_kpi(ps)
    return {
        "system": _system_kpi(),
        "workflow": workflow,
        "ai_task": ai_task,
        "today": _today_kpi(cfg),
        "cost": _cost_kpi(cfg, ps),
    }
