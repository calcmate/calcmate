# -*- coding: utf-8 -*-
"""
tests/test_oneoff_blog_schedule.py
CALCMATE-ONEOFF-SCHEDULE-STRUCTURE-02 — 1회성(one-off) 예약 실행 구조 검증.

기존 recurring publish_slots(today_schedule.json 기반) 경로는 여기서 전혀
건드리지 않는다 — 이 테스트는 완전히 분리된 oneoff_schedule.json 경로만
검증한다. 실제 WordPress에 POST하지 않으며, main.resolve_blog_oneoff_publish_fn이
반환하는 run_once_fn은 전부 mock으로 대체한다.
"""
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.scheduler as sch
import main as PIPE

KST = ZoneInfo("Asia/Seoul")


def _cfg(tmp_path):
    return {"_root": str(tmp_path), "scheduler_line": "blog"}


# ── A/B: main.resolve_blog_oneoff_publish_fn — mode -> status 매핑 ──────

def test_a_mode_draft_maps_to_status_draft():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft")
    assert fn.func.__name__ == "run_blog_once_wp"
    assert fn.keywords.get("status") == "draft"


def test_b_mode_publish_maps_to_status_publish():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "publish")
    assert fn.func.__name__ == "run_blog_once_wp"
    assert fn.keywords.get("status") == "publish"


def test_a_b_actual_call_forwards_status_kwarg():
    """resolve_fn이 반환한 callable을 실제로 호출했을 때 run_blog_once_wp가
    status=mode 그대로 전달받는지 mock으로 확인한다(실제 WP 호출 없음)."""
    with mock.patch("modules.blog_scheduler_adapter.run_blog_once_wp") as m:
        m.return_value = {"produced": 1}
        fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft")
        fn({"x": 1}, max_count=1)
        _, kwargs = m.call_args
        assert kwargs.get("status") == "draft"

    with mock.patch("modules.blog_scheduler_adapter.run_blog_once_wp") as m:
        m.return_value = {"produced": 1}
        fn = PIPE.resolve_blog_oneoff_publish_fn({}, "publish")
        fn({"x": 1}, max_count=1)
        _, kwargs = m.call_args
        assert kwargs.get("status") == "publish"


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        PIPE.resolve_blog_oneoff_publish_fn({}, "weird_mode")


# ── C/D: scheduled_at 미래/도달 판정 ────────────────────────────────

def test_c_future_scheduled_at_not_due(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    future = now + timedelta(hours=1)
    sch.add_oneoff_reservation(cfg, future, "draft")

    due = sch.get_due_oneoff(cfg, now=now)
    assert due == []


def test_d_reached_scheduled_at_is_due(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    past = now - timedelta(minutes=1)
    entry = sch.add_oneoff_reservation(cfg, past, "publish")

    due = sch.get_due_oneoff(cfg, now=now)
    assert len(due) == 1
    assert due[0]["id"] == entry["id"]


def test_d_exact_same_time_is_due(tmp_path):
    """scheduled_at == now(경계값)도 due로 취급되어야 한다(<=)."""
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now, "draft")

    due = sch.get_due_oneoff(cfg, now=now)
    assert len(due) == 1
    assert due[0]["id"] == entry["id"]


# ── E: completed 이후 재실행 방지 ───────────────────────────────────

def test_e_completed_reservation_never_returned_again(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    past = now - timedelta(minutes=5)
    entry = sch.add_oneoff_reservation(cfg, past, "draft")

    assert len(sch.get_due_oneoff(cfg, now=now)) == 1

    sch.mark_oneoff_result(cfg, entry["id"], "completed", {"produced": 1})

    # 같은 시점, 심지어 훨씬 미래 시점에도 다시 선택되지 않아야 한다.
    assert sch.get_due_oneoff(cfg, now=now) == []
    assert sch.get_due_oneoff(cfg, now=now + timedelta(days=365)) == []

    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "completed"
    assert saved[0]["executed_at"] is not None


def test_e_execute_due_oneoff_marks_completed_and_no_real_wp_call(tmp_path):
    """execute_due_oneoff()가 mock run_once_fn을 통해 정확히 1회만 호출하고,
    실행 후 completed로 전환되어 재실행되지 않는지 확인한다. 실제 WP 호출 없음."""
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "draft")

    mock_run_once_fn = mock.Mock(return_value={"produced": 1})
    resolve_fn = mock.Mock(return_value=mock_run_once_fn)

    result = sch.execute_due_oneoff(cfg, entry, resolve_fn)

    assert result == "completed"
    # GAP3-IMPLEMENT-01: execute_due_oneoff()가 이제 topic_id(entry에 없으면
    # None)도 함께 전달한다 — topic_id 없는 레거시 entry이므로 두 번째 인자는
    # None이어야 한다.
    resolve_fn.assert_called_once_with("draft", None)
    mock_run_once_fn.assert_called_once_with(cfg, max_count=1)
    assert sch.get_due_oneoff(cfg, now=now) == []


def test_e_execute_due_oneoff_failure_marks_failed_not_pending(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "publish")

    mock_run_once_fn = mock.Mock(return_value={"produced": 0, "reason": "no_calculators"})
    resolve_fn = mock.Mock(return_value=mock_run_once_fn)

    result = sch.execute_due_oneoff(cfg, entry, resolve_fn)

    assert result == "failed"
    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "failed"
    # failed도 pending이 아니므로 다시 선택되지 않는다(무한 재시도 없음 — 구조만
    # 만드는 이번 단계에서는 자동 재시도를 구현하지 않는다).
    assert sch.get_due_oneoff(cfg, now=now) == []


# ── F: Asia/Seoul timezone, naive/aware 혼용 금지 ───────────────────

def test_f_add_reservation_rejects_naive_datetime(tmp_path):
    cfg = _cfg(tmp_path)
    naive = datetime(2026, 9, 25, 14, 0)  # tzinfo 없음
    with pytest.raises(ValueError):
        sch.add_oneoff_reservation(cfg, naive, "draft")


def test_f_get_due_oneoff_rejects_naive_now(tmp_path):
    cfg = _cfg(tmp_path)
    naive_now = datetime(2026, 9, 25, 14, 0)
    with pytest.raises(ValueError):
        sch.get_due_oneoff(cfg, now=naive_now)


def test_f_kst_offset_preserved_across_save_and_load(tmp_path):
    """KST(+09:00)로 저장한 예약이 다시 로드해도 동일 절대시각을 가리키는지
    (naive로 뭉개지지 않는지) UTC 비교로 확인한다."""
    cfg = _cfg(tmp_path)
    kst_dt = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    sch.add_oneoff_reservation(cfg, kst_dt, "draft")

    saved = sch.load_oneoff(cfg)[0]
    loaded_dt = datetime.fromisoformat(saved["scheduled_at"])
    assert loaded_dt.tzinfo is not None
    assert loaded_dt.astimezone(timezone.utc) == kst_dt.astimezone(timezone.utc)


def test_f_utc_now_equivalent_to_kst_now_for_due_check(tmp_path):
    """다른 timezone(UTC)으로 넘긴 aware now도 KST 예약과 올바르게 비교되는지
    (aware라면 어떤 tz든 절대시각 비교가 정확해야 한다) 확인한다."""
    cfg = _cfg(tmp_path)
    kst_scheduled = datetime(2026, 9, 25, 5, 0, tzinfo=KST)  # KST 05:00 = UTC 전날 20:00
    entry = sch.add_oneoff_reservation(cfg, kst_scheduled, "draft")

    now_utc = kst_scheduled.astimezone(timezone.utc) + timedelta(minutes=1)
    due = sch.get_due_oneoff(cfg, now=now_utc)
    assert len(due) == 1
    assert due[0]["id"] == entry["id"]


def test_f_invalid_mode_on_add_rejected(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    with pytest.raises(ValueError):
        sch.add_oneoff_reservation(cfg, now, "not_a_mode")


# ── G: 기존 recurring publish_slots 미영향 ──────────────────────────

def test_g_oneoff_storage_completely_separate_from_recurring_schedule(tmp_path):
    """oneoff 예약 추가/실행이 today_schedule.json(recurring)에 어떤 흔적도
    남기지 않는지 확인한다 — 파일 자체가 별도(oneoff_schedule.json)여야 한다."""
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "draft")

    mock_run_once_fn = mock.Mock(return_value={"produced": 1})
    resolve_fn = mock.Mock(return_value=mock_run_once_fn)
    sch.execute_due_oneoff(cfg, entry, resolve_fn)

    recurring_path = sch._schedule_path(cfg)
    oneoff_path = sch._oneoff_path(cfg)
    assert oneoff_path != recurring_path
    assert not recurring_path.exists(), "oneoff 실행이 recurring today_schedule.json을 건드림"
    assert oneoff_path.exists()

    # 기존 recurring lock 파일도 별개여야 한다(자원 공유 없음 — 동시 실행 시
    # 서로 block하지 않아야 하며, oneoff 실행 후에도 남아있으면 안 된다).
    assert not sch._lock_path(cfg).exists()
    assert not sch._oneoff_lock_path(cfg).exists()


def test_g_recurring_slot_functions_unaffected_by_oneoff_module(tmp_path):
    """get_slots_for()/default_slots() 등 기존 recurring 함수가 oneoff 관련
    코드 추가로 인해 전혀 영향받지 않는지(기존 동작 그대로) 확인한다."""
    from datetime import date
    cfg = {
        "_root": str(tmp_path),
        "scheduler_line": "blog",
        "BLOG_SCHEDULE": {
            "publish_slots": [{"start": "10:00", "end": "10:30"}],
            "weekday_only": False,
        },
    }
    day_type, slots = sch.get_slots_for(cfg, date(2026, 9, 25))
    assert slots == [{"start": "10:00", "end": "10:30"}]


# ══════════════════════════════════════════════════════════════════
# CALCMATE-ONEOFF-SCHEDULE-SAFETY-FIX-01 — 중복 방지 / lock / atomic write 검증
# ══════════════════════════════════════════════════════════════════

# ── 1: 동일 scheduled_at + mode pending 중복 → 두 번째 거부 ─────────

def test_dup1_same_scheduled_at_and_mode_pending_rejected(tmp_path):
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)

    first = sch.add_oneoff_reservation(cfg, when, "draft")
    assert first["duplicate"] is False

    second = sch.add_oneoff_reservation(cfg, when, "draft")
    assert second["duplicate"] is True
    assert second["id"] == first["id"]  # 새로 만들지 않고 기존 entry를 그대로 반환

    all_reservations = sch.load_oneoff(cfg)
    assert len(all_reservations) == 1  # 실제로 1건만 저장됨


# ── 2: 같은 scheduled_at, mode 다름 → 각각 허용 ─────────────────────

def test_dup2_same_time_different_mode_both_allowed(tmp_path):
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)

    draft_entry = sch.add_oneoff_reservation(cfg, when, "draft")
    publish_entry = sch.add_oneoff_reservation(cfg, when, "publish")

    assert draft_entry["duplicate"] is False
    assert publish_entry["duplicate"] is False
    assert draft_entry["id"] != publish_entry["id"]
    assert len(sch.load_oneoff(cfg)) == 2


# ── 3: completed 예약과 동일 scheduled_at+mode → 재예약 허용 ────────

def test_dup3_completed_reservation_does_not_block_same_time_mode_reretry(tmp_path):
    """완료(completed)된 예약은 "pending 중복"이 아니므로, 같은 시각·모드로
    다시 예약을 추가하는 것은 허용된다(현재 정책: pending만 중복 방지 대상)."""
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)

    first = sch.add_oneoff_reservation(cfg, when, "draft")
    sch.mark_oneoff_result(cfg, first["id"], "completed", {"produced": 1})

    second = sch.add_oneoff_reservation(cfg, when, "draft")
    assert second["duplicate"] is False
    assert second["id"] != first["id"]

    all_reservations = sch.load_oneoff(cfg)
    assert len(all_reservations) == 2
    statuses = {r["id"]: r["status"] for r in all_reservations}
    assert statuses[first["id"]] == "completed"
    assert statuses[second["id"]] == "pending"


def test_dup3_failed_reservation_does_not_block_same_time_mode_reretry(tmp_path):
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)

    first = sch.add_oneoff_reservation(cfg, when, "publish")
    sch.mark_oneoff_result(cfg, first["id"], "failed", {"error": "test"})

    second = sch.add_oneoff_reservation(cfg, when, "publish")
    assert second["duplicate"] is False
    assert len(sch.load_oneoff(cfg)) == 2


# ── 4: add_oneoff_reservation과 mark_oneoff_result의 lock 충돌 없음 ──

def test_lock1_add_reservation_releases_lock_after_success(tmp_path):
    """정상 추가 후 lock 파일이 남아있지 않아야 한다(다음 호출이 막히지 않음)."""
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    sch.add_oneoff_reservation(cfg, when, "draft")
    assert not sch._oneoff_lock_path(cfg).exists()


def test_lock2_add_reservation_waits_and_succeeds_when_lock_briefly_held(tmp_path):
    """execute_due_oneoff()가 lock을 잠깐 잡고 있는 동안 add_oneoff_reservation을
    호출해도 데드락 없이 재시도 후 정상적으로 성공해야 한다."""
    cfg = _cfg(tmp_path)

    # execute 경로가 lock을 잡은 상태를 흉내낸다(별도 스레드가 아니라, 짧은
    # 재시도 로직 자체를 검증하기 위해 lock을 수동으로 잡아둔 뒤 별도 스레드에서
    # 짧게 해제한다).
    import threading
    assert sch._acquire_oneoff_lock(cfg)

    def _release_after_delay():
        time.sleep(0.3)
        sch._release_oneoff_lock(cfg)

    t = threading.Thread(target=_release_after_delay)
    t.start()
    try:
        when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
        entry = sch.add_oneoff_reservation(
            cfg, when, "draft", lock_retries=10, lock_retry_interval=0.1)
        assert entry["duplicate"] is False
    finally:
        t.join()

    assert not sch._oneoff_lock_path(cfg).exists()


def test_lock3_add_reservation_raises_when_lock_never_released(tmp_path):
    """lock이 계속 점유돼 있으면(비정상 장기 실행 등) 무한 대기하지 않고
    명확한 RuntimeError로 실패해야 한다."""
    cfg = _cfg(tmp_path)
    assert sch._acquire_oneoff_lock(cfg)  # 해제하지 않고 그대로 유지
    try:
        when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
        with pytest.raises(RuntimeError):
            sch.add_oneoff_reservation(
                cfg, when, "draft", lock_retries=3, lock_retry_interval=0.05)
    finally:
        sch._release_oneoff_lock(cfg)


def test_lock4_execute_due_oneoff_and_add_reservation_do_not_deadlock(tmp_path):
    """실행 경로(execute_due_oneoff, lock 보유)와 추가 경로(add_oneoff_reservation,
    같은 lock 요청)가 동시에 발생해도 서로 영원히 블록하지 않고 순차적으로
    처리되는지 확인한다(실제 WP 호출 없음, mock)."""
    import threading
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    due_entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "draft")

    def _slow_run_once_fn(_cfg, max_count=1):
        time.sleep(0.3)  # WP 네트워크 호출을 흉내낸 지연(mock, 실제 호출 없음)
        return {"produced": 1}

    resolve_fn = mock.Mock(return_value=_slow_run_once_fn)

    results = {}

    def _executor():
        results["exec"] = sch.execute_due_oneoff(cfg, due_entry, resolve_fn)

    def _adder():
        time.sleep(0.05)  # executor가 먼저 lock을 잡을 시간을 준다
        results["add"] = sch.add_oneoff_reservation(
            cfg, now, "publish", lock_retries=20, lock_retry_interval=0.05)

    t1 = threading.Thread(target=_executor)
    t2 = threading.Thread(target=_adder)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive() and not t2.is_alive(), "데드락 발생 — 스레드가 종료되지 않음"
    assert results.get("exec") == "completed"
    assert results.get("add", {}).get("duplicate") is False
    assert not sch._oneoff_lock_path(cfg).exists()


# ── 5: atomic write — 저장 중단 시 기존 파일 보존 ───────────────────

def test_atomic1_save_failure_leaves_previous_file_intact(tmp_path):
    """save_oneoff() 도중 예외가 발생해도(디스크 오류 등을 흉내냄) 기존
    oneoff_schedule.json은 손상되지 않고 이전 상태 그대로 남아야 한다."""
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    sch.add_oneoff_reservation(cfg, when, "draft")

    before_path = sch._oneoff_path(cfg)
    before_content = before_path.read_text(encoding="utf-8")

    with mock.patch("os.replace", side_effect=OSError("simulated disk failure")):
        with pytest.raises(OSError):
            sch.save_oneoff(cfg, [{"id": "corrupt_attempt"}])

    after_content = before_path.read_text(encoding="utf-8")
    assert after_content == before_content, "쓰기 실패 후 기존 파일이 변형됨"

    # 실패한 임시 파일이 정리(삭제)됐는지도 확인(잔여 tmp 파일 누적 방지).
    leftover_tmp = list(before_path.parent.glob(".oneoff_schedule_*.tmp"))
    assert leftover_tmp == [], f"임시 파일이 정리되지 않고 남음: {leftover_tmp}"


def test_atomic2_save_oneoff_produces_valid_json_on_success(tmp_path):
    cfg = _cfg(tmp_path)
    sch.save_oneoff(cfg, [{"id": "a"}, {"id": "b"}])
    loaded = sch.load_oneoff(cfg)
    assert [r["id"] for r in loaded] == ["a", "b"]

    # 임시 파일이 남아있지 않아야 한다(정상 경로에서도 정리 확인).
    leftover_tmp = list(sch._oneoff_path(cfg).parent.glob(".oneoff_schedule_*.tmp"))
    assert leftover_tmp == []


# ── topic_id 연결(CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01) ────────

# TEST A: legacy — topic_id 없음 -> 기존 Golden10 resolver 경로(명시적 재확인)
def test_topicid_a_none_topic_id_uses_golden10_resolver():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft", topic_id=None)
    assert fn.func.__name__ == "run_blog_once_wp"


# TEST B: topic_id 존재 -> Topic resolver 경로
def test_topicid_b_present_topic_id_uses_topic_resolver():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft", topic_id="topic_abc")
    assert fn.func.__name__ == "run_topic_once_wp"
    assert fn.keywords.get("topic_id") == "topic_abc"


# TEST C: draft + topic_id
def test_topicid_c_draft_forwarded_to_topic_resolver():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft", topic_id="topic_abc")
    assert fn.keywords.get("status") == "draft"


# TEST D: publish + topic_id
def test_topicid_d_publish_forwarded_to_topic_resolver():
    fn = PIPE.resolve_blog_oneoff_publish_fn({}, "publish", topic_id="topic_abc")
    assert fn.keywords.get("status") == "publish"


def test_topicid_invalid_mode_with_topic_id_still_rejected():
    with pytest.raises(ValueError):
        PIPE.resolve_blog_oneoff_publish_fn({}, "weird_mode", topic_id="topic_abc")


def test_topicid_actual_call_routes_to_run_topic_once_wp_not_golden10():
    """topic_id가 있으면 실제 호출 시 run_blog_once_wp(Golden10)가 아니라
    run_topic_once_wp가 호출되는지 확인한다(실제 WP/생성 없음, mock)."""
    with mock.patch("modules.topic_publish_adapter.run_topic_once_wp") as m_topic, \
         mock.patch("modules.blog_scheduler_adapter.run_blog_once_wp") as m_golden:
        m_topic.return_value = {"produced": 1}
        fn = PIPE.resolve_blog_oneoff_publish_fn({}, "draft", topic_id="topic_abc")
        fn({"x": 1}, max_count=1)
        m_topic.assert_called_once()
        m_golden.assert_not_called()


# TEST F: JSON round-trip — topic_id 저장 -> load -> 동일 topic_id 복원
def test_topicid_f_json_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, when, "draft", topic_id="topic_roundtrip_1")
    assert entry["topic_id"] == "topic_roundtrip_1"

    loaded = sch.load_oneoff(cfg)
    assert len(loaded) == 1
    assert loaded[0]["topic_id"] == "topic_roundtrip_1"


def test_topicid_legacy_entry_has_no_topic_id_key_when_omitted(tmp_path):
    """topic_id를 넘기지 않은 신규 예약은 entry에 'topic_id' 키 자체가 없어야
    한다(기존 레거시 entry와 완전히 동일한 shape 유지 — additive 원칙)."""
    cfg = _cfg(tmp_path)
    when = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, when, "draft")
    assert "topic_id" not in entry

    loaded = sch.load_oneoff(cfg)
    assert "topic_id" not in loaded[0]


# TEST G: 기존(topic_id 없는) reservation이 execute_due_oneoff를 통해 정상
# 실행되는지(레거시 backward compatibility) — resolve_fn이 (mode, None)으로
# 호출되고 정상적으로 완료 처리되는지 확인.
def test_topicid_g_legacy_reservation_without_topic_id_still_executes(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "draft")
    assert "topic_id" not in entry

    mock_run_once_fn = mock.Mock(return_value={"produced": 1})
    resolve_fn = mock.Mock(return_value=mock_run_once_fn)

    result = sch.execute_due_oneoff(cfg, entry, resolve_fn)

    assert result == "completed"
    resolve_fn.assert_called_once_with("draft", None)


# TEST H: topic 있는 예약의 실행 실패가 기존 One-off failure 처리와 정상
# 연결되는지(resolve_fn에 topic_id가 정확히 전달되고, 실패 시 기존과 동일하게
# "failed"로 마킹되는지).
def test_topicid_h_topic_reservation_execution_failure_marks_failed(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 25, 14, 0, tzinfo=KST)
    entry = sch.add_oneoff_reservation(cfg, now - timedelta(minutes=1), "draft",
                                        topic_id="topic_missing_xyz")

    mock_run_once_fn = mock.Mock(
        return_value={"produced": 0, "reason": "topic_not_found"})
    resolve_fn = mock.Mock(return_value=mock_run_once_fn)

    result = sch.execute_due_oneoff(cfg, entry, resolve_fn)

    assert result == "failed"
    resolve_fn.assert_called_once_with("draft", "topic_missing_xyz")
    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "failed"
    assert saved[0]["topic_id"] == "topic_missing_xyz"
