# -*- coding: utf-8 -*-
"""tests/test_content_integrity_g_consistency.py — STEP138

modules/content_integrity.py::check_g_consistency()의 요율(%) 비교 로직에서
확인된 설계 한계(STEP137)를 최소 수정한 것을 회귀 검증한다.

버그: FAQ가 본문에 이미 나온 두 요율의 합을 스스로 설명하는 자기완결적 문장
(예: "근로자 0.9% + 사업주 0.9% = 1.8%")까지 "FAQ에만 있는 새 숫자"로 보고
major를 발생시켰다(WP 506/four-insurances 실측 발견, STEP134~137). STEP138에서
FAQ 텍스트 안에 그 합을 이루는 두 항목이 실제로 존재하는 경우에만 예외로 허용하도록
_is_self_derived_sum()을 추가했다 — 근거 없는 합산 주장이나 실제 불일치는 여전히
major로 검출된다.

이 파일은 순수 함수(check_g_consistency)만 호출한다 — DB/WP/Sheets/Telegram
어디에도 접근하지 않는다(506 재검증은 STEP134~137에서 이미 로컬에 저장한 캐시된
WP 응답 파일을 재사용한다).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_consistency

_WP_CACHE_DIR = r"C:/Users/연수/AppData/Local/Temp/wp_check2"


def _wrap(body_line: str, faq_line: str) -> str:
    return f"<p>{body_line}</p><h2>FAQ</h2><dl><dt>q</dt><dd>{faq_line}</dd></dl>"


class TestSelfDerivedSumAllowed:
    """CASE A/E: FAQ 안에 두 요율이 실제로 존재하고 그 합이 FAQ의 새 숫자와 일치하면 PASS."""

    def test_case_a_normal_self_sum(self):
        html = _wrap(
            "근로자 부담률은 0.9%입니다.",
            "근로자는 0.9%, 사업주도 0.9%를 부담하므로 합산 요율은 1.8%입니다.",
        )
        assert check_g_consistency(html) == []

    def test_case_e_duplicate_value_sum(self):
        """STEP137 CASE D의 핵심 재현 — 동일 값(0.9%)이 FAQ 안에서 두 번 등장해 합산되는 경우."""
        html = _wrap(
            "근로자 부담률은 0.9%입니다.",
            "근로자가 부담하는 요율은 0.9%입니다. 사업주도 별도로 0.9%를 부담하며, "
            "합산 요율은 1.8%입니다.",
        )
        assert check_g_consistency(html) == []


class TestExistingBehaviorPreserved:
    """CASE B: 완전히 동일한 값이면 기존과 동일하게 PASS."""

    def test_case_b_identical_value(self):
        html = _wrap("보험료율은 0.9%입니다.", "보험료율은 0.9%입니다.")
        assert check_g_consistency(html) == []


class TestRealMismatchStillDetected:
    """CASE C: 합산 근거가 없는 실제 불일치는 여전히 major."""

    def test_case_c_actual_mismatch(self):
        html = _wrap("보험료율은 3.595%입니다.", "보험료율은 9.999%입니다.")
        fails = check_g_consistency(html)
        assert len(fails) == 1
        assert fails[0]["gate"] == "G-CONSISTENCY"
        assert fails[0]["grade"] == "major"


class TestFalseSumClaimStillRejected:
    """CASE D: FAQ 안에 실제로 등장하지 않는(본문에만 있는) 두 요율의 합이라고
    주장해도, FAQ 자체에 그 두 요율이 없으면 여전히 major(근거 없는 합산 주장 차단)."""

    def test_case_d_wrong_sum_claim(self):
        html = _wrap(
            "보험료율은 0.9%와 0.5%입니다.",  # 0.9 + 0.5 = 1.4 (본문에도 없음)
            "합산 요율은 1.8%입니다.",
        )
        fails = check_g_consistency(html)
        assert len(fails) == 1
        assert fails[0]["grade"] == "major"


class TestNoGroundedFaqNumberStillRejected:
    """CASE F: 합산 근거 전혀 없이 FAQ에만 새 숫자가 등장하면 여전히 major."""

    def test_case_f_ungrounded_new_number(self):
        html = _wrap("보험료율은 0.9%입니다.", "보험료율은 1.8%입니다.")
        fails = check_g_consistency(html)
        assert len(fails) == 1
        assert fails[0]["grade"] == "major"


class TestLegalCeilingAndPeriodUnaffected:
    """CASE G/H: 금액(상한/하한)·법정기간 비교 로직은 이번 STEP에서 전혀 건드리지
    않았으므로 기존 동작(불일치 시 major) 그대로 유지되어야 한다."""

    def test_case_g_legal_ceiling_mismatch_still_detected(self):
        html = _wrap(
            "국민연금 상한액 6,590,000원입니다.",
            "국민연금 상한액 9,999,999원입니다.",
        )
        fails = check_g_consistency(html)
        assert any(f["detail"].startswith("FAQ 법정금액") for f in fails)

    def test_case_h_legal_period_mismatch_still_detected(self):
        html = _wrap(
            "퇴직금은 14일 이내에 지급해야 합니다.",
            "신청은 30일 이내에 해야 합니다.",
        )
        fails = check_g_consistency(html)
        assert any(f["detail"].startswith("FAQ 법정기간") for f in fails)


class TestActualWp506NoLongerFalsePositive:
    """실제 WP 506(four-insurances) 콘텐츠 재검증 — 로컬에 캐시된 응답 재사용,
    네트워크 호출 없음."""

    def test_wp_506_no_longer_flags_1_8_percent(self):
        path = Path(_WP_CACHE_DIR) / "wp_506.json"
        if not path.exists():
            import pytest
            pytest.skip("로컬 WP 캐시 파일이 없음(이전 STEP에서 생성된 임시 캐시)")
        d = json.loads(path.read_text(encoding="utf-8"))
        cont = d.get("content", {}).get("rendered", "")
        fails = check_g_consistency(cont, slug="four-insurances")
        assert fails == []
