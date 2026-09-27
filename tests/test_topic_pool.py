# -*- coding: utf-8 -*-
"""
tests/test_topic_pool.py
CALCMATE-AUTO-CONTENT-TOPIC-IMPLEMENT-01 — Topic Pool storage/CRUD/state
machine 검증.

전부 tmp_path로 격리된 SQLite를 사용한다 — 실제 production DB/Sheets에는
어떤 topic도 생성하지 않는다. Golden10/calculators/blog_articles/
oneoff_schedule.json은 이 테스트에서 전혀 참조하지 않는다(단, Golden10
보호 테스트는 원본이 실제로 불변임을 별도로 증명하기 위해 읽기만 한다).
"""
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.topic_pool as tp


def _cfg(tmp_path):
    return {"_root": str(tmp_path), "SQLITE_PATH": "test_topic_pool.db",
            "DB_ADAPTER": "sqlite"}


def _make(cfg, **overrides):
    kwargs = dict(slug="jeonse-vs-monthly", topic="전세vs월세 신규 topic",
                  intent="howto", title="t", priority=100)
    kwargs.update(overrides)
    return tp.create_topic(cfg, **kwargs)


# ── 기본 CRUD ────────────────────────────────────────────────────────

def test_create_topic_defaults(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    assert t["status"] == "candidate"
    assert t["slug"] == "jeonse-vs-monthly"
    assert t["intent"] == "howto"
    assert t["priority"] == 100
    assert t["failure_count"] == 0
    assert t["approved_at"] is None
    assert len(t["status_history"]) == 1
    assert t["status_history"][0]["to_status"] == "candidate"


def test_create_topic_rejects_empty_slug(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        _make(cfg, slug="")


def test_create_topic_rejects_empty_topic(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        _make(cfg, topic="")


def test_create_topic_rejects_invalid_intent(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        _make(cfg, intent="not_a_valid_intent")


def test_get_topic_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    created = _make(cfg)
    fetched = tp.get_topic(cfg, created["topic_id"])
    assert fetched is not None
    assert fetched["topic_id"] == created["topic_id"]
    assert fetched["topic"] == created["topic"]


def test_get_topic_nonexistent_returns_none(tmp_path):
    cfg = _cfg(tmp_path)
    assert tp.get_topic(cfg, "nonexistent_topic_id") is None


def test_list_topics_returns_all(tmp_path):
    cfg = _cfg(tmp_path)
    _make(cfg)
    _make(cfg, slug="bmi-calculator")
    result = tp.list_topics(cfg)
    assert len(result) == 2


def test_list_topics_filters_by_status(tmp_path):
    cfg = _cfg(tmp_path)
    a = _make(cfg)
    b = _make(cfg, slug="bmi-calculator")
    tp.transition_status(cfg, a["topic_id"], "approved", actor="t", reason="r")
    candidates = tp.list_topics(cfg, status="candidate")
    approved = tp.list_topics(cfg, status="approved")
    assert [x["topic_id"] for x in candidates] == [b["topic_id"]]
    assert [x["topic_id"] for x in approved] == [a["topic_id"]]


def test_update_topic_generic_field(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    updated = tp.update_topic(cfg, t["topic_id"], title="새 제목", priority=50)
    assert updated["title"] == "새 제목"
    assert updated["priority"] == "50" or updated.get("priority") in (50, "50")


def test_update_topic_rejects_status_field(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    with pytest.raises(ValueError):
        tp.update_topic(cfg, t["topic_id"], status="approved")


def test_update_topic_rejects_status_history_field(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    with pytest.raises(ValueError):
        tp.update_topic(cfg, t["topic_id"], status_history="[]")


def test_update_topic_nonexistent_raises(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        tp.update_topic(cfg, "nonexistent", title="x")


# ── 허용 상태 전이 ───────────────────────────────────────────────────

class TestAllowedTransitions:
    def test_candidate_to_approved(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        r = tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        assert r["status"] == "approved"

    def test_candidate_to_duplicate(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        r = tp.transition_status(cfg, t["topic_id"], "duplicate", actor="t", reason="r")
        assert r["status"] == "duplicate"

    def test_candidate_to_rejected(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        r = tp.transition_status(cfg, t["topic_id"], "rejected", actor="t", reason="r")
        assert r["status"] == "rejected"

    def test_candidate_to_hold(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        r = tp.transition_status(cfg, t["topic_id"], "hold", actor="t", reason="r")
        assert r["status"] == "hold"

    def test_approved_to_scheduled(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
        assert r["status"] == "scheduled"

    def test_scheduled_to_publishing(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
        assert r["status"] == "publishing"

    def test_publishing_to_published(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        for s in ("approved", "scheduled", "publishing"):
            tp.transition_status(cfg, t["topic_id"], s, actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "published", actor="t", reason="r")
        assert r["status"] == "published"

    def test_publishing_to_publish_failed(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        for s in ("approved", "scheduled", "publishing"):
            tp.transition_status(cfg, t["topic_id"], s, actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "publish_failed", actor="t", reason="r")
        assert r["status"] == "publish_failed"

    def test_hold_to_candidate_manual(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "hold", actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="human",
                                  reason="재검토", manual=True)
        assert r["status"] == "candidate"


# ── 금지 전이(반드시 실패) ───────────────────────────────────────────

class TestForbiddenTransitions:
    @pytest.mark.parametrize("from_status,to_status", [
        ("candidate", "published"),
        ("candidate", "publishing"),
        ("published", "candidate"),
        ("published", "approved"),
        ("rejected", "published"),
        ("duplicate", "published"),
        ("hold", "published"),
    ])
    def test_forbidden_transition_raises(self, tmp_path, from_status, to_status):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        path_to_status = {
            "candidate": [],
            "published": ["approved", "scheduled", "publishing", "published"],
            "rejected": ["rejected"],
            "duplicate": ["duplicate"],
            "hold": ["hold"],
        }[from_status]
        for s in path_to_status:
            tp.transition_status(cfg, t["topic_id"], s, actor="t", reason="r",
                                  manual=(s == "candidate"))
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], to_status, actor="t", reason="r")

    def test_manual_transition_without_manual_flag_rejected(self, tmp_path):
        """hold -> candidate는 manual=True 없이는 차단되어야 한다."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "hold", actor="t", reason="r")
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="t", reason="r")
            # manual=False(기본값) — 차단되어야 함


# ── status_history ───────────────────────────────────────────────────

def test_status_history_records_all_fields(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    r = tp.transition_status(cfg, t["topic_id"], "approved", actor="tester",
                              reason="심사 통과")
    last = r["status_history"][-1]
    assert last["from_status"] == "candidate"
    assert last["to_status"] == "approved"
    assert last["actor"] == "tester"
    assert last["reason"] == "심사 통과"
    assert "timestamp" in last and last["timestamp"]


def test_status_history_accumulates_across_transitions(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r1")
    tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r2")
    final = tp.get_topic(cfg, t["topic_id"])
    assert len(final["status_history"]) == 3  # created + approved + scheduled


# ── priority 정렬 ────────────────────────────────────────────────────

def test_priority_ordering(tmp_path):
    cfg = _cfg(tmp_path)
    t2 = _make(cfg, priority=2, slug="calc-a")
    t1a = _make(cfg, priority=1, slug="calc-b")
    t1b = _make(cfg, priority=1, slug="calc-c")

    result = tp.list_topics(cfg)
    priorities = [t["priority"] for t in result]
    assert priorities == [1, 1, 2]

    # priority=1인 두 항목은 approved_at이 둘 다 없으므로(candidate) created_at,
    # 그 다음 topic_id로 정렬 — topic_id는 생성 순서상 t1a < t1b(타임스탬프 동일해도
    # uuid 접미사가 달라 사전순 비교가 되지만, 최소한 순서 자체가 일관/재현 가능해야 함)
    ids_priority1 = [t["topic_id"] for t in result if t["priority"] == 1]
    assert set(ids_priority1) == {t1a["topic_id"], t1b["topic_id"]}


def test_priority_ordering_with_approved_at(tmp_path):
    import time
    cfg = _cfg(tmp_path)
    a = _make(cfg, priority=1, slug="calc-a")
    b = _make(cfg, priority=1, slug="calc-b")
    # b를 먼저 approve(더 이른 approved_at) -> priority 동률이면 approved_at ASC로
    # b가 먼저 나와야 한다.
    tp.transition_status(cfg, b["topic_id"], "approved", actor="t", reason="r")
    time.sleep(0.01)
    tp.transition_status(cfg, a["topic_id"], "approved", actor="t", reason="r")

    result = tp.list_topics(cfg, status="approved")
    assert [t["topic_id"] for t in result] == [b["topic_id"], a["topic_id"]]


# ── failure_count / 3회 -> hold ──────────────────────────────────────

class TestFailureModel:
    @pytest.mark.parametrize("failure_type", ["generation_failed", "schedule_failed"])
    def test_failure_1_stays_approved(self, tmp_path, failure_type):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        r = tp.record_failure(cfg, t["topic_id"], failure_type, "err1")
        assert r["status"] == "approved"
        assert r["failure_count"] == 1
        assert r["last_failure_type"] == failure_type

    @pytest.mark.parametrize("failure_type", ["generation_failed", "schedule_failed"])
    def test_failure_2_stays_approved(self, tmp_path, failure_type):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        tp.record_failure(cfg, t["topic_id"], failure_type, "err1")
        r = tp.record_failure(cfg, t["topic_id"], failure_type, "err2")
        assert r["status"] == "approved"
        assert r["failure_count"] == 2

    @pytest.mark.parametrize("failure_type", ["generation_failed", "schedule_failed"])
    def test_failure_3_goes_to_hold(self, tmp_path, failure_type):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        tp.record_failure(cfg, t["topic_id"], failure_type, "err1")
        tp.record_failure(cfg, t["topic_id"], failure_type, "err2")
        r = tp.record_failure(cfg, t["topic_id"], failure_type, "err3")
        assert r["status"] == "hold"
        assert r["failure_count"] == 3
        assert r["last_error"] == "err3"
        assert r["last_failed_at"]

    def test_record_failure_appends_two_history_events(self, tmp_path):
        """approved -> generation_failed -> approved 두 이벤트가 기록되는지."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        r = tp.record_failure(cfg, t["topic_id"], "generation_failed", "err1")
        history = r["status_history"]
        assert history[-2]["from_status"] == "approved"
        assert history[-2]["to_status"] == "generation_failed"
        assert history[-1]["from_status"] == "generation_failed"
        assert history[-1]["to_status"] == "approved"

    def test_record_failure_from_non_approved_rejected(self, tmp_path):
        """candidate 상태에서는 record_failure()가 허용되지 않아야 한다
        (approved -> generation_failed/schedule_failed만 허용)."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        with pytest.raises(ValueError):
            tp.record_failure(cfg, t["topic_id"], "generation_failed", "err")

    def test_record_failure_invalid_type_rejected(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
        with pytest.raises(ValueError):
            tp.record_failure(cfg, t["topic_id"], "not_a_failure_type", "err")


# ── publish_failed: 자동 retry 없음 ──────────────────────────────────

def test_publish_failed_no_auto_retry(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    for s in ("approved", "scheduled", "publishing"):
        tp.transition_status(cfg, t["topic_id"], s, actor="t", reason="r")
    r = tp.transition_status(cfg, t["topic_id"], "publish_failed", actor="t", reason="timeout")
    assert r["status"] == "publish_failed"

    # publish_failed -> approved/publishing으로 자동 전이될 수 있는 경로가
    # 전혀 없어야 한다(_AUTO_ALLOWED_TRANSITIONS에 "publish_failed" 키 자체가 없음).
    with pytest.raises(ValueError):
        tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="retry")
    with pytest.raises(ValueError):
        tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="retry")

    # list_topics()를 여러 번 호출해도(=스케줄러 루프가 반복되는 상황을 흉내냄)
    # 상태가 스스로 바뀌지 않는다(순수 조회이므로 당연하지만 명시적으로 확인).
    tp.list_topics(cfg)
    tp.list_topics(cfg)
    still = tp.get_topic(cfg, t["topic_id"])
    assert still["status"] == "publish_failed"


# ── manual reactivation ──────────────────────────────────────────────

class TestManualReactivation:
    @pytest.mark.parametrize("blocked_status", ["duplicate", "rejected", "hold"])
    def test_manual_reactivation_to_candidate(self, tmp_path, blocked_status):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], blocked_status, actor="t", reason="r")
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="human_reviewer",
                                  reason="수동 재검토 요청", manual=True)
        assert r["status"] == "candidate"
        last = r["status_history"][-1]
        assert last["actor"] == "human_reviewer"
        assert last["reason"] == "수동 재검토 요청"
        assert last["from_status"] == blocked_status
        assert last["to_status"] == "candidate"

    @pytest.mark.parametrize("blocked_status", ["duplicate", "rejected", "hold"])
    def test_manual_reactivation_requires_manual_flag(self, tmp_path, blocked_status):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], blocked_status, actor="t", reason="r")
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="t", reason="r")

    def test_manual_reactivation_requires_nonempty_actor(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        tp.transition_status(cfg, t["topic_id"], "hold", actor="t", reason="r")
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="", reason="r",
                                  manual=True)


# ── publish_failed 수동 재활성화(CALCMATE-AUTO-CONTENT-TOPIC-GAP4-IMPLEMENT-01) ──

def _to_publish_failed(cfg, topic_id, *, failure_error="wp_500"):
    """approved -> scheduled -> publishing -> publish_failed까지 진행시키는 헬퍼.
    failure metadata(failure_count 등)를 채워두기 위해 publish_failed 진입 전에
    generation_failed 1회를 기록해둔다(approved에서만 record_failure()가 허용되므로)."""
    tp.transition_status(cfg, topic_id, "approved", actor="t", reason="r")
    tp.record_failure(cfg, topic_id, "generation_failed", failure_error)
    for s in ("scheduled", "publishing"):
        tp.transition_status(cfg, topic_id, s, actor="t", reason="r")
    return tp.transition_status(cfg, topic_id, "publish_failed", actor="t", reason="wp_error")


class TestPublishFailedManualReactivation:
    def test_publish_failed_to_candidate_manual_true_succeeds(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        assert r["status"] == "candidate"

    def test_publish_failed_to_candidate_manual_false_fails(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation")
            # manual=False(기본값) — 차단되어야 함

    def test_publish_failed_to_candidate_history_recorded(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        last = r["status_history"][-1]
        assert last["from_status"] == "publish_failed"
        assert last["to_status"] == "candidate"
        assert last["actor"] == "dashboard"
        assert last["reason"] == "manual_reactivation"
        assert "timestamp" in last and last["timestamp"]

    def test_publish_failed_to_candidate_preserves_failure_count(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        before = tp.get_topic(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        assert r["failure_count"] == before["failure_count"] == 1

    def test_publish_failed_to_candidate_preserves_last_failure_type(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        assert r["last_failure_type"] == "generation_failed"

    def test_publish_failed_to_candidate_preserves_last_error(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"], failure_error="specific_wp_error_detail")
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        assert r["last_error"] == "specific_wp_error_detail"

    def test_publish_failed_to_candidate_preserves_last_failed_at(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        before = tp.get_topic(cfg, t["topic_id"])
        assert before["last_failed_at"]
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="dashboard",
                                  reason="manual_reactivation", manual=True)
        assert r["last_failed_at"] == before["last_failed_at"]

    def test_publish_failed_auto_transition_blocked(self, tmp_path):
        """publish_failed 상태에서 자동(manual=False) 전이는 어떤 목표 상태로도
        차단되어야 한다 — _AUTO_ALLOWED_TRANSITIONS에 publish_failed 키 자체가
        없으므로 approved/candidate 둘 다 확인."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="t", reason="r")
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")

    def test_publish_failed_to_approved_not_added(self, tmp_path):
        """publish_failed -> approved는 이번 STEP에서 추가하지 않는다(수동이어도
        금지) — 재승인은 반드시 candidate를 거쳐야 한다."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_publish_failed(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "approved", actor="dashboard",
                                  reason="manual_reactivation", manual=True)


# ── scheduled 수동 재활성화(CALCMATE-AUTO-CONTENT-E2E-REALTEST-RECOVERY-GAP-
# IMPLEMENT-01) ──────────────────────────────────────────────────────────

def _to_scheduled(cfg, topic_id, *, reservation_id="test-reservation-id"):
    """approved -> scheduled까지 진행시키고 oneoff_reservation_id를 채워두는
    헬퍼(실제 Planner를 거치지 않고 update_topic()으로 직접 채움 — 이 파일은
    scheduler/planner를 전혀 import하지 않는 순수 topic_pool 단위 테스트)."""
    tp.transition_status(cfg, topic_id, "approved", actor="t", reason="r")
    tp.update_topic(cfg, topic_id, oneoff_reservation_id=reservation_id)
    return tp.transition_status(cfg, topic_id, "scheduled", actor="t", reason="r")


class TestScheduledManualReactivation:
    # Test A — manual scheduled -> candidate 성공
    def test_scheduled_to_candidate_manual_true_succeeds(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="scheduled_recovery_test", manual=True)
        assert r["status"] == "candidate"

    def test_scheduled_to_candidate_adds_exactly_one_history_event(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        before_len = len(tp.get_topic(cfg, t["topic_id"])["status_history"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="scheduled_recovery_test", manual=True)
        assert len(r["status_history"]) == before_len + 1
        last = r["status_history"][-1]
        assert last["from_status"] == "scheduled"
        assert last["to_status"] == "candidate"
        assert last["actor"] == "test"
        assert last["reason"] == "scheduled_recovery_test"

    # Test B — automatic(manual=False) scheduled -> candidate 차단
    def test_scheduled_to_candidate_manual_false_blocked(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        before = tp.get_topic(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="scheduled_recovery_test")
        after = tp.get_topic(cfg, t["topic_id"])
        assert after["status"] == before["status"] == "scheduled"
        assert after["status_history"] == before["status_history"]

    def test_scheduled_auto_transition_to_candidate_blocked_even_with_different_actor(self, tmp_path):
        """_AUTO_ALLOWED_TRANSITIONS["scheduled"]는 여전히 {"publishing"}뿐이어야
        한다 — manual=False에서는 어떤 actor/reason으로도 차단되어야 함."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="scheduler",
                                  reason="auto attempt")

    # Test C — reservation reference 보존(전이 자체는 정리하지 않음)
    def test_scheduled_to_candidate_does_not_clear_reservation_id(self, tmp_path):
        """상태 전이와 reservation reference cleanup의 책임을 섞지 않는다 —
        transition_status()는 oneoff_reservation_id를 임의로 건드리지 않아야
        한다(호출자가 필요하면 update_topic()으로 별도 처리)."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"], reservation_id="test-reservation-id")
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="scheduled_recovery_test", manual=True)
        assert r["oneoff_reservation_id"] == "test-reservation-id"

    def test_scheduled_to_candidate_then_manual_clear_reservation_id(self, tmp_path):
        """전이 후 호출자가 명시적으로 update_topic()을 호출하면 정상적으로
        비울 수 있어야 한다(기존 API 그대로, 신규 API 불필요)."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"], reservation_id="test-reservation-id")
        tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                              reason="scheduled_recovery_test", manual=True)
        r = tp.update_topic(cfg, t["topic_id"], oneoff_reservation_id="")
        assert r["oneoff_reservation_id"] == ""
        assert r["status"] == "candidate"

    def test_scheduled_to_approved_not_added(self, tmp_path):
        """scheduled -> approved는 이번 STEP에서 추가하지 않는다(수동이어도
        금지) — 재승인은 반드시 candidate를 거쳐야 한다는 기존 원칙과 동일."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "approved", actor="test",
                                  reason="scheduled_recovery_test", manual=True)

    def test_scheduled_to_publishing_still_works(self, tmp_path):
        """기존 auto 전이(scheduled -> publishing)가 이번 변경으로 깨지지
        않았는지 회귀 확인."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
        assert r["status"] == "publishing"


# ── Golden10 보호 ─────────────────────────────────────────────────────

def test_golden10_unchanged_after_topic_pool_operations(tmp_path):
    """Topic Pool 함수 실행 전후 GOLDEN_10이 완전히 동일한지(hash + object
    equality) 확인한다. topic_pool.py는 GOLDEN_10을 import/참조하지 않지만,
    이 테스트는 향후 실수로 결합되더라도 즉시 감지하기 위한 보호장치다."""
    from content.blog import GOLDEN_10

    before_repr = repr(GOLDEN_10)
    before_hash = hashlib.sha256(before_repr.encode()).hexdigest()
    before_list = list(GOLDEN_10)

    cfg = _cfg(tmp_path)
    t = _make(cfg)
    tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
    tp.record_failure(cfg, t["topic_id"], "generation_failed", "err")
    tp.list_topics(cfg)
    tp.update_topic(cfg, t["topic_id"], title="변경됨")

    from content.blog import GOLDEN_10 as GOLDEN_10_AFTER
    after_repr = repr(GOLDEN_10_AFTER)
    after_hash = hashlib.sha256(after_repr.encode()).hexdigest()

    assert before_hash == after_hash
    assert before_list == list(GOLDEN_10_AFTER)
    assert GOLDEN_10 is GOLDEN_10_AFTER  # 같은 객체(재할당되지 않음)


# ── 기존 데이터 완전 분리 확인 ─────────────────────────────────────────

def test_topic_pool_does_not_touch_other_tables(tmp_path):
    """topic_pool 테이블에 대한 CRUD가 같은 DB 파일 안의 다른 테이블(예:
    calculators)에 어떤 영향도 주지 않는지 확인한다."""
    from adapters.db.sqlite_adapter import SQLiteAdapter

    cfg = _cfg(tmp_path)
    adapter = SQLiteAdapter(cfg)
    adapter.insert("calculators", {"id": "calc_1", "slug": "dummy", "name": "더미"})

    t = _make(cfg)
    tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")

    calc_rows = adapter.get_all("calculators")
    assert len(calc_rows) == 1
    assert calc_rows[0]["slug"] == "dummy"

    topic_rows = adapter.get_all("topic_pool")
    assert len(topic_rows) == 1


# ── published 재활성화(PUBLISHED-WP-RECONCILIATION-GAP-FOLLOWUP-DECISION-01) ──

def _to_published(cfg, topic_id, *, reservation_id="test-reservation-id"):
    """approved -> scheduled -> publishing -> published까지 진행시키는 헬퍼
    (_to_scheduled와 동일한 관례 — scheduler/planner를 import하지 않음)."""
    _to_scheduled(cfg, topic_id, reservation_id=reservation_id)
    tp.transition_status(cfg, topic_id, "publishing", actor="t", reason="r")
    return tp.transition_status(cfg, topic_id, "published", actor="t", reason="r")


class TestPublishedManualReactivation:
    # Test 1 — manual published -> candidate 성공
    def test_published_to_candidate_manual_true_succeeds(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_published(cfg, t["topic_id"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="wp_mismatch_recovery_test", manual=True)
        assert r["status"] == "candidate"

    def test_published_to_candidate_adds_exactly_one_history_event(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_published(cfg, t["topic_id"])
        before_len = len(tp.get_topic(cfg, t["topic_id"])["status_history"])
        r = tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="wp_mismatch_recovery_test", manual=True)
        assert len(r["status_history"]) == before_len + 1
        last = r["status_history"][-1]
        assert last["from_status"] == "published"
        assert last["to_status"] == "candidate"

    # Test 2 — automatic(manual=False) published -> candidate 차단
    def test_published_to_candidate_manual_false_blocked(self, tmp_path):
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_published(cfg, t["topic_id"])
        before = tp.get_topic(cfg, t["topic_id"])
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="wp_mismatch_recovery_test")
        after = tp.get_topic(cfg, t["topic_id"])
        assert after["status"] == before["status"] == "published"
        assert after["status_history"] == before["status_history"]

    def test_published_auto_transition_to_candidate_blocked_even_with_different_actor(self, tmp_path):
        """_AUTO_ALLOWED_TRANSITIONS에 "published"가 없어야 한다 — manual=False에서는
        어떤 actor/reason으로도 차단되어야 함(스케줄러/플래너가 실수로도 이 전이를
        자동 실행할 수 없음을 보장)."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_published(cfg, t["topic_id"])
        for actor in ("oneoff_scheduler", "publishing_planner", "system", "random_actor"):
            with pytest.raises(ValueError):
                tp.transition_status(cfg, t["topic_id"], "candidate", actor=actor,
                                      reason="r")

    def test_published_manual_grant_is_scoped_only_to_published_source(self, tmp_path):
        """WIREUP-01 STEP4 항목 6: "published": {"candidate"}는 오직
        from_status="published"에만 적용되어야 한다 — 예를 들어 "publishing"
        상태에서는 manual=True를 줘도 여전히 candidate로 갈 수 없어야 한다
        (다른 상태에서 이 manual-only 허용이 잘못 넓게 적용되지 않는지 확인)."""
        cfg = _cfg(tmp_path)
        t = _make(cfg)
        _to_scheduled(cfg, t["topic_id"])
        tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
        before = tp.get_topic(cfg, t["topic_id"])
        assert before["status"] == "publishing"
        with pytest.raises(ValueError):
            tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                                  reason="r", manual=True)
        after = tp.get_topic(cfg, t["topic_id"])
        assert after["status"] == before["status"] == "publishing"
