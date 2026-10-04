# -*- coding: utf-8 -*-
"""tests/test_step23_3_confidence_display.py — STEP 23-3 회귀 테스트

STEP 23-3: Tier AI 추천은 confidence=high일 때 "높은 확신도로 자동 선택됨"으로
표시하고, medium/low는 기존 안내 문구를 유지한다. AI값 기본 반영(tier, Tier2-B
subtype)은 confidence와 무관하게 항상 일어난다.

Streamlit 제거(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP) 이후 이 파일은
review_center.suggest_tier()의 반환값(tier/confidence)만 검증한다. 표시 분기는
React(frontend/src/components/AppFactoryAiAssist.jsx,
frontend/src/__tests__/AppFactoryAi02.test.jsx)가 담당한다.
실제 GPT/OpenAI 호출은 발생시키지 않는다 — modules.app_factory._chat을 mock한다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules import review_center as RC


def _mock_chat(tier: str, confidence: str):
    import json
    return (json.dumps({"tier": tier, "reason": "테스트", "confidence": confidence}), 0, 0)


# ── A. high ────────────────────────────────────────────────────────────────

class TestHighConfidenceDisplay:
    def test_1_tier1_high_auto_select_and_success_display(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier1", "high")):
            result = RC.suggest_tier({}, "퇴직금 계산기", "")
        assert result["tier"] == "Tier1"
        assert result["confidence"] == "high"

    def test_2_tier2a_high_auto_select_and_success_display(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier2-A", "high")):
            result = RC.suggest_tier({}, "BMI 계산기", "")
        assert result["tier"] == "Tier2-A"
        assert result["confidence"] == "high"

    def test_3_tier2b_high_subtype_preserved_and_success_display(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier2-B", "high")):
            result = RC.suggest_tier({}, "군인 전역일 계산기", "")
        assert result["tier"] == "Tier2-B"  # subtype 소실 없음(STEP23-2 유지)
        assert result["confidence"] == "high"


# ── B. medium ──────────────────────────────────────────────────────────────

class TestMediumConfidenceDisplay:
    def test_4_tier1_medium_no_success_badge(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier1", "medium")):
            result = RC.suggest_tier({}, "애매한 계산기", "")
        assert result["confidence"] == "medium"
        # AI값 기본 반영 자체는 confidence와 무관하게 여전히 일어남
        assert result["tier"] == "Tier1"

    def test_5_tier2a_medium_existing_flow_preserved(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier2-A", "medium")):
            result = RC.suggest_tier({}, "애매한 계산기2", "")
        assert result["confidence"] == "medium"
        assert result["tier"] == "Tier2-A"


# ── C. low ─────────────────────────────────────────────────────────────────

class TestLowConfidenceDisplay:
    def test_6_tier1_low_no_success_badge(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier1", "low")):
            result = RC.suggest_tier({}, "불확실 계산기", "")
        assert result["confidence"] == "low"
        assert result["tier"] == "Tier1"

    def test_7_tier2a_low_existing_flow_preserved(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier2-A", "low")):
            result = RC.suggest_tier({}, "불확실 계산기2", "")
        assert result["confidence"] == "low"
        assert result["tier"] == "Tier2-A"


# ── D. 실패 ────────────────────────────────────────────────────────────────

class TestFailureFallbackNoAutoConfirm:
    def test_8_ai_exception_confidence_low_no_success_badge(self):
        with patch("modules.app_factory._chat", side_effect=RuntimeError("API down")):
            result = RC.suggest_tier({}, "아무거나", "")
        assert result["confidence"] == "low"
        assert result["tier"] == "Tier2-A"
        assert result["tier"] != "Tier2-B"

    def test_9_invalid_tier_fallback_no_success_badge(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat("Tier99-Invalid", "high")):
            result = RC.suggest_tier({}, "이상한 계산기", "")
        # review_center.py의 기존 fallback: 허용 범위 밖 tier는 Tier2-A로 강제
        assert result["tier"] == "Tier2-A"
        # confidence는 AI가 반환한 값 그대로 유지된다
        assert result["confidence"] == "high"
