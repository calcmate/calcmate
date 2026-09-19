# -*- coding: utf-8 -*-
"""
tests/test_calculator_faq_example_context.py — CALCMATE-BLOG-QUALITY-STEP135 (Phase C)

검증 범위: FAQ 생성 경로에 deterministic example_context가 전달되는지, 그리고
example_context=None일 때 기존 동작이 완전히 보존되는지.

경로: auto_generate_all(example_context=ctx) → generate_faq(example_context=ctx)
      → get_faq_prompt(example_context=ctx) → "[검증된 계산 데이터]" 블록
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content.calculator import prompt as PM
from modules import calculator_faq_generator as faq_mod
from content.calculator.example_builder import build_example_context


_FAKE_CALC = {
    "name": "테스트 계산기", "slug": "test-calc", "category": "노무/급여",
    "formula": "a * b", "input_schema": "{}", "output_schema": "{}",
}


# ── Test A: None fallback — 기존 caller가 깨지지 않는지 ──────────────────────

def test_get_faq_prompt_none_context_same_as_before():
    """example_context 인자를 아예 안 주는 기존 positional 호출이 여전히 동작하고,
    결과에 [검증된 계산 데이터] 블록이 '제공된 계산 데이터 없음'으로 채워진다."""
    system_no_arg, user_no_arg = PM.get_faq_prompt(_FAKE_CALC, 6, 8)
    system_explicit_none, user_explicit_none = PM.get_faq_prompt(_FAKE_CALC, 6, 8, "", None)
    assert system_no_arg == system_explicit_none
    assert user_no_arg == user_explicit_none
    assert "[검증된 계산 데이터]" in system_no_arg
    assert "제공된 계산 데이터 없음" in system_no_arg


def test_generate_faq_existing_callers_unaffected(monkeypatch):
    """calculator_pipeline.py/calculator_reviewer.py 등 기존 caller 패턴
    (cfg, calc) 2-positional 호출이 example_context 없이 여전히 동작해야 한다."""
    captured = {}

    def _fake_get_faq_prompt(calc, n, n_max, law_ssot_block="", example_context=None):
        captured["example_context"] = example_context
        return "sys", "user"

    class _FakeProvider:
        def chat(self, system, user, model, max_tokens=1200):
            return '{"faq": [{"question": "q", "answer": "a"}]}', 10

    monkeypatch.setattr(faq_mod.PM, "get_faq_prompt", _fake_get_faq_prompt)
    monkeypatch.setattr(faq_mod, "build_provider_for_role", lambda role, cfg: (_FakeProvider(), "fake-model"))

    result = faq_mod.generate_faq({}, _FAKE_CALC)  # 기존 방식 그대로: example_context 생략

    assert captured["example_context"] is None
    assert result == [{"question": "q", "answer": "a"}]


# ── Test B: prompt injection ──────────────────────────────────────────────

def test_get_faq_prompt_injects_verified_data_block():
    ctx = {"verified_examples": [{"inputs": {"x": 1}, "result": {"y": 2}}], "facts": []}
    system, user = PM.get_faq_prompt(_FAKE_CALC, 6, 8, "", ctx)
    assert "[검증된 계산 데이터]" in system
    import json
    assert json.dumps(ctx, ensure_ascii=False) in system
    assert "제공된 계산 데이터 없음" not in system


def test_get_faq_prompt_context_does_not_alter_other_rules():
    """example_context 유무와 무관하게 FAQ 요구사항/JSON 포맷 지시 등 기존 규칙 문구는
    완전히 동일해야 한다(주입 블록만 추가, 기존 텍스트 변경 없음)."""
    ctx = {"verified_examples": [{"inputs": {}, "result": {}}], "facts": []}
    system_none, _ = PM.get_faq_prompt(_FAKE_CALC, 6, 8, "", None)
    system_with_ctx, _ = PM.get_faq_prompt(_FAKE_CALC, 6, 8, "", ctx)
    # 두 system 문자열에서 "[검증된 계산 데이터]" 블록 이전 부분은 완전히 동일해야 한다.
    marker = "[검증된 계산 데이터]\n"
    before_none = system_none.split(marker)[0]
    before_ctx = system_with_ctx.split(marker)[0]
    assert before_none == before_ctx


# ── Test C: writer forwarding ──────────────────────────────────────────────

def test_auto_generate_all_forwards_example_context_to_faq(monkeypatch):
    import content.calculator.writer as writer_mod

    captured = {}

    def _fake_generate_faq(cfg, calc, example_context=None):
        captured["faq_example_context"] = example_context
        return [{"question": "q", "answer": "a"}]

    monkeypatch.setattr(writer_mod, "generate_faq", _fake_generate_faq)
    monkeypatch.setattr(writer_mod, "_seo_pair", lambda cfg, calc: {"seo_title": "t", "seo_description": "d"})
    monkeypatch.setattr(writer_mod, "generate_article", lambda *a, **kw: "<p>dummy</p>")
    monkeypatch.setattr(writer_mod, "_image_pair", lambda cfg, calc: {"body": "", "thumbnail": ""})

    ctx = {"verified_examples": [{"inputs": {"a": 1}, "result": {"b": 2}}], "facts": []}
    calc = dict(_FAKE_CALC)
    writer_mod.auto_generate_all({}, calc, save=False, auto_review=False, example_context=ctx)

    assert captured["faq_example_context"] == ctx


def test_auto_generate_all_none_context_reaches_faq_as_none(monkeypatch):
    import content.calculator.writer as writer_mod

    captured = {}

    def _fake_generate_faq(cfg, calc, example_context=None):
        captured["faq_example_context"] = example_context
        return [{"question": "q", "answer": "a"}]

    monkeypatch.setattr(writer_mod, "generate_faq", _fake_generate_faq)
    monkeypatch.setattr(writer_mod, "_seo_pair", lambda cfg, calc: {"seo_title": "t", "seo_description": "d"})
    monkeypatch.setattr(writer_mod, "generate_article", lambda *a, **kw: "<p>dummy</p>")
    monkeypatch.setattr(writer_mod, "_image_pair", lambda cfg, calc: {"body": "", "thumbnail": ""})

    calc = dict(_FAKE_CALC)
    writer_mod.auto_generate_all({}, calc, save=False, auto_review=False)  # example_context 생략

    assert captured["faq_example_context"] is None


# ── Test D: 실제 production context identity (jeonse-vs-monthly) ────────────

def test_real_jeonse_context_values_preserved_through_faq_prompt():
    """build_example_context()가 만든 실제 deterministic 값(STEP132 source of truth)이
    FAQ prompt 문자열까지 그대로(재계산 없이) 보존되는지 확인한다."""
    calc = {
        "slug": "jeonse-vs-monthly", "name": "전세 vs 월세 비교 계산기", "category": "부동산/임대",
        "formula": (
            '{"jeonse_opp_cost": "(jeonse_deposit - wolse_deposit) * rate / 100 / 12", '
            '"wolse_to_jeonse_equiv": "wolse_deposit + wolse_amount * 1200 / rate", '
            '"monthly_savings": "wolse_amount - (jeonse_deposit - wolse_deposit) * rate / 100 / 12"}'
        ),
        "input_schema": (
            '{"jeonse_deposit": "number", "wolse_deposit": "number", '
            '"wolse_amount": "number", "rate": "number"}'
        ),
        "output_schema": (
            '{"jeonse_opp_cost": "number", "wolse_to_jeonse_equiv": "number", '
            '"monthly_savings": "number"}'
        ),
    }
    ctx = build_example_context(calc)  # source of truth — 재계산하지 않음
    assert ctx is not None
    result = ctx["verified_examples"][0]["result"]
    assert result["jeonse_opp_cost"] == pytest.approx(708_333, abs=1)
    assert result["wolse_to_jeonse_equiv"] == pytest.approx(222_000_000, abs=1)
    assert result["monthly_savings"] == pytest.approx(91_667, abs=1)

    system, _ = PM.get_faq_prompt(calc, 6, 8, "", ctx)
    import json
    assert json.dumps(ctx, ensure_ascii=False) in system
    # 직렬화된 블록 안에 실제 숫자가 그대로 문자열로 보존되는지도 확인.
    assert "708333" in system.replace(".0", "") or "708333.0" in system or str(result["jeonse_opp_cost"]) in system
    assert str(result["wolse_to_jeonse_equiv"]) in system
    assert str(result["monthly_savings"]) in system


# ── Test E: 기존 caller compatibility(positional/keyword 둘 다) ─────────────

def test_generate_faq_positional_and_keyword_calls_both_work(monkeypatch):
    calls = []

    def _fake_get_faq_prompt(calc, n, n_max, law_ssot_block="", example_context=None):
        calls.append(example_context)
        return "sys", "user"

    class _FakeProvider:
        def chat(self, system, user, model, max_tokens=1200):
            return '{"faq": [{"question": "q", "answer": "a"}]}', 10

    monkeypatch.setattr(faq_mod.PM, "get_faq_prompt", _fake_get_faq_prompt)
    monkeypatch.setattr(faq_mod, "build_provider_for_role", lambda role, cfg: (_FakeProvider(), "fake-model"))

    # 기존 caller 패턴 1: 완전 positional (modules/calculator_pipeline.py 스타일)
    faq_mod.generate_faq({}, _FAKE_CALC.get("name"))
    # 기존 caller 패턴 2: (cfg, calc) 2-positional (modules/calculator_reviewer.py 스타일)
    faq_mod.generate_faq({}, _FAKE_CALC)
    # 신규 caller 패턴: keyword로 example_context 명시 전달
    ctx = {"verified_examples": [], "facts": []}
    faq_mod.generate_faq({}, _FAKE_CALC, example_context=ctx)

    assert calls == [None, None, ctx]
