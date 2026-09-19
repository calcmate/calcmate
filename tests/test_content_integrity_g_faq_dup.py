# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_faq_dup.py — STEP153 (P1-C)

modules/content_integrity.py::check_g_faq_dup()의 최소 구현을 검증한다.
STEP152에서 확정한 설계: "전체 세트 완전동일"이 아니라 "질문+답변 쌍 단위
완전동일 개수/비율"을 기준으로 하며, 공백/줄바꿈/HTML entity 정도의 최소
정규화만 허용한다(의미 유사도/embedding/LLM 미사용). 초기 정책은 항상
minor(WARN)만 반환 — critical/major로 승격하지 않는다.

순수 함수만 호출한다 — 실제 AI/DB/WP 호출 없음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import (
    check_g_faq_dup,
    measure_faq_duplicate_qa,
    run_integrity_gates,
)
from content.calculator.prompt import get_faq_prompt


def _body(pairs: list[tuple[str, str]]) -> str:
    dl = "".join(f"<dt>{q}</dt><dd>{a}</dd>" for q, a in pairs)
    return f"<h2>FAQ</h2><dl>{dl}</dl>"


CALC_FAQ_QA = [
    {"question": "질문1", "answer": "답변1"},
    {"question": "질문2", "answer": "답변2"},
]
CALC_FAQ_qa = [
    {"q": "질문1", "a": "답변1"},
    {"q": "질문2", "a": "답변2"},
]


class TestExactDuplicateWarns:
    def test_complete_qa_match_produces_warn(self):
        body = _body([("질문1", "답변1"), ("질문2", "답변2")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert len(fails) == 1
        assert fails[0]["gate"] == "G-FAQ-DUP"
        assert fails[0]["grade"] == "minor"
        assert "2/2" in fails[0]["detail"]


class TestQuestionOnlyMatchIsNotDuplicate:
    def test_same_question_different_answer_not_counted(self):
        body = _body([("질문1", "완전히 다른 답변")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert fails == []


class TestAnswerOnlyMatchIsNotDuplicate:
    def test_same_answer_different_question_not_counted(self):
        body = _body([("완전히 다른 질문", "답변1")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert fails == []


class TestWhitespaceNormalization:
    def test_extra_whitespace_and_newlines_treated_as_identical(self):
        body = _body([("  질문1  \n", "답변1\n\n  ")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert len(fails) == 1
        assert "1/1" in fails[0]["detail"]


class TestHtmlEntityNormalization:
    def test_html_entity_difference_treated_as_identical(self):
        calc_faq = [{"question": "질문1", "answer": "A&B 답변"}]
        body = _body([("질문1", "A&amp;B 답변")])
        fails = check_g_faq_dup(body, calc_faq)
        assert len(fails) == 1
        assert "1/1" in fails[0]["detail"]


class TestOrderIndependent:
    def test_reordered_faq_still_detected(self):
        body = _body([("질문2", "답변2"), ("질문1", "답변1")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert len(fails) == 1
        assert "2/2" in fails[0]["detail"]


class TestPartialMatchRatio:
    def test_partial_match_counts_and_ratio_correct(self):
        calc_faq = [
            {"question": "질문1", "answer": "답변1"},
            {"question": "질문2", "answer": "답변2"},
            {"question": "질문3", "answer": "답변3"},
        ]
        body = _body([("질문1", "답변1"), ("질문2", "답변2"),
                       ("전혀 다른 질문", "전혀 다른 답변")])
        fails = check_g_faq_dup(body, calc_faq)
        assert len(fails) == 1
        assert "2/3" in fails[0]["detail"]
        assert "67%" in fails[0]["detail"]

    def test_high_ratio_without_full_set_match_still_detected(self):
        """STEP152에서 확인한 실제 bmi-calculator 5/6 사례를 재현한다 —
        FAQ 전체(6개)가 완전동일하지 않아도(1개는 서식만 다름) 높은 비율(5/6)이면
        검출되어야 한다."""
        calc_faq = [{"question": f"질문{i}", "answer": f"답변{i}"} for i in range(1, 7)]
        body_pairs = [(f"질문{i}", f"답변{i}") for i in range(1, 6)]
        body_pairs.append(("질문6", "답변6 (마크다운 `백틱` 제거된 버전)"))
        body = _body(body_pairs)
        fails = check_g_faq_dup(body, calc_faq)
        assert len(fails) == 1
        assert "5/6" in fails[0]["detail"]
        assert "83%" in fails[0]["detail"]


class TestQaKeySchemaSupported:
    def test_q_a_key_schema_also_detected(self):
        """다수 계산기(12/14)가 쓰는 {"q","a"} 스키마도 지원해야 한다(STEP152 확인)."""
        body = _body([("질문1", "답변1"), ("질문2", "답변2")])
        fails = check_g_faq_dup(body, CALC_FAQ_qa)
        assert len(fails) == 1
        assert "2/2" in fails[0]["detail"]


class TestNoOpCases:
    def test_calculator_faq_none_is_noop(self):
        body = _body([("질문1", "답변1")])
        assert check_g_faq_dup(body, None) == []

    def test_calculator_faq_empty_list_is_noop(self):
        body = _body([("질문1", "답변1")])
        assert check_g_faq_dup(body, []) == []

    def test_body_without_faq_is_noop(self):
        assert check_g_faq_dup("<p>FAQ 없는 본문</p>", CALC_FAQ_QA) == []

    def test_never_escalates_beyond_minor(self):
        """어떤 경우에도 critical/major로 승격되지 않는다(이번 STEP 범위 고정)."""
        body = _body(CALC_FAQ_QA and [("질문1", "답변1"), ("질문2", "답변2")])
        fails = check_g_faq_dup(body, CALC_FAQ_QA)
        assert all(f["grade"] == "minor" for f in fails)


class TestFaqDuplicateQaMetric:
    def test_body_faq_exact_copy_is_qa_warning_only(self):
        body = (
            "<p>실업급여는 일정 요건을 충족해야 신청할 수 있습니다.</p>"
            "<h2>FAQ</h2><dl><dt>어떤 요건이 필요한가요?</dt>"
            "<dd>실업급여는 일정 요건을 충족해야 신청할 수 있습니다.</dd></dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["body_faq_exact_sentence_matches"] == 1
        assert result["body_faq_exact_paragraph_matches"] == 1
        assert result["severity"] == "minor"
        assert result["blocking"] is False

    def test_whitespace_and_entity_normalization_is_exact_copy(self):
        body = (
            "<p>신청&nbsp;절차를 확인하세요.</p>"
            "<h2>FAQ</h2><dl><dt>신청 절차</dt>"
            "<dd>신청  절차를\n확인하세요.</dd></dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["body_faq_exact_sentence_matches"] == 1
        assert result["body_faq_exact_paragraph_matches"] == 1

    def test_normal_summary_is_not_exact_duplicate(self):
        body = (
            "<p>실업급여는 일정 요건과 고용보험 가입 이력을 함께 확인합니다.</p>"
            "<h2>FAQ</h2><dl><dt>무엇을 확인하나요?</dt>"
            "<dd>신청 전에 가입 기간을 확인하면 됩니다.</dd></dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["body_faq_exact_sentence_matches"] == 0
        assert result["body_faq_exact_paragraph_matches"] == 0

    def test_faq_internal_exact_pair_is_measured(self):
        body = (
            "<h2>FAQ</h2><dl>"
            "<dt>질문</dt><dd>답변</dd>"
            "<dt>질문</dt><dd>답변</dd>"
            "</dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["faq_internal_exact_pair_matches"] == 1
        assert result["cross_post_exact_pair_matches"] == 0
        assert result["blocking"] is False

    def test_same_question_different_answer_is_not_internal_duplicate(self):
        body = (
            "<h2>FAQ</h2><dl>"
            "<dt>질문</dt><dd>답변1</dd>"
            "<dt>질문</dt><dd>답변2</dd>"
            "</dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["faq_internal_exact_pair_matches"] == 0

    def test_numeric_difference_is_not_faq_duplicate_metric(self):
        body = (
            "<p>보험료율은 3.595%입니다.</p>"
            "<h2>FAQ</h2><dl><dt>보험료율은?</dt>"
            "<dd>보험료율은 3.52%입니다.</dd></dl>"
        )
        result = measure_faq_duplicate_qa(body)
        assert result["body_faq_exact_sentence_matches"] == 0
        assert result["blocking"] is False


class TestFaqPromptRoleSeparation:
    def test_prompt_preserves_legal_facts_and_separates_faq_role(self):
        system, _ = get_faq_prompt({"category": "고용/실업", "name": "실업급여"})
        assert "추가로 궁금해할 질문" in system
        assert "문장이나 문단을 그대로 복사" in system
        assert "법률상 핵심 사실" in system
        assert "수치·기간을 임의로 변경" in system


class TestRunIntegrityGatesWiringBackwardCompatible:
    def test_default_calculator_faq_none_is_noop_and_gate_passes(self):
        """calculator_faq를 넘기지 않는 기존 호출부는 완전히 하위호환 동작한다."""
        clean_html = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>계산 예시</h2><p>내용</p><h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(clean_html, slug=None, intent="general_calculator")
        assert "G-FAQ-DUP" in passed
        assert failed == []

    def test_calculator_faq_passed_through_and_surfaces_warn(self):
        html = _body([("질문1", "답변1")])
        passed, failed = run_integrity_gates(
            html, slug=None, intent=None, calculator_faq=CALC_FAQ_QA)
        assert any(f["gate"] == "G-FAQ-DUP" and f["grade"] == "minor" for f in failed)
        assert "G-FAQ-DUP" not in passed
        # minor는 blocked 판정에 영향 없음 — 다른 8개 게이트는 그대로 통과
        for g in ("G-CALC", "G-NUMCON", "G-LEGAL", "G-STYLE+", "G-LEGAL-CURRENT",
                  "G-AI-LINK", "G-HTML-CLEAN"):
            assert g in passed


class TestExistingEightGatesUnaffected:
    """기존 8개 게이트(G-H2 포함) 결과가 이번 변경으로 달라지지 않았는지 회귀 확인."""

    def test_existing_gates_same_result_with_and_without_calculator_faq(self):
        html = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>계산 예시</h2><p>내용</p><h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        p1, f1 = run_integrity_gates(html, slug=None, intent="general_calculator")
        p2, f2 = run_integrity_gates(html, slug=None, intent="general_calculator",
                                      calculator_faq=None)
        assert p1 == p2
        assert f1 == f2
