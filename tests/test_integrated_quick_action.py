# -*- coding: utf-8 -*-
"""tests/test_integrated_quick_action.py — STEP S13: Dashboard Quick Action
「▶ 실행」(통합 실행) React/FastAPI 이관 검증.

dashboard.py "▶ 실행" 버튼(dashboard.py:432-469, render_quick_actions()의
qa_run)과 동일한 실행 의미를 검증한다. 이 버튼은 새 파이프라인이 아니라 site의
활성 platforms에 따라 이미 존재하는 두 서비스(calculator_quick_action_service
= S11, pipeline_run_service = S12) 중 하나(또는 순차)를 고르는 dispatcher다.
run_calculator_once()/main.run_once()의 실제 구현은 이 파일의 어떤 테스트에서도
실행하지 않는다 — 항상 monkeypatch로 대체한다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "integrated-quick-action-test-viewer-token"
ADMIN_TOKEN = "integrated-quick-action-test-admin-token"

CALC_RESULT = {"produced": 1, "processed": 3, "failed": 0, "dup": 1,
               "quality_hold": 0, "hold_skip": 1, "reason": "정상완료", "attempted": 1}
BLOG_RESULT = {"produced": 1, "processed": 4, "dup": 1, "failed": 1, "no_wp": 0, "reason": "ok"}


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


def _no_platforms(monkeypatch):
    """활성 site가 없는(현재 실제 상태) 경우 — has_wp/has_calc 둘 다 False."""
    monkeypatch.setattr("api.services.integrated_run_service._resolve_platforms", lambda cfg: [])


def _platforms(monkeypatch, platforms):
    monkeypatch.setattr("api.services.integrated_run_service._resolve_platforms", lambda cfg: list(platforms))


def _mock_calc_service(monkeypatch, result=None, side_effect=None):
    if side_effect is not None:
        def _raise(*a, **k):
            raise side_effect
        monkeypatch.setattr("api.services.calculator_quick_action_service.run_once", _raise)
    else:
        monkeypatch.setattr("api.services.calculator_quick_action_service.run_once", lambda: dict(result or CALC_RESULT))


def _mock_pipeline_service(monkeypatch, result=None, side_effect=None):
    if side_effect is not None:
        def _raise(*a, **k):
            raise side_effect
        monkeypatch.setattr("api.services.pipeline_run_service.run_once", _raise)
    else:
        monkeypatch.setattr("api.services.pipeline_run_service.run_once", lambda: dict(result or BLOG_RESULT))


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_run_without_auth_returns_401():
    r = _client().post("/api/scheduler/integrated/run-once")
    assert r.status_code == 401


def test_run_as_viewer_returns_403():
    r = _client().post("/api/scheduler/integrated/run-once", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_as_admin_returns_200(monkeypatch):
    _no_platforms(monkeypatch)
    _mock_pipeline_service(monkeypatch)
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 분기 로직 — dashboard.py qa_run과 동일한 조건
# ══════════════════════════════════════════════════════════════════════════

def test_falls_back_to_pipeline_service_when_no_active_site(monkeypatch):
    """현재 실제 상태(활성 site 0개)와 동일한 fallback 분기 검증."""
    _no_platforms(monkeypatch)
    pipe_called = {}
    def _pipe():
        pipe_called["n"] = pipe_called.get("n", 0) + 1
        return dict(BLOG_RESULT)
    monkeypatch.setattr("api.services.pipeline_run_service.run_once", _pipe)
    monkeypatch.setattr("api.services.calculator_quick_action_service.run_once",
                         lambda: (_ for _ in ()).throw(AssertionError("calculator service should not be called")))
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert pipe_called.get("n") == 1
    assert r.json()["data"] == BLOG_RESULT


def test_calls_calculator_service_when_only_calculator_platform_active(monkeypatch):
    _platforms(monkeypatch, ["Calculator"])
    monkeypatch.setattr("api.services.pipeline_run_service.run_once",
                         lambda: (_ for _ in ()).throw(AssertionError("pipeline service should not be called")))
    _mock_calc_service(monkeypatch)
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"] == CALC_RESULT


def test_default_order_runs_both_sequentially_and_returns_fixed_string(monkeypatch):
    """dashboard.py _run_seq(): 두 서비스를 순서대로 호출하고 각 반환값은 버린 채
    고정 문자열만 반환한다 — 그대로 재현(수정하지 않음)."""
    _platforms(monkeypatch, ["WordPress", "Calculator"])
    calls = []
    monkeypatch.setattr("api.services.calculator_quick_action_service.run_once",
                         lambda: calls.append("calc") or dict(CALC_RESULT))
    monkeypatch.setattr("api.services.pipeline_run_service.run_once",
                         lambda: calls.append("blog") or dict(BLOG_RESULT))
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert calls == ["calc", "blog"]  # 순서 보존
    assert r.json()["data"] == "계산기→블로그 순차 완료"  # 두 결과 모두 버려짐


def test_order_calculator_only_skips_pipeline_service(monkeypatch):
    _platforms(monkeypatch, ["WordPress", "Calculator"])
    _mock_calc_service(monkeypatch)
    monkeypatch.setattr("api.services.pipeline_run_service.run_once",
                         lambda: (_ for _ in ()).throw(AssertionError("pipeline service should not be called")))
    r = _client().post("/api/scheduler/integrated/run-once", json={"order": "Calculator만"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"] == CALC_RESULT


def test_order_wordpress_only_skips_calculator_service(monkeypatch):
    _platforms(monkeypatch, ["WordPress", "Calculator"])
    monkeypatch.setattr("api.services.calculator_quick_action_service.run_once",
                         lambda: (_ for _ in ()).throw(AssertionError("calculator service should not be called")))
    _mock_pipeline_service(monkeypatch)
    r = _client().post("/api/scheduler/integrated/run-once", json={"order": "WordPress만"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"] == BLOG_RESULT


def test_invalid_order_value_returns_422(monkeypatch):
    _no_platforms(monkeypatch)
    r = _client().post("/api/scheduler/integrated/run-once", json={"order": "아무거나"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# 예외/lock 전파
# ══════════════════════════════════════════════════════════════════════════

def test_calculator_service_busy_propagates_as_lock_conflict(monkeypatch):
    from api.services import calculator_quick_action_service as calc_svc
    _platforms(monkeypatch, ["Calculator"])
    _mock_calc_service(monkeypatch, side_effect=calc_svc.CalculatorQuickActionBusy("busy"))
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"


def test_pipeline_service_busy_propagates_as_lock_conflict(monkeypatch):
    from api.services import pipeline_run_service as pipe_svc
    _no_platforms(monkeypatch)
    _mock_pipeline_service(monkeypatch, side_effect=pipe_svc.PipelineRunBusy("busy"))
    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"


def test_unexpected_exception_does_not_produce_a_fabricated_success(monkeypatch):
    _no_platforms(monkeypatch)
    def _boom():
        raise RuntimeError("예상치 못한 오류(시뮬레이션)")
    monkeypatch.setattr("api.services.pipeline_run_service.run_once", _boom)

    from api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════
# 실제 파일 lock 기반 동시 실행 방지(fallback=blog 분기, 실제 lock 재사용 검증)
# ══════════════════════════════════════════════════════════════════════════

def test_concurrent_requests_only_run_once_via_real_underlying_lock(monkeypatch, tmp_path):
    """fallback 분기(main.run_once 경유)에서 실제 blog scheduler lock(S12와 동일
    파일)이 두 번째 요청을 실제로 차단하는지 확인한다."""
    import modules.scheduler as SCH
    monkeypatch.setattr(SCH, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.integrated_run_service._resolve_platforms", lambda cfg: [])
    monkeypatch.setattr("api.services.pipeline_run_service.load_config", lambda *a, **k: {})

    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_run(cfg):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return dict(BLOG_RESULT)

    monkeypatch.setattr("main.run_once", _slow_run)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r2.json()["error"]["code"] == "LOCK_CONFLICT"

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# 구조 검증 — S11/S12 entry point를 직접 호출하지 않고 서비스만 재사용하는지
# ══════════════════════════════════════════════════════════════════════════

def test_service_never_imports_run_calculator_once_or_main_run_once_directly():
    """S11의 run_calculator_once()/S12의 main.run_once()를 직접 호출하지 않고,
    반드시 calculator_quick_action_service/pipeline_run_service를 통해서만
    호출하는지 확인한다(§13-13,14,15 요구사항)."""
    import ast
    import inspect
    from api.services import integrated_run_service
    source = inspect.getsource(integrated_run_service)

    for forbidden in ("run_calculator_once", "calculator_pipeline", "import main"):
        assert forbidden not in source

    tree = ast.parse(source)
    imported_modules = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert imported_modules == {
        "calculator_quick_action_service", "pipeline_run_service", "load_config", "SiteManager",
    }


def test_never_touches_other_domain_modules(monkeypatch):
    _no_platforms(monkeypatch)
    _mock_pipeline_service(monkeypatch)

    import sys as _sys
    originally_absent = [
        m for m in (
            "modules.retry_queue", "modules.registry_loader",
            "modules.content_sync", "modules.strategy_room",
        ) if m not in _sys.modules
    ]

    r = _client().post("/api/scheduler/integrated/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 통합 실행 중 새로 import됨"


def test_only_one_new_write_route_added_under_scheduler_integrated():
    from _route_utils import write_routes
    from api.main import app
    assert write_routes(app, prefix="/api/scheduler/integrated") == [
        ("/api/scheduler/integrated/run-once", "POST"),
    ]


# ══════════════════════════════════════════════════════════════════════════
# ── CURRENT-SITE-02: 현재 Site(dashboard.py current_site_id) 계약
# 선택된 site의 platforms로 분기한다. SiteManager는 가짜 site 목록으로 대체 —
# 운영 sites 데이터(Sheets/SQLite)는 읽지 않는다.
# ══════════════════════════════════════════════════════════════════════════

SITES = [
    {"site_id": "site-A", "site_name": "A", "status": "active", "platforms": '["Calculator"]'},
    {"site_id": "site-B", "site_name": "B", "status": "inactive", "platforms": '["WordPress"]'},
    {"site_id": "site-C", "site_name": "C", "status": "archived", "platforms": '["WordPress", "Calculator"]'},
]


def _fake_sites(monkeypatch, sites=None):
    rows = list(SITES if sites is None else sites)
    seen = {"get_by_id": [], "get_all_sites": 0, "get_active_sites": 0}

    class _FakeSiteManager:
        def __init__(self, cfg):
            pass

        def get_all_sites(self):
            seen["get_all_sites"] += 1
            return list(rows)

        def get_active_sites(self):
            seen["get_active_sites"] += 1
            return [r for r in rows if r.get("status") == "active"]

        def get_by_id(self, site_id):
            seen["get_by_id"].append(site_id)
            return next((r for r in rows if r["site_id"] == site_id), None)

    monkeypatch.setattr("api.services.integrated_run_service.SiteManager", _FakeSiteManager)
    monkeypatch.setattr("api.services.integrated_run_service.load_config", lambda *a, **k: {})
    return seen


def _track_services(monkeypatch):
    calls = []
    monkeypatch.setattr("api.services.calculator_quick_action_service.run_once",
                         lambda: calls.append("calc") or dict(CALC_RESULT))
    monkeypatch.setattr("api.services.pipeline_run_service.run_once",
                         lambda: calls.append("blog") or dict(BLOG_RESULT))
    return calls


def _run(body):
    return _client().post("/api/scheduler/integrated/run-once", json=body, headers=_auth(ADMIN_TOKEN))


def test_cs_selected_site_platforms_are_used(monkeypatch):
    """Test 1/2: site-A(첫 번째, Calculator) 대신 선택한 site-B(WordPress) → Blog branch."""
    seen = _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    r = _run({"site_id": "site-B"})
    assert r.status_code == 200 and r.json()["data"] == BLOG_RESULT
    assert calls == ["blog"] and seen["get_by_id"] == ["site-B"]


def test_cs_first_site_can_be_selected_explicitly(monkeypatch):
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    assert _run({"site_id": "site-A"}).json()["data"] == CALC_RESULT
    assert calls == ["calc"]


def test_cs_inactive_and_archived_sites_are_allowed(monkeypatch):
    """Test 3/5: dashboard.py와 같이 상태와 무관하게 선택 site의 platforms를 쓴다."""
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    assert _run({"site_id": "site-B"}).json()["success"] is True      # inactive
    r = _run({"site_id": "site-C"})                                    # archived, WP+Calc
    assert r.json()["data"] == "계산기→블로그 순차 완료"
    assert calls == ["blog", "calc", "blog"]


def test_cs_selected_site_used_even_when_no_active_site(monkeypatch):
    """Test 5: active site가 0개여도 선택된(inactive) site의 platforms를 쓴다."""
    seen = _fake_sites(monkeypatch, [{"site_id": "only", "status": "inactive", "platforms": '["Calculator"]'}])
    calls = _track_services(monkeypatch)
    assert _run({"site_id": "only"}).json()["data"] == CALC_RESULT
    assert calls == ["calc"] and seen["get_active_sites"] == 0


def test_cs_invalid_site_is_validation_error_without_fallback(monkeypatch):
    """Test 4: 존재하지 않는 site_id → VALIDATION_ERROR, 어떤 서비스도 실행하지 않음."""
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    r = _run({"site_id": "nonexistent"})
    assert r.status_code == 200
    assert r.json()["success"] is False and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert calls == []


def test_cs_empty_site_id_rejected(monkeypatch):
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    assert _run({"site_id": ""}).status_code == 422
    assert calls == []


def test_cs_missing_site_id_uses_first_site_regardless_of_status(monkeypatch):
    """site_id 생략(기존 호출 호환): dashboard.py 기본값 = 전체 목록의 첫 번째 site.
    첫 번째가 inactive여도 active site로 건너뛰지 않는다."""
    rows = [dict(SITES[1]), dict(SITES[0])]       # 첫 번째 = inactive WordPress
    seen = _fake_sites(monkeypatch, rows)
    calls = _track_services(monkeypatch)
    assert _run({}).json()["data"] == BLOG_RESULT
    assert calls == ["blog"] and seen["get_all_sites"] == 1 and seen["get_active_sites"] == 0


def test_cs_missing_site_id_with_no_sites_falls_back_to_blog(monkeypatch):
    _fake_sites(monkeypatch, [])
    calls = _track_services(monkeypatch)
    assert _run({}).json()["data"] == BLOG_RESULT
    assert calls == ["blog"]


@pytest.mark.parametrize("order,expected_calls,expected_data", [
    ("순차(Calculator→WordPress)", ["calc", "blog"], "계산기→블로그 순차 완료"),
    ("Calculator만", ["calc"], CALC_RESULT),
    ("WordPress만", ["blog"], BLOG_RESULT),
])
def test_cs_order_branches_unchanged_with_selected_site(monkeypatch, order, expected_calls, expected_data):
    """Test 6: WP+Calc site 선택 시 기존 order 분기 그대로."""
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    assert _run({"site_id": "site-C", "order": order}).json()["data"] == expected_data
    assert calls == expected_calls


def test_cs_busy_contract_unchanged_with_selected_site(monkeypatch):
    """Test 7: LOCK_CONFLICT 계약 유지."""
    from api.services import pipeline_run_service as P

    def _busy():
        raise P.PipelineRunBusy("lock 보유 중")
    _fake_sites(monkeypatch)
    monkeypatch.setattr("api.services.pipeline_run_service.run_once", _busy)
    r = _run({"site_id": "site-B"})
    assert r.status_code == 200 and r.json()["error"]["code"] == "LOCK_CONFLICT"


def test_cs_client_platforms_are_not_accepted(monkeypatch):
    """서버가 site를 다시 조회한다 — 클라이언트가 platforms를 보내는 필드는 없다."""
    _fake_sites(monkeypatch)
    calls = _track_services(monkeypatch)
    assert _run({"site_id": "site-B", "platforms": ["Calculator"]}).status_code == 422
    assert calls == []
