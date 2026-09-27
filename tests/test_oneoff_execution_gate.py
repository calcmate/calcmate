# -*- coding: utf-8 -*-
"""tests/test_oneoff_execution_gate.py

CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-EXECUTION-DECOUPLING-A-IMPLEMENT-01 검증.

목적: One-off Scheduler(modules/scheduler.py::run_oneoff_scheduler_loop)가
"BLOG_SCHEDULE.enabled OR AUTO_PUBLISHING.enabled"로 기동될 수 있게 된 뒤에도,
topic_id가 없는(Golden10 계열) due 예약은 BLOG_SCHEDULE.enabled가 켜져 있을
때만 실행되고, 꺼져 있으면 실행하지 않고 pending을 그대로 유지하는지 확인한다
(실패 처리 금지). topic_id가 있는(Topic Pool) 예약은 이 gate와 무관하게 항상
정상 실행되어야 한다.

기존 tests/test_content_sync_enabled_reload.py의 "fake sleep + capped tick"
기법을 그대로 재사용해 run_oneoff_scheduler_loop()의 while True를 안전하게
끊는다. 실제 WordPress/DB/AI 호출은 전혀 발생하지 않는다(resolve_fn을 fake로
완전히 대체).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.scheduler as sch

KST = ZoneInfo("Asia/Seoul")


class _StopLoop(Exception):
    """run_oneoff_scheduler_loop()의 while True를 안전하게 끊기 위한 신호
    (tests/test_content_sync_enabled_reload.py와 동일한 기법)."""


def _write_config(tmp_path, blog_schedule_enabled: bool):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.dump({"BLOG_SCHEDULE": {"enabled": blog_schedule_enabled}},
                  allow_unicode=True),
        encoding="utf-8",
    )


def _cfg(tmp_path, blog_schedule_enabled: bool):
    _write_config(tmp_path, blog_schedule_enabled)
    # SINGLE-OWNER-HARDENING M1: 이 테스트들은 production owner 루프의 동작을 검증한다.
    return {"_root": str(tmp_path), "scheduler_line": "blog", "_wp_target": "production",
            "BLOG_SCHEDULE": {"enabled": blog_schedule_enabled}}


def _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks, on_tick=None):
    calls = {"n": 0}

    def _fake_sleep(seconds):
        calls["n"] += 1
        if on_tick:
            on_tick(calls["n"])
        if calls["n"] >= n_ticks:
            raise _StopLoop()

    monkeypatch.setattr(sch.time, "sleep", _fake_sleep)
    with pytest.raises(_StopLoop):
        sch.run_oneoff_scheduler_loop(cfg, resolve_fn, poll_seconds=1)


def _make_resolve_fn(calls: list, produced: int = 1):
    """resolve_fn(mode, topic_id) -> run_once_fn(cfg, max_count) 형태를 그대로
    흉내내는 fake. 실제 WP/생성 없이 호출 여부만 기록한다."""
    def _resolve(mode, topic_id=None):
        def _run_once_fn(cfg, max_count=1):
            calls.append({"mode": mode, "topic_id": topic_id})
            return {"produced": produced}
        return _run_once_fn
    return _resolve


def _past(minutes=1):
    return datetime.now(KST) - timedelta(minutes=minutes)


# ── _blog_schedule_enabled_now() / _blog_schedule_config_path() 단위 테스트 ──
# (content_sync의 동일 계열 테스트와 같은 구조)

def test_enabled_now_reads_true_from_disk(tmp_path):
    cfg = _cfg(tmp_path, blog_schedule_enabled=True)
    assert sch._blog_schedule_enabled_now(cfg, fallback=False) is True


def test_enabled_now_reads_false_from_disk(tmp_path):
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    assert sch._blog_schedule_enabled_now(cfg, fallback=True) is False


def test_enabled_now_reflects_change_between_calls(tmp_path):
    cfg = _cfg(tmp_path, blog_schedule_enabled=True)
    assert sch._blog_schedule_enabled_now(cfg, fallback=True) is True

    _write_config(tmp_path, blog_schedule_enabled=False)
    assert sch._blog_schedule_enabled_now(cfg, fallback=True) is False

    _write_config(tmp_path, blog_schedule_enabled=True)
    assert sch._blog_schedule_enabled_now(cfg, fallback=False) is True


def test_enabled_now_falls_back_when_file_missing(tmp_path):
    cfg = {"_root": str(tmp_path / "does-not-exist")}
    assert sch._blog_schedule_enabled_now(cfg, fallback=True) is True
    assert sch._blog_schedule_enabled_now(cfg, fallback=False) is False


def test_enabled_now_missing_key_preserves_default_semantics(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.dump({}), encoding="utf-8")
    cfg = {"_root": str(tmp_path)}
    assert sch._blog_schedule_enabled_now(cfg, fallback=True) is True


# ── A. Golden10 예약(topic_id=None) ───────────────────────────────────

def test_a1_golden10_runs_when_blog_schedule_on(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, blog_schedule_enabled=True)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")  # topic_id 없음
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=1)

    assert calls == [{"mode": "draft", "topic_id": None}]
    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "completed"


def test_a2_golden10_skipped_when_blog_schedule_off(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=2)

    assert calls == [], "BLOG_SCHEDULE off일 때 Golden10 예약이 실행되면 안 된다"


def test_a3_skipped_golden10_reservation_stays_pending(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")
    resolve_fn = _make_resolve_fn([])

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=2)

    saved = sch.load_oneoff(cfg)
    assert saved[0]["id"] == entry["id"]
    assert saved[0]["status"] == "pending"


def test_a4_skipped_golden10_reservation_not_marked_failed_or_mutated(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")
    resolve_fn = _make_resolve_fn([])

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=3)

    saved = sch.load_oneoff(cfg)[0]
    assert saved["status"] not in ("completed", "failed")
    assert saved["executed_at"] is None
    assert saved["result"] is None
    assert saved["duplicate"] is False
    assert not sch._oneoff_lock_path(cfg).exists()  # lock을 건드리지도 않았어야 함


# ── B. Topic 예약(topic_id!=None) — gate와 무관하게 항상 실행 ─────────

@pytest.mark.parametrize("blog_enabled", [True, False])
def test_b_topic_reservation_runs_regardless_of_blog_schedule(tmp_path, monkeypatch, blog_enabled):
    cfg = _cfg(tmp_path, blog_schedule_enabled=blog_enabled)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft", topic_id="topic_abc")
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=1)

    assert calls == [{"mode": "draft", "topic_id": "topic_abc"}]
    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "completed"


def test_b_topic_and_golden10_mixed_only_golden10_gated(tmp_path, monkeypatch):
    """같은 tick에 Golden10과 Topic 예약이 동시에 due여도, Golden10만 gate에
    걸리고 Topic은 정상 실행되어야 한다."""
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    golden = sch.add_oneoff_reservation(cfg, _past(), "draft")
    topic = sch.add_oneoff_reservation(cfg, _past(minutes=2), "publish", topic_id="topic_xyz")
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=1)

    assert calls == [{"mode": "publish", "topic_id": "topic_xyz"}]
    saved = {e["id"]: e for e in sch.load_oneoff(cfg)}
    assert saved[golden["id"]]["status"] == "pending"
    assert saved[topic["id"]]["status"] == "completed"


# ── E. 재활성화: OFF -> ON 전환 후 다음 tick에서 실행 가능 ────────────

def test_e_golden10_off_then_on_allows_next_tick(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, blog_schedule_enabled=False)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    def _on_tick(n):
        if n == 1:
            _write_config(tmp_path, blog_schedule_enabled=True)  # tick1 이후 ON

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=2, on_tick=_on_tick)

    assert calls == [{"mode": "draft", "topic_id": None}]
    saved = sch.load_oneoff(cfg)
    assert saved[0]["status"] == "completed"


def test_e_golden10_on_then_off_blocks_pending_run(tmp_path, monkeypatch):
    """가장 중요한 안전 방향(tests/test_content_sync_enabled_reload.py::
    test_enabled_flips_off_mid_loop_blocks_pending_run과 동일한 구조): tick1에서
    BLOG_SCHEDULE=true였지만 lock이 바빠 보류된 상태에서 config가 false로
    바뀌면, lock이 풀려도 tick2는 실행하면 안 된다."""
    cfg = _cfg(tmp_path, blog_schedule_enabled=True)
    entry = sch.add_oneoff_reservation(cfg, _past(), "draft")
    calls = []
    resolve_fn = _make_resolve_fn(calls)

    lock_busy_for_tick1 = {"acquired_once": False}
    real_acquire = sch._acquire_oneoff_lock

    def _fake_acquire(cfg, stale_seconds=1800):
        if not lock_busy_for_tick1["acquired_once"]:
            lock_busy_for_tick1["acquired_once"] = True
            return False  # tick1: 다른 실행이 진행 중이라고 가정 — 이번 tick은 건너뜀
        return real_acquire(cfg, stale_seconds)

    monkeypatch.setattr(sch, "_acquire_oneoff_lock", _fake_acquire)

    def _on_tick(n):
        if n == 1:
            _write_config(tmp_path, blog_schedule_enabled=False)  # tick1과 tick2 사이 OFF 전환

    _run_loop_n_ticks(monkeypatch, cfg, resolve_fn, n_ticks=2, on_tick=_on_tick)

    assert calls == [], "OFF 전환 이후에는 lock이 풀려도 Golden10 예약이 실행되면 안 된다"
    assert sch.load_oneoff(cfg)[0]["status"] == "pending"


# ── 기존 recurring/기존 dedup/lock 로직 무변경 회귀(간접 확인) ─────────

def test_existing_dedup_still_works_after_gate_change(tmp_path):
    """4번 gate 추가가 기존 add_oneoff_reservation()의 dedup 로직 자체를
    건드리지 않았는지 재확인(회귀)."""
    cfg = _cfg(tmp_path, blog_schedule_enabled=True)
    when = _past()
    first = sch.add_oneoff_reservation(cfg, when, "draft")
    second = sch.add_oneoff_reservation(cfg, when, "draft")
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
