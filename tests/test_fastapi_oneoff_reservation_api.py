# -*- coding: utf-8 -*-
"""tests/test_fastapi_oneoff_reservation_api.py — CALCMATE-STREAMLIT-RESERVATION-
API-IMPLEMENT-01 검증(Phase A).

3개 신규 endpoint(POST /api/scheduler/blog/oneoff, GET /api/scheduler/topics,
POST /api/scheduler/planner/run-once)를 검증한다. 전부 monkeypatch로 실제
modules.scheduler/modules.topic_pool/modules.publishing_planner 호출을 격리해
실제 파일/DB/WP를 건드리지 않는다(실제 예약 생성/Topic 상태 변경/WP 요청 없음).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


def _client():
    from api.main import app
    return TestClient(app)


ADMIN_TOKEN = "reservation-api-test-admin-token"
VIEWER_TOKEN = "reservation-api-test-viewer-token"


@pytest.fixture(autouse=True)
def _tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _viewer_headers():
    return {"Authorization": f"Bearer {VIEWER_TOKEN}"}


# ── POST /api/scheduler/blog/oneoff — 예약 생성(add_oneoff_reservation()에 위임) ──

def test_create_oneoff_reservation_delegates_to_add_oneoff_reservation(monkeypatch):
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    calls = []

    def _fake_add(cfg, scheduled_at, mode, lock_retries=5, lock_retry_interval=0.5, topic_id=None):
        calls.append((cfg.get("scheduler_line"), scheduled_at.isoformat(), mode, topic_id))
        return {
            "id": "oneoff_test_1", "scheduled_at": scheduled_at.isoformat(),
            "mode": mode, "status": "pending", "created_at": scheduled_at.isoformat(),
            "executed_at": None, "result": None, "duplicate": False, "topic_id": topic_id,
        }

    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", _fake_add)
    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: {"topic_id": topic_id, "status": "approved"})
    transitions = []
    monkeypatch.setattr(topic_pool, "transition_status", lambda cfg, topic_id, to_status, **kw: transitions.append((topic_id, to_status)))
    updates = []
    monkeypatch.setattr(topic_pool, "update_topic", lambda cfg, topic_id, **fields: updates.append((topic_id, fields)))

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_1"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is True
    assert body["data"]["id"] == "oneoff_test_1"
    assert body["data"]["duplicate"] is False
    assert calls == [("blog", "2026-10-01T14:00:00+09:00", "draft", "topic_1")]
    assert transitions == [("topic_1", "scheduled")]
    assert updates == [("topic_1", {"oneoff_reservation_id": "oneoff_test_1"})]


def test_create_oneoff_reservation_without_topic_id(monkeypatch):
    from api.services import blog_scheduler_service as svc

    def _fake_add(cfg, scheduled_at, mode, lock_retries=5, lock_retry_interval=0.5, topic_id=None):
        entry = {
            "id": "oneoff_test_2", "scheduled_at": scheduled_at.isoformat(),
            "mode": mode, "status": "pending", "created_at": scheduled_at.isoformat(),
            "executed_at": None, "result": None, "duplicate": False,
        }
        if topic_id is not None:
            entry["topic_id"] = topic_id
        return entry

    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", _fake_add)

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "publish"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is True
    assert "topic_id" not in body["data"]


def test_create_oneoff_reservation_rejects_invalid_mode():
    # mode는 Literal["draft","publish"]이므로 FastAPI가 422로 거부한다(add_oneoff_
    # reservation()까지 도달하지 않음 — validation은 그 함수의 것을 그대로 재현).
    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "bogus"},
        headers=_admin_headers(),
    )
    assert r.status_code == 422


def test_create_oneoff_reservation_rejects_naive_datetime(monkeypatch):
    from api.services import blog_scheduler_service as svc

    def _real_add(cfg, scheduled_at, mode, lock_retries=5, lock_retry_interval=0.5, topic_id=None):
        # 실제 add_oneoff_reservation()의 naive datetime 거부 계약을 그대로 재현.
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at은 timezone-aware datetime이어야 합니다(naive 금지)")
        raise AssertionError("naive datetime 검증 실패 시 여기 도달하면 안 됨")

    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", _real_add)

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00", "mode": "draft"},  # 오프셋 없음(naive)
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_create_oneoff_reservation_returns_duplicate_without_new_entry(monkeypatch):
    from api.services import blog_scheduler_service as svc

    def _fake_add(cfg, scheduled_at, mode, lock_retries=5, lock_retry_interval=0.5, topic_id=None):
        return {
            "id": "oneoff_existing", "scheduled_at": scheduled_at.isoformat(),
            "mode": mode, "status": "pending", "created_at": scheduled_at.isoformat(),
            "executed_at": None, "result": None, "duplicate": True,
        }

    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", _fake_add)

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is True
    assert body["data"]["duplicate"] is True
    assert body["data"]["id"] == "oneoff_existing"


def test_create_oneoff_reservation_lock_conflict(monkeypatch):
    from api.services import blog_scheduler_service as svc

    def _fake_add(cfg, scheduled_at, mode, lock_retries=5, lock_retry_interval=0.5, topic_id=None):
        raise RuntimeError("1회성 예약 lock 획득 실패")

    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", _fake_add)

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"


def test_create_oneoff_reservation_requires_authentication():
    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft"},
    )
    assert r.status_code == 401


def test_create_oneoff_reservation_forbidden_for_viewer():
    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft"},
        headers=_viewer_headers(),
    )
    assert r.status_code == 403


# ── CALCMATE-DIRECT-RESERVATION-IMPLEMENT-01: topic_id 직접 예약의 approved→scheduled ──

def _reject_status_case(monkeypatch, status):
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    add_calls = []
    monkeypatch.setattr(
        svc.scheduler_engine, "add_oneoff_reservation",
        lambda *a, **kw: add_calls.append(1) or {"id": "should_not_be_created", "duplicate": False},
    )
    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: {"topic_id": topic_id, "status": status})

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_x"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert add_calls == []  # 예약 생성 자체가 시도되지 않음


def test_create_oneoff_reservation_rejects_scheduled_topic(monkeypatch):
    _reject_status_case(monkeypatch, "scheduled")


def test_create_oneoff_reservation_rejects_published_topic(monkeypatch):
    _reject_status_case(monkeypatch, "published")


def test_create_oneoff_reservation_rejects_publish_failed_topic(monkeypatch):
    _reject_status_case(monkeypatch, "publish_failed")


def test_create_oneoff_reservation_rejects_nonexistent_topic(monkeypatch):
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    add_calls = []
    monkeypatch.setattr(
        svc.scheduler_engine, "add_oneoff_reservation",
        lambda *a, **kw: add_calls.append(1) or {"id": "should_not_be_created", "duplicate": False},
    )
    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: None)

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_missing"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert add_calls == []


def test_create_oneoff_reservation_keeps_topic_approved_when_add_fails(monkeypatch):
    # add_oneoff_reservation() 자체가 실패(RuntimeError)하면 transition_status()가
    # 전혀 호출되지 않아야 한다 — Topic은 approved로 남는다.
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: {"topic_id": topic_id, "status": "approved"})
    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lock busy")))
    transition_calls = []
    monkeypatch.setattr(topic_pool, "transition_status", lambda *a, **kw: transition_calls.append(1))

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_y"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"
    assert transition_calls == []  # Topic 전이 시도 자체가 없었음(approved로 남음)


def test_create_oneoff_reservation_duplicate_does_not_transition_topic(monkeypatch):
    # duplicate=True(기존 pending 예약을 그대로 반환)면 Topic 전이를 절대 호출하지 않는다.
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: {"topic_id": topic_id, "status": "approved"})
    monkeypatch.setattr(
        svc.scheduler_engine, "add_oneoff_reservation",
        lambda *a, **kw: {"id": "oneoff_existing", "duplicate": True},
    )
    transition_calls = []
    update_calls = []
    monkeypatch.setattr(topic_pool, "transition_status", lambda *a, **kw: transition_calls.append(1))
    monkeypatch.setattr(topic_pool, "update_topic", lambda *a, **kw: update_calls.append(1))

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_z"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is True
    assert body["data"]["duplicate"] is True
    assert transition_calls == []
    assert update_calls == []


def test_create_oneoff_reservation_transition_failure_leaves_reservation_pending_and_topic_approved(monkeypatch):
    # 예약 생성은 성공했지만 transition_status()가 실패하는 경우: 새 rollback 코드는
    # 없으므로 reservation은 이미 pending으로 만들어진 채로 남고(반환은 실패 응답),
    # Topic도 approved로 남는다(전이 자체가 예외로 끝나 저장되지 않음).
    from api.services import blog_scheduler_service as svc
    from modules import topic_pool

    monkeypatch.setattr(topic_pool, "get_topic", lambda cfg, topic_id: {"topic_id": topic_id, "status": "approved"})
    created = {"id": "oneoff_created_before_transition_failure", "duplicate": False}
    monkeypatch.setattr(svc.scheduler_engine, "add_oneoff_reservation", lambda *a, **kw: created)
    monkeypatch.setattr(
        topic_pool, "transition_status",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("금지된 전이: 'approved' -> 'scheduled'")),
    )
    update_calls = []
    monkeypatch.setattr(topic_pool, "update_topic", lambda *a, **kw: update_calls.append(1))

    r = _client().post(
        "/api/scheduler/blog/oneoff",
        json={"scheduled_at": "2026-10-01T14:00:00+09:00", "mode": "draft", "topic_id": "topic_w"},
        headers=_admin_headers(),
    )
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert update_calls == []  # transition이 실패했으므로 update_topic까지 도달하지 않음


# ── GET /api/scheduler/topics — Topic Pool 조회(list_topics()에 위임) ──────────

def test_get_topics_delegates_to_list_topics_and_selects_minimal_fields(monkeypatch):
    from api.services import topic_pool_service as svc

    def _fake_list_topics(cfg, status=None):
        assert status == "approved"
        return [{
            "topic_id": "topic_1", "slug": "slug-1", "topic": "토픽1", "title": "제목1",
            "status": "approved", "priority": 0, "created_at": "2026-09-01T00:00:00+09:00",
            "approved_at": "2026-09-02T00:00:00+09:00", "status_history": [{"to_status": "approved"}],
            "sync_status": "synced", "matched_content_id": None,
        }]

    monkeypatch.setattr(svc.topic_pool, "list_topics", _fake_list_topics)

    r = _client().get("/api/scheduler/topics?status=approved")
    body = r.json()
    assert body["success"] is True
    topics = body["data"]["topics"]
    assert len(topics) == 1
    assert set(topics[0].keys()) == {
        "topic_id", "slug", "topic", "title", "status", "priority", "created_at", "approved_at",
    }
    assert "status_history" not in topics[0]
    assert "sync_status" not in topics[0]


def test_get_topics_no_auth_required(monkeypatch):
    from api.services import topic_pool_service as svc
    monkeypatch.setattr(svc.topic_pool, "list_topics", lambda cfg, status=None: [])

    r = _client().get("/api/scheduler/topics")
    assert r.status_code == 200
    assert r.json()["success"] is True


# ── POST /api/scheduler/planner/run-once — Planner 실행(run_planner_once()에 위임) ──

def test_planner_run_once_delegates_to_run_planner_once(monkeypatch):
    from api.services import publishing_planner_service as svc

    captured_cfg = {}

    def _fake_run_planner_once(cfg):
        captured_cfg.update(cfg)
        return {"scheduled": 2, "reason": "", "results": [
            {"topic_id": "topic_1", "status": "SCHEDULED", "reservation_id": "oneoff_1"},
            {"topic_id": "topic_2", "status": "SCHEDULED", "reservation_id": "oneoff_2"},
        ]}

    monkeypatch.setattr(svc, "_run_planner_once", _fake_run_planner_once)

    r = _client().post("/api/scheduler/planner/run-once", headers=_admin_headers())
    body = r.json()
    assert body["success"] is True
    assert body["data"]["scheduled"] == 2
    assert len(body["data"]["results"]) == 2
    # Worker(scheduler_line="blog")가 실제로 읽는 파일과 일치하는 cfg로 호출됐는지 확인
    assert captured_cfg.get("scheduler_line") == "blog"


def test_planner_run_once_no_approved_topics(monkeypatch):
    from api.services import publishing_planner_service as svc
    monkeypatch.setattr(svc, "_run_planner_once", lambda cfg: {"scheduled": 0, "reason": "no_approved_topics", "results": []})

    r = _client().post("/api/scheduler/planner/run-once", headers=_admin_headers())
    body = r.json()
    assert body["success"] is True
    assert body["data"]["scheduled"] == 0
    assert body["data"]["reason"] == "no_approved_topics"


def test_planner_run_once_requires_authentication():
    r = _client().post("/api/scheduler/planner/run-once")
    assert r.status_code == 401


# ── CALCMATE-PLANNER-WP-TARGET-FIX-01: wp_target이 CALCMATE_WP_TARGET과 일치하는지 ──

def test_planner_run_once_uses_production_wp_target_when_env_set(monkeypatch):
    from api.services import publishing_planner_service as svc

    monkeypatch.setenv("CALCMATE_WP_TARGET", "production")
    captured = {}

    def _fake_load_config(*, wp_target=None):
        captured["wp_target"] = wp_target
        return {"WORDPRESS_URL": "https://blog.genon.app"}

    monkeypatch.setattr(svc, "load_config", _fake_load_config)
    monkeypatch.setattr(svc, "_run_planner_once", lambda cfg: {"scheduled": 0, "reason": "", "results": []})

    r = _client().post("/api/scheduler/planner/run-once", headers=_admin_headers())
    assert r.json()["success"] is True
    assert captured["wp_target"] == "production"


def test_planner_run_once_uses_local_wp_target_when_env_unset(monkeypatch):
    from api.services import publishing_planner_service as svc

    monkeypatch.delenv("CALCMATE_WP_TARGET", raising=False)
    captured = {}

    def _fake_load_config(*, wp_target=None):
        captured["wp_target"] = wp_target
        return {"WORDPRESS_URL": "http://salarymate.test"}

    monkeypatch.setattr(svc, "load_config", _fake_load_config)
    monkeypatch.setattr(svc, "_run_planner_once", lambda cfg: {"scheduled": 0, "reason": "", "results": []})

    r = _client().post("/api/scheduler/planner/run-once", headers=_admin_headers())
    assert r.json()["success"] is True
    assert captured["wp_target"] == "local"


def test_planner_run_once_still_sets_scheduler_line_blog_with_production_target(monkeypatch):
    from api.services import publishing_planner_service as svc

    monkeypatch.setenv("CALCMATE_WP_TARGET", "production")
    monkeypatch.setattr(svc, "load_config", lambda *, wp_target=None: {"WORDPRESS_URL": "https://blog.genon.app"})

    captured_cfg = {}

    def _fake_run_planner_once(cfg):
        captured_cfg.update(cfg)
        return {"scheduled": 0, "reason": "", "results": []}

    monkeypatch.setattr(svc, "_run_planner_once", _fake_run_planner_once)

    r = _client().post("/api/scheduler/planner/run-once", headers=_admin_headers())
    assert r.json()["success"] is True
    assert captured_cfg.get("scheduler_line") == "blog"
    assert captured_cfg.get("WORDPRESS_URL") == "https://blog.genon.app"


def test_planner_run_once_forbidden_for_viewer():
    r = _client().post("/api/scheduler/planner/run-once", headers=_viewer_headers())
    assert r.status_code == 403
