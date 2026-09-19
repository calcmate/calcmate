# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_numcon.py — STEP136

modules/content_integrity.py::check_g_numcon()의 2항 산술식 검사
("A만원 × B = C만원" 패턴)에서 확인된 버그를 회귀 검증한다.

버그: "%"가 없는 단순 배수(예: "150만 원 × 3 = 450만 원", 인적공제 3명분 등)를
_check_mul()의 "1<b<100이면 %로 추정" 휴리스틱이 3%(0.03)로 잘못 해석해
허위 산술 오류(major)를 발생시켰다(WP 510/연말정산_환급액_계산기 실측 발견,
STEP134/135). STEP136에서 정규식이 '%' 존재 여부를 명시적으로 캡처하도록
수정하고, is_percent가 True일 때만 100으로 나누도록 고쳤다.

이 파일은 순수 함수(check_g_numcon)만 호출한다 — DB/WP/Sheets/Telegram
어디에도 접근하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_numcon


def _passes(text: str) -> bool:
    return check_g_numcon(f"<p>{text}</p>") == []


class TestPlainMultiplierNoLongerMisreadAsPercent:
    """A. '%'가 없는 단순 배수는 정상 계산으로 통과해야 한다(버그 수정 확인)."""

    def test_150man_times_3_equals_450man(self):
        assert _passes("150만 원 × 3 = 450만 원")

    def test_plain_multiplier_x_notation(self):
        assert _passes("100만원 x 5 = 500만원")

    def test_plain_multiplier_with_commas(self):
        assert _passes("1,000만원 × 12 = 12,000만원")


class TestExplicitPercentStillWorks:
    """B. '%'가 명시된 경우 기존과 동일하게 백분율로 정확히 처리되어야 한다."""

    def test_150man_times_3_percent_equals_4p5man(self):
        assert _passes("150만 원 × 3% = 4.5만 원")

    def test_100man_times_10_percent_equals_10man(self):
        assert _passes("100만원 × 10% = 10만원")


class TestActualErrorsStillDetected:
    """기존 정책(잘못된 산술식은 여전히 major FAIL)이 약화되지 않았는지 확인한다."""

    def test_wrong_plain_multiplier_still_fails(self):
        """100만원 × 3 = 400만원(실제 300만원이어야 함) — 여전히 FAIL."""
        fails = check_g_numcon("<p>100만원 × 3 = 400만원</p>")
        assert len(fails) == 1
        assert fails[0]["gate"] == "G-NUMCON"
        assert fails[0]["grade"] == "major"

    def test_wrong_percent_still_fails(self):
        """100만원 × 10% = 50만원(실제 10만원이어야 함) — 여전히 FAIL."""
        fails = check_g_numcon("<p>100만원 × 10% = 50만원</p>")
        assert len(fails) == 1
        assert fails[0]["gate"] == "G-NUMCON"
        assert fails[0]["grade"] == "major"


class TestExistingGoldenContentUnaffected:
    """STEP134에서 실제 WP 콘텐츠 검수 시 문제없었던 산술 표현들이
    이번 수정 이후에도 계속 정상 통과하는지 확인한다(회귀 방지)."""

    def test_506_four_insurances_example_amounts(self):
        text = (
            "국민연금 = 3,000,000 × 4.75% = 142,500원 "
            "건강보험 = 3,000,000 × 3.595% = 107,850원"
        )
        # "만원" 단위 패턴이 아니므로 _ARITH2_RE와 무관 — 매치 자체가 없어야 하며
        # (원 단위 표기라 패턴 밖) 예외/오탐 없이 통과해야 한다.
        assert check_g_numcon(f"<p>{text}</p>") == []

    def test_510_dependent_deduction_example(self):
        """실제 문제가 발견됐던 원문 그대로 재검증."""
        text = "인적공제(본인·배우자·자녀): 150만 원 × 3 = 450만 원"
        assert _passes(text)
