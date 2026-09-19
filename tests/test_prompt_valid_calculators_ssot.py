# -*- coding: utf-8 -*-
"""tests/test_prompt_valid_calculators_ssot.py — STEP125 (Group C)

content/calculator/prompt.py::get_article_prompt()의 valid_calculators 인자가
ssot_block 조립에 정확히 반영되는지 검증한다:
  - 명시적으로 전달한 값이 그대로 사용되는지(정적 _VALID_CALCULATORS로 오염되지 않는지)
  - 전달하지 않으면(None, 기존 호출자와 동일) 정적 _VALID_CALCULATORS로 fallback하는지
  - 빈 문자열("")은 None과 다르게 취급되어 그대로(빈 값으로) 사용되는지
    (구현: `valid_calculators if valid_calculators is not None else _VALID_CALCULATORS`
    — falsy 체크가 아니라 `is not None` 체크이므로 ""는 fallback되지 않는다)

실제 AI API는 호출하지 않는다 — get_article_prompt()는 순수 문자열 조립 함수라
네트워크/DB 접근이 전혀 없다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content.calculator.prompt as PM
from content.calculator.prompt import get_article_prompt


CALC = {"name": "테스트 계산기", "category": "", "seo_desc": "", "formula": "",
        "input_schema": "", "output_schema": ""}


class TestExplicitValidCalculatorsUsed:
    def test_explicit_value_used_and_replaces_static_list(self):
        """명시적으로 전달한 값이 그대로 반영되고, 정적 목록(_VALID_CALCULATORS)의
        항목과 섞이지 않는지(대체이지 병합이 아님) 함께 확인한다."""
        custom = "- TEST-CALC-A (test-calc-a)\n- TEST-CALC-B (test-calc-b)\n"
        system, _ = get_article_prompt(CALC, intent="calculator", valid_calculators=custom)
        assert custom in system
        assert "annual-leave-allowance" not in system


class TestMissingValidCalculatorsFallsBackToStatic:
    def test_default_call_uses_static_valid_calculators(self):
        """기존 호출자(content/blog/prompt.py 등)처럼 valid_calculators를 넘기지
        않으면 정적 _VALID_CALCULATORS로 fallback한다."""
        system, _ = get_article_prompt(CALC, intent="calculator")
        assert PM._VALID_CALCULATORS in system


class TestEmptyStringIsNotNoneSoNotFallback:
    """valid_calculators=""는 None이 아니므로 fallback되지 않고 빈 값 그대로 사용된다
    (구현이 `is not None` 체크를 쓰기 때문 — falsy 체크였다면 "" also fallback했을 것)."""

    def test_empty_string_does_not_fall_back_to_static_list(self):
        system, _ = get_article_prompt(CALC, intent="calculator", valid_calculators="")
        assert PM._VALID_CALCULATORS not in system
