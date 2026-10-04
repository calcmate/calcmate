# -*- coding: utf-8 -*-
"""tests/test_step25_2_mode_suggestion.py — STEP 25-2 회귀 테스트

STEP 25-2 변경:
- modules/review_center.py: suggest_mode() 신규 함수 + LEGAL_SIGNAL_KEYWORDS /
  detect_legal_signal_keywords() 추가 (suggest_tier() 패턴 재사용).
- Mode AI 추천 UI는 추천 표시 전용 — 자동 생성/legal_refs/test_cases에는 일체
  관여하지 않는다. Streamlit 제거(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP) 이후 UI는
  React(AppFactoryAiAssist.jsx), API는 /api/calculators/ai/suggest-mode가 담당하며
  이 파일은 suggest_mode() 등 모듈 함수만 검증한다.

핵심 안전 원칙(STEP 25-1 진단 기반):
  Mode B → A 오판이 A → B 오판보다 구조적으로 더 위험하다(Mode A에는 legal_refs
  입력 경로와 check_hold_rules() 사전 게이트가 없음). 따라서 법령/규정성 신호가
  있을 때 AI가 A/HIGH를 반환해도 후처리로 MEDIUM으로 강등하고, 판단 실패/malformed
  응답 시 기본값은 안전한 쪽(B)으로 둔다.

실제 GPT/OpenAI 호출은 발생시키지 않는다 — modules.app_factory._chat을 mock한다.
"""
import ast
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import modules.review_center as rc_mod


def _func_source_without_docstring(func) -> str:
    """함수 소스에서 docstring을 제거한 코드 본문(설명용 문구로 인한 오탐 방지)."""
    src = inspect.getsource(func)
    tree = ast.parse(src)
    func_node = tree.body[0]
    if (func_node.body and isinstance(func_node.body[0], ast.Expr)
            and isinstance(func_node.body[0].value, ast.Constant)
            and isinstance(func_node.body[0].value.value, str)):
        func_node.body = func_node.body[1:]
    return ast.unparse(func_node)


def _mock_chat_json(payload_json: str):
    return (payload_json, "gpt-4o", 50)


# ── 1. 정상 Mode A (법령 신호 없음) ──────────────────────────────────────────

class TestModeAHighConfidence:
    def test_1_bmi_like_returns_a_high_unchanged(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "A", "reason": "단순 산술 계산", "confidence": "high"}')):
            result = rc_mod.suggest_mode({}, "BMI 계산기", "건강", "키/몸무게로 BMI 계산")
        assert result["mode"] == "A"
        assert result["confidence"] == "high"


# ── 2. 명확한 Mode B (법령 기반) ─────────────────────────────────────────────

class TestModeBHighConfidence:
    def test_2_severance_pay_like_returns_b_high(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "B", "reason": "근로기준법 기반 퇴직금 계산", "confidence": "high"}')):
            result = rc_mod.suggest_mode({}, "퇴직금 계산기", "노무/급여", "근속연수와 평균임금으로 퇴직금 계산")
        assert result["mode"] == "B"
        assert result["confidence"] == "high"


# ── 3. 날짜형(Tier2-B) 계산기 + Tier2-B 배선 독립성 ──────────────────────────

class TestDateBasedModeBAndTier2BIndependence:
    def test_3_military_discharge_like_returns_b(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "B", "reason": "병역법 기반 전역일 계산", "confidence": "high"}')):
            result = rc_mod.suggest_mode({}, "전역일 계산기", "병역/공무", "입영일 기준 전역일 계산")
        assert result["mode"] == "B"


# ── 4. 경계 사례 ─────────────────────────────────────────────────────────────

class TestBoundaryCaseMedium:
    def test_4_weekly_holiday_allowance_like_returns_b_medium(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "B", "reason": "근로기준법상 주휴수당 조건부 계산", "confidence": "medium"}')):
            result = rc_mod.suggest_mode({}, "주휴수당 계산기", "노무/급여", "주당 근무시간으로 주휴수당 계산")
        assert result["mode"] == "B"
        assert result["confidence"] == "medium"


# ── 5/6. B→A 오판 보정(후처리) ───────────────────────────────────────────────

class TestConservativeDowngrade:
    def test_5_legal_keyword_with_a_high_downgraded_to_medium(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "A", "reason": "간단해 보임", "confidence": "high"}')):
            result = rc_mod.suggest_mode({}, "근로기준법 요율 계산기", "노무/급여", "법정 요율 상한 적용")
        assert result["mode"] == "A"
        assert result["confidence"] == "medium", "법령 키워드가 있는데 A/HIGH가 그대로 유지되면 안 됨"

    def test_6_no_legal_keyword_a_high_stays_high(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json(
                       '{"mode": "A", "reason": "단순 비율 계산", "confidence": "high"}')):
            result = rc_mod.suggest_mode({}, "물비율 계산기", "생활", "하루 물 섭취량 비율 계산")
        assert result["mode"] == "A"
        assert result["confidence"] == "high"


# ── 7. malformed 응답 안전 처리 ──────────────────────────────────────────────

class TestMalformedResponseFallback:
    def test_7_malformed_json_falls_back_to_conservative_b(self):
        with patch("modules.app_factory._chat", return_value=_mock_chat_json("이것은 JSON이 아님")):
            result = rc_mod.suggest_mode({}, "계산기", "", "")
        assert result["mode"] == "B"
        assert result["confidence"] == "low"

    def test_7b_missing_mode_key_falls_back_to_b(self):
        with patch("modules.app_factory._chat",
                   return_value=_mock_chat_json('{"reason": "불명확", "confidence": "low"}')):
            result = rc_mod.suggest_mode({}, "계산기", "", "")
        assert result["mode"] == "B"


# ── 8. AI 호출 예외 시 안전 처리 ─────────────────────────────────────────────

class TestChatExceptionFallback:
    def test_8_chat_raises_returns_safe_default(self):
        with patch("modules.app_factory._chat", side_effect=RuntimeError("API 오류")):
            result = rc_mod.suggest_mode({}, "계산기", "", "")
        assert result["mode"] == "B"
        assert result["confidence"] == "low"
        assert "추천 실패" in result["reason"]


# ── 10. 자동 생성 직접 호출 금지 ─────────────────────────────────────────────

class TestNoAutoGenerationCall:

    def test_10b_suggest_mode_source_never_calls_generation_functions(self):
        # 함수 본문(docstring 제외)에는 generate_app/save_app 호출이 전혀 없어야 한다.
        # docstring에는 "호출하지 않는다"는 설명으로 이름이 정당하게 언급될 수 있다.
        src = _func_source_without_docstring(rc_mod.suggest_mode)
        assert "generate_app" not in src
        assert "save_app" not in src


# ── 11. legal_refs 자동 확정 금지 ────────────────────────────────────────────

class TestNoLegalRefsAutoConfirm:
    def test_11_suggest_mode_never_touches_legal_refs(self):
        src = _func_source_without_docstring(rc_mod.suggest_mode)
        assert "legal_refs" not in src
        assert "entity_id" not in src


# ── 12. test_cases 자동 생성 금지 ────────────────────────────────────────────

class TestNoTestCasesAutoGeneration:
    def test_12_suggest_mode_never_touches_test_cases(self):
        src = _func_source_without_docstring(rc_mod.suggest_mode)
        assert "test_cases" not in src


# ── 13. Tier2-B 독립성(함수 레벨) ────────────────────────────────────────────

class TestTier2BIndependenceAtFunctionLevel:
    def test_13_suggest_mode_source_has_no_tier2b_reference(self):
        src = inspect.getsource(rc_mod.suggest_mode)
        assert "tier2b" not in src.lower()
        assert "af_contract_is_tier2b" not in src


# ── 부가: 기존 함수/스키마 무변경 확인 ───────────────────────────────────────

class TestExistingContractsUnchanged:
    def test_suggest_tier_signature_unchanged(self):
        sig = str(inspect.signature(rc_mod.suggest_tier))
        assert sig == "(cfg: dict, name: str, desc: str = '') -> dict"

    def test_suggest_mode_signature(self):
        sig = str(inspect.signature(rc_mod.suggest_mode))
        assert sig == "(cfg: dict, name: str, category: str = '', desc: str = '') -> dict"

    def test_detect_legal_signal_keywords_pure_rule_based(self):
        assert rc_mod.detect_legal_signal_keywords("근로기준법 요율 계산기", "") is True
        assert rc_mod.detect_legal_signal_keywords("BMI 계산기", "키/몸무게로 계산") is False
