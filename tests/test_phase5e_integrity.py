# -*- coding: utf-8 -*-
"""
Phase 5-E 정합성 게이트 단위 테스트
G-CALC / G-NUMCON / G-LEGAL / G-STYLE+

절대 건드리지 않는 것: 기존 37개 production 콘텐츠, production pipeline.
"""
import pytest
from modules.content_integrity import (
    check_g_calc,
    check_g_numcon,
    check_g_legal,
    check_g_style_plus,
    run_integrity_gates,
)


def _gate_names(failed: list) -> set:
    return {f["gate"] for f in failed}


def _grades(failed: list, gate: str) -> set:
    return {f["grade"] for f in failed if f["gate"] == gate}


# ═══════════════════════════════════════════════════════════════════════════
# G-CALC
# ═══════════════════════════════════════════════════════════════════════════

class TestGCalc:

    def _ex_ctx(self, **result_kw):
        """단일 예시를 가진 example_context 생성."""
        return {"examples": [{"inputs": {}, "result": result_kw}]}

    def _total_ctx(self, total: int):
        return {"examples": [{"inputs": {}, "result": {"total": total}}]}

    # ── 기본 탐지 ────────────────────────────────────────────────────────

    def test_total_present_passes(self):
        """result.total = 14400000 이고 본문에 '1,440만원'이 있으면 PASS."""
        body = "<p>실업급여 총액은 1,440만원입니다.</p>"
        fails = check_g_calc(body, self._total_ctx(14_400_000))
        assert "G-CALC" not in _gate_names(fails)

    def test_total_missing_fails(self):
        """result.total = 14400000 인데 본문에 없으면 FAIL."""
        body = "<p>실업급여 총액은 2,400만원입니다.</p>"
        fails = check_g_calc(body, self._total_ctx(14_400_000))
        assert "G-CALC" in _gate_names(fails)
        assert _grades(fails, "G-CALC") == {"major"}

    def test_non_total_component_present_passes(self):
        """total 없는 경우 컴포넌트 값이 본문에 있으면 PASS."""
        body = "<p>건강보험 105,600원 부과됩니다.</p>"
        ctx = {"examples": [{"inputs": {}, "result": {"health_insurance": 105_600}}]}
        fails = check_g_calc(body, ctx)
        assert "G-CALC" not in _gate_names(fails)

    def test_small_amount_exempt(self):
        """1만원 미만 금액(요율값 등)은 검사 대상 제외."""
        body = "<p>아무 금액도 없습니다.</p>"
        ctx = {"examples": [{"inputs": {}, "result": {"ratio": 9_000}}]}
        fails = check_g_calc(body, ctx)
        assert "G-CALC" not in _gate_names(fails)

    # ── intent 면제 ─────────────────────────────────────────────────────

    def test_documents_intent_exempt(self):
        """documents intent → 계산 결과 인용 없어도 면제."""
        body = "<p>서류를 준비하세요.</p>"
        fails = check_g_calc(body, self._total_ctx(6_000_000), intent="documents")
        assert "G-CALC" not in _gate_names(fails)

    def test_non_documents_not_exempt(self):
        """calculator intent → documents 면제 없음."""
        body = "<p>서류를 준비하세요.</p>"
        fails = check_g_calc(body, self._total_ctx(6_000_000), intent="calculator")
        assert "G-CALC" in _gate_names(fails)

    # ── 금액 표기 변형 ───────────────────────────────────────────────────

    def test_man_won_no_comma_matches(self):
        """'1440만원' (쉼표 없음) 도 인식."""
        body = "<p>총액은 1440만원입니다.</p>"
        fails = check_g_calc(body, self._total_ctx(14_400_000))
        assert "G-CALC" not in _gate_names(fails)

    def test_man_won_space_matches(self):
        """'1,440만 원' (공백 포함) 도 인식."""
        body = "<p>총액은 약 1,440만 원이 됩니다.</p>"
        fails = check_g_calc(body, self._total_ctx(14_400_000))
        assert "G-CALC" not in _gate_names(fails)

    def test_raw_won_matches(self):
        """'864,000,000원' (원화 직접) 도 인식."""
        body = "<p>864,000,000원을 지급합니다.</p>"
        ctx = {"examples": [{"inputs": {}, "result": {"total": 864_000_000}}]}
        fails = check_g_calc(body, ctx)
        assert "G-CALC" not in _gate_names(fails)

    def test_no_examples_passes(self):
        """examples 없으면 G-CALC 면제."""
        body = "<p>내용입니다.</p>"
        fails = check_g_calc(body, {})
        assert "G-CALC" not in _gate_names(fails)


# ═══════════════════════════════════════════════════════════════════════════
# G-NUMCON
# ═══════════════════════════════════════════════════════════════════════════

class TestGNumcon:

    def test_correct_2term_passes(self):
        """200만원 × 0.8 = 160만원 → 정확한 산술 → PASS."""
        body = "<p>급여는 200만원 × 0.8 = 160만원입니다.</p>"
        fails = check_g_numcon(body)
        assert "G-NUMCON" not in _gate_names(fails)

    def test_wrong_2term_fails(self):
        """200만원 × 0.8 = 200만원 → 오류 → FAIL."""
        body = "<p>급여는 200만원 × 0.8 = 200만원입니다.</p>"
        fails = check_g_numcon(body)
        assert "G-NUMCON" in _gate_names(fails)
        assert _grades(fails, "G-NUMCON") == {"major"}

    def test_correct_3term_passes(self):
        """6만원 × 0.6 × 240일 = 86만원이 아니라 6×0.6×240=864이므로 86만원은 틀림.
        올바른: 10만원 × 0.6 × 240일 = 1,440만원."""
        body = "<p>실업급여는 10만원 × 0.6 × 240일 = 1,440만원입니다.</p>"
        fails = check_g_numcon(body)
        assert "G-NUMCON" not in _gate_names(fails)

    def test_wrong_3term_fails(self):
        """10만원 × 0.6 × 240일 = 2,400만원 → 오류 탐지."""
        body = "<p>실업급여는 10만원 × 0.6 × 240일 = 2,400만원입니다.</p>"
        fails = check_g_numcon(body)
        assert "G-NUMCON" in _gate_names(fails)

    def test_no_arithmetic_passes(self):
        """산술식 없는 텍스트 → 통과."""
        body = "<p>퇴직금은 14일 이내에 지급해야 합니다.</p>"
        fails = check_g_numcon(body)
        assert "G-NUMCON" not in _gate_names(fails)


# ═══════════════════════════════════════════════════════════════════════════
# G-LEGAL
# ═══════════════════════════════════════════════════════════════════════════

class TestGLegal:

    def test_severance_wrong_article_fails(self):
        """퇴직금 기사에서 '근로기준법 제36조' 인용 → 오인용 탐지."""
        body = "<p>퇴직금은 퇴직 후 14일 이내에 지급되어야 합니다. 이는 근로기준법 제36조에 명시되어 있습니다.</p>"
        fails = check_g_legal(body, "severance-pay")
        assert "G-LEGAL" in _gate_names(fails)
        assert _grades(fails, "G-LEGAL") == {"major"}

    def test_severance_correct_article_passes(self):
        """퇴직금 기사에서 '근로자퇴직급여보장법 제9조' 인용 → PASS."""
        body = "<p>퇴직금은 근로자퇴직급여보장법 제9조에 따라 퇴직 후 14일 이내에 지급되어야 합니다.</p>"
        fails = check_g_legal(body, "severance-pay")
        assert "G-LEGAL" not in _gate_names(fails)

    def test_four_insurances_vat_mention_fails(self):
        """4대보험 기사에 '부가가치세' 언급 → 오인용 탐지."""
        body = "<p>부가가치세전자신고납부를 이용해 가입 및 신고가 가능합니다.</p>"
        fails = check_g_legal(body, "four-insurances")
        assert "G-LEGAL" in _gate_names(fails)

    def test_four_insurances_no_vat_passes(self):
        """4대보험 기사에 '부가가치세' 없음 → PASS."""
        body = "<p>4대사회보험 정보연계센터에서 온라인으로 신고합니다.</p>"
        fails = check_g_legal(body, "four-insurances")
        assert "G-LEGAL" not in _gate_names(fails)

    def test_unknown_slug_no_fail(self):
        """등록되지 않은 slug → 규칙 없음 → PASS."""
        body = "<p>임의의 내용입니다.</p>"
        fails = check_g_legal(body, "unknown-calc")
        assert "G-LEGAL" not in _gate_names(fails)


# ═══════════════════════════════════════════════════════════════════════════
# G-STYLE+
# ═══════════════════════════════════════════════════════════════════════════

class TestGStylePlus:

    def test_ai_phrase_detected(self):
        """'살펴보겠습니다' 탐지 → MINOR 실패."""
        body = "<p>주요 내용을 살펴보겠습니다.</p>"
        fails = check_g_style_plus(body)
        assert "G-STYLE+" in _gate_names(fails)
        assert _grades(fails, "G-STYLE+") == {"minor"}

    def test_no_ai_phrase_passes(self):
        """금지 표현 없는 텍스트 → PASS."""
        body = "<p>주요 내용을 정리합니다.</p>"
        fails = check_g_style_plus(body)
        assert "G-STYLE+" not in _gate_names(fails)

    @pytest.mark.parametrize("phrase", [
        "살펴보겠습니다", "알아보겠습니다", "이해하셨을 것입니다",
        "살펴봅시다", "알아봅시다",
    ])
    def test_each_phrase_detected(self, phrase):
        body = f"<p>내용: {phrase}</p>"
        fails = check_g_style_plus(body)
        assert "G-STYLE+" in _gate_names(fails)


# ═══════════════════════════════════════════════════════════════════════════
# run_integrity_gates 통합
# ═══════════════════════════════════════════════════════════════════════════

class TestRunIntegrityGates:

    def test_all_pass_clean_body(self):
        """오류 없는 본문 → 원래 4개 게이트 모두 passed 목록에 포함."""
        # G-H2 gate를 위해 eligibility intent 필수 H2 포함
        body = (
            "<h2>지급 대상</h2><p>1년 이상 근로자. 무주택 세대주는 주거 목적 중간정산을 신청할 수 있습니다.</p>"
            "<h2>제외 대상</h2><p>1년 미만 제외.</p>"
            "<h2>계산 방법</h2><p>퇴직금은 근로자퇴직급여보장법 제9조에 따라 지급됩니다. 총액은 600만원입니다. "
            "주택 구입 또는 전세보증금 마련을 목적으로 하는 경우 중간정산 요건을 확인합니다.</p>"
            "<h2>FAQ</h2><dl><dt>질문</dt><dd>답변입니다.</dd></dl>"
        )
        ctx = {"examples": [{"inputs": {}, "result": {"total": 6_000_000}}]}
        passed, failed = run_integrity_gates(body, slug="severance-pay", example_context=ctx, intent="eligibility")
        assert "G-CALC" in passed
        assert "G-LEGAL" in passed
        major_fails = [f for f in failed if f["grade"] == "major"]
        assert not major_fails, f"예상치 못한 major 실패: {major_fails}"

    def test_multiple_gate_fail(self):
        """여러 게이트 동시 실패 시 각각 보고."""
        # G-LEGAL: 근로기준법 제36조 (severance-pay 오인용)
        # G-CALC: total 미등장
        # G-STYLE+: 살펴보겠습니다
        body = (
            "<p>퇴직금은 근로기준법 제36조에 따라 지급됩니다. "
            "총액은 200만원입니다. 자세히 살펴보겠습니다.</p>"
        )
        ctx = {"examples": [{"inputs": {}, "result": {"total": 6_000_000}}]}
        _, failed = run_integrity_gates(
            body, slug="severance-pay", example_context=ctx, intent="eligibility"
        )
        failed_gates = _gate_names(failed)
        assert "G-LEGAL" in failed_gates
        assert "G-CALC" in failed_gates
        assert "G-STYLE+" in failed_gates
