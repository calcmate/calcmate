# -*- coding: utf-8 -*-
"""tests/test_blog_h2_structure_regression.py — STEP132

STEP131에서 git 이력 대조로 확정한 두 가지 P1을 검증한다.

1. eligibility: "계산 예시"/"주의사항" H2가 "계산 방법" 다음, "FAQ" 이전에 존재해야 한다
   (502/severance-pay, 505/unemployment-benefit, 509/육아휴직_급여_계산기 base 구조와
   일치 — Golden10 실측 기준).
2. calculator: intent == "calculator" 전용 분기가 신설되어 "지급 조건"(506/510 실측에
   존재, git 이력 b6cf116~951362a=HEAD 전체에서 한 번도 빠진 적 없던 요소)을 포함하고,
   "계산 방법"은 포함하지 않아야 한다.

실제 AI API는 호출하지 않는다 — get_article_prompt()는 순수 문자열 조립 함수라
네트워크/DB 접근이 전혀 없다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content.calculator.prompt import get_article_prompt


def _h2_order(system_prompt: str) -> list:
    return re.findall(r"<h2>([^<]+)</h2>", system_prompt)


CALC = {"name": "테스트 계산기", "category": "", "seo_desc": "", "formula": "",
        "input_schema": "", "output_schema": ""}


class TestEligibilityStructure:
    def test_계산_예시_and_주의사항_present(self):
        system, _ = get_article_prompt(CALC, intent="eligibility")
        assert "<h2>계산 예시</h2>" in system
        assert "<h2>주의사항</h2>" in system

    def test_faq_present(self):
        system, _ = get_article_prompt(CALC, intent="eligibility")
        assert "<h2>FAQ</h2>" in system

    def test_order_is_correct(self):
        system, _ = get_article_prompt(CALC, intent="eligibility")
        order = _h2_order(system)
        assert order == ["지급 대상", "근로시간 조건", "제외 대상", "계산 방법",
                          "계산 예시", "주의사항", "FAQ"]


class TestCalculatorStructure:
    def test_exact_order(self):
        system, _ = get_article_prompt(CALC, intent="calculator")
        order = _h2_order(system)
        assert order == ["계산 원리", "지급 조건", "계산 예시", "주의사항", "FAQ"]

    def test_지급_조건_present(self):
        system, _ = get_article_prompt(CALC, intent="calculator")
        assert "<h2>지급 조건</h2>" in system

    def test_계산_방법_not_present(self):
        """calculator 전용 구조에는 '계산 방법' H2가 들어가지 않는다(506/510 실측과 일치)."""
        system, _ = get_article_prompt(CALC, intent="calculator")
        assert "<h2>계산 방법</h2>" not in system


class TestExistingIntentsUnchanged:
    """howto/documents는 STEP130에서 이미 실제 WP와 완전히 일치함을 확인했다 —
    이번 STEP132 수정이 이 둘을 건드리지 않았는지 회귀 검증한다."""

    def test_howto_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="howto")
        order = _h2_order(system)
        assert order == ["이용 절차", "계산 예시", "주의사항", "FAQ"]

    def test_documents_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="documents")
        order = _h2_order(system)
        assert order == ["필수 서류 목록", "서류 발급 방법", "제출 기한 및 절차",
                          "주의사항", "FAQ"]


class TestGeneralCalculatorFallbackUnchanged:
    """intent가 명시적으로 'calculator'가 아니고 카테고리 기반 자동판정이
    general_calculator로 떨어지는 기존 폴백 구조는 이번 STEP에서 변경하지 않는다."""

    def test_general_calculator_fallback_structure_unchanged(self):
        calc = dict(CALC, category="존재하지 않는 카테고리")
        system, _ = get_article_prompt(calc, intent=None)
        order = _h2_order(system)
        assert order == ["계산 원리", "계산 방법", "계산 예시", "주의사항", "FAQ"]


class TestHealthMetricStructure:
    """STEP160: health_metric의 '계산 원리' H2 설명 문구를 조건부 역사 언급
    허용으로 최소 수정했다 — H2 이름/순서는 그대로 유지되어야 한다."""

    def test_h2_order_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="health_metric")
        order = _h2_order(system)
        assert order == ["계산 원리", "계산 방법", "판정 기준", "해석 방법", "주의사항", "FAQ"]

    def test_conditional_history_phrase_present(self):
        """'공식 유래와 계산 원리 설명'(무조건적 유래 서술 요구)이 아니라
        '실질적으로 도움이 될 때만 1~2문장 이내로 간단히 언급'하는 조건부
        문구로 교체되었는지 확인한다."""
        system, _ = get_article_prompt(CALC, intent="health_metric")
        assert "공식 유래와 계산 원리 설명" not in system
        assert "실질적으로 도움이 될 때만" in system
        assert "1~2문장 이내" in system

    def test_faq_requirement_unchanged(self):
        """FAQ 최소 문항 요구사항 등 다른 문구는 건드리지 않았는지 확인."""
        system, _ = get_article_prompt(CALC, intent="health_metric")
        assert "최소 5문항" in system


class TestOtherFiveIntentsUnaffectedByHealthMetricChange:
    """STEP160의 health_metric 전용 수정이 다른 5개 intent의 H2 구조에
    전혀 전파되지 않았는지 확인한다(각 intent는 독립된 elif 분기)."""

    def test_labor_money_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="labor_money")
        order = _h2_order(system)
        assert order == ["계산 원리", "지급 조건", "계산 방법", "계산 예시", "주의사항", "FAQ"]

    def test_welfare_benefit_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="welfare_benefit")
        order = _h2_order(system)
        assert order == ["지급 조건", "지급 대상", "계산 방법", "신청 방법", "주의사항", "FAQ"]

    def test_tax_insurance_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="tax_insurance")
        order = _h2_order(system)
        assert order == ["계산 원리", "납부/공제 기준", "계산 예시", "주의사항", "FAQ"]

    def test_housing_finance_unchanged(self):
        system, _ = get_article_prompt(CALC, intent="housing_finance")
        order = _h2_order(system)
        assert order == ["계산 원리", "적용 기준", "계산 예시", "주의사항", "FAQ"]

    def test_general_calculator_fallback_unchanged_by_health_metric_change(self):
        calc = dict(CALC, category="존재하지 않는 카테고리")
        system, _ = get_article_prompt(calc, intent=None)
        order = _h2_order(system)
        assert order == ["계산 원리", "계산 방법", "계산 예시", "주의사항", "FAQ"]

    def test_no_other_intent_gained_the_conditional_history_phrase(self):
        """조건부 역사 언급 문구가 health_metric 전용으로만 추가되고
        다른 intent에는 새어나가지 않았는지 확인한다."""
        for intent in ("labor_money", "welfare_benefit", "tax_insurance",
                       "housing_finance"):
            system, _ = get_article_prompt(CALC, intent=intent)
            assert "실질적으로 도움이 될 때만" not in system
        calc = dict(CALC, category="존재하지 않는 카테고리")
        system, _ = get_article_prompt(calc, intent=None)
        assert "실질적으로 도움이 될 때만" not in system


class TestNoRelatedCalculatorSectionEnforced:
    """STEP129/130에서 509의 '관련 계산기' 섹션은 재현 불필요로 확정됐다 —
    이번 수정이 그 섹션을 H2 구조에 강제로 추가하지 않았는지 확인한다.
    (시스템 프롬프트 자체에는 _NO_LINK_RULE로 인해 "관련 계산기 섹션을 작성하지
    않는다"는 금지 문구가 이미 포함돼 있으므로, 여기서는 H2 구조 목록만 검사한다.)"""

    def test_eligibility_h2_list_excludes_related_calculator(self):
        system, _ = get_article_prompt(CALC, intent="eligibility")
        assert "관련 계산기" not in _h2_order(system)

    def test_calculator_h2_list_excludes_related_calculator(self):
        system, _ = get_article_prompt(CALC, intent="calculator")
        assert "관련 계산기" not in _h2_order(system)
