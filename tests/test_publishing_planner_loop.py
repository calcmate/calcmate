# -*- coding: utf-8 -*-
"""tests/test_publishing_planner_loop.py

CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-EXECUTION-DECOUPLING-B-IMPLEMENT-01 검증.

modules/publishing_planner.py::run_planner_loop()의 AUTO_PUBLISHING.enabled
기반 polling 동작을 검증한다. 기존 tests/test_content_sync_enabled_reload.py/
tests/test_oneoff_execution_gate.py와 동일한 "fake sleep + capped tick" 기법으로
while True를 안전하게 끊는다. run_planner_once()는 전부 fake로 대체하므로
실제 DB/파일/WP/AI는 전혀 건드리지 않는다.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.publishing_planner as planner


class _StopLoop(Exception):
    """run_planner_loop()의 while True를 안전하게 끊기 위한 신호."""


def _write_config(tmp_path, auto_publishing_enabled):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    if auto_publishing_enabled is None:
        payload = {}  # AUTO_PUBLISHING 키 자체가 없는 경우
    else:
        payload = {"AUTO_PUBLISHING": {"enabled": auto_publishing_enabled}}
    (cfg_dir / "config.yaml").write_text(yaml.dump(payload, allow_unicode=True),
                                          encoding="utf-8")


def _cfg(tmp_path, auto_publishing_enabled):
    _write_config(tmp_path, auto_publishing_enabled)
    return {"_root": str(tmp_path),
            "AUTO_PUBLISHING": {"enabled": bool(auto_publishing_enabled)}}


def _run_loop_n_ticks(monkeypatch, cfg, n_ticks, on_tick=None, run_once_fn=None):
    calls = {"n": 0}

    def _fake_sleep(seconds):
        calls["n"] += 1
        if on_tick:
            on_tick(calls["n"])
        if calls["n"] >= n_ticks:
            raise _StopLoop()

    monkeypatch.setattr(planner.time, "sleep", _fake_sleep)
    if run_once_fn is not None:
        monkeypatch.setattr(planner, "run_planner_once", run_once_fn)
    with pytest.raises(_StopLoop):
        planner.run_planner_loop(cfg, poll_seconds=1)


def _counting_run_once(calls, result=None):
    def _fn(cfg, now=None, rng=None, dup_check_fn=None):
        calls.append(1)
        return result or {"scheduled": 0, "reason": "", "results": []}
    return _fn


# ── _auto_publishing_enabled_now() 단위 테스트 ───────────────────────

def test_enabled_now_reads_true_from_disk(tmp_path):
    cfg = _cfg(tmp_path, True)
    assert planner._auto_publishing_enabled_now(cfg, fallback=False) is True


def test_enabled_now_reads_false_from_disk(tmp_path):
    cfg = _cfg(tmp_path, False)
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is False


def test_enabled_now_reflects_change_between_calls(tmp_path):
    cfg = _cfg(tmp_path, True)
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is True

    _write_config(tmp_path, False)
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is False

    _write_config(tmp_path, True)
    assert planner._auto_publishing_enabled_now(cfg, fallback=False) is True


def test_enabled_now_missing_key_preserves_fallback(tmp_path):
    """AUTO_PUBLISHING 키 자체가 없는(파일은 정상 파싱됨) 경우 — content_sync와
    동일하게 fallback을 사용한다(정상적인 누락 상황)."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(yaml.dump({}), encoding="utf-8")
    cfg = {"_root": str(tmp_path)}
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is True
    assert planner._auto_publishing_enabled_now(cfg, fallback=False) is False


def test_enabled_now_fail_closed_on_read_failure(tmp_path):
    """content_sync와의 의도적 차이(Test E): 재로딩 자체가 실패(파일 없음)하면
    fallback이 True여도 무조건 False를 반환해야 한다(fail-closed)."""
    cfg = {"_root": str(tmp_path / "does-not-exist")}
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is False
    assert planner._auto_publishing_enabled_now(cfg, fallback=False) is False


def test_enabled_now_fail_closed_on_malformed_yaml(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text("not: valid: yaml: [[[", encoding="utf-8")
    cfg = {"_root": str(tmp_path)}
    assert planner._auto_publishing_enabled_now(cfg, fallback=True) is False


# ── Test A: disabled — run_planner_once 호출 0회 ────────────────────

def test_a_disabled_calls_run_planner_once_zero_times(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, False)
    calls = []
    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=3,
                       run_once_fn=_counting_run_once(calls))
    assert calls == []


# ── Test B: enabled — 각 tick에서 호출 ───────────────────────────────

def test_b_enabled_calls_run_planner_once_each_tick(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, True)
    calls = []
    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=3,
                       run_once_fn=_counting_run_once(calls))
    assert len(calls) == 3


def test_b_run_planner_once_receives_cfg(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, True)
    received = []

    def _fn(cfg_arg, now=None, rng=None, dup_check_fn=None):
        received.append(cfg_arg)
        return {"scheduled": 0, "reason": "", "results": []}

    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=1, run_once_fn=_fn)
    assert received == [cfg]


# ── Test C: runtime toggle ────────────────────────────────────────────

def test_c_runtime_toggle_reflected_each_tick(tmp_path, monkeypatch):
    """tick1: false->0회, tick2: true->1회, tick3: false->0회."""
    cfg = _cfg(tmp_path, False)
    calls = []

    def _on_tick(n):
        if n == 1:
            _write_config(tmp_path, True)   # tick1 이후 ON
        elif n == 2:
            _write_config(tmp_path, False)  # tick2 이후 다시 OFF

    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=3, on_tick=_on_tick,
                       run_once_fn=_counting_run_once(calls))
    # tick1(false)->0, tick2(true, tick1 이후 ON으로 바뀐 상태에서 실행)->1,
    # tick3(false, tick2 이후 OFF로 바뀐 상태에서 실행)->0
    assert len(calls) == 1


# ── Test D: exception recovery ───────────────────────────────────────

def test_d_exception_in_tick1_does_not_stop_loop(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, True)
    calls = []
    alert_calls = []

    def _fake_alert(cfg_arg, tag, level, title, detail="", event="error", min_interval=1800):
        alert_calls.append(tag)

    # 예외 알림이 실제 telegram_ops/telegram_notifier 경로를 타지 않도록 차단(아래 테스트와 동일 패턴).
    monkeypatch.setattr(planner.scheduler, "_alert_throttled", _fake_alert)

    def _fn(cfg_arg, now=None, rng=None, dup_check_fn=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated_planner_failure")
        return {"scheduled": 0, "reason": "", "results": []}

    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=2, run_once_fn=_fn)

    assert len(calls) == 2, "tick1 예외 발생 후에도 tick2가 정상 실행되어야 한다"
    assert alert_calls == ["publishing_planner_loop"]


def test_d_exception_notification_uses_existing_alert_throttled(tmp_path, monkeypatch):
    """새 알림 시스템을 만들지 않고 기존 scheduler._alert_throttled를
    재사용하는지 확인."""
    cfg = _cfg(tmp_path, True)
    alert_calls = []

    def _fake_alert(cfg_arg, tag, level, title, detail="", event="error", min_interval=1800):
        alert_calls.append(tag)

    monkeypatch.setattr(planner.scheduler, "_alert_throttled", _fake_alert)

    def _raising_fn(cfg_arg, now=None, rng=None, dup_check_fn=None):
        raise RuntimeError("boom")

    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=1, run_once_fn=_raising_fn)

    assert alert_calls == ["publishing_planner_loop"]


# ── Test E: config read failure -> fail-closed(위 단위 테스트에서 이미 확인) ──

def test_e_config_missing_during_loop_falls_closed(tmp_path, monkeypatch):
    """loop 도중 config.yaml 자체가 사라지면(권한/삭제 등) 그 tick은
    fail-closed로 건너뛰어야 한다."""
    cfg = _cfg(tmp_path, True)
    calls = []
    cfg_path = tmp_path / "config" / "config.yaml"

    def _on_tick(n):
        if n == 1:
            cfg_path.unlink()  # tick1 이후 파일 삭제

    _run_loop_n_ticks(monkeypatch, cfg, n_ticks=2, on_tick=_on_tick,
                       run_once_fn=_counting_run_once(calls))
    # tick1: 파일 있음+enabled=True -> 실행(1회), tick2: 파일 없음 -> fail-closed로 skip
    assert len(calls) == 1


# ── Test F: run_planner_once 계약 보존(간접 — loop가 시그니처를 그대로 전달하는지) ──

def test_f_loop_passes_through_now_rng_dup_check_fn(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fixed_now = datetime(2026, 9, 21, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    sentinel_rng = object()
    sentinel_dup = object()
    received = {}

    def _fn(cfg_arg, now=None, rng=None, dup_check_fn=None):
        received["now"] = now
        received["rng"] = rng
        received["dup_check_fn"] = dup_check_fn
        return {"scheduled": 0, "reason": "", "results": []}

    cfg = _cfg(tmp_path, True)
    calls = {"n": 0}

    def _fake_sleep(seconds):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise _StopLoop()

    monkeypatch.setattr(planner.time, "sleep", _fake_sleep)
    monkeypatch.setattr(planner, "run_planner_once", _fn)
    with pytest.raises(_StopLoop):
        planner.run_planner_loop(cfg, poll_seconds=1, now=fixed_now, rng=sentinel_rng,
                                 dup_check_fn=sentinel_dup)

    assert received["now"] == fixed_now
    assert received["rng"] is sentinel_rng
    assert received["dup_check_fn"] is sentinel_dup


def test_f_loop_does_not_reimplement_scheduling_logic():
    """run_planner_loop() 자체의 소스(주석 제외 실행 코드)에 scheduling 관련
    함수 호출이 재구현되지 않았는지 정적으로 확인(전부 run_planner_once()에
    위임). 주석/docstring에는 설명을 위해 이 단어들이 등장할 수 있으므로,
    "#"으로 시작하지 않고 docstring 밖의 실제 코드 라인만 검사한다."""
    import inspect
    import textwrap
    src = inspect.getsource(planner.run_planner_loop)
    # docstring(첫 함수의 """...""" 블록)을 제거하고 남은 실행 코드만 본다.
    body = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
    code_lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    code_only = "\n".join(code_lines)
    forbidden_calls = ["add_oneoff_reservation(", "transition_status(",
                       "record_failure(", "list_topics(", "candidate_times_for_date(",
                       "find_next_available_slot("]
    for f in forbidden_calls:
        assert f not in code_only, f"run_planner_loop()가 로직을 재구현한 것으로 보임: {f}"
    assert "run_planner_once(" in code_only, "run_planner_once() 위임 호출 자체가 없음"
