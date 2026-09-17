# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_ai_link_html_clean.py — STEP150

STEP149에서 확정한 P0 후보 A(AI 외부 링크 검출)와 B(HTML/Markdown 오염 검출)를
modules/content_integrity.py::check_g_ai_link()/check_g_html_clean()로 구현한 것을
검증한다.

두 함수 모두 run_integrity_gates()가 build_blog_html() 호출 이전의 raw AI article에만
적용하므로, 코드가 후삽입하는 CTA/기관 공식 링크는 애초에 검사 대상에 없다 —
이 파일의 테스트는 그 raw 시점의 body_html 문자열만 다룬다(실제 AI/DB/WP 호출 없음).

modules/cleaner.py::strip_prompt_artifacts()/normalize_bold_markdown()가 generate_article()
내부에서 이미 같은 종류의 오염 일부를 조용히 제거하므로, G-HTML-CLEAN의 프롬프트
지시어 검사는 "1차 방어(cleaner)를 통과하고 남은 잔여물을 잡는 안전망"이라는 점을
일부 테스트에서 함께 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_ai_link, check_g_html_clean, run_integrity_gates
from modules import cleaner


# ═══════════════════════════════════════════════════════════════════════════
# Gate A — G-AI-LINK
# ═══════════════════════════════════════════════════════════════════════════

class TestGateAPass:
    def test_1_plain_text(self):
        assert check_g_ai_link("이것은 일반 텍스트입니다.") == []

    def test_2_html_body_without_a_tag(self):
        html = "<h2>계산 원리</h2><p>BMI는 체중을 신장의 제곱으로 나눕니다.</p>"
        assert check_g_ai_link(html) == []

    def test_3_numbers_and_formula(self):
        html = "<p>BMI = 70 / ((170 / 100) ** 2) = 24.22이며, 3.595%가 적용됩니다.</p>"
        assert check_g_ai_link(html) == []

    def test_4_korean_english_mixed(self):
        html = "<p>BMI(Body Mass Index)는 체질량지수를 의미하며 WHO 기준을 따릅니다.</p>"
        assert check_g_ai_link(html) == []

    def test_false_positive_check_word_url_without_actual_link(self):
        """'URL'이라는 단어 자체는 링크가 아니므로 통과해야 한다(오탐 방지 확인)."""
        html = "<p>이 계산기는 URL 없이도 이용할 수 있습니다.</p>"
        assert check_g_ai_link(html) == []


class TestGateAFail:
    def test_5_html_a_tag(self):
        html = '<p>자세히 보려면 <a href="https://example.com">여기</a>를 클릭하세요.</p>'
        fails = check_g_ai_link(html)
        assert any(f["gate"] == "G-AI-LINK" and f["grade"] == "major" for f in fails)

    def test_6_markdown_link(self):
        html = "<p>자세한 내용은 [공식 사이트](https://example.com)에서 확인하세요.</p>"
        fails = check_g_ai_link(html)
        assert any(f["gate"] == "G-AI-LINK" and f["grade"] == "major" for f in fails)

    def test_7_calculator_url_link(self):
        html = '<p><a href="https://calcmate.kr/severance-pay/">퇴직금 계산기</a>를 이용하세요.</p>'
        fails = check_g_ai_link(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_8_external_url_bare_text_is_warn_not_block(self):
        """태그/Markdown 없이 순수 텍스트로만 등장하는 URL은 major가 아니라
        minor(WARN)로만 표시한다 — 정상 문장과의 구분이 애매하기 때문."""
        html = "<p>자세한 내용은 https://example.com 에서 확인할 수 있습니다.</p>"
        fails = check_g_ai_link(html)
        assert fails, "bare URL도 최소한 minor로는 잡혀야 한다"
        assert all(f["grade"] == "minor" for f in fails)


# ═══════════════════════════════════════════════════════════════════════════
# Gate B — G-HTML-CLEAN
# ═══════════════════════════════════════════════════════════════════════════

class TestGateBPass:
    def test_9_normal_html(self):
        html = "<h2>계산 원리</h2><p>본문 내용입니다.</p><h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        assert check_g_html_clean(html) == []

    def test_10_normal_h2_h3(self):
        html = "<h2>계산 방법</h2><h3>세부 절차</h3><p>내용</p>"
        assert check_g_html_clean(html) == []

    def test_11_normal_parentheses_and_special_chars(self):
        html = "<p>BMI(체질량지수)는 (체중/신장²)으로 계산하며, 25~29.9는 과체중입니다.</p>"
        assert check_g_html_clean(html) == []

    def test_12_normal_formula_expression(self):
        html = "<p>BMI = 70 / ((170 / 100) ** 2) = 24.22, 오차범위는 ±1.5%입니다.</p>"
        assert check_g_html_clean(html) == []

    def test_false_positive_hashtag_word_no_space(self):
        """'#단어'처럼 공백 없이 붙는 해시태그형 표현은 Markdown heading이 아니므로
        통과해야 한다(오탐 방지 설계 확인)."""
        html = "<p>#4대보험 관련 안내입니다.</p>"
        assert check_g_html_clean(html) == []

    def test_false_positive_numbered_list_inside_p_tag(self):
        """<h2>/<h3> 밖의 일반 <p> 안에 있는 번호 목록(1. 2. 3.)은 프롬프트 지시어
        헤딩 패턴이 아니므로 통과해야 한다."""
        html = "<p>1. 신장을 측정합니다.</p><p>2. 체중을 측정합니다.</p>"
        assert check_g_html_clean(html) == []


class TestGateBFail:
    def test_13_placeholder_double_brace(self):
        html = "<p>안내: {{calculator_name}} 계산기를 이용하세요.</p>"
        fails = check_g_html_clean(html)
        assert any(f["gate"] == "G-HTML-CLEAN" and f["grade"] == "major" for f in fails)

    def test_14_placeholder_data_ph_attribute(self):
        html = '<p data-ph="calc_result">결과: </p>'
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_15_prompt_artifact_heading(self):
        html = "<h2>CTA</h2><p>계산기를 사용해보세요.</p>"
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_15b_numbered_heading_prefix(self):
        html = "<h2>3. 계산 원리</h2><p>내용</p>"
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_16_markdown_heading_residue(self):
        html = "## 계산 원리\n<p>본문</p>"
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_17_code_fence_residue(self):
        html = "<p>다음과 같이 계산합니다.</p>```BMI = weight / height ** 2```"
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)

    def test_doc_wrapper_tag_residue(self):
        html = "<html><body><h2>계산 원리</h2></body></html>"
        fails = check_g_html_clean(html)
        assert any(f["grade"] == "major" for f in fails)


class TestGateBSafetyNetOverCleaner:
    """G-HTML-CLEAN의 프롬프트 지시어 검사는 cleaner.strip_prompt_artifacts()가
    이미 제거하는 정확일치 패턴보다 넓게(레이블 뒤에 다른 텍스트가 붙어도) 잡아내는
    안전망임을 확인한다 — cleaner는 정확히 '<h2>CTA</h2>' 형태만 제거하므로,
    '<h2>CTA 안내</h2>'처럼 레이블 뒤에 텍스트가 붙으면 cleaner를 통과해 살아남는다."""

    def test_cleaner_removes_exact_match_only(self):
        html = "<h2>CTA</h2><p>내용</p>"
        cleaned = cleaner.strip_prompt_artifacts(html)
        assert "<h2>CTA</h2>" not in cleaned

    def test_cleaner_does_not_catch_label_with_trailing_text(self):
        html = "<h2>CTA 안내</h2><p>내용</p>"
        cleaned = cleaner.strip_prompt_artifacts(html)
        assert "<h2>CTA 안내</h2>" in cleaned, "이 케이스는 cleaner를 통과해 살아남아야 한다"

    def test_g_html_clean_catches_what_cleaner_missed(self):
        """cleaner를 통과해 살아남은 위 케이스를 G-HTML-CLEAN이 안전망으로 잡아낸다."""
        html = "<h2>CTA 안내</h2><p>내용</p>"
        cleaned = cleaner.strip_prompt_artifacts(html)
        fails = check_g_html_clean(cleaned)
        assert any(f["grade"] == "major" for f in fails)


# ═══════════════════════════════════════════════════════════════════════════
# run_integrity_gates() 배선 확인 — 기존 7개 게이트 시그니처/동작 불변
# ═══════════════════════════════════════════════════════════════════════════

class TestRunIntegrityGatesWiringUnchanged:
    def test_new_gates_included_in_dispatch(self):
        clean_html = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>계산 예시</h2><p>내용</p><h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(clean_html, slug=None, intent="general_calculator")
        assert "G-AI-LINK" in passed
        assert "G-HTML-CLEAN" in passed
        assert failed == []

    def test_ai_link_violation_surfaces_through_run_integrity_gates(self):
        html = '<h2>FAQ</h2><p><a href="https://x.com">링크</a></p>'
        passed, failed = run_integrity_gates(html, slug=None, intent=None)
        assert any(f["gate"] == "G-AI-LINK" for f in failed)
        assert "G-AI-LINK" not in passed

    def test_existing_seven_gates_still_run(self):
        """기존 7개 게이트 이름이 여전히 결과에 등장할 수 있는지(시그니처/호출 불변)
        확인 — 완전히 깨끗한 본문을 넣어 전부 passed에 들어가는지 확인한다."""
        clean_html = (
            "<h2>계산 원리</h2><p>내용</p><h2>계산 방법</h2><p>내용</p>"
            "<h2>계산 예시</h2><p>내용</p><h2>주의사항</h2><p>내용</p>"
            "<h2>FAQ</h2><dl><dt>q</dt><dd>a</dd></dl>"
        )
        passed, failed = run_integrity_gates(clean_html, slug=None, intent="general_calculator")
        for gate in ("G-CALC", "G-NUMCON", "G-LEGAL", "G-STYLE+",
                     "G-LEGAL-CURRENT", "G-CONSISTENCY", "G-H2"):
            assert gate in passed, f"{gate}가 기존과 다르게 동작함"
