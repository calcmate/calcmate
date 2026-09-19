# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_h2.py — STEP148

modules/content_integrity.py::check_g_h2_structure()의 _INTENT_REQUIRED_H2에
STEP147에서 발견된 6개 누락 intent(health_metric/labor_money/welfare_benefit/
tax_insurance/housing_finance/general_calculator)를 추가한 것을 회귀 검증한다.

H2 이름은 content/calculator/prompt.py::get_article_prompt()에 이미 정의된
구조를 그대로 사용했다(새 이름을 만들지 않음) — 각 테스트는 그 사실을
prompt.py 쪽에서도 교차 확인한다.

순수 함수만 호출한다 — 실제 AI/DB/WP 호출 없음.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_h2_structure, _INTENT_REQUIRED_H2
from content.calculator.prompt import get_article_prompt


def _h2_order_from_prompt(system_prompt: str) -> list:
    return re.findall(r"<h2>([^<]+)</h2>", system_prompt)


def _body_with_h2(headings: list) -> str:
    parts = []
    for h in headings:
        if h == "FAQ":
            parts.append(f"<h2>{h}</h2><dl><dt>q</dt><dd>a</dd></dl>")
        else:
            parts.append(f"<h2>{h}</h2><p>내용</p>")
    return "".join(parts)


CALC = {"name": "테스트 계산기", "category": "", "seo_desc": "", "formula": "",
        "input_schema": "", "output_schema": ""}

NEW_INTENTS = [
    "health_metric", "labor_money", "welfare_benefit",
    "tax_insurance", "housing_finance", "general_calculator",
]


class TestNewIntentsMatchPromptStructure:
    """_INTENT_REQUIRED_H2에 추가한 목록이 prompt.py 실제 구조의 부분집합인지 확인한다
    (임의로 새 H2 이름을 만들지 않았음을 코드로 재확인)."""

    def test_all_required_h2_exist_in_prompt_structure(self):
        for intent in NEW_INTENTS:
            system, _ = get_article_prompt(CALC, intent=intent)
            prompt_h2s = set(_h2_order_from_prompt(system))
            required = set(_INTENT_REQUIRED_H2[intent])
            missing = required - prompt_h2s
            assert not missing, f"{intent}: prompt에 없는 H2가 required에 있음: {missing}"


class TestNewIntentsPass:
    """필수 H2가 모두 존재하면 PASS(실패 없음)."""

    def test_health_metric_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["health_metric"])
        assert check_g_h2_structure(body, "health_metric") == []

    def test_labor_money_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["labor_money"])
        assert check_g_h2_structure(body, "labor_money") == []

    def test_welfare_benefit_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["welfare_benefit"])
        assert check_g_h2_structure(body, "welfare_benefit") == []

    def test_tax_insurance_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["tax_insurance"])
        assert check_g_h2_structure(body, "tax_insurance") == []

    def test_housing_finance_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["housing_finance"])
        assert check_g_h2_structure(body, "housing_finance") == []

    def test_general_calculator_full_structure_passes(self):
        body = _body_with_h2(_INTENT_REQUIRED_H2["general_calculator"])
        assert check_g_h2_structure(body, "general_calculator") == []


class TestNewIntentsFailOnMissingH2:
    """필수 H2 하나를 제거하면 major fail이 발생해야 한다(각 intent당 1개씩 대표 검증)."""

    def test_health_metric_missing_판정_기준_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["health_metric"] if h != "판정 기준"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "health_metric")
        assert any(f["gate"] == "G-H2" and "판정 기준" in f["detail"] for f in fails)
        assert all(f["grade"] == "major" for f in fails)

    def test_labor_money_missing_지급_조건_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["labor_money"] if h != "지급 조건"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "labor_money")
        assert any("지급 조건" in f["detail"] for f in fails)

    def test_welfare_benefit_missing_신청_방법_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["welfare_benefit"] if h != "신청 방법"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "welfare_benefit")
        assert any("신청 방법" in f["detail"] for f in fails)

    def test_tax_insurance_missing_납부_공제_기준_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["tax_insurance"] if h != "납부/공제 기준"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "tax_insurance")
        assert any("납부/공제 기준" in f["detail"] for f in fails)

    def test_housing_finance_missing_적용_기준_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["housing_finance"] if h != "적용 기준"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "housing_finance")
        assert any("적용 기준" in f["detail"] for f in fails)

    def test_general_calculator_missing_faq_fails(self):
        headings = [h for h in _INTENT_REQUIRED_H2["general_calculator"] if h != "FAQ"]
        body = _body_with_h2(headings)
        fails = check_g_h2_structure(body, "general_calculator")
        assert any("FAQ" in f["detail"] for f in fails)


class TestExistingFourIntentsUnaffected:
    """기존 4개 intent(eligibility/howto/documents/calculator)의 필수 H2 목록은
    이번 STEP에서 절대 변경하지 않았다 — 회귀 확인."""

    def test_eligibility_unchanged(self):
        assert _INTENT_REQUIRED_H2["eligibility"] == ["지급 대상", "제외 대상", "계산 방법", "FAQ"]

    def test_howto_unchanged(self):
        assert _INTENT_REQUIRED_H2["howto"] == ["이용 절차", "계산 예시", "FAQ"]

    def test_documents_unchanged(self):
        assert _INTENT_REQUIRED_H2["documents"] == ["필수 서류 목록", "서류 발급 방법", "FAQ"]

    def test_calculator_unchanged(self):
        assert _INTENT_REQUIRED_H2["calculator"] == ["계산 원리", "지급 조건", "FAQ"]


class TestUnknownIntentStillNoop:
    """등록되지 않은 intent(None 등)는 기존과 동일하게 필수 H2 검사를 건너뛴다."""

    def test_none_intent_no_required_h2_check(self):
        assert check_g_h2_structure("<p>본문만 있음</p>", None) == []

    def test_unregistered_intent_no_required_h2_check(self):
        assert check_g_h2_structure("<p>본문만 있음</p>", "존재하지_않는_intent") == []
