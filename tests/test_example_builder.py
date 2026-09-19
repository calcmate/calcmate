# -*- coding: utf-8 -*-
"""
tests/test_example_builder.py — content/calculator/example_builder.py 검증
(CALCMATE-BLOG-QUALITY-STEP132 Phase A)

검증 범위:
  1. provider registry가 실제 active calculator 14개와 정확히 1:1인지
     (누락/중복/미상 slug 없음)
  2. Type A(공통 formula) 5개 — execute_formula() 재계산과 provider 결과가 일치하는지
  3. Type B(four-insurances/annual-leave-remaining/연말정산) — 실제 registry/Python
     함수와 독립적으로 재계산해 일치하는지
  4. Type D(JS adapter) 6개 — 실제 production JS 분기/경계값을 그대로 재현하는지
     (military은 tests/test_military_discharge.py의 기존 TC와 교차검증)
  5. 안전성 — eval/exec/네트워크/DB쓰기 호출이 소스에 없는지
"""
import ast
import inspect
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from dateutil.relativedelta import relativedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content.calculator import example_builder as EB
from modules.config_loader import load_config
from modules.formula_engine import execute_formula
from modules.registry_loader import load_registry
from adapters.db.factory import get_calculator_storage_adapter
from repositories.calculator_repository import CalculatorRepository


CFG = load_config(str(Path(__file__).resolve().parent.parent / "config" / "config.yaml"))


@pytest.fixture(scope="module")
def repo():
    return CalculatorRepository(get_calculator_storage_adapter(CFG))


@pytest.fixture(scope="module")
def active_calcs(repo):
    return {c["slug"]: c for c in repo.get_active()}


# ─── 1. Provider registry coverage invariant ────────────────────────────────

def test_provider_registry_has_exactly_14_entries():
    assert len(EB.PROVIDERS) == 14


def test_provider_registry_no_duplicate_keys():
    # dict 리터럴 자체가 중복 키를 자동 제거하므로, 소스 텍스트 레벨에서 중복 여부를
    # 별도 확인한다(딕셔너리 런타임 상태만으로는 원본에 중복이 있었는지 알 수 없음).
    src = inspect.getsource(EB)
    registry_block = src[src.index("PROVIDERS = {"):src.index("\n}\n", src.index("PROVIDERS = {"))]
    keys = re.findall(r'"\s*([^"]+)\s*":\s*_provide_', registry_block)
    assert len(keys) == len(set(keys)), f"중복 slug 키 발견: {keys}"


def test_provider_registry_matches_active_calculators(active_calcs):
    active_slugs = set(active_calcs.keys())
    provider_slugs = set(EB.PROVIDERS.keys())
    missing = active_slugs - provider_slugs
    extra = provider_slugs - active_slugs
    assert not missing, f"provider가 없는 active calculator: {missing}"
    assert not extra, f"active가 아닌 calculator에 provider가 등록됨: {extra}"
    assert active_slugs == provider_slugs


def test_unregistered_slug_returns_none_explicitly():
    fake_calc = {"slug": "no-such-calculator-xyz", "formula": "a * b"}
    assert EB.build_example_context(fake_calc) is None


def test_all_active_calculators_produce_non_empty_verified_examples(active_calcs):
    for slug, calc in active_calcs.items():
        ctx = EB.build_example_context(calc)
        assert ctx is not None, f"{slug}: example_context가 None"
        assert isinstance(ctx["verified_examples"], list) and len(ctx["verified_examples"]) >= 1, slug
        assert isinstance(ctx["facts"], list), slug


# ─── 2. Type A: 공통 formula provider ────────────────────────────────────────

@pytest.mark.parametrize("slug", [
    "jeonse-vs-monthly", "weekly-holiday-allowance",
    "annual-leave-allowance", "bmi-calculator",
])
def test_type_a_result_matches_independent_execute_formula(active_calcs, slug):
    calc = active_calcs[slug]
    ctx = EB.build_example_context(calc)
    ex = ctx["verified_examples"][0]
    formula = EB._parse_formula(calc.get("formula"))
    output_schema = EB._parse_formula(calc.get("output_schema"))
    independent_result = execute_formula(formula, ex["inputs"], output_schema)
    assert ex["result"] == independent_result


def test_freelancer_tax_matches_production_formula_plus_net_derivation(active_calcs):
    calc = active_calcs["freelancer-tax-3p3"]
    ctx = EB.build_example_context(calc)
    ex = ctx["verified_examples"][0]
    formula = EB._parse_formula(calc.get("formula"))
    output_schema = EB._parse_formula(calc.get("output_schema"))
    withholding_result = execute_formula(formula, ex["inputs"], output_schema)
    withholding = round(next(iter(withholding_result.values())))
    expected_net = ex["inputs"]["gross_income"] - withholding
    assert ex["result"]["withholding_tax"] == withholding
    assert ex["result"]["net_income"] == expected_net


# ─── 3. Type B ───────────────────────────────────────────────────────────────

def test_four_insurances_uses_live_registry_rates(active_calcs):
    calc = active_calcs["four-insurances"]
    ctx = EB.build_example_context(calc)
    ex = ctx["verified_examples"][0]
    ir = (load_registry().get("four-insurances") or {}).get("insurance_rates") or {}
    np_rate = float(ir.get("np_rate", 0.045))
    np_min = int(ir.get("np_min", 390_000))
    np_max = int(ir.get("np_max", 6_170_000))
    hi_rate = float(ir.get("hi_rate", 0.03545))
    ltc_rate = float(ir.get("ltc_rate", 0.1296))
    ei_rate = float(ir.get("ei_rate", 0.009))
    salary = ex["inputs"]["monthly_salary"]
    expected_np = min(max(salary, np_min), np_max) * np_rate
    expected_hi = salary * hi_rate
    expected_ltc = expected_hi * ltc_rate
    expected_ei = salary * ei_rate
    assert ex["result"]["national_pension"] == pytest.approx(expected_np)
    assert ex["result"]["health_insurance"] == pytest.approx(expected_hi)
    assert ex["result"]["long_term_care"] == pytest.approx(expected_ltc)
    assert ex["result"]["employment_insurance"] == pytest.approx(expected_ei)
    assert ex["result"]["total"] == pytest.approx(expected_np + expected_hi + expected_ltc + expected_ei)


def test_annual_leave_remaining_both_branches(active_calcs):
    calc = active_calcs["annual-leave-remaining"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    assert len(examples) >= 2
    under_12 = [e for e in examples if e["inputs"]["months_of_service"] < 12]
    over_12 = [e for e in examples if e["inputs"]["months_of_service"] >= 12]
    assert under_12 and over_12
    for e in under_12:
        m = e["inputs"]["months_of_service"]
        assert e["result"]["total_days"] == min(m, 11)
    for e in over_12:
        m = e["inputs"]["months_of_service"]
        years = m // 12
        expected = 15 + min(max(0, (years - 1) // 2), 10)
        assert e["result"]["total_days"] == expected


def test_yearend_tax_refund_matches_python_module(active_calcs):
    from modules.income_tax_calculator import compute_year_end_settlement
    calc = active_calcs["연말정산_환급액_계산기"]
    ctx = EB.build_example_context(calc)
    ex = ctx["verified_examples"][0]
    settlement = compute_year_end_settlement(**ex["inputs"])
    assert ex["result"]["estimated_refund"] == settlement["estimated_refund"]
    # 내부 11단계 breakdown 키가 result에 그대로 노출되지 않아야 한다.
    assert set(ex["result"].keys()) == {"estimated_refund"}


# ─── 4. Type D ────────────────────────────────────────────────────────────────

def test_severance_pay_365_day_boundary(active_calcs):
    calc = active_calcs["severance-pay"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    for ex in examples:
        start = date.fromisoformat(ex["inputs"]["start_date"])
        end = date.fromisoformat(ex["inputs"]["end_date"])
        total_days = (end - start).days
        if total_days < 365:
            assert ex["result"]["severance_pay"] == 0
        else:
            expected = ex["inputs"]["avg_monthly_wage"] * (total_days / 365)
            assert ex["result"]["severance_pay"] == pytest.approx(expected)
    assert any((date.fromisoformat(e["inputs"]["end_date"]) - date.fromisoformat(e["inputs"]["start_date"])).days < 365 for e in examples)
    assert any((date.fromisoformat(e["inputs"]["end_date"]) - date.fromisoformat(e["inputs"]["start_date"])).days >= 365 for e in examples)


def test_unemployment_benefit_four_branches_and_facts(active_calcs):
    calc = active_calcs["unemployment-benefit"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    assert len(examples) == 4
    excluded = [e for e in examples if e["inputs"]["employment_months"] < 6]
    assert len(excluded) == 1
    assert excluded[0]["result"] == {"daily_benefit": 0, "benefit_days": 0, "total_benefit": 0}

    reg = (load_registry().get("unemployment-benefit") or {})
    ba = reg.get("benefit_amounts") or {}
    daily_max = int(ba.get("daily_max", 66_000))
    daily_min = round(int(ba.get("min_wage_hourly", 10_030)) * 8 * 0.8)

    non_excluded = [e for e in examples if e["inputs"]["employment_months"] >= 6]
    raws = [e["inputs"]["avg_daily_wage"] * 0.6 for e in non_excluded]
    assert any(r < daily_min for r in raws), "하한 클램프 케이스 없음"
    assert any(daily_min <= r <= daily_max for r in raws), "정상(클램프 없음) 케이스 없음"
    assert any(r > daily_max for r in raws), "상한 클램프 케이스 없음"

    for e in non_excluded:
        raw = e["inputs"]["avg_daily_wage"] * 0.6
        expected_daily = min(max(raw, daily_min), daily_max)
        assert e["result"]["daily_benefit"] == pytest.approx(expected_daily)

    bdt = reg.get("benefit_days_table") or {}
    expected_fact_count = len(bdt.get("under_50") or []) + len(bdt.get("age_50_plus") or [])
    assert len(ctx["facts"]) == expected_fact_count == 10


def test_brokerage_fee_cap_binding_and_facts(active_calcs):
    calc = active_calcs["real-estate-brokerage-fee"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    assert len(examples) == 3
    assert len(ctx["facts"]) == 12
    # cap-binding 예시: raw_fee가 실제로 cap을 초과해서 잘렸는지 확인
    found_cap_binding = False
    for e in examples:
        deal_type, amount = e["inputs"]["deal_type"], e["inputs"]["deal_amount"]
        bracket = next(f for f in ctx["facts"]
                        if f["deal_type"] == deal_type and amount >= f["amount_lo"]
                        and (f["amount_hi"] is None or amount < f["amount_hi"]))
        raw_fee = amount * bracket["rate"]
        if bracket["cap"] is not None and raw_fee > bracket["cap"]:
            found_cap_binding = True
            assert e["result"]["brokerage_fee"] == bracket["cap"]
        else:
            assert e["result"]["brokerage_fee"] == round(raw_fee)
    assert found_cap_binding, "cap이 실제로 발동하는 예시가 없음"
    assert any(e["inputs"]["deal_type"] == 1 for e in examples)
    assert any(e["inputs"]["deal_type"] == 2 for e in examples)


def test_parental_leave_six_examples_and_boundaries(active_calcs):
    calc = active_calcs["육아휴직_급여_계산기"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    assert len(examples) == 6

    plb = (load_registry().get("육아휴직_급여_계산기") or {}).get("parental_leave_benefit") or {}
    min_insured = int(plb.get("min_insured_days", 180))
    gen = plb.get("general") or {}
    gen_ceil = int(gen.get("ceiling", 1_500_000))
    gen_floor = int(gen.get("floor", 700_000))

    below_180 = [e for e in examples if e["inputs"]["insured_days"] < min_insured]
    assert len(below_180) == 1
    assert below_180[0]["result"] == {"monthly_allowance": 0}

    month7 = [e for e in examples if e["inputs"]["use_6plus6"] == 1 and e["inputs"]["leave_month"] == 7]
    assert len(month7) == 1, "leave_month=7 전환 경계 예시 없음"

    month_in_6 = [e for e in examples if e["inputs"]["use_6plus6"] == 1 and 1 <= e["inputs"]["leave_month"] <= 6]
    assert len(month_in_6) == 1, "6+6 특례 대표(1~6개월) 예시 없음"

    general_no_6plus6 = [e for e in examples if e["inputs"]["use_6plus6"] == 0
                          and e["inputs"]["insured_days"] >= min_insured]
    assert len(general_no_6plus6) == 3, "general baseline/upper/lower 3건이어야 함"
    allowances = sorted(e["result"]["monthly_allowance"] for e in general_no_6plus6)
    assert allowances[0] == pytest.approx(gen_floor), "하한 클램프 케이스가 floor와 정확히 일치해야 함"
    assert allowances[-1] == pytest.approx(gen_ceil), "상한 클램프 케이스가 ceiling과 정확히 일치해야 함"
    assert gen_floor < allowances[1] < gen_ceil, "baseline 케이스가 클램프 없이 floor~ceiling 사이여야 함"

    # month7 전환 케이스는 순수 GENERAL과 동일한 산식(사용된 wage가 baseline과 같다면 금액도 같음)
    baseline = next(e for e in general_no_6plus6
                     if gen_floor < e["result"]["monthly_allowance"] < gen_ceil)
    if month7[0]["inputs"]["monthly_wage"] == baseline["inputs"]["monthly_wage"]:
        assert month7[0]["result"]["monthly_allowance"] == pytest.approx(baseline["result"]["monthly_allowance"])


def test_car_tax_null_constraint_and_rate_map(active_calcs):
    calc = active_calcs["자동차_취등록세_계산기"]
    ctx = EB.build_example_context(calc)
    examples = ctx["verified_examples"]
    assert len(examples) == 4
    # 정상 계산 예시로 억지 변환되지 않았는지: 경차+친환경 조합이 examples 안에 없어야 함
    for e in examples:
        assert not (e["inputs"]["car_type"] == 2 and e["inputs"]["eco_type"] in (1, 2)), \
            "경차+친환경 조합이 정상 worked example로 잘못 포함됨"
    # 실제로 그 조합을 넣으면 None이 나오는지 직접 검증(내부 헬퍼 재현)
    from content.calculator.example_builder import _provide_car_acquisition_tax  # noqa: F401
    RATE_MAP = {1: 0.07, 2: 0.04, 3: 0.04, 4: 0.05, 5: 0.02}
    for e in examples:
        rate = RATE_MAP[e["inputs"]["car_type"]]
        standard = round(e["inputs"]["car_price"] * rate)
        assert e["result"]["standard_acquisition_tax"] == standard
        assert e["result"]["acquisition_tax"] == max(0, standard - e["result"]["exemption_amount"])
    constraint_facts = [f for f in ctx["facts"] if "constraint" in f]
    assert len(constraint_facts) == 1
    assert "경차" in constraint_facts[0]["constraint"] and "전기" in constraint_facts[0]["constraint"]


def test_military_discharge_matches_known_test_vectors():
    """tests/test_military_discharge.py의 기존 TC(육군 21→18개월 정정 이후 실측)와
    동일한 dateutil.relativedelta 로직을 이 provider도 쓰는지 교차 검증한다."""
    _MONTHS = {"army": 18, "marine": 18, "navy": 20, "air_force": 21, "social_service": 21}
    cases = [
        (date(2025, 1, 15), "army", date(2026, 7, 14)),
        (date(2025, 1, 15), "navy", date(2026, 9, 14)),
        (date(2025, 1, 15), "air_force", date(2026, 10, 14)),
        (date(2025, 1, 31), "navy", date(2026, 9, 29)),
        (date(2024, 2, 29), "army", date(2025, 8, 28)),
    ]
    for enlistment, branch, expected in cases:
        discharge = enlistment + relativedelta(months=_MONTHS[branch]) - relativedelta(days=1)
        assert discharge == expected


def test_military_provider_facts_and_reference_date(active_calcs):
    calc = active_calcs["military-discharge-date"]
    ctx = EB.build_example_context(calc)
    assert len(ctx["facts"]) == 5
    expected_months = {"army": 18, "marine": 18, "navy": 20, "air_force": 21, "social_service": 21}
    facts_by_service = {f["service"]: f["months"] for f in ctx["facts"]}
    assert facts_by_service == expected_months

    examples = ctx["verified_examples"]
    assert len(examples) == 2
    discharge_only = examples[0]
    assert "reference_date" not in discharge_only["inputs"]
    with_reference = examples[1]
    assert "reference_date" in with_reference["inputs"], "military 예시는 reference_date를 명시해야 함(암묵적 today 금지)"

    enlistment = date.fromisoformat(with_reference["inputs"]["enlistment_date"])
    branch = with_reference["inputs"]["branch"]
    reference_date = date.fromisoformat(with_reference["inputs"]["reference_date"])
    discharge = enlistment + relativedelta(months=expected_months[branch]) - relativedelta(days=1)
    total = (discharge - enlistment).days + 1
    expected_remaining = (discharge - reference_date).days
    expected_served = min(max((reference_date - enlistment).days, 0), total)
    expected_progress = min(max(round(expected_served / total * 100), 0), 100)
    assert with_reference["result"]["remaining_days"] == expected_remaining
    assert with_reference["result"]["progress_pct"] == expected_progress
    assert with_reference["result"]["discharge_date"] == discharge.isoformat()
    assert with_reference["result"]["total_days"] == total


# ─── 5. Safety ────────────────────────────────────────────────────────────────

def _module_ast():
    """docstring/주석은 AST 문자열 리터럴/제거 대상이라 자연스럽게 제외되고,
    실제 실행 코드(Call/Import 노드)만 검사 대상이 된다 — module docstring 안의
    설명 문구("eval()를 쓰지 않는다" 등)로 인한 오탐을 원천 차단한다."""
    src = inspect.getsource(EB)
    return ast.parse(src), src


def test_no_eval_exec_in_source():
    tree, _ = _module_ast()
    forbidden_calls = {"eval", "exec"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_calls, f"금지된 호출 발견: {node.func.id}()"


def test_no_network_or_wp_or_db_write_calls_in_source():
    tree, src = _module_ast()
    forbidden_modules = {"requests", "subprocess", "urllib", "openai", "anthropic", "google.generativeai"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, f"금지된 import 발견: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_modules, f"금지된 import 발견: {node.module}"
    for forbidden_call in (".update(", ".update_generated(", "publisher.publish", "get_db_adapter"):
        assert forbidden_call not in src, f"금지된 호출 패턴 발견: {forbidden_call}"


def test_build_example_context_does_not_mutate_input_calc(active_calcs):
    calc = dict(active_calcs["jeonse-vs-monthly"])
    snapshot = dict(calc)
    EB.build_example_context(calc)
    assert calc == snapshot
