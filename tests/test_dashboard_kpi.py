# -*- coding: utf-8 -*-
"""tests/test_dashboard_kpi.py — STEP P2-01: Dashboard Home/KPI React/FastAPI
이관 검증.

dashboard.py render_kpi_cards()(dashboard.py:333-378, "🏠 운영센터" 탭 최상단 5개
KPI 카드)와 동일한 계산을 검증한다. 전부 READ-ONLY이며, 실제 파일/DB를 이 파일의
테스트에서 직접 건드리지 않는다 — 항상 monkeypatch로 대체한다.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "dashboard-kpi-test-viewer-token"
ADMIN_TOKEN = "dashboard-kpi-test-admin-token"

FAKE_PIPELINE_STATUS = {
    "stages": [
        {"name": "수집", "model": "-", "status": "completed"},
        {"name": "전략", "model": "gpt-4o", "status": "running"},
        {"name": "발행", "model": "-", "status": "pending"},
    ],
    "finished": False,
    "has_error": False,
    "cost_today": 0.5,
    "tokens_today": 1000,
    "model_costs": {},
    "last_lines": [],
}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _mock_common(monkeypatch, tmp_path, *, health=None, pipeline_status=None,
                  schedule_summary=None, articles=None, cost_status=None,
                  cost_raises=False):
    """get_kpi()의 5개 데이터 source를 전부 격리된 값으로 대체한다."""
    health_path = tmp_path / "health_last.json"
    if health is not None:
        health_path.write_text(json.dumps(health, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("api.services.dashboard_kpi_service._HEALTH_CACHE_PATH", health_path)
    monkeypatch.setattr("api.services.dashboard_kpi_service.load_config", lambda: {"FAKE": True})
    monkeypatch.setattr(
        "api.services.log_service.get_pipeline_status",
        lambda: dict(pipeline_status if pipeline_status is not None else FAKE_PIPELINE_STATUS),
    )
    monkeypatch.setattr(
        "modules.scheduler.summarize",
        lambda sched: dict(schedule_summary if schedule_summary is not None else {"completed": 0}),
    )
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    monkeypatch.setattr(
        "modules.dashboard_cache.read",
        lambda cfg, table, ttl=120: list(articles if articles is not None else []),
    )
    if cost_raises:
        def _boom(cfg):
            raise RuntimeError("cost source unavailable")
        monkeypatch.setattr("modules.cost_manager.status", _boom)
    else:
        monkeypatch.setattr(
            "modules.cost_manager.status",
            lambda cfg: dict(cost_status if cost_status is not None else
                              {"used": 1.23, "limit": 5, "pct": 24.6,
                               "daily_exceeded": False, "monthly_exceeded": False}),
        )


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_kpi_without_auth_returns_401():
    r = _client().get("/api/dashboard/kpi")
    assert r.status_code == 401


def test_kpi_as_viewer_returns_403():
    r = _client().get("/api/dashboard/kpi", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_kpi_as_admin_returns_200_with_all_five_cards(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data.keys()) == {"system", "workflow", "ai_task", "today", "cost"}
    for card in data.values():
        assert "value" in card and "sub" in card


# ══════════════════════════════════════════════════════════════════════════
# 데이터 source 정확성 + 계산식(§3/§4)
# ══════════════════════════════════════════════════════════════════════════

def test_system_kpi_reads_project_root_health_cache_path():
    """_HEALTH_CACHE_PATH가 실제로 dashboard.py의 _read_health_cache()와 동일한
    경로(프로젝트 루트 data/logs/health_last.json)를 가리키는지 확인 — health_
    service.get_external_health_cache()가 쓰는 modules/utils/data/logs/... 경로가
    아니다(기존 Streamlit 버그를 그대로 재현해야 하므로)."""
    from api.services.dashboard_kpi_service import _HEALTH_CACHE_PATH, _PROJECT_ROOT
    assert _HEALTH_CACHE_PATH == _PROJECT_ROOT / "data" / "logs" / "health_last.json"


def test_system_kpi_all_critical_ok(monkeypatch, tmp_path):
    health = {
        "openai": {"status": "OK", "level": "CRITICAL"},
        "claude": {"status": "OK", "level": "CRITICAL"},
        "wordpress": {"status": "FAIL", "level": "WARNING"},
    }
    _mock_common(monkeypatch, tmp_path, health=health)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    system = r.json()["data"]["system"]
    assert system == {"value": "정상", "sub": "2/2 OK"}


def test_system_kpi_partial_critical_failure(monkeypatch, tmp_path):
    health = {
        "openai": {"status": "OK", "level": "CRITICAL"},
        "claude": {"status": "FAIL", "level": "CRITICAL"},
    }
    _mock_common(monkeypatch, tmp_path, health=health)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    system = r.json()["data"]["system"]
    assert system == {"value": "주의", "sub": "1/2 OK"}


def test_system_kpi_no_critical_checks(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={"wordpress": {"status": "FAIL", "level": "WARNING"}})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    system = r.json()["data"]["system"]
    assert system == {"value": "—", "sub": "헬스 미실행"}


def test_workflow_and_ai_kpi_use_running_stage(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["workflow"] == {"value": "전략", "sub": "현재 단계"}
    assert data["ai_task"] == {"value": "gpt-4o", "sub": "활성 모델"}


def test_workflow_kpi_shows_완료_when_finished(monkeypatch, tmp_path):
    ps = {"stages": [{"name": "발행", "model": "-", "status": "completed"}], "finished": True, "cost_today": 0}
    _mock_common(monkeypatch, tmp_path, health={}, pipeline_status=ps)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["workflow"]["value"] == "완료"
    assert data["ai_task"]["value"] == "대기"


def test_workflow_kpi_shows_대기_when_no_stages(monkeypatch, tmp_path):
    ps = {"stages": [], "finished": False, "cost_today": 0}
    _mock_common(monkeypatch, tmp_path, health={}, pipeline_status=ps)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["workflow"]["value"] == "대기"


def test_today_kpi_reflects_schedule_summary_and_article_count(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={}, schedule_summary={"completed": 3},
                 articles=[{"ID": "1"}, {"ID": "2"}])
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    today = r.json()["data"]["today"]
    assert today == {"value": "3건", "sub": "발행 / 생성 2"}


def test_today_kpi_uses_generic_schedule_line_not_blog_scoped_cfg(monkeypatch, tmp_path):
    """render_kpi_cards()는 scheduler_line을 지정하지 않은 cfg로 load_schedule을
    호출한다 — /api/scheduler/blog/today(scheduler_line="blog")와는 다른
    데이터 source임을 확인한다."""
    _mock_common(monkeypatch, tmp_path, health={})
    called_cfg = {}
    def _load_schedule(cfg):
        called_cfg.update(cfg)
        return {"schedule": []}
    monkeypatch.setattr("modules.scheduler.load_schedule", _load_schedule)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert "scheduler_line" not in called_cfg


def test_cost_kpi_uses_cost_manager_status(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={},
                 cost_status={"used": 2.5, "limit": 10, "pct": 25.0,
                              "daily_exceeded": False, "monthly_exceeded": False})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    cost = r.json()["data"]["cost"]
    assert cost == {"value": "$2.50", "sub": "/ $10 (25%)"}


def test_cost_kpi_falls_back_to_pipeline_cost_today_on_exception(monkeypatch, tmp_path):
    ps = dict(FAKE_PIPELINE_STATUS)
    ps["cost_today"] = 0.75
    _mock_common(monkeypatch, tmp_path, health={}, pipeline_status=ps, cost_raises=True)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    cost = r.json()["data"]["cost"]
    assert cost == {"value": "$0.75", "sub": "예산 정보"}


# ══════════════════════════════════════════════════════════════════════════
# empty / malformed / source 오류(각 KPI는 독립적으로 실패해도 전체가 죽지 않는다)
# ══════════════════════════════════════════════════════════════════════════

def test_missing_health_cache_file_is_treated_as_empty(monkeypatch, tmp_path):
    """health_last.json 파일 자체가 없으면(가능한 실제 상태) — 정상적으로 '헬스
    미실행'으로 처리되어야 하며 500이 나면 안 된다."""
    monkeypatch.setattr("api.services.dashboard_kpi_service.load_config", lambda: {"FAKE": True})
    monkeypatch.setattr("api.services.dashboard_kpi_service._HEALTH_CACHE_PATH", tmp_path / "does_not_exist.json")
    monkeypatch.setattr("api.services.log_service.get_pipeline_status", lambda: dict(FAKE_PIPELINE_STATUS))
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {"completed": 0})
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    monkeypatch.setattr("modules.dashboard_cache.read", lambda cfg, table, ttl=120: [])
    monkeypatch.setattr("modules.cost_manager.status", lambda cfg: {"used": 0, "limit": 5, "pct": 0,
                                                                     "daily_exceeded": False, "monthly_exceeded": False})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["system"] == {"value": "—", "sub": "헬스 미실행"}


def test_malformed_health_cache_json_does_not_crash(monkeypatch, tmp_path):
    bad_path = tmp_path / "health_last.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("api.services.dashboard_kpi_service.load_config", lambda: {"FAKE": True})
    monkeypatch.setattr("api.services.dashboard_kpi_service._HEALTH_CACHE_PATH", bad_path)
    monkeypatch.setattr("api.services.log_service.get_pipeline_status", lambda: dict(FAKE_PIPELINE_STATUS))
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {"completed": 0})
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    monkeypatch.setattr("modules.dashboard_cache.read", lambda cfg, table, ttl=120: [])
    monkeypatch.setattr("modules.cost_manager.status", lambda cfg: {"used": 0, "limit": 5, "pct": 0,
                                                                     "daily_exceeded": False, "monthly_exceeded": False})
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["system"] == {"value": "—", "sub": "헬스 미실행"}


def test_schedule_source_error_does_not_crash_other_kpis(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={})
    def _boom(cfg):
        raise RuntimeError("schedule file corrupt")
    monkeypatch.setattr("modules.scheduler.load_schedule", _boom)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["today"]["value"] == "—건"
    assert data["system"]["value"] in ("정상", "주의", "—")  # 다른 KPI는 영향 없음


def test_articles_source_error_does_not_crash_other_kpis(monkeypatch, tmp_path):
    _mock_common(monkeypatch, tmp_path, health={})
    def _boom(cfg, table, ttl=120):
        raise RuntimeError("db unavailable")
    monkeypatch.setattr("modules.dashboard_cache.read", _boom)
    r = _client().get("/api/dashboard/kpi", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert "—" in r.json()["data"]["today"]["sub"]


# ══════════════════════════════════════════════════════════════════════════
# read-only 보장 + write route 없음
# ══════════════════════════════════════════════════════════════════════════

def test_service_source_never_writes_anything():
    import inspect
    from api.services import dashboard_kpi_service
    source = inspect.getsource(dashboard_kpi_service)
    for forbidden in ("_save", ".record(", "save_schedule", "open(", "write_text", "run_calculator_once",
                      "run_once", "BudgetTracker("):
        assert forbidden not in source


def test_only_get_route_exists_under_dashboard_kpi():
    from _route_utils import write_routes
    from api.main import app
    assert write_routes(app, prefix="/api/dashboard/kpi") == []
