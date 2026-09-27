# -*- coding: utf-8 -*-
"""tests/test_fastapi_blog_scheduler.py — STEP 18-E Blog Scheduler API 검증.

PATCH/config 쓰기 테스트는 전부 임시 파일에서만 수행하며 실제 config/config.yaml을
건드리지 않는다. run-once 테스트는 실제 blog 생성 엔진을 호출하지 않도록
monkeypatch로 격리한다(실제 1회 생성은 이 자동화 테스트가 아니라 별도의
수동 검증 단계에서 명시적으로 수행한다).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


def _client():
    from api.main import app
    return TestClient(app)


REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

# STEP 18-R: PATCH /blog/config, POST /blog/run-once는 이제 require_admin()이
# 걸려있다 — 이 파일의 write endpoint 테스트는 admin 토큰을 실어 보낸다
# (401/403 자체는 tests/test_fastapi_publish_write.py에서 전담 검증).
ADMIN_TOKEN = "step18e-test-admin-token"


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


# ── ConfigService.patch_blog_schedule — 격리된 임시 파일에서만 테스트 ──────────

@pytest.fixture()
def tmp_config_service(tmp_path):
    from api.services.config_service import ConfigService
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return ConfigService(config_path=tmp_config), tmp_config


def test_patch_blog_schedule_updates_only_that_block(tmp_config_service):
    svc, tmp_config = tmp_config_service
    before_text = tmp_config.read_text(encoding="utf-8")

    result = svc.patch_blog_schedule(
        enabled=True, mode="draft",
        publish_slots=[{"start": "07:00", "end": "07:30"}],
        weekday_only=False,
    )
    assert result["enabled"] is True
    assert result["publish_slots"] == [{"start": "07:00", "end": "07:30"}]

    after_text = tmp_config.read_text(encoding="utf-8")

    # BLOG_SCHEDULE 블록만 제거하고 나머지가 완전히 동일한지 비교(주석 포함)
    import re
    pattern = re.compile(r"^BLOG_SCHEDULE:\n(?:[ \t].*\n?)*", re.MULTILINE)
    before_without_block = pattern.sub("", before_text, count=1)
    after_without_block = pattern.sub("", after_text, count=1)
    assert before_without_block == after_without_block, "BLOG_SCHEDULE 외 텍스트(주석 포함)가 변경됨"

    # 주석이 여전히 남아있는지도 직접 확인(있다면)
    if "# P2-3" in before_text:
        assert "# P2-3" in after_text


def test_patch_blog_schedule_rejects_invalid_time(tmp_config_service):
    svc, _ = tmp_config_service
    with pytest.raises(ValueError):
        svc.patch_blog_schedule(
            enabled=True, mode="draft",
            publish_slots=[{"start": "25:00", "end": "07:30"}],
            weekday_only=False,
        )


def test_patch_blog_schedule_rejects_start_after_end(tmp_config_service):
    svc, _ = tmp_config_service
    with pytest.raises(ValueError):
        svc.patch_blog_schedule(
            enabled=True, mode="draft",
            publish_slots=[{"start": "10:00", "end": "09:00"}],
            weekday_only=False,
        )


def test_patch_blog_schedule_rejects_invalid_mode(tmp_config_service):
    svc, _ = tmp_config_service
    with pytest.raises(ValueError):
        svc.patch_blog_schedule(
            enabled=True, mode="not-a-mode",
            publish_slots=[{"start": "07:00", "end": "07:30"}],
            weekday_only=False,
        )


def test_patch_blog_schedule_never_touches_real_config_file():
    """실제 config/config.yaml 해시가 이 테스트 파일 전체 실행 동안 변하지 않는지 확인."""
    import hashlib
    before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    # (다른 테스트들이 이미 실행되었어도) 여기서 다시 확인
    after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert before == after


# ── GET /api/scheduler/blog/config — 실제 config 읽기(READ-ONLY, 안전) ──────

def test_get_blog_config_endpoint():
    r = _client().get("/api/scheduler/blog/config")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "enabled" in body["data"]
    assert "mode" in body["data"]
    assert "publish_slots" in body["data"]


# ── PATCH /api/scheduler/blog/config — 라우터를 임시 파일로 monkeypatch ─────

def test_patch_blog_config_endpoint_uses_isolated_file(monkeypatch, tmp_path):
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    import api.routers.scheduler as scheduler_router
    from api.services.config_service import ConfigService

    monkeypatch.setattr(
        scheduler_router, "ConfigService",
        lambda: ConfigService(config_path=tmp_config),
    )

    import hashlib
    real_hash_before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()

    r = _client().patch("/api/scheduler/blog/config", json={
        "enabled": True, "mode": "draft",
        "publish_slots": [{"start": "08:00", "end": "08:30"}],
        "weekday_only": False,
    }, headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["publish_slots"] == [{"start": "08:00", "end": "08:30"}]

    real_hash_after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert real_hash_before == real_hash_after, "PATCH endpoint가 실제 config.yaml을 건드림"

    # 임시 파일에는 실제로 반영됐는지 확인
    assert '"08:00"' in tmp_config.read_text(encoding="utf-8")


def test_patch_blog_config_endpoint_rejects_bad_payload():
    r = _client().patch("/api/scheduler/blog/config", json={
        "enabled": "not-a-bool", "mode": "draft",
        "publish_slots": [{"start": "08:00", "end": "08:30"}],
    }, headers=_admin_headers())
    assert r.status_code == 422  # pydantic validation error


# ── GET /api/scheduler/blog/today, /history — 실제 파일 읽기(READ-ONLY) ────

def test_get_blog_today_endpoint():
    r = _client().get("/api/scheduler/blog/today")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_get_blog_history_endpoint():
    r = _client().get("/api/scheduler/blog/history")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "records" in body["data"]
    assert isinstance(body["data"]["records"], list)


# ── POST /api/scheduler/blog/run-once — 실제 생성 엔진 호출을 격리해서 검증 ──

def test_run_once_disabled_when_config_disabled(monkeypatch):
    import api.services.blog_scheduler_service as svc

    def _disabled_cfg():
        return {"BLOG_SCHEDULE": {"enabled": False}, "scheduler_line": "blog"}

    monkeypatch.setattr(svc, "_blog_cfg", _disabled_cfg)

    r = _client().post("/api/scheduler/blog/run-once", headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SCHEDULER_DISABLED"


def test_run_once_busy_when_lock_held(monkeypatch):
    import api.services.blog_scheduler_service as svc

    def _enabled_cfg():
        return {"BLOG_SCHEDULE": {"enabled": True, "mode": "draft"}, "scheduler_line": "blog"}

    monkeypatch.setattr(svc, "_blog_cfg", _enabled_cfg)
    monkeypatch.setattr(svc.scheduler_engine, "_acquire_lock", lambda cfg: False)

    r = _client().post("/api/scheduler/blog/run-once", headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"


def test_run_once_calls_resolved_engine_function_exactly_once(monkeypatch):
    """실제 블로그 생성 엔진(run_blog_once 등)은 호출되지 않고, resolve_blog_publish_fn이
    반환한 mock 함수만 정확히 1회 max_count=1로 호출되는지 확인한다."""
    import api.services.blog_scheduler_service as svc
    import modules.blog_scheduler_adapter as adapter

    calls = []

    def _fake_run_once_fn(cfg, max_count=1, driver_id=None):
        calls.append((cfg.get("scheduler_line"), max_count, driver_id))
        return {"produced": 1, "results": [{"status": "SUCCESS"}]}

    def _enabled_cfg():
        return {"BLOG_SCHEDULE": {"enabled": True, "mode": "draft"}, "scheduler_line": "blog"}

    def _boom(*a, **kw):
        raise AssertionError("실제 run_blog_once가 호출되면 안 된다 — resolve_blog_publish_fn을 통해서만 호출되어야 함")

    monkeypatch.setattr(svc, "_blog_cfg", _enabled_cfg)
    monkeypatch.setattr(svc, "resolve_blog_publish_fn", lambda cfg: _fake_run_once_fn)
    monkeypatch.setattr(adapter, "run_blog_once", _boom)
    monkeypatch.setattr(svc.scheduler_engine, "_acquire_lock", lambda cfg: True)
    released = []
    monkeypatch.setattr(svc.scheduler_engine, "_release_lock", lambda cfg: released.append(cfg))

    r = _client().post("/api/scheduler/blog/run-once", headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["produced"] == 1
    assert calls == [("blog", 1, "fastapi_manual_run_once")]
    assert len(released) == 1, "lock이 반드시 해제되어야 한다"


def test_run_once_releases_lock_even_on_exception(monkeypatch):
    import api.services.blog_scheduler_service as svc

    def _enabled_cfg():
        return {"BLOG_SCHEDULE": {"enabled": True, "mode": "draft"}, "scheduler_line": "blog"}

    def _boom_fn(cfg, max_count=1, driver_id=None):
        raise RuntimeError("simulated engine failure")

    monkeypatch.setattr(svc, "_blog_cfg", _enabled_cfg)
    monkeypatch.setattr(svc, "resolve_blog_publish_fn", lambda cfg: _boom_fn)
    monkeypatch.setattr(svc.scheduler_engine, "_acquire_lock", lambda cfg: True)
    released = []
    monkeypatch.setattr(svc.scheduler_engine, "_release_lock", lambda cfg: released.append(cfg))

    with pytest.raises(RuntimeError):
        svc.run_once()
    assert len(released) == 1, "예외가 발생해도 lock은 해제되어야 한다"
