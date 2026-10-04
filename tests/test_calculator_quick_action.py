# -*- coding: utf-8 -*-
"""tests/test_calculator_quick_action.py — STEP S11: Dashboard Quick Action
「🧮 계산기 생성」 React/FastAPI 이관 검증.

dashboard.py "🧮 계산기 생성" 버튼(dashboard.py:474-476, "🔧 고급 실행(수동)"
expander 안)과 동일한 실행 의미를 검증한다.
modules.calculator_pipeline.run_calculator_once()의 실제 구현(진짜 AI 호출 +
진짜 DB write)은 이 파일의 어떤 테스트에서도 실행하지 않는다 — 항상 monkeypatch로
대체한다. Registry/HOLD/Retry Queue/cost_state 관련 함수가 호출되지 않는지도
구조적으로 확인한다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "calc-quick-action-test-viewer-token"
ADMIN_TOKEN = "calc-quick-action-test-admin-token"

FAKE_RESULT = {
    "produced": 1, "processed": 3, "failed": 0, "dup": 1,
    "quality_hold": 0, "hold_skip": 1, "reason": "정상완료", "attempted": 1,
    "published": {"keyword": "퇴직금 계산법", "title": "퇴직금 계산법 총정리", "status": "completed"},
}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _mock_lock_always_free(monkeypatch):
    monkeypatch.setattr("api.services.calculator_quick_action_service.load_config", lambda *a, **k: {})
    monkeypatch.setattr("modules.scheduler._acquire_lock", lambda cfg, **kw: True)
    monkeypatch.setattr("modules.scheduler._release_lock", lambda cfg: None)


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_run_without_auth_returns_401():
    r = _client().post("/api/scheduler/calculator/run-once")
    assert r.status_code == 401


def test_run_as_viewer_returns_403():
    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_as_admin_returns_200(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", lambda cfg, max_count: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 기존 함수 호출 확인 + 반환값 보존
# ══════════════════════════════════════════════════════════════════════════

def test_calls_the_real_run_calculator_once_with_correct_args(monkeypatch):
    """dashboard.py의 실제 호출부(run_calculator_once(cfg, max_count=1))와
    동일한 인자로 호출되는지 확인 — 새로운 payload를 설계하지 않는다는 원칙 검증."""
    _mock_lock_always_free(monkeypatch)
    called = {}
    def _spy(cfg, max_count):
        called["cfg"] = cfg
        called["max_count"] = max_count
        return dict(FAKE_RESULT)
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", _spy)
    monkeypatch.setattr("api.services.calculator_quick_action_service.load_config", lambda *a, **k: {"FAKE": True})

    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert called["max_count"] == 1
    assert called["cfg"] == {"FAKE": True}


def test_return_structure_passed_through_unmodified(monkeypatch):
    """run_calculator_once()의 반환 구조를 임의로 재가공하지 않고 그대로
    전달하는지 확인 — 새로운 포맷을 설계하지 않는다는 원칙 검증."""
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", lambda cfg, max_count: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data == FAKE_RESULT


def test_zero_produced_result_is_a_clean_success_envelope(monkeypatch):
    """dashboard.py의 "후보소진"/"예산초과" 케이스 — run_calculator_once() 자체가
    예외 없이 {"produced": 0, "reason": ...}을 반환하는 정상 동작이다. HTTP 200 +
    명확히 구분되는 data.produced=0 이어야 하며, 애매한 구조가 아니다."""
    _mock_lock_always_free(monkeypatch)
    no_candidates = {"produced": 0, "reason": "no_calculators"}
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", lambda cfg, max_count: dict(no_candidates))
    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["produced"] == 0
    assert data["reason"] == "no_calculators"


def test_unexpected_exception_does_not_produce_a_fabricated_success(monkeypatch):
    """run_calculator_once() 자체에서 진짜 예상 밖 예외가 나면(blog/run-once의
    기존 처리 방식과 동일하게) 성공으로 위장하지 않아야 한다."""
    _mock_lock_always_free(monkeypatch)
    def _boom(cfg, max_count):
        raise RuntimeError("예상치 못한 오류(시뮬레이션)")
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", _boom)

    from api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════
# 중복 실행 방지(기존 파일 lock 재사용 — 실제 lock 함수로 검증)
# ══════════════════════════════════════════════════════════════════════════

def test_lock_conflict_when_another_run_holds_the_real_file_lock(monkeypatch, tmp_path):
    """기존 modules.scheduler._acquire_lock()/_release_lock()을 실제로(모킹 없이)
    격리된 tmp_path에 대해 사용해, 이미 lock이 걸려 있으면 LOCK_CONFLICT로 명확히
    차단되는지 확인한다(§9 — 기존 lock 재사용 검증)."""
    import modules.scheduler as SCH
    monkeypatch.setattr(SCH, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.calculator_quick_action_service.load_config", lambda *a, **k: {})

    assert SCH._acquire_lock({}) is True  # 최초 획득(다른 실행이 보유 중이라고 가정)
    def _boom(cfg, max_count):
        raise AssertionError("lock이 걸려 있는데 run_calculator_once()가 호출되면 안 된다")
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", _boom)

    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"

    SCH._release_lock({})  # 정리


def test_concurrent_requests_only_run_once_via_real_lock(monkeypatch, tmp_path):
    """실제 threading으로 두 요청이 진짜 겹치게 만들어, 실제 파일 lock이 두 번째
    요청을 차단하는지 확인한다(동일 요청 중복 실행 방지의 핵심 증거)."""
    import modules.scheduler as SCH
    monkeypatch.setattr(SCH, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.calculator_quick_action_service.load_config", lambda *a, **k: {})

    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_run(cfg, max_count):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return dict(FAKE_RESULT)

    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", _slow_run)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r2.json()["error"]["code"] == "LOCK_CONFLICT"

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Side Effect 보호
# ══════════════════════════════════════════════════════════════════════════

def test_never_touches_registry_hold_or_retry_queue(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.calculator_pipeline.run_calculator_once", lambda cfg, max_count: dict(FAKE_RESULT))

    import sys as _sys
    originally_absent = [m for m in ("modules.retry_queue", "modules.registry_loader") if m not in _sys.modules]

    r = _client().post("/api/scheduler/calculator/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 계산기 생성 실행 중 새로 import됨"


def test_service_source_never_references_other_domain_write_functions():
    import inspect
    from api.services import calculator_quick_action_service
    source = inspect.getsource(calculator_quick_action_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "validate_formula", "save_app", "registry_loader",
        "retry_queue", "cost_manager", "BudgetTracker",
        "content_sync", "strategy_room",
    ):
        assert forbidden not in source


def test_routes_under_scheduler_calculator():
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    calc_routes = [(r.path, sorted(r.methods)) for r in routes if r.path.startswith("/api/scheduler/calculator")]
    calc_routes.sort()

    # Expected routes under /api/scheduler/calculator (collect_routes returns separate entries per method)
    expected = [
        ("/api/scheduler/calculator/config", ["GET"]),
        ("/api/scheduler/calculator/config", ["PATCH"]),
        ("/api/scheduler/calculator/run-once", ["POST"]),
        ("/api/scheduler/calculator-webapp/run-once", ["POST"]),
    ]
    for exp_path, exp_methods in expected:
        found = [r for r in calc_routes if r[0] == exp_path and r[1] == exp_methods]
        assert found, f"Expected route {exp_path} with methods {exp_methods} not found in {calc_routes}"
