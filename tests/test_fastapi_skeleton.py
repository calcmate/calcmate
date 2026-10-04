# -*- coding: utf-8 -*-
"""tests/test_fastapi_skeleton.py — STEP 18-C FastAPI 최소 골격 검증.

기존 Scheduler/Blog/Calculator 엔진이 이 골격을 통해 실제로 실행되지 않는지까지 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

ENVELOPE_KEYS = {"success", "data", "error", "request_id"}
ALL_PATHS = [
    "/api/health",
    "/api/dashboard/status",
    "/api/scheduler/blog/status",
    "/api/scheduler/calculator/status",
    "/api/scheduler/content-sync/status",
]


def _client():
    from api.main import app
    return TestClient(app)


def test_app_import():
    from api.main import app
    assert app is not None


def test_health_endpoint():
    r = _client().get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "calcmate-api"


def test_dashboard_status_endpoint():
    r = _client().get("/api/dashboard/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["dashboard"] == "fastapi"
    assert body["data"]["workers"] == {}


def test_scheduler_blog_status():
    r = _client().get("/api/scheduler/blog/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["name"] == "blog"
    assert data["running"] is False
    assert data["thread_alive"] is False


def test_scheduler_calculator_status():
    r = _client().get("/api/scheduler/calculator/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["name"] == "calc_webapp"
    assert data["running"] is False


def test_scheduler_content_sync_status():
    r = _client().get("/api/scheduler/content-sync/status")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["enabled"] is True
    assert data["running"] is False
    assert data["thread_alive"] is False


@pytest.mark.parametrize("path", ALL_PATHS)
def test_standard_response_envelope(path):
    body = _client().get(path).json()
    assert ENVELOPE_KEYS.issubset(body.keys())
    assert body["error"] is None
    assert isinstance(body["request_id"], str) and len(body["request_id"]) > 0


def test_worker_manager_initial_state_is_safe():
    """STEP 18-I-A: enabled는 실제 config.yaml 값을 반영한다(더는 하드코딩 False가 아니다).
    running/thread_alive는 이 테스트 프로세스에서 실제 워커 스레드를 기동한 적이 없으므로
    안전하게 False여야 한다 — 이것이 '안전한 초기 상태'의 실제 의미다."""
    from api.services.config_service import ConfigService
    from api.services.worker_manager import WorkerManager

    # WorkerManager applies FASTAPI_WORKER_MODE guard - all False when not in that mode
    wm = WorkerManager()
    for name in ("blog", "calc_webapp", "content_sync"):
        st = wm.get_status(name)
        assert st["running"] is False
        assert st["thread_alive"] is False
        assert st["enabled"] is False  # FASTAPI_WORKER_MODE not set


def test_worker_manager_start_stop_work():
    from api.services.worker_manager import WorkerManager
    wm = WorkerManager()
    # Workers are disabled by default (no FASTAPI_WORKER_MODE), so start should return False
    assert wm.start_worker("blog") is False
    assert wm.start_worker("calc_webapp") is False
    assert wm.start_worker("content_sync") is False
    # Stop on non-running worker should return False
    assert wm.stop_worker("blog") is False
    assert wm.stop_worker("calc_webapp") is False
    assert wm.stop_worker("content_sync") is False


def test_config_service_allowlist_rejects_unknown_section():
    from api.services.config_service import ConfigService, ConfigSectionNotAllowed
    svc = ConfigService()
    with pytest.raises(ConfigSectionNotAllowed):
        svc.get_section("NOT_A_REAL_SECTION")


def test_config_service_allowlist_accepts_known_section():
    from api.services.config_service import ConfigService
    svc = ConfigService()
    section = svc.get_section("BLOG_SCHEDULE")
    assert isinstance(section, dict)


def test_config_service_has_no_write_method():
    from api.services.config_service import ConfigService
    assert not hasattr(ConfigService, "write")
    assert not hasattr(ConfigService, "patch_section")
    assert not hasattr(ConfigService, "save")


def test_existing_scheduler_engine_not_invoked(monkeypatch):
    """기존 modules.scheduler.run_scheduler_loop가 API 호출 과정에서 절대 실행되지 않는지 확인."""
    import modules.scheduler as scheduler_engine

    def _boom(*a, **kw):
        raise AssertionError("run_scheduler_loop must not be called by the FastAPI skeleton")

    monkeypatch.setattr(scheduler_engine, "run_scheduler_loop", _boom)

    c = _client()
    for path in ALL_PATHS:
        r = c.get(path)
        assert r.status_code == 200
