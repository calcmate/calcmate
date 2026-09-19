# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_style_plus.py — STEP150

modules/content_integrity.py::check_g_style_plus()의 G7 보완 AI 문체 패턴
검출을 검증한다.

실제 AI/DB/WP/Sheets/Telegram 어디에도 접근하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_style_plus


class TestGStylePlusPass:
    """정상 텍스트는 PASS([])해야 한다."""

    def test_plain_text_passes(self):
        body = "<p>주요 내용을 정리합니다.</p>"
        assert check_g_style_plus(body) == []

    def test_html_structure_passes(self):
        body = (
            "<h2>계산 원리</h2>"
            "<p>BMI는 체중과 신장을 이용해 계산합니다.</p>"
        )
        assert check_g_style_plus(body) == []

    def test_formula_text_passes(self):
        body = "<p>BMI = 70 / ((170 / 100) ** 2) = 24.22입니다.</p>"
        assert check_g_style_plus(body) == []

    def test_korean_english_mixed_passes(self):
        body = "<p>BMI(Body Mass Index)는 체질량지수를 의미합니다.</p>"
        assert check_g_style_plus(body) == []


class TestGStylePlusDetect:
    """현재 _AI_STYLE_EXTRA 실제 패턴들이 검출되는지 확인한다."""

    def test_salajabogessseumnida_detected(self):
        body = "<p>주요 내용을 살펴보겠습니다.</p>"
        fails = check_g_style_plus(body)
        assert fails != []
        assert fails[0]["gate"] == "G-STYLE+"
        assert fails[0]["grade"] == "minor"
        assert "살펴보겠습니다" in fails[0]["detail"]

    def test_arabogessseumnida_detected(self):
        body = "<p>자세히 알아보겠습니다.</p>"
        fails = check_g_style_plus(body)
        assert fails != []
        assert fails[0]["grade"] == "minor"
        assert "알아보겠습니다" in fails[0]["detail"]

    def test_saenggakhaebomyeon_detected(self):
        body = "<p>생각해보면 이렇습니다.</p>"
        fails = check_g_style_plus(body)
        assert fails != []
        assert fails[0]["grade"] == "minor"
        assert "생각해보면" in fails[0]["detail"]


class TestGStylePlusMultiple:
    """여러 패턴이 동시에 등장해도 모두 검출되는지 확인한다."""

    def test_two_patterns_detected(self):
        body = "<p>살펴보겠습니다. 알아보겠습니다.</p>"
        fails = check_g_style_plus(body)
        assert fails != []
        assert fails[0]["grade"] == "minor"
        assert "살펴보겠습니다" in fails[0]["detail"]
        assert "알아보겠습니다" in fails[0]["detail"]
        assert "2건" in fails[0]["detail"]

    def test_three_patterns_detected(self):
        body = "<p>살펴보겠습니다. 알아보겠습니다. 생각해보면 됩니다.</p>"
        fails = check_g_style_plus(body)
        assert fails != []
        assert fails[0]["grade"] == "minor"
        assert "3건" in fails[0]["detail"]


class TestGStylePlusBoundary:
    """경계값/빈 입력 처리."""

    def test_empty_string(self):
        assert check_g_style_plus("") == []

    def test_empty_html_tag(self):
        assert check_g_style_plus("<p></p>") == []

    def test_whitespace_only(self):
        assert check_g_style_plus("<p>   </p>") == []