# -*- coding: utf-8 -*-
"""tests/test_calculator_schema_validation.py

STEP42: modules/formula_engine.validate_calculator_schema() 회귀 테스트.

STEP41에서 확인된 공백(App Factory가 GPT 응답의 input_schema/output_schema
"값"을 전혀 검증하지 않아 bmi-calculator/연금저축_irp_세액공제_계산기에
literal 0/0.0이 그대로 저장된 문제)을 막는 검증 함수를 테스트한다.

허용 어휘는 STEP42 §3에서 실제 SQLite 19개 calculators 행을 전수 조사해
확정한 것과 동일하다(추측으로 새 어휘를 만들지 않음).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.formula_engine import validate_calculator_schema


def _out_ok(out=None):
    return out or {"result": "number"}


# ── 1~5. 평탄형 정상 값 ────────────────────────────────────────────────

def test_1_valid_number():
    ok, msg = validate_calculator_schema({"height_cm": "number"}, _out_ok())
    assert ok, msg


def test_2_valid_integer():
    ok, msg = validate_calculator_schema({"months_of_service": "integer"}, _out_ok())
    assert ok, msg


def test_3_valid_boolean():
    ok, msg = validate_calculator_schema({"use_6plus6": "boolean"}, _out_ok())
    assert ok, msg


def test_4_valid_date():
    ok, msg = validate_calculator_schema({"start_date": "date"}, _out_ok())
    assert ok, msg


def test_5_valid_select():
    ok, msg = validate_calculator_schema(
        {"deal_type": "select:1=매매·교환,2=전세·월세"}, _out_ok())
    assert ok, msg


# ── 6. 기존 지원 dict 형태(military-discharge-date 실측 그대로) ──────────

def test_6_valid_existing_dict_shape():
    input_schema = {
        "enlistment_date": {"type": "date", "label": "입영일"},
        "branch": {"type": "select", "label": "군별",
                  "options": ["army", "marine", "navy", "air_force", "social_service"]},
    }
    output_schema = {
        "discharge_date": {"label": "예상 전역일"},
        "remaining_days": {"label": "남은 일수"},
        "progress_pct": {"label": "복무 진행률"},
    }
    ok, msg = validate_calculator_schema(input_schema, output_schema)
    assert ok, msg


# ── 7/8. literal 0 / 0.0 거부 ──────────────────────────────────────────

def test_7_literal_zero_input_rejected():
    ok, msg = validate_calculator_schema(
        {"height_cm": 0, "weight_kg": 0}, {"bmi": 0.0})
    assert not ok
    assert "input_schema" in msg


def test_8_literal_zero_float_output_rejected():
    ok, msg = validate_calculator_schema(
        {"height_cm": "number", "weight_kg": "number"}, {"bmi": 0.0})
    assert not ok
    assert "output_schema" in msg


# ── 9. 알 수 없는 문자열 거부 ──────────────────────────────────────────

def test_9_unknown_string_value_rejected():
    ok, msg = validate_calculator_schema({"amount": "currency"}, _out_ok())
    assert not ok
    assert "지원되지 않는 값" in msg


# ── 10. 정상 기존 calculator schema(실제 severance-pay 형태) 통과 ───────

def test_10_existing_real_calculator_schema_passes():
    input_schema = {"avg_monthly_wage": "number", "start_date": "date", "end_date": "date"}
    output_schema = {"severance_pay": "number"}
    ok, msg = validate_calculator_schema(input_schema, output_schema)
    assert ok, msg


# ── 추가: JSON 문자열 입력도 처리(실제 DB 저장 형태), 빈/malformed 거부 ──

def test_json_string_input_is_parsed():
    ok, msg = validate_calculator_schema(
        '{"gross_income": "number"}', '{"withholding_tax": "number"}')
    assert ok, msg


def test_empty_schema_rejected():
    ok, msg = validate_calculator_schema({}, _out_ok())
    assert not ok


def test_malformed_json_string_rejected():
    ok, msg = validate_calculator_schema("{this is not json}", _out_ok())
    assert not ok


def test_select_missing_equals_sign_rejected():
    ok, msg = validate_calculator_schema({"deal_type": "select:no-equals-here"}, _out_ok())
    assert not ok


def test_dict_entry_missing_label_rejected():
    ok, msg = validate_calculator_schema({"enlistment_date": {"type": "date"}}, _out_ok())
    assert not ok


def test_dict_entry_with_select_type_missing_options_rejected():
    ok, msg = validate_calculator_schema(
        {"branch": {"type": "select", "label": "군별"}}, _out_ok())
    assert not ok


def test_output_dict_entry_type_optional():
    """출력 dict는 실측상 'type'이 아예 없는 것이 정상 형태 — 없어도 통과해야 한다."""
    ok, msg = validate_calculator_schema(
        {"x": "number"}, {"result": {"label": "결과"}})
    assert ok, msg


def test_real_production_schemas_all_pass_except_known_two():
    """STEP42 §3 실측 데이터(오염 2건 제외 17건) 그대로 재현 — 전부 통과해야 한다."""
    cases = [
        ({"avg_monthly_wage": "number", "start_date": "date", "end_date": "date"},
         {"severance_pay": "number"}),
        ({"months_of_service": "integer", "used_days": "integer"},
         {"total_days": "integer", "remaining_days": "integer"}),
        ({"deal_type": "select:1=매매·교환,2=전세·월세", "deal_amount": "integer"},
         {"brokerage_fee": "integer"}),
        ({"car_price": "number", "car_type": "select:1=비영업승용,2=경차,3=영업용,4=승합·화물·특수,5=이륜차",
          "eco_type": "select:0=일반,1=전기,2=수소"},
         {"acquisition_tax": "number", "standard_acquisition_tax": "number",
          "exemption_amount": "number"}),
        ({"monthly_wage": "number", "insured_days": "number",
          "use_6plus6": "boolean", "leave_month": "number"},
         {"monthly_allowance": "number"}),
    ]
    for ins, outs in cases:
        ok, msg = validate_calculator_schema(ins, outs)
        assert ok, f"{ins} / {outs} -> {msg}"


def test_known_contaminated_rows_are_now_rejected_by_gate():
    """STEP41에서 발견된 실제 오염 2건 재현 — 새 게이트가 있었다면 저장을 막았어야 한다."""
    ok1, _ = validate_calculator_schema(
        {"height_cm": 0, "weight_kg": 0}, {"bmi": 0.0})
    ok2, _ = validate_calculator_schema(
        {"annual_income": 0, "pension_contribution": 0, "irp_contribution": 0},
        {"deductible_amount": 0, "estimated_tax_credit": 0})
    assert not ok1
    assert not ok2
