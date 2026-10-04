# -*- coding: utf-8 -*-
"""tests/test_step24_2_field_suggestion.py — STEP 24-2 회귀 테스트

STEP 24-2: Mode B Contract의 "💡 필드 자동 제안"은 STEP 24-1의
modules.app_factory._suggest_spec()을 그대로 재사용한다(신규 AI 프롬프트/로직 없음).

Streamlit 제거(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP) 이후 이 파일은 모듈 레벨
불변조건만 검증한다. 제안 결과의 화면 반영/기존 값 보존은 React(Calculators.jsx,
frontend/src/__tests__/AppFactoryAi02.test.jsx)와 FastAPI(/api/calculators/ai/suggest-spec,
tests/test_app_factory_ai_02.py)가 담당한다. 실제 GPT/OpenAI 호출은 발생시키지 않는다.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import modules.app_factory as af_mod


# ── Test 3: Contract는 필드명만 Lock(label 파라미터 없음) ───────────────────

class TestFieldExtraction:

    def test_3_labels_not_forced_into_contract_fields(self):
        """build_contract()에 label 파라미터가 없으므로(Contract는 필드명만 Lock),
        label은 입력란에 직접 채우지 않고 성공 메시지에만 참고용으로 표시되어야 한다."""
        sig = inspect.signature(af_mod.build_contract)
        assert "label" not in sig.parameters
        assert "labels" not in sig.parameters


# ── Test 15: _suggest_spec() 재사용(무변경) ─────────────────────────────────

class TestNoUnrelatedModuleChanges:

    def test_15_suggest_spec_itself_unmodified_by_this_step(self):
        """_suggest_spec()은 STEP24-1에서 이미 검증된 함수 — 이번 STEP은
        이를 '재사용'만 해야 하므로 그 내부에 STEP24-2 마커가 있으면 안 된다."""
        src = inspect.getsource(af_mod._suggest_spec)
        assert "STEP 24-2" not in src
