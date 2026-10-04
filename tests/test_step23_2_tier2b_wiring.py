# -*- coding: utf-8 -*-
"""tests/test_step23_2_tier2b_wiring.py — STEP 23-2 회귀 테스트

STEP 23-1에서 발견된 결함: review_center.suggest_tier()가 "Tier2-B"를 반환해도
Tier2-A/B가 동일한 정수 2로 축약되어 Mode B의 Tier2-B 체크박스로 전달되지 않았다.

STEP 23-2 수정: AI 추천 버튼 핸들러에서 confidence와 무관하게
"tier == 'Tier2-B'" 여부만 session_state(af_tier2b_suggested, af_contract_is_tier2b)에
보존하여 체크박스 기본값까지 배선한다. Mode A는 subtype 개념이 없으므로 무변경.

Streamlit 제거(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP) 이후 이 파일은
review_center.suggest_tier()의 Tier2-B 신호 보존과 generate_app() 시그니처만 검증한다.
UI 배선은 React(AppFactoryAiAssist.jsx, AppFactoryAi02.test.jsx)가 담당한다.
"""
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules import review_center as RC


# ── Tier2-B 신호 판정 ───────────────────────────────────────────────────────

def _tier2b_suggested_from(result: dict) -> bool:
    """suggest_tier() 결과에서 Tier2-B subtype 신호를 판정한다."""
    return result.get("tier") == "Tier2-B"


# ── Test 1~6: suggest_tier() 반환값 → subtype 신호가 confidence와 무관하게 보존 ──

class TestTier2BSuggestionSignal:
    """confidence(high/medium/low)와 무관하게 tier=='Tier2-B'일 때만 True."""

    def _mock_chat(self, tier: str, confidence: str):
        import json
        return (json.dumps({"tier": tier, "reason": "테스트", "confidence": confidence}), 0, 0)

    def test_1_tier2b_high_confidence(self):
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier2-B", "high")):
            result = RC.suggest_tier({}, "군인 전역일 계산기", "입대일로 전역일 계산")
        assert result["tier"] == "Tier2-B"
        assert _tier2b_suggested_from(result) is True

    def test_2_tier2a_high_confidence_is_false(self):
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier2-A", "high")):
            result = RC.suggest_tier({}, "BMI 계산기", "키/몸무게로 BMI 계산")
        assert _tier2b_suggested_from(result) is False

    def test_3_tier1_high_confidence_is_false(self):
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier1", "high")):
            result = RC.suggest_tier({}, "퇴직금 계산기", "평균임금 기반 퇴직금")
        assert _tier2b_suggested_from(result) is False

    def test_4_tier2b_medium_confidence_still_true(self):
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier2-B", "medium")):
            result = RC.suggest_tier({}, "날짜 계산기", "")
        assert _tier2b_suggested_from(result) is True

    def test_5_tier2b_low_confidence_still_true(self):
        """핵심: confidence가 낮아도 '추천 결과 자체'는 소실되면 안 된다(자동확정과는 별개)."""
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier2-B", "low")):
            result = RC.suggest_tier({}, "애매한 날짜 계산기", "")
        assert _tier2b_suggested_from(result) is True

    def test_6_tier2a_low_confidence_is_false(self):
        with patch("modules.app_factory._chat", return_value=self._mock_chat("Tier2-A", "low")):
            result = RC.suggest_tier({}, "애매한 산술 계산기", "")
        assert _tier2b_suggested_from(result) is False


# ── Test 7: AI 실패 fallback ──────────────────────────────────────────────

class TestAIFailureFallback:
    def test_7_ai_failure_fallback_subtype_false(self):
        with patch("modules.app_factory._chat", side_effect=RuntimeError("API down")):
            result = RC.suggest_tier({}, "아무 계산기", "")
        assert result["tier"] == "Tier2-A"
        assert result["confidence"] == "low"
        assert _tier2b_suggested_from(result) is False


# ── Test 12b: generate_app() 시그니처 무변경 ──────────────────────────────

class TestModeAUnaffected:

    def test_12b_generate_app_signature_unchanged(self):
        """generate_app() 시그니처가 이번 변경으로 바뀌지 않았는지 확인."""
        import modules.app_factory as af_mod
        sig = str(inspect.signature(af_mod.generate_app))
        assert "tier" in sig
        assert "subtype" not in sig.lower()
