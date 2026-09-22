# -*- coding: utf-8 -*-
"""
tests/test_run_blog_oneoff_scheduler_loop.py
CALCMATE-ONEOFF-SCHEDULER-STANDALONE-IMPLEMENT-01 —
scripts/run_blog_oneoff_scheduler_loop.py 검증.

modules.scheduler.run_oneoff_scheduler_loop()와 main.resolve_blog_oneoff_publish_fn()
는 항상 monkeypatch로 대체한다 — 이 테스트는 실제 one-off 루프를 절대 실행하지
않으며, 실제 WP/DB 호출도 발생하지 않는다.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_blog_oneoff_scheduler_loop as launcher


def _base_cfg(tmp_path):
    return {"_root": str(tmp_path)}


# ── A: launcher import 가능 ──────────────────────────────────────────

def test_a_launcher_module_imports_and_has_expected_functions():
    assert hasattr(launcher, "main")
    assert hasattr(launcher, "build_blog_cfg")
    assert hasattr(launcher, "parse_args")


# ── B: resolver wiring(mock 기반) ────────────────────────────────────

def test_b_resolver_wiring_delegates_to_resolve_blog_oneoff_publish_fn(tmp_path, monkeypatch):
    """launcher가 main.resolve_blog_oneoff_publish_fn()을 정확한 인자로 호출하는지
    확인한다 — 실제 run_oneoff_scheduler_loop()는 monkeypatch로 완전히 대체해
    호출되지 않게 한다(인자로 받은 resolve_fn만 캡처)."""
    captured_calls = []
    captured_resolve_fn = {}

    def _fake_run_oneoff_scheduler_loop(cfg, resolve_fn, poll_seconds=30):
        captured_resolve_fn["fn"] = resolve_fn
        # 실제 loop(while True)는 절대 실행하지 않는다 — 여기서 즉시 반환.

    def _fake_resolve_blog_oneoff_publish_fn(cfg, mode, topic_id=None):
        captured_calls.append({"mode": mode, "topic_id": topic_id})
        return lambda cfg, max_count=1, driver_id=None: {"produced": 0}

    monkeypatch.setattr("modules.scheduler.run_oneoff_scheduler_loop",
                         _fake_run_oneoff_scheduler_loop)

    import main as _PIPE
    monkeypatch.setattr(_PIPE, "resolve_blog_oneoff_publish_fn",
                         _fake_resolve_blog_oneoff_publish_fn)

    (tmp_path / "config").mkdir(exist_ok=True)
    cfg_path = tmp_path / "config" / "config.yaml"
    cfg_path.write_text(
        "BLOG_SCHEDULE:\n  enabled: true\n"
        "OPENAI_API_KEY: dummy\nMODEL_CLEANER: dummy\nMODEL_WRITER: dummy\n",
        encoding="utf-8")

    monkeypatch.setattr(launcher, "BASE", tmp_path)

    class _FakeArgs:
        instance = None

    monkeypatch.setattr(launcher, "parse_args", lambda: _FakeArgs())

    def _fake_load_config(path):
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    monkeypatch.setattr(launcher, "load_config", _fake_load_config)

    launcher.main()

    # run_oneoff_scheduler_loop() 자체는 즉시 반환하는 stub이었지만, launcher가
    # 넘긴 resolve_fn을 호출해보면 main.resolve_blog_oneoff_publish_fn()이
    # 정확한 인자로 위임되는지 확인할 수 있다(실제 WP/DB 호출 없음).
    resolve_fn = captured_resolve_fn["fn"]
    resolve_fn("draft", None)          # Golden10 계열(topic_id 없음)
    resolve_fn("draft", "topic_xyz")   # Topic Pool 계열(topic_id 있음)

    assert captured_calls == [
        {"mode": "draft", "topic_id": None},
        {"mode": "draft", "topic_id": "topic_xyz"},
    ]


# ── C: run_oneoff_scheduler_loop 실제 signature 일치 확인 ────────────

def test_c_run_oneoff_scheduler_loop_signature_matches_launcher_call():
    import inspect
    import modules.scheduler as sch
    sig = inspect.signature(sch.run_oneoff_scheduler_loop)
    params = list(sig.parameters.keys())
    assert params[:2] == ["cfg", "resolve_fn"]


def test_c_resolve_blog_oneoff_publish_fn_signature_matches_launcher_call():
    import inspect
    import main as _PIPE
    sig = inspect.signature(_PIPE.resolve_blog_oneoff_publish_fn)
    params = list(sig.parameters.keys())
    assert params == ["cfg", "mode", "topic_id"]


# ── CALCMATE-ONEOFF-LAUNCHER-GATE-FIX-IMPLEMENT-01: 상위 gate 제거 확인 ──
# run_oneoff_scheduler_loop() 자체는 BLOG_SCHEDULE.enabled/AUTO_PUBLISHING.enabled에
# 의존하지 않으므로(모듈 docstring 원문: Topic Pool 예약은 이 gate의 영향을
# 받지 않고 항상 처리된다), 이 launcher도 두 플래그가 모두 false여도
# run_oneoff_scheduler_loop()를 반드시 호출해야 한다 — 이전에는 반대로
# "둘 다 false면 호출 안 함"을 검증했으나, 그 가정 자체가 이번 GATE-FIX의
# 대상이었다(오래된 테스트를 삭제하지 않고 새 정답에 맞게 갱신).

def test_both_switches_off_still_calls_the_loop(tmp_path, monkeypatch):
    called = {"n": 0}

    def _fake_run_oneoff_scheduler_loop(cfg, resolve_fn, poll_seconds=30):
        called["n"] += 1

    monkeypatch.setattr("modules.scheduler.run_oneoff_scheduler_loop",
                         _fake_run_oneoff_scheduler_loop)

    class _FakeArgs:
        instance = None

    monkeypatch.setattr(launcher, "parse_args", lambda: _FakeArgs())
    monkeypatch.setattr(launcher, "BASE", tmp_path)

    (tmp_path / "config").mkdir(exist_ok=True)
    cfg_path = tmp_path / "config" / "config.yaml"
    cfg_path.write_text(
        "BLOG_SCHEDULE:\n  enabled: false\nAUTO_PUBLISHING:\n  enabled: false\n"
        "OPENAI_API_KEY: dummy\nMODEL_CLEANER: dummy\nMODEL_WRITER: dummy\n",
        encoding="utf-8")

    def _fake_load_config(path):
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    monkeypatch.setattr(launcher, "load_config", _fake_load_config)

    launcher.main()

    assert called["n"] == 1
