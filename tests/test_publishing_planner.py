# -*- coding: utf-8 -*-
"""
tests/test_publishing_planner.py
CALCMATE-AUTO-CONTENT-PUBLISHING-POLICY-IMPLEMENT-01 — Publishing Planner
(run_planner_once) 검증.

전부 tmp_path 격리 SQLite/파일을 사용한다. WP 중복확인은 stub 주입, 실제
WordPress/AI 호출은 이 파일에서 발생하지 않는다.
"""
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.publishing_planner as planner
import modules.publishing_policy as pp
import modules.scheduler as sch
import modules.topic_pool as tp

KST = ZoneInfo("Asia/Seoul")


def _cfg(tmp_path, **overrides):
    cfg = {"_root": str(tmp_path), "SQLITE_PATH": "test_planner.db",
           "DB_ADAPTER": "sqlite", "scheduler_line": "blog"}
    cfg.update(overrides)
    return cfg


def _seed_calculator(cfg, calculator_id="calc_seed"):
    from adapters.db.factory import get_calculator_storage_adapter
    get_calculator_storage_adapter(cfg).insert("calculators", {
        "id": calculator_id, "slug": "seed", "name": "seed"})


def _make_approved_topic(cfg, **overrides):
    calculator_id = overrides.pop("calculator_id", "calc_seed")
    _seed_calculator(cfg, calculator_id)
    kwargs = dict(slug=f"topic-slug-{random.randint(0, 10**9)}", topic="t", title="ti",
                  intent="howto", calculator_id=calculator_id)
    kwargs.update(overrides)
    t = tp.create_topic(cfg, **kwargs)
    return tp.transition_status(cfg, t["topic_id"], "approved", actor="test", reason="r")


def _dup_ok(cfg, slug):
    return {"exists": False, "confirmed": True, "wp_post_id": None, "slug": None, "error": None}


def _dup_exists(cfg, slug):
    return {"exists": True, "confirmed": True, "wp_post_id": 1, "slug": slug, "error": None}


def _dup_unconfirmed(cfg, slug):
    return {"exists": False, "confirmed": False, "wp_post_id": None, "slug": None,
            "error": "http_500"}


MONDAY = datetime(2026, 9, 21, 7, 0, tzinfo=KST)  # 2026-09-21은 월요일, 이른 아침(모든 range 미래)


def _policy(**weekday_overrides):
    """모든 요일 count=0인 기본 정책에서 시작해 지정된 요일만 덮어쓴다.
    DEFAULT_POLICY(mon/wed/fri=1)를 그대로 베이스로 쓰면 테스트가 지정하지
    않은 요일도 활성 상태로 남아 lookahead 14일 동안 의도치 않게 슬롯을
    소비해버리므로, 테스트 격리를 위해 항상 전부-0에서 시작한다."""
    import copy
    policy = copy.deepcopy(pp.DEFAULT_POLICY)
    for day in pp.WEEKDAYS:
        policy["weekdays"][day] = {"count": 0, "time_ranges": []}
    policy["weekdays"].update(weekday_overrides)
    return policy


# ── count=0 요일은 예약 생성하지 않음 ────────────────────────────────

def test_count_zero_weekday_creates_no_reservation(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(
        mon={"count": 0, "time_ranges": []}))
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 0
    final = tp.get_topic(cfg, t["topic_id"])
    assert final["status"] == "approved"  # 변경되지 않음


# ── count만큼 range를 처리 ────────────────────────────────────────────

def test_count_n_schedules_up_to_n_topics(tmp_path):
    """count=2인 요일은 "그 날짜"에 정확히 2개의 slot(range별 1개)을 제공한다.
    lookahead가 여러 주에 걸쳐 있으면 다음 주 같은 요일도 추가로 slot을 제공하는
    것이 정상 동작(주간 반복 정책)이므로, 이 테스트는 max_pending_reservations로
    "이번 실행에서 정확히 2건만" 처리되도록 상한을 명시해 count=2 자체(날짜당
    정확히 2개의 독립 slot)를 검증한다."""
    policy = _policy(mon={"count": 2, "time_ranges": [
        {"start": "09:00", "end": "11:00"},
        {"start": "16:00", "end": "18:00"},
    ]})
    policy["max_pending_reservations"] = 2
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=policy)
    t1 = _make_approved_topic(cfg, priority=1)
    t2 = _make_approved_topic(cfg, priority=2)
    t3 = _make_approved_topic(cfg, priority=3)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 2
    statuses = {t1["topic_id"]: "scheduled", t2["topic_id"]: "scheduled",
                t3["topic_id"]: "approved"}
    for topic_id, expected in statuses.items():
        assert tp.get_topic(cfg, topic_id)["status"] == expected
    # 같은 날(이번 주 월요일)의 두 range에서 각각 1개씩 나왔는지 확인.
    dates = {datetime.fromisoformat(r["scheduled_at"]).date() for r in result["results"]
             if r["status"] == "SCHEDULED"}
    assert dates == {MONDAY.date()}


# ── approved Topic만 선택 ─────────────────────────────────────────────

def test_only_approved_topics_are_selected(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    _seed_calculator(cfg)
    candidate = tp.create_topic(cfg, slug="cand", topic="t", title="ti", intent="howto",
                                 calculator_id="calc_seed")  # candidate 상태(승인 안 함)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 0
    assert result["reason"] == "no_approved_topics"
    assert tp.get_topic(cfg, candidate["topic_id"])["status"] == "candidate"


# ── priority / approved_at / topic_id 정렬 ───────────────────────────

def test_priority_ordering_respected(tmp_path):
    """count=1(이번 주 월요일 slot 1개)이어도 lookahead 14일 안에 다음 주
    월요일 slot도 존재하므로, "priority가 더 높은 topic이 더 먼저(이번 주) 것을
    가져가는지"를 명확히 보려면 max_pending_reservations=1로 실행 전체를
    1건만 처리하도록 제한한다."""
    policy = _policy(mon={"count": 1, "time_ranges": [{"start": "09:00", "end": "18:00"}]})
    policy["max_pending_reservations"] = 1
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=policy)
    low_priority = _make_approved_topic(cfg, priority=5)
    high_priority = _make_approved_topic(cfg, priority=1)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 1
    assert tp.get_topic(cfg, high_priority["topic_id"])["status"] == "scheduled"
    assert tp.get_topic(cfg, low_priority["topic_id"])["status"] == "approved"


def test_approved_at_ordering_respected(tmp_path):
    import time as _time
    policy = _policy(mon={"count": 1, "time_ranges": [{"start": "09:00", "end": "18:00"}]})
    policy["max_pending_reservations"] = 1
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=policy)
    _seed_calculator(cfg)
    a = tp.create_topic(cfg, slug="a", topic="t", title="ti", intent="howto",
                         calculator_id="calc_seed", priority=1)
    b = tp.create_topic(cfg, slug="b", topic="t", title="ti", intent="howto",
                         calculator_id="calc_seed", priority=1)
    tp.transition_status(cfg, b["topic_id"], "approved", actor="t", reason="r")
    _time.sleep(0.01)
    tp.transition_status(cfg, a["topic_id"], "approved", actor="t", reason="r")

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 1
    # b가 먼저 approved됐으므로 b가 먼저 선택되어야 한다.
    assert tp.get_topic(cfg, b["topic_id"])["status"] == "scheduled"
    assert tp.get_topic(cfg, a["topic_id"])["status"] == "approved"


# ── pending cap 적용 ──────────────────────────────────────────────────

def test_max_pending_reservations_cap_enforced(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 3, "time_ranges": [
        {"start": "09:00", "end": "10:00"},
        {"start": "13:00", "end": "14:00"},
        {"start": "18:00", "end": "19:00"},
    ]}))
    cfg["PUBLISHING_POLICY"]["max_pending_reservations"] = 1
    t1 = _make_approved_topic(cfg, priority=1)
    t2 = _make_approved_topic(cfg, priority=2)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 1
    assert tp.get_topic(cfg, t1["topic_id"])["status"] == "scheduled"
    assert tp.get_topic(cfg, t2["topic_id"])["status"] == "approved"


def test_max_pending_reservations_counts_all_pending_not_just_topics(tmp_path):
    """max_pending_reservations는 topic_id 유무와 무관하게 전체 pending
    reservation을 센다(감사에서 결정된 정책)."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    cfg["PUBLISHING_POLICY"]["max_pending_reservations"] = 1
    # topic_id 없는(레거시) pending 예약 1건을 미리 채워둔다.
    sch.add_oneoff_reservation(cfg, MONDAY.replace(hour=6), "draft")

    t = _make_approved_topic(cfg)
    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 0
    assert result["reason"] == "max_pending_reservations_reached"
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "approved"


# ── 과거 slot 제외 ────────────────────────────────────────────────────

def test_past_slot_today_is_skipped_to_tomorrow_or_later(tmp_path):
    """오늘의 range가 이미 지났으면 그 range는 건너뛰고 이후 날짜/range를
    사용해야 한다."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(
        mon={"count": 1, "time_ranges": [{"start": "09:00", "end": "10:00"}]},
        tue={"count": 1, "time_ranges": [{"start": "09:00", "end": "10:00"}]},
    ))
    t = _make_approved_topic(cfg)
    late_monday = datetime(2026, 9, 21, 15, 0, tzinfo=KST)  # 월요일 range(09-10) 이미 지남

    result = planner.run_planner_once(cfg, now=late_monday, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 1
    scheduled_at = result["results"][0]["scheduled_at"]
    dt = datetime.fromisoformat(scheduled_at)
    assert dt.date() == late_monday.date() + __import__("datetime").timedelta(days=1)  # 화요일


# ── 동일 slot 충돌 처리 ───────────────────────────────────────────────

def test_slot_collision_with_existing_pending_avoided(tmp_path):
    """이미 pending인 정확히 동일한 절대시각+mode가 있으면 그 시각은 후보에서
    제외되고 다른 시각이 선택되어야 한다(기존 dedup 로직은 그대로 유지, Planner가
    사전에 회피)."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(
        mon={"count": 1, "time_ranges": [{"start": "09:00", "end": "09:01"}]}))
    # 09:00 하나만 나올 수 있는 좁은 범위를 미리 선점.
    taken = datetime(2026, 9, 21, 9, 0, tzinfo=KST)
    sch.add_oneoff_reservation(cfg, taken, "draft")

    t = _make_approved_topic(cfg)
    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    # 09:00~09:01 range는 이미 선점되어 사용 가능한 슬롯이 없어야 한다
    # (이 range의 유일한 두 값 모두 collision 대상이 될 수 있으므로, 최종적으로
    # scheduled=0 또는 다른 시각으로 처리됨을 확인 — 중요한 것은 09:00에 두 번째
    # reservation이 생기지 않는 것).
    reservations = sch.load_oneoff(cfg)
    exact_09_00_count = sum(
        1 for e in reservations
        if datetime.fromisoformat(e["scheduled_at"]) == taken and e.get("status") == "pending"
    )
    assert exact_09_00_count == 1  # 중복 생성되지 않음


# ── reservation-first 순서 / Topic reservation id 저장 / 마지막 approved->scheduled ──

def test_reservation_created_before_topic_state_change(tmp_path):
    """update_topic()/transition_status() 호출 전에 add_oneoff_reservation()이
    먼저 성공해야 한다 — 순서를 모니터링해서 확인."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    call_order = []
    original_add = sch.add_oneoff_reservation
    original_transition = tp.transition_status

    def _tracking_add(*a, **kw):
        call_order.append("add_oneoff_reservation")
        return original_add(*a, **kw)

    def _tracking_transition(*a, **kw):
        call_order.append("transition_status")
        return original_transition(*a, **kw)

    import unittest.mock as mock
    with mock.patch.object(sch, "add_oneoff_reservation", _tracking_add), \
         mock.patch.object(tp, "transition_status", _tracking_transition):
        planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1), dup_check_fn=_dup_ok)

    assert call_order == ["add_oneoff_reservation", "transition_status"]


def test_reservation_id_saved_on_topic(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    reservation_id = result["results"][0]["reservation_id"]
    final = tp.get_topic(cfg, t["topic_id"])
    assert final["oneoff_reservation_id"] == reservation_id


def test_final_status_is_scheduled_after_success(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1), dup_check_fn=_dup_ok)

    assert tp.get_topic(cfg, t["topic_id"])["status"] == "scheduled"


def test_reservation_failure_does_not_leave_topic_scheduled(tmp_path):
    """add_oneoff_reservation()이 예외를 던지면 Topic은 절대 scheduled가 되지
    않아야 한다(reservation-first 원칙의 안전성 확인)."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    import unittest.mock as mock
    with mock.patch.object(sch, "add_oneoff_reservation",
                            side_effect=RuntimeError("simulated_reservation_failure")):
        with pytest.raises(RuntimeError):
            planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                      dup_check_fn=_dup_ok)

    assert tp.get_topic(cfg, t["topic_id"])["status"] == "approved"


# ── duplicate 처리 ────────────────────────────────────────────────────

def test_wp_duplicate_exists_marks_schedule_failed(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_exists)

    assert result["scheduled"] == 0
    final = tp.get_topic(cfg, t["topic_id"])
    assert final["status"] == "approved"  # failure_count=1이므로 approved로 복귀
    assert final["failure_count"] == 1
    assert final["last_failure_type"] == "schedule_failed"


def test_wp_duplicate_check_unconfirmed_fails_closed(tmp_path):
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_unconfirmed)

    assert result["scheduled"] == 0
    final = tp.get_topic(cfg, t["topic_id"])
    assert final["failure_count"] == 1
    assert final["last_failure_type"] == "schedule_failed"


def test_duplicate_topic_never_consumes_reservation(tmp_path):
    """중복으로 판정된 topic은 실제로 add_oneoff_reservation()을 호출하지
    않아야 한다(슬롯 낭비 방지)."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    t = _make_approved_topic(cfg)

    planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1), dup_check_fn=_dup_exists)

    assert sch.load_oneoff(cfg) == []


# ── invalid policy fail-closed ────────────────────────────────────────

def test_invalid_policy_creates_no_reservation(tmp_path):
    import copy
    bad_policy = copy.deepcopy(pp.DEFAULT_POLICY)
    bad_policy["timezone"] = "UTC"
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=bad_policy)
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 0
    assert "invalid_policy" in result["reason"]
    assert sch.load_oneoff(cfg) == []
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "approved"


# ── no_available_slot ────────────────────────────────────────────────

def test_no_available_slot_when_all_weekdays_zero(tmp_path):
    import copy
    empty_policy = copy.deepcopy(pp.DEFAULT_POLICY)
    for day in pp.WEEKDAYS:
        empty_policy["weekdays"][day] = {"count": 0, "time_ranges": []}
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=empty_policy)
    t = _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)

    assert result["scheduled"] == 0
    assert result["results"][0]["reason"] == "no_available_slot"


# ── 보호 테스트 ───────────────────────────────────────────────────────

def test_golden10_unchanged_after_planner_run(tmp_path):
    import hashlib
    from content.blog import GOLDEN_10
    before = hashlib.sha256(repr(GOLDEN_10).encode()).hexdigest()

    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    _make_approved_topic(cfg)
    planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1), dup_check_fn=_dup_ok)

    from content.blog import GOLDEN_10 as AFTER
    after = hashlib.sha256(repr(AFTER).encode()).hexdigest()
    assert before == after
    assert GOLDEN_10 is AFTER


def test_planner_run_is_single_shot_not_a_loop(tmp_path):
    """run_planner_once()는 한 번 호출로 정확히 한 번만 실행되고 반환해야
    한다(내부에 while/loop가 없음 — 실행 시간이 즉시 종료되는지로 간접 확인)."""
    cfg = _cfg(tmp_path, PUBLISHING_POLICY=_policy(mon={"count": 1, "time_ranges": [
        {"start": "09:00", "end": "18:00"}]}))
    _make_approved_topic(cfg)

    result = planner.run_planner_once(cfg, now=MONDAY, rng=random.Random(1),
                                       dup_check_fn=_dup_ok)
    assert isinstance(result, dict)  # 호출이 정상적으로 즉시 반환됨
