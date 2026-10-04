# -*- coding: utf-8 -*-
"""tests/test_step26_1_contract_slug_suggestion.py — STEP 26-1 회귀 테스트

STEP 26-1: Mode B(Contract 확정 스펙 입력)의 확정 slug 자동 제안은 기존
modules.slug_generator.generate_slug()를 그대로 재사용한다(신규 slug 생성 규칙 없음).

Streamlit 제거(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP) 이후 이 파일은 generate_slug()
자체만 검증한다. 프리필/사용자 입력 보호는 React(frontend/src/__tests__/AppFactoryAi02.test.jsx),
중복 확인은 FastAPI(/api/calculators/generate/contract/slug-suggest, /slug-check —
tests/test_app_factory_ai_02.py, tests/test_contract_generation.py)가 담당한다.

핵심 안전 원칙:
  slug 자동 제안 ≠ Contract 자동 확정 ≠ Contract 기반 생성 ≠ 저장 자동 실행.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules.slug_generator import generate_slug


# ── 2. generate_slug() 결정적 결과 ───────────────────────────────────────────

class TestSameAsExistingGenerateSlug:
    def test_2_matches_generate_slug_directly(self):
        assert generate_slug("퇴직금 계산기") == "severance-pay"
        for name in ["퇴직금 계산기", "주휴수당 계산기", "4대보험 계산기", "BMI 계산기"]:
            slug = generate_slug(name)
            assert slug, f"빈 slug: {name}"
            assert generate_slug(name) == slug  # 결정적(같은 입력 → 같은 출력)


# ── 10. generate_slug() 시그니처 무변경 ──────────────────────────────────────

class TestModeAUnaffected:

    def test_10b_generate_slug_function_itself_unmodified(self):
        import inspect
        from modules import slug_generator
        src = inspect.getsource(slug_generator.generate_slug)
        assert "def generate_slug(name: str) -> str:" in src
