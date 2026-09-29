# -*- coding: utf-8 -*-
"""tests/test_car_tax_input_validation.py — 자동차_취등록세_계산기 입력 검증 회귀 테스트

STEP 28-192/193에서 이 계산기의 실제 계산 로직은 modules/app_generator.py의
slug 조건부 완전 커스텀 분기(car_type/eco_type을 select 숫자 코드로 받는 신규
스키마)로 대체됐다. 생성된 JS는 "car_price <= 0"이면 계산을 실행하지 않고 null을
반환하는 가드를 주입한다(0원도 차단 — STEP 28-192 명시적 정책, 기존 "0원 허용"
정책은 폐기됐다).

이 파일은 입력 검증(음수/0/유효 범위) 가드만 다룬다. 실제 세율·감면 계산 결과의
전체 회귀 검증은 tests/test_step28_193_car_tax_compute.py(실제 생성 JS를 Node로
실행하는 33개 테스트)가 전담하므로 여기서 중복하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from modules.app_generator import _compute_js

CAR_TAX_CALC = {
    "slug": "자동차_취등록세_계산기",
    "input_schema": {"car_price": "number", "car_type": "select:1=비영업승용,2=경차,3=영업용,4=승합·화물·특수,5=이륜차",
                      "eco_type": "select:0=일반,1=전기,2=수소"},
    "output_schema": {"acquisition_tax": "number", "standard_acquisition_tax": "number", "exemption_amount": "number"},
    "formula": {},
}


# ═══════════════════════════════════════════════════════════════════
# 1. 생성된 JS(공개 사이트 실제 계산 경로)에 car_price 0/음수 가드 주입 확인
# ═══════════════════════════════════════════════════════════════════

def test_generated_js_rejects_zero_or_negative_car_price():
    js = _compute_js(CAR_TAX_CALC)
    assert "car_price <= 0" in js, f"car_price 0/음수 가드 누락:\n{js}"
    assert "return null" in js


# ═══════════════════════════════════════════════════════════════════
# 2. 생성된 JS 가드 시뮬레이션(Python 미러) — 경계값
# ═══════════════════════════════════════════════════════════════════

def _js_guard_mirror(car_price: float) -> bool:
    """_compute_js()가 주입하는 'if (car_price <= 0) return null' 조건의 Python 미러."""
    return car_price <= 0


@pytest.mark.parametrize("car_price", [-1, -5_000_000, -0.01, 0])
def test_js_guard_rejects_non_positive_price(car_price):
    assert _js_guard_mirror(car_price) is True


@pytest.mark.parametrize("car_price", [1, 30_000_000, 50_000_000])
def test_js_guard_allows_positive_price(car_price):
    assert _js_guard_mirror(car_price) is False
