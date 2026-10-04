# -*- coding: utf-8 -*-
"""tests/test_content_qa.py — P0-4: modules/content_qa.py 단위 테스트.

계산기 콘텐츠 생성(SEO/FAQ/본문/이미지) 저장 전 게이트로 쓰이는 결정적(deterministic,
AI 미사용) QA 함수들을 검증한다. 핵심은 cross-calculator contamination(다른 계산기
내용이 섞여 저장되는 것) 탐지 — content/calculator/writer.py의 제거된 하드코딩 mock
버그(계산기 종류와 무관하게 "주휴수당 계산기" 본문을 반환)가 재발해도 이 게이트가
잡아내는지 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_qa import (
    check_empty_content, check_mock_or_dev_markers,
    check_identity_and_contamination, run_generation_qa,
)

CALC = {"slug": "annual-leave-remaining", "name": "연차 잔여일 계산기"}
OTHER_NAMES = ["주휴수당 계산기", "퇴직금 계산기", "4대보험 계산기"]


class TestCheckEmptyContent:
    def test_passes_on_complete_content(self):
        fails = check_empty_content(
            {"seo_title": "t", "seo_description": "d"}, [{"question": "q", "answer": "a"}],
            "<p>본문 내용입니다</p>",
        )
        assert fails == []

    def test_fails_on_empty_seo_title(self):
        fails = check_empty_content({"seo_title": "", "seo_description": "d"}, None, None)
        assert any(f["gate"] == "EMPTY" for f in fails)

    def test_fails_on_empty_faq_list(self):
        fails = check_empty_content(None, [], None)
        assert any("FAQ" in f["detail"] for f in fails)

    def test_fails_on_empty_article(self):
        fails = check_empty_content(None, None, "   ")
        assert any("본문" in f["detail"] for f in fails)

    def test_short_article_flagged_only_when_required(self):
        short = "<p>짧음</p>"
        assert check_empty_content(None, None, short, require_article=False) == []
        fails = check_empty_content(None, None, short, require_article=True)
        assert any("짧" in f["detail"] for f in fails)

    def test_fails_on_empty_image_prompts(self):
        fails = check_empty_content(None, None, None, img={"thumbnail": "", "body": "x"})
        assert any("이미지" in f["detail"] for f in fails)


class TestCheckMockOrDevMarkers:
    def test_passes_on_clean_content(self):
        fails = check_mock_or_dev_markers(
            {"seo_title": "연차 잔여일 계산기 안내", "seo_description": "d"}, None,
            "<h1>연차 잔여일 계산기</h1><p>본문</p>",
        )
        assert fails == []

    def test_detects_removed_mock_signature(self):
        fails = check_mock_or_dev_markers(None, None, "<h1>주휴수당 계산기</h1><p>...</p>")
        assert any(f["gate"] == "MOCK_SIGNATURE" for f in fails)

    def test_detects_dev_placeholder_todo(self):
        fails = check_mock_or_dev_markers({"seo_title": "TODO: 제목 작성", "seo_description": "d"}, None, None)
        assert any(f["gate"] == "MOCK_SIGNATURE" for f in fails)


class TestCheckIdentityAndContamination:
    def test_passes_when_own_name_present_and_no_other_names(self):
        fails = check_identity_and_contamination(
            CALC, seo={"seo_title": "연차 잔여일 계산기", "seo_description": "d"},
            other_calc_names=OTHER_NAMES,
        )
        assert fails == []

    def test_fails_when_own_identity_entirely_absent(self):
        fails = check_identity_and_contamination(
            CALC, seo={"seo_title": "완전히 무관한 제목", "seo_description": "설명도 무관함"},
            other_calc_names=OTHER_NAMES,
        )
        assert any(f["gate"] == "IDENTITY" for f in fails)

    def test_detects_cross_calculator_contamination(self):
        """실제 버그 재현: 연차 계산기인데 본문이 '주휴수당 계산기'로 나온 경우."""
        fails = check_identity_and_contamination(
            CALC, article="<h1>주휴수당 계산기</h1><p>주휴수당에 대해 알아봅니다.</p>",
            other_calc_names=OTHER_NAMES,
        )
        assert any(f["gate"] == "CROSS_CONTAMINATION" for f in fails)

    def test_own_name_not_flagged_as_contamination(self):
        fails = check_identity_and_contamination(
            CALC, article="<h1>연차 잔여일 계산기</h1><p>연차에 대해 안내합니다.</p>",
            other_calc_names=OTHER_NAMES,
        )
        assert not any(f["gate"] == "CROSS_CONTAMINATION" for f in fails)

    def test_empty_content_skipped_not_double_flagged(self):
        # 빈 콘텐츠는 check_empty_content가 처리하므로 이 함수는 조용히 통과한다.
        assert check_identity_and_contamination(CALC, seo=None, faq=None, article="") == []

    def test_partial_token_match_does_not_false_positive(self):
        """실 E2E(annual-leave-remaining, 실제 GPT-4o 호출)에서 발견된 오탐 고정:
        계산기명 '연차 잔여일 계산기'의 전체 구문 '연차 잔여일'이 문자 그대로 등장하지
        않아도, 실제로는 '연차'를 자연스럽게 반복 언급하는 정상적인 온토픽 콘텐츠라면
        통과해야 한다(토큰 단위 일치 — 전체 구문 일치 아님)."""
        faq = [
            {"question": "연차는 누구에게 지급되며 언제 받을 수 있나요?",
             "answer": "연차는 근로자의 고용 형태에 상관없이 모든 근로자에게 지급됩니다."},
            {"question": "연차 일수를 계산하는 방법은 무엇인가요?",
             "answer": "연차 일수는 근속개월수를 기준으로 계산합니다."},
        ]
        fails = check_identity_and_contamination(CALC, faq=faq, other_calc_names=OTHER_NAMES)
        assert fails == []


class TestRunGenerationQa:
    def test_all_pass(self):
        ok, fails = run_generation_qa(
            CALC,
            seo={"seo_title": "연차 잔여일 계산기", "seo_description": "연차를 계산하세요"},
            faq=[{"question": "연차는 어떻게 계산하나요?", "answer": "근속기간에 따라 계산합니다"}],
            article="<h1>연차 잔여일 계산기</h1><p>연차 계산 방법을 설명합니다.</p>",
            other_calc_names=OTHER_NAMES,
        )
        assert ok is True
        assert fails == []

    def test_cross_contamination_blocks(self):
        ok, fails = run_generation_qa(
            CALC, article="<h1>주휴수당 계산기</h1><p>주휴수당 지급조건을 설명합니다.</p>",
            other_calc_names=OTHER_NAMES,
        )
        assert ok is False
        assert any(f["gate"] == "CROSS_CONTAMINATION" for f in fails)
