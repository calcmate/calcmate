# -*- coding: utf-8 -*-
"""tests/test_cost_remove.py — STEP S6: Retry Queue Manual Remove React/FastAPI
이관 검증.

dashboard.py "🗑 제거" 버튼과 동일한 실행 의미를 검증한다. modules.retry_queue.
remove()의 실제 구현은 이 파일의 정상/차단 분기 테스트에서 monkeypatch로
대체한다. publisher.publish()/retry_queue.retry()/cost_manager.resume()은 이
파일의 어떤 테스트에서도 호출되지 않는다(Remove는 그 기능들과 완전히 독립적).
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "cost-rm-test-viewer-token"
ADMIN_TOKEN = "cost-rm-test-admin-token"


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
    from api.services import cost_service
    cost_service._retry_in_flight.clear()
    yield
    cost_service._retry_in_flight.clear()


@pytest.fixture(autouse=True)
def _block_retry_and_resume(monkeypatch):
    """Remove는 Retry/Resume과 완전히 독립적이어야 한다 — 이 파일의 어떤
    테스트에서도 호출되면 안 된다."""
    def _boom(*a, **k):
        raise AssertionError("Remove 처리 중 Retry/Resume 관련 함수가 호출되면 안 된다")
    monkeypatch.setattr("modules.retry_queue.retry", _boom)
    monkeypatch.setattr("modules.cost_manager.resume", _boom)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════
# §11-1~3: 인증
# ══════════════════════════════════════════════════════════════════════════

def test_remove_without_auth_returns_401():
    r = _client().post("/api/costs/remove", json={"id": "x"})
    assert r.status_code == 401


def test_remove_as_viewer_returns_403():
    r = _client().post("/api/costs/remove", json={"id": "x"}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_remove_as_admin_succeeds_for_a_real_pending_item(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    called = {}
    def _fake_remove(pid):
        called["pid"] = pid
    monkeypatch.setattr("modules.retry_queue.remove", _fake_remove)

    r = _client().post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is True
    assert called["pid"] == "p1"


# ══════════════════════════════════════════════════════════════════════════
# §11-4~5: 정상 삭제
# ══════════════════════════════════════════════════════════════════════════

def test_remove_calls_the_real_remove_function_with_correct_id(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [
        {"id": "target", "status": "pending"}, {"id": "other", "status": "pending"},
    ])
    called = {}
    monkeypatch.setattr("modules.retry_queue.remove", lambda pid: called.setdefault("pid", pid))

    r = _client().post("/api/costs/remove", json={"id": "target"}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["ok"] is True
    assert called["pid"] == "target"


def test_remove_disappears_from_subsequent_list(monkeypatch, tmp_path):
    """실제 retry_queue.remove()를 격리된 임시 파일에 대해 그대로 실행해,
    삭제 후 list_pending()에서 실제로 사라지는지 종단 확인한다(모듈 내부
    로직 자체는 재구현하지 않고 그대로 사용)."""
    import json
    from modules import retry_queue as RQ

    tmp_file = tmp_path / "pending_posts.json"
    tmp_file.write_text(json.dumps([
        {"id": "p1", "seo": {}, "html": "", "image_urls": {}, "error": "", "created_at": "t", "status": "pending"},
    ]), encoding="utf-8")
    monkeypatch.setattr(RQ, "_PATH", tmp_file)

    assert len(RQ.list_pending()) == 1
    r = _client().post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["ok"] is True
    assert RQ.list_pending() == []


# ══════════════════════════════════════════════════════════════════════════
# §11-6~9: 잘못된 입력
# ══════════════════════════════════════════════════════════════════════════

def test_remove_nonexistent_id_is_blocked(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    def _boom(pid):
        raise AssertionError("존재하지 않는 id인데 remove()가 호출되면 안 된다")
    monkeypatch.setattr("modules.retry_queue.remove", _boom)

    r = _client().post("/api/costs/remove", json={"id": "does-not-exist"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["ok"] is False
    assert "없음" in body["data"]["message"]


def test_remove_empty_id_returns_422():
    r = _client().post("/api/costs/remove", json={"id": ""}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422  # pydantic Field(min_length=1)


def test_remove_extra_field_returns_422():
    r = _client().post(
        "/api/costs/remove", headers=_auth(ADMIN_TOKEN),
        json={"id": "p1", "status": "pending"},
    )
    assert r.status_code == 422  # pydantic extra="forbid"


def test_remove_ignores_client_supplied_status(monkeypatch):
    """클라이언트가 status='pending'을 주장해도, 서버는 실제 list_pending()
    결과만 신뢰한다 — extra='forbid'로 그 필드 자체가 거부되므로 애초에
    반영될 수 없음을 위 422 테스트가 이미 증명하지만, 여기서는 실제로
    없는 item에 대해 그 어떤 클라이언트 주장도 통하지 않음을 재확인한다."""
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    r = _client().post("/api/costs/remove", json={"id": "ghost"}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["ok"] is False


# ══════════════════════════════════════════════════════════════════════════
# §11-10~11: 동시성
# ══════════════════════════════════════════════════════════════════════════

def test_remove_duplicate_same_id_is_blocked_while_in_flight(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_remove(pid):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr("modules.retry_queue.remove", _slow_remove)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r2.json()["data"]["ok"] is False
    assert "처리 중" in r2.json()["data"]["message"]

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


def test_remove_different_ids_run_independently(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [
        {"id": "p1", "status": "pending"}, {"id": "p2", "status": "pending"},
    ])
    monkeypatch.setattr("modules.retry_queue.remove", lambda pid: None)

    client = _client()
    r1 = client.post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    r2 = client.post("/api/costs/remove", json={"id": "p2"}, headers=_auth(ADMIN_TOKEN))
    assert r1.json()["data"]["ok"] is True
    assert r2.json()["data"]["ok"] is True


def test_remove_and_retry_share_the_inflight_guard_for_the_same_id(monkeypatch):
    """S5의 Retry in-flight 집합을 재사용하므로, 같은 id에 대해 Retry가
    진행 중이면 Remove도 차단되어야 한다(반대도 마찬가지) — 새 전역
    동시성 구조를 따로 만들지 않는다는 원칙의 실제 증명."""
    from api.services import cost_service
    cost_service._retry_in_flight.add("shared-id")
    try:
        r = _client().post("/api/costs/remove", json={"id": "shared-id"}, headers=_auth(ADMIN_TOKEN))
        assert r.json()["data"]["ok"] is False
        assert "처리 중" in r.json()["data"]["message"]
    finally:
        cost_service._retry_in_flight.discard("shared-id")


# ══════════════════════════════════════════════════════════════════════════
# §11-12~17: Side effect 없음
# ══════════════════════════════════════════════════════════════════════════

def test_remove_never_calls_publisher(monkeypatch):
    """remove()는 원본부터 publisher를 전혀 사용하지 않는다 — 이 테스트는
    그 사실이 앞으로도 유지되는지 회귀 방지 차원에서 확인한다."""
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    import sys
    originally_absent = "modules.publisher" not in sys.modules
    monkeypatch.setattr("modules.retry_queue.remove", lambda pid: None)

    r = _client().post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    if originally_absent:
        assert "modules.publisher" not in sys.modules


def test_remove_never_touches_calculator_or_registry(monkeypatch):
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [{"id": "p1", "status": "pending"}])
    monkeypatch.setattr("modules.retry_queue.remove", lambda pid: None)

    import sys
    originally_absent = [m for m in ("modules.app_factory",) if m not in sys.modules]
    r = _client().post("/api/costs/remove", json={"id": "p1"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in sys.modules, f"{m}이 remove 처리 중 새로 import됨(계산기 파이프라인 접근 의심)"


def test_cost_service_source_still_never_references_protected_pipeline():
    import inspect
    from api.services import cost_service
    source = inspect.getsource(cost_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "check_hold_rules", "validate_formula", "save_app",
        "CalculatorRepository", "registry_loader",
    ):
        assert forbidden not in source


def test_only_three_write_routes_exist_under_costs():
    from _route_utils import write_routes
    from api.main import app
    assert sorted(write_routes(app, prefix="/api/costs")) == [
        ("/api/costs/remove", "POST"),
        ("/api/costs/resume", "POST"),
        ("/api/costs/retry", "POST"),
    ]
