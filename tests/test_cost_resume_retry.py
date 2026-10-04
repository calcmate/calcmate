# -*- coding: utf-8 -*-
"""tests/test_cost_resume_retry.py — STEP S5: Cost Monitor Manual Resume /
Retry Queue React/FastAPI 이관 검증.

dashboard.py "▶ 지금 수동 재개"/"🔁 재발행" 버튼과 동일한 실행 의미를 검증한다.
modules.cost_manager.resume()/modules.retry_queue.retry()의 실제 구현은 이 파일의
정상/차단 분기 테스트에서 monkeypatch로 대체한다(실제 WordPress 발행/파일 쓰기
없이 호출 여부만 스파이로 확인) — 단, "원본 로직을 그대로 재사용하는지"를 증명하는
스파이 테스트는 실제 함수 참조를 사용한다. publisher.publish()는 이 파일의 어떤
테스트에서도 실제로 실행되지 않는다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "cost-rr-test-viewer-token"
ADMIN_TOKEN = "cost-rr-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _reset_inflight_state():
    """cost_service의 in-memory 중복 방지 lock/set을 테스트 간 격리한다."""
    from api.services import cost_service
    cost_service._retry_in_flight.clear()
    yield
    cost_service._retry_in_flight.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════
# §13-1~4: 인증
# ══════════════════════════════════════════════════════════════════════════

def test_resume_without_auth_returns_401():
    r = _client().post("/api/costs/resume")
    assert r.status_code == 401


def test_resume_as_viewer_returns_403():
    r = _client().post("/api/costs/resume", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_retry_without_auth_returns_401():
    r = _client().post("/api/costs/retry", json={"id": "x"})
    assert r.status_code == 401


def test_retry_as_viewer_returns_403():
    r = _client().post("/api/costs/retry", json={"id": "x"}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# §13-5~8: Resume
# ══════════════════════════════════════════════════════════════════════════

def test_resume_when_paused_calls_the_real_resume_function(monkeypatch):
    monkeypatch.setattr("modules.cost_manager.is_paused", lambda cfg: True)
    called = {}
    def _fake_resume(cfg):
        called["resumed"] = True
    monkeypatch.setattr("modules.cost_manager.resume", _fake_resume)

    r = _client().post("/api/costs/resume", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is True
    assert called.get("resumed") is True


def test_resume_when_not_paused_is_blocked(monkeypatch):
    monkeypatch.setattr("modules.cost_manager.is_paused", lambda cfg: False)
    def _boom(cfg):
        raise AssertionError("paused가 아닌데 resume()이 호출되면 안 된다")
    monkeypatch.setattr("modules.cost_manager.resume", _boom)

    r = _client().post("/api/costs/resume", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is False
    assert "일시정지" in body["data"]["message"] or "재개" in body["data"]["message"]


def test_resume_ignores_client_supplied_paused_flag(monkeypatch):
    """클라이언트가 body에 paused=true를 실어 보내도 서버는 실제
    cost_manager.is_paused()만 기준으로 판단해야 한다."""
    monkeypatch.setattr("modules.cost_manager.is_paused", lambda cfg: False)

    r = _client().post(
        "/api/costs/resume", headers=_auth(ADMIN_TOKEN),
        json={"paused": True, "force": True},
    )
    # /costs/resume는 body를 받지 않는 endpoint이므로 body가 있어도 무시되고
    # 실제 서버 상태(is_paused=False) 기준으로 차단되어야 한다.
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is False


def test_resume_duplicate_requests_do_not_call_resume_twice_concurrently(monkeypatch):
    """동시에 여러 재개 요청이 들어와도 실제 resume()은 동시에 여러 스레드에서
    실행되지 않는지 확인(락 보유 중이면 즉시 차단 응답)."""
    monkeypatch.setattr("modules.cost_manager.is_paused", lambda cfg: True)
    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_resume(cfg):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr("modules.cost_manager.resume", _slow_resume)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/costs/resume", headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/costs/resume", headers=_auth(ADMIN_TOKEN))
    assert r2.json()["data"]["ok"] is False
    assert "이미" in r2.json()["data"]["message"]

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# §13-9~14: Retry
# ══════════════════════════════════════════════════════════════════════════

def test_retry_pending_item_calls_the_real_retry_function(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    called = {}
    def _fake_retry(cfg, pid):
        called["pid"] = pid
        return True, "재발행 성공: http://example.test/post/1"
    monkeypatch.setattr("modules.retry_queue.retry", _fake_retry)

    r = _client().post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is True
    assert called["pid"] == "p1"


def test_retry_nonexistent_item_is_blocked(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    def _boom(cfg, pid):
        raise AssertionError("존재하지 않는 item인데 retry()가 호출되면 안 된다")
    monkeypatch.setattr("modules.retry_queue.retry", _boom)

    r = _client().post("/api/costs/retry", json={"id": "does-not-exist"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is False
    assert "없음" in body["data"]["message"]


def test_retry_non_pending_item_is_blocked(monkeypatch):
    """list_pending()에 없는(=pending이 아닌) id는 실행되지 않는다 — 이 시스템엔
    'pending' 외 다른 status가 실제로 존재하지 않으므로, list_pending()에 없다는
    것 자체가 '존재하지 않거나 이미 처리됨'을 뜻한다(§8-B를 list_pending() 필터로
    구현 — retry_queue.py 원본은 수정하지 않는다)."""
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "other-item", "status": "pending"}])
    def _boom(cfg, pid):
        raise AssertionError("pending 목록에 없는 id로 retry()가 호출되면 안 된다")
    monkeypatch.setattr("modules.retry_queue.retry", _boom)

    r = _client().post("/api/costs/retry", json={"id": "already-done"}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["ok"] is False


def test_retry_ignores_client_supplied_queue_state(monkeypatch):
    """클라이언트가 body에 status='pending' 같은 값을 실어 보내도 RetryRequest는
    id 외 필드를 extra='forbid'로 거부하므로애초에 반영될 수 없다."""
    r = _client().post(
        "/api/costs/retry", headers=_auth(ADMIN_TOKEN),
        json={"id": "p1", "status": "pending", "error": None},
    )
    assert r.status_code == 422  # pydantic extra='forbid' 위반


def test_retry_duplicate_same_item_is_blocked_while_in_flight(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_retry(cfg, pid):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return True, "ok"

    monkeypatch.setattr("modules.retry_queue.retry", _slow_retry)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r2.json()["data"]["ok"] is False
    assert "처리 중" in r2.json()["data"]["message"]

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


def test_retry_different_items_can_run_independently(monkeypatch):
    """같은 pid의 중복만 막아야 한다 — 서로 다른 pid는 동시에 처리 가능해야 한다."""
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [
        {"id": "p1", "status": "pending"}, {"id": "p2", "status": "pending"},
    ])
    monkeypatch.setattr("modules.retry_queue.retry", lambda cfg, pid: (True, f"ok-{pid}"))

    client = _client()
    r1 = client.post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    r2 = client.post("/api/costs/retry", json={"id": "p2"}, headers=_auth(ADMIN_TOKEN))
    assert r1.json()["data"]["ok"] is True
    assert r2.json()["data"]["ok"] is True


def test_retry_no_new_retry_limit_invented():
    """§8-E: 기존 시스템에 retry count/limit이 없으므로 새로 만들지 않는다 —
    cost_service.py 소스에 그런 카운터/제한 로직이 없는지 확인."""
    import inspect
    from api.services import cost_service
    source = inspect.getsource(cost_service)
    for forbidden in ("retry_count", "max_retries", "retry_limit", "attempt_count"):
        assert forbidden not in source


def test_retry_failure_from_publish_surfaces_the_real_message(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    monkeypatch.setattr("modules.retry_queue.retry", lambda cfg, pid: (False, "재발행 실패: WordPress 연결 거부"))

    r = _client().post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["data"]["ok"] is False
    assert "WordPress" in body["data"]["message"]


# ══════════════════════════════════════════════════════════════════════════
# §13-15~19: Side effect 없음
# ══════════════════════════════════════════════════════════════════════════

def test_resume_never_touches_calculator_or_registry_or_deploy(monkeypatch):
    monkeypatch.setattr("modules.cost_manager.is_paused", lambda cfg: True)
    monkeypatch.setattr("modules.cost_manager.resume", lambda cfg: None)

    import sys
    blocked_modules = ["modules.app_factory"]
    originally_absent = [m for m in blocked_modules if m not in sys.modules]

    r = _client().post("/api/costs/resume", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in sys.modules, f"{m}이 resume 처리 중 새로 import됨(계산기 파이프라인 접근 의심)"


def test_retry_never_touches_calculator_or_registry_or_deploy(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    monkeypatch.setattr("modules.retry_queue.retry", lambda cfg, pid: (True, "ok"))

    import sys
    blocked_modules = ["modules.app_factory"]
    originally_absent = [m for m in blocked_modules if m not in sys.modules]

    r = _client().post("/api/costs/retry", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in sys.modules, f"{m}이 retry 처리 중 새로 import됨(계산기 파이프라인 접근 의심)"


def test_cost_service_source_never_references_protected_pipeline():
    """generate_app/save_app/build_contract 등 절대 보호 함수가 cost_service.py에
    전혀 언급되지 않는지 확인(호출 가능성 자체를 소스 레벨에서 배제)."""
    import inspect
    from api.services import cost_service
    source = inspect.getsource(cost_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "check_hold_rules", "validate_formula", "save_app",
        "CalculatorRepository", "registry_loader",
    ):
        assert forbidden not in source


def test_only_two_new_write_routes_added_under_costs():
    """이 STEP(S5) 시점엔 resume/retry 2개뿐이었다. STEP S6에서 remove가
    정당하게 추가되어 이제 3개다 — tests/test_cost_remove.py가 그 셋을 전담
    검증한다."""
    from _route_utils import write_routes
    from api.main import app
    assert sorted(write_routes(app, prefix="/api/costs")) == [
        ("/api/costs/remove", "POST"),
        ("/api/costs/resume", "POST"),
        ("/api/costs/retry", "POST"),
    ]
