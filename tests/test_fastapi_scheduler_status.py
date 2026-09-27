# -*- coding: utf-8 -*-
"""tests/test_fastapi_scheduler_status.py — STEP 18-I-A WorkerManager 실제 상태 연결 검증.

실제 Scheduler(run_scheduler_loop/run_sync_loop)는 절대 실행하지 않는다. thread_alive
판정 로직만 검증하기 위해, 실제 워커와 동일한 이름의 "아무 일도 하지 않는" 더미 스레드를
테스트 더블로 잠깐 띄웠다가 join한다 — Blog 생성/Content Sync/실제 loop는 전혀 실행하지 않는다.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _route_utils import collect_routes
from api.services.config_service import ConfigService
from api.services.worker_manager import WorkerManager, get_worker_manager, _THREAD_NAMES


def _client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _real_config_enabled(section: str, default: bool) -> bool:
    return bool(ConfigService().get_section(section).get("enabled", default))


# ── config.enabled == status.enabled (실제 config 기준, 하드코딩 아님) ──────────

def test_blog_status_enabled_matches_real_config():
    expected = _real_config_enabled("BLOG_SCHEDULE", False)
    r = _client().get("/api/scheduler/blog/status")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["enabled"] is expected


def test_content_sync_status_enabled_matches_real_config():
    expected = _real_config_enabled("CONTENT_SYNC", True)
    r = _client().get("/api/scheduler/content-sync/status")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["enabled"] is expected


def test_calculator_status_enabled_matches_real_config():
    expected = _real_config_enabled("CALC_WEBAPP_SCHEDULE", False)
    r = _client().get("/api/scheduler/calculator/status")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["enabled"] is expected


# ── running/thread_alive: 실제 스레드가 없으면 False (mock으로 True를 지어내지 않는다) ──

def test_no_real_worker_thread_running_by_default():
    """이 테스트 프로세스에서는 아무 워커 스레드도 기동하지 않았으므로 전부 False여야 한다."""
    for name in ("blog", "calculator", "content_sync"):
        r = _client().get(f"/api/scheduler/{'content-sync' if name == 'content_sync' else name}/status")
        body = r.json()["data"]
        assert body["running"] is False, f"{name}: running should be False (no real thread started)"
        assert body["thread_alive"] is False, f"{name}: thread_alive should be False (no real thread started)"


# ── thread_alive 판정 로직 자체가 실제로 동작하는지: 테스트 더블(동일 이름의 무동작 스레드) ──

def test_thread_alive_detection_reflects_real_named_thread():
    """blog-scheduler-loop라는 이름의 더미(무동작) 스레드를 잠깐 띄워 real detection이
    True로 바뀌는지 확인한 뒤 join하여 정리한다. run_scheduler_loop()는 호출하지 않는다."""
    dummy = threading.Thread(target=lambda: time.sleep(0.4), name=_THREAD_NAMES["blog"], daemon=True)
    dummy.start()
    try:
        time.sleep(0.05)  # 스레드가 확실히 alive 상태가 되도록 짧게 대기
        r = _client().get("/api/scheduler/blog/status")
        body = r.json()["data"]
        assert body["running"] is True
        assert body["thread_alive"] is True
    finally:
        dummy.join(timeout=2)

    assert not dummy.is_alive()
    r2 = _client().get("/api/scheduler/blog/status")
    body2 = r2.json()["data"]
    assert body2["running"] is False
    assert body2["thread_alive"] is False


# ── running == thread_alive (동일 실측 신호, §9 설계 의도 문서화) ─────────────────

def test_running_and_thread_alive_share_the_same_signal():
    wm = WorkerManager()
    for name in ("blog", "calculator", "content_sync"):
        status = wm.get_status(name)
        assert status["running"] == status["thread_alive"]


# ── Singleton (§7) ──────────────────────────────────────────────────────────

def test_worker_manager_is_process_singleton():
    assert get_worker_manager() is get_worker_manager()


def test_get_status_without_name_returns_all_three():
    wm = WorkerManager()
    all_status = wm.get_status()
    assert set(all_status.keys()) == {"blog", "calculator", "content_sync"}


# ── start/stop는 여전히 미구현(실제 기동/정지는 이번 STEP 범위 밖) ───────────────

def test_start_stop_still_not_implemented():
    wm = WorkerManager()
    import pytest
    with pytest.raises(NotImplementedError):
        wm.start_worker("blog")
    with pytest.raises(NotImplementedError):
        wm.stop_worker("blog")


# ── 쓰기 endpoint가 여전히 없는지(§17: config/today/history/run-once 보호, status만 변경) ──

def test_status_endpoints_are_get_only():
    """STEP 18-N: tests/_route_utils.collect_routes()로 nested router까지 재귀
    수집해 검사한다(app.routes 얕은 순회는 vacuously PASS했음 — STEP 18-M 발견)."""
    from api.main import app
    status_routes = [r for r in collect_routes(app) if r.path.endswith("/status") and "/scheduler/" in r.path]
    assert len(status_routes) >= 3, "실제 scheduler status route를 하나도 못 찾았다면 collector가 잘못된 것이다"
    for r in status_routes:
        assert r.methods & {"POST", "PATCH", "PUT", "DELETE"} == frozenset(), f"{r.path} must stay GET-only"
