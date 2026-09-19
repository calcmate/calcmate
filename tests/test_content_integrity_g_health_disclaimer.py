# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_health_disclaimer.py — STEP156 (P1-D)

modules/content_integrity.py::check_g_health_disclaimer()의 최소 구현을 검증한다.
STEP155에서 확정한 설계: "위험 표현(진단/확정) 탐지"는 부정문까지 오탐하는 근본적
한계가 있어 채택하지 않고, 대신 "안전 고지(참고용/보조지표, 비진단, 전문가 상담
권고)가 존재하는가"만 결정론적으로 검사한다. intent == "health_metric"에만
적용되며, 초기 정책은 항상 minor(WARN)만 반환한다 — critical/major 없음.

순수 함수만 호출한다 — 실제 AI/DB/WP 호출 없음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_health_disclaimer, run_integrity_gates


# ═══════════════════════════════════════════════════════════════════════════
# PASS — 안전 고지 존재
# ═══════════════════════════════════════════════════════════════════════════

class TestPassCases:
    def test_1_explicit_reference_only_phrase(self):
        html = "<p>이 계산기의 BMI 수치는 참고용 지표이며 정확한 진단을 대체하지 않습니다.</p>"
        assert check_g_health_disclaimer(html, "health_metric") == []

    def test_2_draft585_style_simple_indicator_with_other_metrics(self):
        """실제 Draft585 표현 재현: '단순한 지표...다른 건강 지표와 함께 고려'."""
        html = (
            "<p>BMI는 단순한 지표일 뿐, 체중을 평가할 때 허리둘레, 체지방률 등의 "
            "다른 건강 지표와 함께 고려하는 것이 좋습니다.</p>"
        )
        assert check_g_health_disclaimer(html, "health_metric") == []

    def test_3_not_a_diagnostic_tool_phrase(self):
        html = "<p>BMI는 질병을 판단하는 진단 도구가 아닙니다.</p>"
        assert check_g_health_disclaimer(html, "health_metric") == []

    def test_4_expert_consultation_recommended(self):
        html = "<p>정확한 건강 상태 평가를 위해서는 전문가와 상담하시기 바랍니다.</p>"
        assert check_g_health_disclaimer(html, "health_metric") == []


# ═══════════════════════════════════════════════════════════════════════════
# WARN — 안전 고지 전혀 없음
# ═══════════════════════════════════════════════════════════════════════════

class TestWarnCase:
    def test_5_generic_bmi_explanation_without_any_disclaimer(self):
        html = (
            "<h2>계산 원리</h2><p>BMI는 체중을 신장의 제곱으로 나눈 값입니다.</p>"
            "<h2>판정 기준</h2><p>25 이상이면 과체중으로 분류됩니다.</p>"
        )
        fails = check_g_health_disclaimer(html, "health_metric")
        assert len(fails) == 1
        assert fails[0]["gate"] == "G-HEALTH-DISCLAIMER"
        assert fails[0]["grade"] == "minor"

        # G-H2 등 다른 게이트의 영향을 배제하기 위해 health_metric 필수 H2를 모두
        # 갖춘 본문으로 run_integrity_gates() 전체를 실행 -> G-HEALTH-DISCLAIMER의
        # minor만 존재해야 하고, 그로 인해 blocked=False여야 함을 확인한다.
        full_h2_html = (
            "<h2>계산 원리</h2><p>BMI는 체중을 신장의 제곱으로 나눈 값입니다.</p>"
            "<h2>계산 방법</h2><p>내용</p>"
            "<h2>판정 기준</h2><p>25 이상이면 과체중으로 분류됩니다.</p>"
            "<h2>해석 방법</h2><p>내용</p>"
            "<h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(full_h2_html, slug=None, intent="health_metric")
        assert any(f["gate"] == "G-HEALTH-DISCLAIMER" for f in failed)
        blocked = any(f["grade"] in ("critical", "major") for f in failed)
        assert blocked is False, "minor만 있으므로 blocked=False여야 한다"


# ═══════════════════════════════════════════════════════════════════════════
# NO-OP — health_metric이 아닌 intent
# ═══════════════════════════════════════════════════════════════════════════

class TestNoOpForOtherIntents:
    _NO_DISCLAIMER_HTML = "<p>안전 고지가 전혀 없는 일반 설명 본문입니다.</p>"

    def test_6_labor_money_no_disclaimer_is_noop(self):
        assert check_g_health_disclaimer(self._NO_DISCLAIMER_HTML, "labor_money") == []

    def test_7_tax_insurance_no_disclaimer_is_noop(self):
        assert check_g_health_disclaimer(self._NO_DISCLAIMER_HTML, "tax_insurance") == []

    def test_8_general_calculator_no_disclaimer_is_noop(self):
        assert check_g_health_disclaimer(self._NO_DISCLAIMER_HTML, "general_calculator") == []

    def test_none_intent_is_noop(self):
        assert check_g_health_disclaimer(self._NO_DISCLAIMER_HTML, None) == []

    def test_other_intents_do_not_surface_gate_in_run_integrity_gates(self):
        passed, failed = run_integrity_gates(
            self._NO_DISCLAIMER_HTML, slug=None, intent="labor_money")
        assert not any(f["gate"] == "G-HEALTH-DISCLAIMER" for f in failed)
        assert "G-HEALTH-DISCLAIMER" in passed


# ═══════════════════════════════════════════════════════════════════════════
# 오탐 방지 — 정상적인 질병/진단/위험/비만 서술만으로 BLOCK되지 않음
# ═══════════════════════════════════════════════════════════════════════════

class TestNoFalseBlockOnNormalMedicalVocabulary:
    def test_9_normal_disease_risk_obesity_vocabulary_without_disclaimer_is_warn_not_block(self):
        """'질병/진단/위험/비만' 같은 정상적인 설명 어휘가 있어도, 고지가 없으면
        WARN(minor)일 뿐 절대 critical/major로 BLOCK되지 않는다."""
        html = (
            "<p>BMI가 30 이상인 경우 심혈관 질환, 당뇨병 등 건강 문제가 발생할 "
            "가능성이 높아지며, 이는 의사가 진단하는 여러 위험 요인 중 하나로 "
            "비만 여부를 판별하는 데 사용됩니다.</p>"
        )
        fails = check_g_health_disclaimer(html, "health_metric")
        assert all(f["grade"] == "minor" for f in fails)
        assert all(f["grade"] not in ("critical", "major") for f in fails)

    def test_negation_sentence_not_falsely_treated_as_violation(self):
        """부정문(고지 문장)이 오히려 위반으로 오탐되지 않는지 확인 —
        '진단하는 도구가 아닙니다'는 PASS 사유이지 위반 사유가 아니다."""
        html = "<p>이 계산기는 질병을 진단하는 도구가 아닙니다.</p>"
        assert check_g_health_disclaimer(html, "health_metric") == []


# ═══════════════════════════════════════════════════════════════════════════
# 기존 9개 Gate 회귀 확인
# ═══════════════════════════════════════════════════════════════════════════

class TestExistingNineGatesUnaffected:
    def test_10_existing_gates_unchanged_by_new_gate_addition(self):
        clean_html = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>판정 기준</h2><p>내용</p><h2>해석 방법</h2><p>내용</p>"
            "<h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(clean_html, slug=None, intent="health_metric")
        # 고지가 없으므로 G-HEALTH-DISCLAIMER만 minor, 나머지 9개는 그대로 PASS
        non_health_failed = [f for f in failed if f["gate"] != "G-HEALTH-DISCLAIMER"]
        assert non_health_failed == []
        for gate in ("G-CALC", "G-NUMCON", "G-LEGAL", "G-STYLE+", "G-LEGAL-CURRENT",
                     "G-CONSISTENCY", "G-H2", "G-AI-LINK", "G-HTML-CLEAN", "G-FAQ-DUP"):
            assert gate in passed, f"{gate}가 기존과 다르게 동작함"

    def test_all_ten_gates_pass_with_disclaimer_present(self):
        clean_html_with_disclaimer = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>판정 기준</h2><p>내용</p><h2>해석 방법</h2><p>내용</p>"
            "<h2>주의사항</h2><p>BMI는 참고용 지표입니다.</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(
            clean_html_with_disclaimer, slug=None, intent="health_metric")
        assert failed == []
        assert "G-HEALTH-DISCLAIMER" in passed
