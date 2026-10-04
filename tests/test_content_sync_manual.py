# -*- coding: utf-8 -*-
"""tests/test_content_sync_manual.py — STEP S10: Content Sync Manual Sync
React/FastAPI 이관 검증.

dashboard.py "🔄 Sync Now" 버튼(dashboard.py:899-930)과 동일한 실행 의미를
검증한다. modules.content_sync.run_sync_once()의 실제 구현(진짜 WordPress
HTTP 호출 + 진짜 Sheet/DB write)은 이 파일의 어떤 테스트에서도 실행하지
않는다 — 항상 monkeypatch로 대체한다. Calculator/Registry/HOLD/Retry Queue
관련 함수가 호출되지 않는지도 구조적으로 확인한다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "content-sync-test-viewer-token"
ADMIN_TOKEN = "content-sync-test-admin-token"

FAKE_RESULT = {
    "ok": True, "mode": "recent", "adapter": "wordpress",
    "checked": 12, "changed": 2, "skipped": 0,
    "anomalies": [
        {"flag": "URL_CHANGED", "post_id": "101", "url": "http://x/1", "wp_status": "publish",
         "article_id": "a1", "title": "제목1"},
        {"flag": "ORPHAN_WP", "post_id": "202", "url": "http://x/2", "wp_status": "publish",
         "article_id": ""},
    ],
    "anomaly_count": 2,
    "started_at": "2026-09-05T00:00:00", "finished_at": "2026-09-05T00:00:05",
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


def _mock_lock_always_free(monkeypatch):
    monkeypatch.setattr("api.services.content_sync_service.load_config", lambda *a, **k: {})
    monkeypatch.setattr("modules.content_sync._acquire_lock", lambda cfg: True)
    monkeypatch.setattr("modules.content_sync._release_lock", lambda cfg: None)


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_run_without_auth_returns_401():
    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"})
    assert r.status_code == 401


def test_run_as_viewer_returns_403():
    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_as_admin_returns_200(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.content_sync.run_sync_once", lambda cfg, mode: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 입력 검증
# ══════════════════════════════════════════════════════════════════════════

def test_mode_defaults_to_recent_when_omitted(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    called = {}
    monkeypatch.setattr("modules.content_sync.run_sync_once", lambda cfg, mode: called.setdefault("mode", mode) or dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/content-sync/run-once", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert called["mode"] == "recent"


def test_invalid_mode_value_returns_422(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    r = _client().post(
        "/api/scheduler/content-sync/run-once", json={"mode": "everything"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 422


def test_extra_field_returns_422(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    r = _client().post(
        "/api/scheduler/content-sync/run-once", json={"mode": "recent", "force": True}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# 기존 함수 호출 확인 + 반환값 보존
# ══════════════════════════════════════════════════════════════════════════

def test_calls_the_real_run_sync_once_with_correct_args(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    called = {}
    def _spy(cfg, mode):
        called["cfg"] = cfg
        called["mode"] = mode
        return dict(FAKE_RESULT)
    monkeypatch.setattr("modules.content_sync.run_sync_once", _spy)
    monkeypatch.setattr("api.services.content_sync_service.load_config", lambda *a, **k: {"FAKE": True})

    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "full"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert called["mode"] == "full"
    assert called["cfg"] == {"FAKE": True}


def test_return_structure_passed_through_unmodified(monkeypatch):
    """run_sync_once()의 반환 구조를 임의로 재가공하지 않고 그대로 전달하는지
    확인 — 새로운 포맷을 설계하지 않는다는 원칙 검증."""
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.content_sync.run_sync_once", lambda cfg, mode: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data == FAKE_RESULT


def test_not_ok_result_is_a_clean_success_envelope_with_ok_false(monkeypatch):
    """dashboard.py의 "동기화 미실행" 케이스(WordPress 미구성 등) — run_sync_once()
    자체가 예외 없이 {"ok": False, "reason": ...}을 반환하는 정상 동작이다.
    HTTP 200 + 명확히 구분되는 data.ok=False 여야 하며, 애매한 구조가 아니다."""
    _mock_lock_always_free(monkeypatch)
    not_ready = {"ok": False, "reason": "adapter_not_ready", "mode": "recent", "checked": 0, "changed": 0, "anomalies": []}
    monkeypatch.setattr("modules.content_sync.run_sync_once", lambda cfg, mode: dict(not_ready))
    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] is False
    assert data["reason"] == "adapter_not_ready"


def test_unexpected_exception_does_not_produce_a_fabricated_success(monkeypatch):
    """run_sync_once() 자체에서 진짜 예상 밖 예외가 나면(blog/run-once의 기존
    처리 방식과 동일하게 — 그 endpoint도 일반 Exception을 별도로 잡지 않는다)
    성공으로 위장하지 않아야 한다. TestClient의 기본 raise_server_exceptions=True는
    테스트 코드로 예외를 재던지므로, 실제 배포된 서버가 클라이언트에게 실제로
    보여줄 응답(500)을 확인하려면 raise_server_exceptions=False로 확인한다."""
    _mock_lock_always_free(monkeypatch)
    def _boom(cfg, mode):
        raise RuntimeError("예상치 못한 오류(시뮬레이션)")
    monkeypatch.setattr("modules.content_sync.run_sync_once", _boom)

    from api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════
# 중복 실행 방지(기존 파일 lock 재사용 — 실제 lock 함수로 검증)
# ══════════════════════════════════════════════════════════════════════════

def test_lock_conflict_when_another_sync_holds_the_real_file_lock(monkeypatch, tmp_path):
    """기존 modules.content_sync._acquire_lock()/_release_lock()을 실제로(모킹
    없이) 격리된 tmp_path에 대해 사용해, 이미 lock이 걸려 있으면 LOCK_CONFLICT로
    명확히 차단되는지 확인한다(§6 — 기존 lock 재사용 검증)."""
    from modules import content_sync as CS
    monkeypatch.setattr(CS, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.content_sync_service.load_config", lambda *a, **k: {})

    # 이미 다른 동기화(자동 03:00 또는 다른 실행)가 lock을 보유 중인 상황을 재현.
    assert CS._acquire_lock({}) is True  # 최초 획득(다른 프로세스/스레드가 보유했다고 가정)
    def _boom(cfg, mode):
        raise AssertionError("lock이 걸려 있는데 run_sync_once()가 호출되면 안 된다")
    monkeypatch.setattr("modules.content_sync.run_sync_once", _boom)

    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"

    CS._release_lock({})  # 정리


def test_concurrent_requests_only_run_once_via_real_lock(monkeypatch, tmp_path):
    """실제 threading으로 두 요청이 진짜 겹치게 만들어, 실제 파일 lock이 두 번째
    요청을 차단하는지 확인한다(동일 요청 중복 실행 방지의 핵심 증거)."""
    from modules import content_sync as CS
    monkeypatch.setattr(CS, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.content_sync_service.load_config", lambda *a, **k: {})

    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_sync(cfg, mode):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return dict(FAKE_RESULT)

    monkeypatch.setattr("modules.content_sync.run_sync_once", _slow_sync)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r2.json()["error"]["code"] == "LOCK_CONFLICT"

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Side Effect 보호
# ══════════════════════════════════════════════════════════════════════════

def test_never_touches_calculator_registry_or_retry_queue(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("modules.content_sync.run_sync_once", lambda cfg, mode: dict(FAKE_RESULT))

    import sys as _sys
    originally_absent = [m for m in ("modules.app_factory", "modules.retry_queue") if m not in _sys.modules]

    r = _client().post("/api/scheduler/content-sync/run-once", json={"mode": "recent"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 Content Sync 실행 중 새로 import됨"


def test_service_source_never_references_protected_pipeline_or_other_write_functions():
    import inspect
    from api.services import content_sync_service
    source = inspect.getsource(content_sync_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "check_hold_rules", "validate_formula", "save_app",
        "CalculatorRepository", "registry_loader",
        "retry_queue", "cost_manager", "BudgetTracker",
    ):
        assert forbidden not in source


def test_only_one_new_write_route_added_under_content_sync():
    from _route_utils import write_routes
    from api.main import app
    # retry/resume은 ee475e5(Group A)에서 추가된 기존 sync 복구 route(PendingSync.jsx 사용).
    assert write_routes(app, prefix="/api/scheduler/content-sync") == [
        ("/api/scheduler/content-sync/resume", "POST"),
        ("/api/scheduler/content-sync/retry", "POST"),
        ("/api/scheduler/content-sync/run-once", "POST"),
    ]
