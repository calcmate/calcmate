# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_legal_current.py — STEP: G-LEGAL-CURRENT 회귀

severance-pay / eligibility에서 주거 목적 중간정산 법률 기준이
positive validation으로 검증되고, 구 기간 요건(hallucination)이
forbidden으로 차단되는 것을 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_legal_current


def _wrap(body: str) -> str:
    return f"<p>{body}</p><h2>FAQ</h2><dl><dt>q</dt><dd>답변</dd></dl>"


class TestSeverancePayEligibilityPositiveValidation:
    """severance-pay + eligibility: 주거 목적 중간정산 필수 기준 포함 검증."""

    def test_required_housing_interim_criterion_present_passes(self):
        """무주택자·주택구입·전세보증금 키워드가 모두 있으면 PASS."""
        body = (
            "주거 목적 퇴직금 중간정산은 <strong>무주택 세대주</strong>가 "
            "<strong>주택 구입</strong> 또는 <strong>전세보증금</strong> 마련 시 "
            "청구할 수 있습니다(근로자퇴직급여보장법 시행령 제3조). "
            "기간 요건은 별도로 없습니다."
        )
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        # positive validation: 필수 기준 중 하나라도 없으면 major fail
        positive_fails = [f for f in fails if f.get("grade") == "major" and "미등장" in f.get("detail", "")]
        assert positive_fails == [], f"필수 기준 통과해야 함: {positive_fails}"

    def test_missing_mujutaek_detected(self):
        """무주택자 언급 없으면 positive validation MAJOR fail."""
        body = (
            "주거 목적 중간정산은 주택 구입 또는 전세보증금 마련 시 "
            "청구할 수 있습니다(근로자퇴직급여보장법 시행령 제3조)."
        )
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        positive_fails = [f for f in fails if f.get("grade") == "major" and "미등장" in f.get("detail", "")]
        assert len(positive_fails) >= 1, "무주택자 미포함 시 major fail 있어야 함"
        assert any("무주택" in f.get("detail", "") for f in positive_fails)

    def test_missing_jeonse_detected(self):
        """전세보증금 언급 없으면 positive validation MAJOR fail."""
        body = (
            "주거 목적 중간정산은 무주택 세대주가 주택 구입 시 "
            "청구할 수 있습니다(근로자퇴직급여보장법 시행령 제3조)."
        )
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        positive_fails = [f for f in fails if f.get("grade") == "major" and "미등장" in f.get("detail", "")]
        assert len(positive_fails) >= 1
        assert any("전세" in f.get("detail", "") for f in positive_fails)

    def test_missing_housing_purchase_detected(self):
        """주택 구입 언급 없으면 positive validation MAJOR fail."""
        body = (
            "주거 목적 중간정산은 무주택 세대주가 전세보증금 마련 시 "
            "청구할 수 있습니다(근로자퇴직급여보장법 시행령 제3조)."
        )
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        positive_fails = [f for f in fails if f.get("grade") == "major" and "미등장" in f.get("detail", "")]
        assert len(positive_fails) >= 1
        assert any("주택" in f.get("detail", "") and "구입" in f.get("detail", "") for f in positive_fails)


class TestSeverancePayEligibilityForbiddenValidation:
    """severance-pay + eligibility: 구 기간 요건(hallucination) 금지 검증."""

    def test_36_months_detected_critical(self):
        """'36개월' 등장 시 CRITICAL fail."""
        body = "주거 목적 중간정산은 36개월 이상 근무해야 합니다."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert len(critical_fails) >= 1
        assert any("36개월" in f.get("detail", "") for f in critical_fails)

    def test_5_years_detected_critical(self):
        """'5년 이상' 등장 시 CRITICAL fail."""
        body = "주거 목적 중간정산은 5년 이상 계속근로해야 합니다."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert len(critical_fails) >= 1
        assert any("5년" in f.get("detail", "") for f in critical_fails)

    def test_10_years_detected_critical(self):
        """'10년 이상' 등장 시 CRITICAL fail."""
        body = "10년 이상 근무해야 중간정산 가능합니다."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert len(critical_fails) >= 1
        assert any("10년" in f.get("detail", "") for f in critical_fails)

    def test_period_requirement_phrase_detected_critical(self):
        """'기간 요건' 등장 시 CRITICAL fail."""
        body = "중간정산에는 별도 기간 요건이 있습니다."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert len(critical_fails) >= 1
        assert any("기간 요건" in f.get("detail", "") for f in critical_fails)


class TestOtherCalculatorsUnaffected:
    """다른 calculator/intent는 영향 받지 않아야 함."""

    def test_four_insurances_calculator_unchanged(self):
        """four-insurances calculator Gate 동작 유지."""
        body = "건강보험료율은 3.595%입니다."
        fails = check_g_legal_current(_wrap(body), "four-insurances", "calculator")
        # four-insurances는 3.595%가 현행값이므로 forbidden 3.52% 등은 없음
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert critical_fails == []

    def test_unemployment_benefit_eligibility_unchanged(self):
        """unemployment-benefit eligibility Gate 동작 유지."""
        body = "구직급여 상한액은 68,100원입니다."
        fails = check_g_legal_current(_wrap(body), "unemployment-benefit", "eligibility")
        # 66,000원이 forbidden이므로 68,100원은 통과
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert critical_fails == []

    def test_severance_pay_documents_intent_no_positive(self):
        """severance-pay documents intent는 positive validation 없음."""
        body = "퇴직금 관련 서류를 준비하세요."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "documents")
        # documents intent에는 requires_in_content_for_intents가 없으므로 positive 검사 건너뜀
        positive_fails = [f for f in fails if f.get("grade") == "major" and "미등장" in f.get("detail", "")]
        assert positive_fails == []


class TestExistingDisciplinaryDismissalForbiddenStillWorks:
    """기존 징계해고 금지 패턴 계속 작동."""

    def test_disciplinary_dismissal_forbidden_critical(self):
        """'징계해고인 경우 퇴직금을 받을 수 없' 패턴 CRITICAL fail."""
        body = "징계해고인 경우 퇴직금을 받을 수 없습니다."
        fails = check_g_legal_current(_wrap(body), "severance-pay", "eligibility")
        critical_fails = [f for f in fails if f.get("grade") == "critical"]
        assert len(critical_fails) >= 1
        assert any("징계해고" in f.get("detail", "") for f in critical_fails)


if __name__ == "__main__":
    sys.exit(sys.executable + " -m pytest " + __file__ + " -v")