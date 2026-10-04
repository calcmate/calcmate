# -*- coding: utf-8 -*-
"""tests/test_dashboard_ai_pipeline.py — STEP P2-11: Dashboard "📊 AI Pipeline
Monitor" React/FastAPI 이관 검증.

dashboard.py "📊 AI Pipeline" 탭(dashboard.py:2875-2901)과 동일한 데이터를
검증한다. 이 서비스는 modules.pipeline_status.get_pipeline_state()/
api.services.log_service.get_pipeline_status()를 재구현 없이 그대로 호출하는
thin wrapper다 — 새 계산 로직이 없어야 한다. 전부 READ-ONLY이며, 실제 운영
파일(pipeline.log/budget.json)을 이 파일의 테스트에서 직접 건드리지 않는다 —
항상 monkeypatch로 대체한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "dashboard-ai-pipeline-test-viewer-token"
ADMIN_TOKEN = "dashboard-ai-pipeline-test-admin-token"

FAKE_STATE = {
    "stages": [
        {"name": "키워드 수집", "model": "RSS/Collector", "status": "completed"},
        {"name": "리서치/전략", "model": "gemini-2.5-flash", "status": "completed"},
        {"name": "본문 작성", "model": "gpt-4o-mini", "status": "running"},
        {"name": "검수", "model": "claude-sonnet-4-6", "status": "pending"},
        {"name": "이미지 생성", "model": "Pollinations", "status": "pending"},
        {"name": "발행", "model": "WordPress REST", "status": "pending"},
    ],
    "finished": False,
    "has_error": False,
    "cost_today": 0.1234,
    "tokens_today": 5000,
    "model_costs": {"gemini-2.5-flash": 0.05, "gpt-4o-mini": 0.0734},
    "last_lines": ["2026-09-06 12:00:00 [INFO] STEP 7 시작"],
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


def _mock(monkeypatch, state=None):
    monkeypatch.setattr("api.services.log_service.get_pipeline_status", lambda: dict(state or FAKE_STATE))


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_ai_pipeline_without_auth_returns_401():
    r = _client().get("/api/dashboard/ai-pipeline")
    assert r.status_code == 401


def test_ai_pipeline_as_viewer_returns_403():
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_ai_pipeline_as_admin_returns_200(monkeypatch):
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 응답 schema / Streamlit 표시값과 동일
# ══════════════════════════════════════════════════════════════════════════

def test_response_matches_underlying_pipeline_state_exactly(monkeypatch):
    """이 endpoint는 새 계산을 하지 않는다 — 반환값이 get_pipeline_status()의
    반환값과 완전히 동일해야 한다(재구현 없음 검증)."""
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"] == FAKE_STATE


def test_stages_include_name_model_status_for_all_six(monkeypatch):
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    stages = r.json()["data"]["stages"]
    assert len(stages) == 6
    for s in stages:
        assert set(s.keys()) == {"name", "model", "status"}


def test_cost_today_and_tokens_today_present(monkeypatch):
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["cost_today"] == 0.1234
    assert data["tokens_today"] == 5000


def test_model_costs_breakdown_present_when_nonempty(monkeypatch):
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["model_costs"] == {"gemini-2.5-flash": 0.05, "gpt-4o-mini": 0.0734}


def test_model_costs_empty_dict_when_no_costs(monkeypatch):
    empty_state = {**FAKE_STATE, "model_costs": {}}
    _mock(monkeypatch, empty_state)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["model_costs"] == {}


def test_last_lines_present(monkeypatch):
    _mock(monkeypatch)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["last_lines"] == ["2026-09-06 12:00:00 [INFO] STEP 7 시작"]


def test_empty_last_lines_when_no_log(monkeypatch):
    empty_state = {**FAKE_STATE, "last_lines": []}
    _mock(monkeypatch, empty_state)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["last_lines"] == []


def test_finished_and_has_error_flags_passed_through(monkeypatch):
    error_state = {**FAKE_STATE, "finished": True, "has_error": True}
    _mock(monkeypatch, error_state)
    r = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["finished"] is True
    assert data["has_error"] is True


# ══════════════════════════════════════════════════════════════════════════
# GET-only / write 없음 / Pipeline 실행 함수 미호출
# ══════════════════════════════════════════════════════════════════════════

def test_ai_pipeline_route_is_get_only():
    from _route_utils import collect_routes
    from api.main import app
    routes = [r for r in collect_routes(app) if r.path == "/api/dashboard/ai-pipeline"]
    assert len(routes) == 1
    assert routes[0].methods == frozenset({"GET"})


def _source_body_without_docstring(fn):
    import ast
    import inspect
    source = inspect.getsource(fn)
    tree = ast.parse(source)
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant) and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]
    return ast.unparse(func)


def test_service_source_has_no_write_calls_and_no_new_logic():
    """이 함수는 get_pipeline_status()를 호출해 그대로 반환하는 것 외에
    아무 로직도 없어야 한다(재구현 없음 — thin wrapper 검증)."""
    from api.services import dashboard_status_service
    source = _source_body_without_docstring(dashboard_status_service.get_ai_pipeline_status)
    for forbidden in ("insert(", "update(", "delete(", ".save(", ".append(", "yaml.dump(",
                      "write(", "record(", "budget.record", "publisher", "pipeline.run"):
        assert forbidden not in source, f"get_ai_pipeline_status가 쓰기/실행 호출({forbidden})을 포함함"
    assert "get_pipeline_status()" in source


def test_service_source_never_touches_other_completed_features():
    from api.services import dashboard_status_service
    source = _source_body_without_docstring(dashboard_status_service.get_ai_pipeline_status)
    for forbidden in (
        "site_service", "SiteRepository", "calculator_service", "CalculatorRepository",
        "registry_auto", "app_factory", "site_wizard", "scheduler",
    ):
        assert forbidden not in source, f"get_ai_pipeline_status가 범위 밖 기능({forbidden})을 참조함"


def test_underlying_pipeline_state_functions_never_write_budget_or_log(monkeypatch, tmp_path):
    """BudgetTracker.get_daily_cost()/get_today_tokens()/get_model_breakdown()가
    실제로 budget.json을 쓰지 않는지 격리 파일로 직접 확인한다(모듈 docstring
    재확인 사항을 실측으로 검증)."""
    from modules.logger import BudgetTracker
    budget_path = tmp_path / "budget.json"
    cfg = {"_root": str(tmp_path)}
    bt = BudgetTracker(cfg)
    assert not budget_path.exists()  # 아직 파일 없음(정상 — mkdir만 함)

    bt.get_daily_cost()
    bt.get_today_tokens()
    bt.get_model_breakdown("daily")

    assert not budget_path.exists(), "조회 메서드가 budget.json을 새로 생성/기록하면 안 된다"


# ══════════════════════════════════════════════════════════════════════════
# 기존 공개 endpoint(/api/pipeline/status)와의 관계 확인
# ══════════════════════════════════════════════════════════════════════════

def test_new_endpoint_returns_identical_data_to_existing_public_endpoint(monkeypatch):
    """이 STEP이 새로 만든 admin 전용 endpoint는 기존 공개 endpoint와 완전히
    동일한 데이터를 반환해야 한다(같은 함수를 감싼 wrapper이므로)."""
    _mock(monkeypatch)
    r_admin = _client().get("/api/dashboard/ai-pipeline", headers=_auth(ADMIN_TOKEN))
    r_public = _client().get("/api/pipeline/status")
    assert r_admin.json()["data"] == r_public.json()["data"]


def test_existing_public_pipeline_status_endpoint_unmodified_still_has_no_auth():
    """발견사항 재확인: 기존 GET /api/pipeline/status는 이 STEP 이후에도 여전히
    인증이 없다 — 완료된 STEP(18-G)의 코드를 이 STEP에서 수정하지 않았음을
    회귀적으로 확인한다(수정 여부를 검증하는 것이지, 이 상태를 승인하는
    것이 아니다 — 최종 보고서에 발견사항으로 기록됨)."""
    r = _client().get("/api/pipeline/status")
    assert r.status_code == 200  # 401/403이 아님 = 여전히 공개
