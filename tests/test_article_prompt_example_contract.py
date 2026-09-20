# -*- coding: utf-8 -*-
"""
tests/test_article_prompt_example_contract.py — CALCMATE-BLOG-QUALITY-STEP157

STEP155/156에서 확정된 원인(verified_examples는 LLM에 정확히 전달되지만,
"숫자를 임의로 생성하거나 변경하지 않는다"는 약한 문구만으로는 LLM이 새로운
날짜/급여 등의 시나리오를 만들어내는 것을 막지 못함)에 대한 수정으로,
content/calculator/prompt.py::get_article_prompt()에 "[계산 예시 작성 규칙]"
블록을 추가했다. 이 테스트는 LLM을 호출하지 않고 get_article_prompt()/
get_faq_prompt()의 반환 문자열만 직접 검사한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content.calculator.prompt import (
    get_article_prompt, get_faq_prompt,
    _H2_RULE, _HTML_OUTPUT_RULE, _NO_LINK_RULE,
)

_CALC = {
    "slug": "severance-pay", "name": "퇴직금 계산기", "category": "노무/급여",
    "formula": "avg_monthly_wage * (days_worked / 365)",
    "input_schema": '{"avg_monthly_wage": "number", "start_date": "date", "end_date": "date"}',
    "output_schema": '{"severance_pay": "number"}',
}

_SEO = {"seo_title": "t", "seo_description": "d"}
_FAQ = []

_EXAMPLE_CONTEXT = {
    "verified_examples": [
        {"inputs": {"avg_monthly_wage": 3000000, "start_date": "2025-01-01", "end_date": "2025-06-01"},
         "result": {"severance_pay": 0}},
        {"inputs": {"avg_monthly_wage": 3000000, "start_date": "2024-01-01", "end_date": "2025-06-01"},
         "result": {"severance_pay": 4249315.068493151}},
    ],
    "facts": [],
}


# ── Test A: 계산 예시 계약 존재 ──────────────────────────────────────────────

def test_a_example_usage_contract_present():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT)

    # verified_examples 중 하나를 그대로 사용하라는 지시
    assert "verified_examples" in system
    assert "그대로 사용" in system

    # 입력값/결과값 변경 금지 + 새로운 입력값 생성 금지
    assert "절대 변경하지 않는다" in system
    assert "임의의 날짜" in system and "새로 만들어" in system

    # 여러 개를 전부 사용할 필요는 없음(ANY COMPLETE와 정합)
    assert "전부 사용할 필요는 없다" in system

    # "모든 verified_examples를 반드시 사용" 같은 과잉 강제 문구는 없어야 한다
    assert "모두 사용" not in system
    assert "전부 사용해야" not in system


# ── Test B: verified_examples 원문 보존(기존 전달 경로 무손상) ──────────────

def test_b_verified_examples_raw_json_preserved():
    import json
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT)
    example_str = json.dumps(_EXAMPLE_CONTEXT, ensure_ascii=False)
    assert example_str in system
    # 결정론적 정확값(severance_pay=4249315.068493151)이 실제로 프롬프트에 존재
    assert "4249315" in system


def test_b_none_context_still_reaches_expected_placeholder():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, None)
    assert "제공된 계산 데이터 없음" in system


# ── Test C: 기존 핵심 prompt 계약 보존 ───────────────────────────────────────

def test_c_existing_core_rules_preserved():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT)
    assert _H2_RULE in system
    assert _HTML_OUTPUT_RULE in system
    assert _NO_LINK_RULE in system
    assert "[검증된 계산 데이터]" in system
    # 기존 숫자 보호 규칙 문구 자체는 삭제/변경되지 않았어야 한다
    assert "[숫자 보호 규칙]\n- 숫자를 임의로 생성하거나 변경하지 않는다.\n" in system
    assert "[BODY_HTML_START]" in system and "[BODY_HTML_END]" in system


def test_c_ssot_calculator_list_block_preserved():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT,
                                    valid_calculators="- 퇴직금 계산기 (severance-pay)\n")
    assert "[현재 SalaryMate에 존재하는 계산기 목록 (SSOT — 이 목록 외에는 존재하지 않는다)]" in system
    assert "- 퇴직금 계산기 (severance-pay)" in system


# ── Test D: FAQ prompt 미변경 확인 ───────────────────────────────────────────

def test_d_faq_prompt_does_not_gain_new_article_contract():
    faq_system, _ = get_faq_prompt(_CALC, example_context=_EXAMPLE_CONTEXT)
    # 이번에 신설한 "계산 예시 작성 규칙" 블록은 article prompt 전용이며
    # FAQ prompt에는 삽입되지 않아야 한다.
    assert "[계산 예시 작성 규칙" not in faq_system
    assert "[숫자 보호 규칙]" not in faq_system

    # FAQ 자체의 기존 계약(본문 복사 금지 등)은 그대로 유지되어야 한다.
    assert "본문의 문장이나 문단을 그대로 복사하거나 어미만 바꿔 반복하지 않는다." in faq_system
    assert "차별화를 위해 법률·수치·기간을 임의로 변경하거나 새로운 사실을 만들어내지 않는다." in faq_system

    # example_context는 FAQ에도 계속 전달되어야 한다(기존 동작 무변경).
    assert "verified_examples" in faq_system


# ── Test A2: 계산 예시 결과값 표기 규칙(Format contract) 존재 — CALCMATE-BLOG-QUALITY-STEP160 ──
#
# STEP158 실제 LLM E2E에서 verified_examples 입력값은 정확히 재사용되었으나,
# result가 "4249315.07원"처럼 소수점 포함 형태로 출력되어 G-CALC이 인식하는
# _format_krw() 변형(정수 기반)과 불일치해 FAIL이 발생했다. STEP159에서 설계하고
# 이번 STEP에서 구현한 신규 문구가 실제로 article prompt에 존재하는지 확인한다.

def test_a2_result_format_contract_present():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT)

    # 금액으로 한정(비금전 계산기(BMI 등) 오적용 방지 — "결과값"/"모든 결과" 같은
    # 일반화된 표현이 아니라 "금액 결과"로 명시되어야 한다)
    assert "금액 결과" in system

    # 소수점 이하 "절사"(버림) — G-CALC의 _pick_check_amounts()가 int(v)로 절사하는
    # 동작과 정확히 일치시키기 위함. "반올림"/"round" 계열 표현은 사용하지 않는다.
    assert "소수점 이하를 버리고" in system
    assert "반올림" not in system
    assert "round" not in system.lower()

    # 정수 원 단위 + 천 단위 쉼표
    assert "정수 원 단위" in system
    assert "천 단위마다 쉼표" in system

    # 구체적 예시(소수 원본 → 정수+쉼표 결과)가 실제로 포함되어야 한다
    assert "4249315.068" in system
    assert "4,249,315원" in system

    # "값을 변경하는 것"이 아니라는 명시(기존 [계산 예시 작성 규칙]의
    # "절대 변경하지 않는다"와의 논리적 충돌을 문구 자체에서 해소)
    assert "값의 의미를 바꾸는 것이 아니라" in system


def test_a2_format_contract_block_header_present():
    system, _ = get_article_prompt(_CALC, _SEO, _FAQ, _EXAMPLE_CONTEXT)
    assert "[계산 예시 결과값 표기 규칙]" in system
    # 기존 STEP157 블록 뒤, [숫자 보호 규칙]/[계산 예시 작성 규칙] 순서 이후에 위치해야 한다.
    idx_existing = system.find("[계산 예시 작성 규칙 — 반드시 준수]")
    idx_new = system.find("[계산 예시 결과값 표기 규칙]")
    assert idx_existing != -1 and idx_new != -1 and idx_existing < idx_new


# ── Test D2: FAQ prompt에 신규 format 규칙 미삽입 확인 ───────────────────────

def test_d2_faq_prompt_does_not_gain_new_format_contract():
    faq_system, _ = get_faq_prompt(_CALC, example_context=_EXAMPLE_CONTEXT)
    assert "[계산 예시 결과값 표기 규칙]" not in faq_system
    assert "소수점 이하를 버리고" not in faq_system
