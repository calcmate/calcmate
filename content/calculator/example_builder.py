# -*- coding: utf-8 -*-
"""
content/calculator/example_builder.py — Deterministic Calculator Example Builder (Phase A)

목적: 계산기 slug별로 "확정된(verified) 계산 예시"와 "외부 사실값(facts)"을
LLM 호출 없이 순수 결정론적으로 생성해 example_context(dict)로 반환한다.
(CALCMATE-BLOG-QUALITY-STEP124~131 감사 결과에 따른 Phase A 구현)

절대 원칙(이 파일 안에서 항상 지켜야 함):
  - LLM을 호출하지 않는다.
  - WordPress API를 호출하지 않는다.
  - DB에 쓰지 않는다(레지스트리/설정 값은 READ만).
  - eval()/exec()를 쓰지 않는다 — 수식 평가는 modules.formula_engine.execute_formula()
    (ast 화이트리스트 기반 안전 평가기)만 사용한다.
  - 네트워크 호출(requests/urllib 등)을 하지 않는다.

이 모듈은 아직 어떤 production 호출 경로(calculator_wp_publish.py, writer.py,
calculator_faq_generator.py 등)에도 연결되지 않는다 — Phase A는 독립 모듈+테스트로만
끝난다(CALCMATE-BLOG-QUALITY-STEP129/132 지시).

반환 구조(example_context):
  {
      "verified_examples": [
          {"inputs": {...}, "result": {...}, "formula": "..." (optional)},
          ...
      ],
      "facts": [ {...}, ... ]   # 계산 결과가 아닌 production SSOT 상수/규칙
  }

Provider 함수 시그니처: provider(calc: dict) -> dict
  calc는 CalculatorRepository가 반환하는 계산기 행(dict) 그대로("slug"/"formula"/
  "input_schema"/"output_schema" 등 포함).

SSOT 근거는 각 provider 함수의 docstring에 파일:라인으로 명시한다
(CALCMATE-BLOG-QUALITY-STEP126~131의 코드 추적 결과를 그대로 반영).
"""
import json
from datetime import date

from dateutil.relativedelta import relativedelta

from modules.formula_engine import execute_formula
from modules.registry_loader import load_registry


# ---------------------------------------------------------------------------
# 공통 유틸리티
# ---------------------------------------------------------------------------

def _parse_formula(raw):
    """calc['formula']/calc['output_schema'] 문자열을 dict 또는 str로 파싱한다.

    modules/formula_engine.py::load_formula()의 내부 헬퍼 _pj()와 동일한 원칙
    (json.loads 시도, 실패 시 원문 그대로 반환)을 이 모듈 전용으로 재구현한다
    (private 헬퍼라 import 불가하므로 동일 로직만 복제 — 원본은 수정하지 않음)."""
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _example(inputs: dict, result: dict, formula=None) -> dict:
    ex = {"inputs": inputs, "result": result}
    if formula is not None:
        ex["formula"] = formula
    return ex


def _context(examples: list, facts: list | None = None) -> dict:
    return {"verified_examples": examples, "facts": facts or []}


# ---------------------------------------------------------------------------
# Type A — 공통 formula 기반 provider (modules.formula_engine.execute_formula 재사용)
# ---------------------------------------------------------------------------

def _formula_provider(representative_inputs: dict):
    """calc['formula']를 그대로 execute_formula()에 넘겨 계산하는 공통 provider 팩토리.
    production formula 문자열을 복사/변형하지 않고 calc 자체에서 읽는다."""

    def _provider(calc: dict) -> dict:
        formula = _parse_formula(calc.get("formula"))
        output_schema = _parse_formula(calc.get("output_schema"))
        result = execute_formula(formula, representative_inputs, output_schema)
        return _context([_example(representative_inputs, result, formula=calc.get("formula"))])

    return _provider


# jeonse-vs-monthly: calc['formula']가 3개 출력 키를 가진 dict, STEP124에서
# 이 정확한 입력값으로 5/5 재현성 확인됨(708,333/222,000,000/91,667원).
_provide_jeonse_vs_monthly = _formula_provider({
    "jeonse_deposit": 200_000_000, "wolse_deposit": 30_000_000,
    "wolse_amount": 800_000, "rate": 5,
})

# weekly-holiday-allowance: formula="hourly_wage * (weekly_hours / 40) * 8"
_provide_weekly_holiday_allowance = _formula_provider({
    "weekly_hours": 40, "hourly_wage": 10_320,
})

# annual-leave-allowance: formula="daily_wage * unused_days"
_provide_annual_leave_allowance = _formula_provider({
    "daily_wage": 100_000, "unused_days": 5,
})

# bmi-calculator: formula="round(weight_kg / ((height_cm / 100) ** 2), 2)"
_provide_bmi_calculator = _formula_provider({
    "height_cm": 170, "weight_kg": 65,
})


def _provide_freelancer_tax_3p3(calc: dict) -> dict:
    """freelancer-tax-3p3: calc['formula']="gross_income * 0.033"는 withholding_tax만
    커버한다. net_income은 실제 JS(app_generator.py:984-987)에서
    'net = gross_income - Math.round(gross_income*0.033)'로 파생되므로, execute_formula로
    withholding_tax를 구한 뒤 동일한 뺄셈을 Python으로 그대로 적용한다(별도 SSOT 발명 없음)."""
    inputs = {"gross_income": 3_000_000}
    formula = _parse_formula(calc.get("formula"))
    output_schema = _parse_formula(calc.get("output_schema"))
    withholding_result = execute_formula(formula, inputs, output_schema)
    withholding_key = next(iter(withholding_result))
    withholding = round(withholding_result[withholding_key])
    net_income = inputs["gross_income"] - withholding
    result = {"withholding_tax": withholding, "net_income": net_income}
    return _context([_example(inputs, result, formula=calc.get("formula"))])


# ---------------------------------------------------------------------------
# Type B — formula + registry 상수 결합 / 기존 Python 함수 재사용
# ---------------------------------------------------------------------------

def _provide_four_insurances(calc: dict) -> dict:
    """SSOT: registry["four-insurances"]["insurance_rates"](app_generator.py:560-593).
    calc['formula']는 "clamp(...)" 표기를 쓰는데 execute_formula()의 화이트리스트 함수
    목록(min/max/round/abs/int/float)에는 clamp가 없으므로, 동일 의미의 min/max 조합
    수식을 레지스트리 값으로 직접 구성한다(calc['formula'] 파싱/재사용 아님 — clamp 미지원
    문제를 피하기 위해 registry 값으로 새로 조립, 값 자체는 하드코딩하지 않음)."""
    ir = (load_registry().get("four-insurances") or {}).get("insurance_rates") or {}
    np_rate = float(ir.get("np_rate", 0.045))
    np_min = int(ir.get("np_min", 390_000))
    np_max = int(ir.get("np_max", 6_170_000))
    hi_rate = float(ir.get("hi_rate", 0.03545))
    ltc_rate = float(ir.get("ltc_rate", 0.1296))
    ei_rate = float(ir.get("ei_rate", 0.009))

    inputs = {"monthly_salary": 3_000_000}
    # long_term_care = health_insurance * LTC_RATE = (monthly_salary*HI_RATE)*LTC_RATE
    # → execute_formula는 다른 출력 키를 변수로 참조할 수 없으므로 대수적으로 동일한
    # monthly_salary*HI_RATE*LTC_RATE로 인라인한다(좌결합 곱셈이라 부동소수점 결과도 동일).
    formula = {
        "national_pension": f"min(max(monthly_salary,{np_min}),{np_max})*{np_rate}",
        "health_insurance": f"monthly_salary*{hi_rate}",
        "long_term_care": f"monthly_salary*{hi_rate}*{ltc_rate}",
        "employment_insurance": f"monthly_salary*{ei_rate}",
        "total": (
            f"min(max(monthly_salary,{np_min}),{np_max})*{np_rate}"
            f"+monthly_salary*{hi_rate}"
            f"+monthly_salary*{hi_rate}*{ltc_rate}"
            f"+monthly_salary*{ei_rate}"
        ),
    }
    result = execute_formula(formula, inputs, None)
    return _context([_example(inputs, result, formula=json.dumps(formula, ensure_ascii=False))])


def _provide_annual_leave_remaining(calc: dict) -> dict:
    """SSOT: app_generator.py:666-686(JS 분기).
    calc['formula']는 12개월 이상(≥1년) 케이스만 담고 있고, 실제 JS에는 12개월 미만
    전용 분기(min(months,11))가 별도로 있어 formula 필드만으로는 불완전
    (STEP126에서 최초 발견) — 두 분기를 Python으로 직접 재현한다."""

    def _total_days(months_of_service: int) -> int:
        if months_of_service < 12:
            return min(months_of_service, 11)
        years = months_of_service // 12
        return 15 + min(max(0, (years - 1) // 2), 10)

    examples = []
    for months, used_days in [(6, 2), (36, 5)]:
        total_days = _total_days(months)
        inputs = {"months_of_service": months, "used_days": used_days}
        result = {"total_days": total_days, "remaining_days": total_days - used_days}
        examples.append(_example(inputs, result))
    return _context(examples)


def _provide_yearend_tax_refund(calc: dict) -> dict:
    """SSOT: modules/income_tax_calculator.py::compute_year_end_settlement() —
    STEP130/131에서 app_generator.py:780-868(JS)와 입력필드명·registry 경로가
    완전히 일치함(MATCH)이 확인된 유일한 계산기. 기존 Python 함수를 그대로 재사용한다."""
    from modules.income_tax_calculator import compute_year_end_settlement

    inputs = {"total_salary": 40_000_000, "family_count": 2, "paid_tax": 1_500_000}
    settlement = compute_year_end_settlement(**inputs)
    # output_schema는 estimated_refund 하나뿐 — 내부 11단계 breakdown은 노출하지 않는다.
    result = {"estimated_refund": settlement["estimated_refund"]}
    return _context([_example(inputs, result)])


# ---------------------------------------------------------------------------
# Type D — production JS를 Python deterministic provider로 이식
# ---------------------------------------------------------------------------

def _provide_severance_pay(calc: dict) -> dict:
    """SSOT: app_generator.py:992-1015(JS, compute_type="date_based").
    total_days = floor((end-start)/일), <365일이면 0원+notice, 아니면
    avg_monthly_wage*(total_days/365)."""

    def _compute(start: date, end: date, avg_monthly_wage: int) -> dict:
        total_days = (end - start).days
        if total_days < 365:
            return {"severance_pay": 0}
        return {"severance_pay": avg_monthly_wage * (total_days / 365)}

    examples = []
    cases = [
        (date(2025, 1, 1), date(2025, 6, 1), 3_000_000),   # <365일
        (date(2024, 1, 1), date(2025, 6, 1), 3_000_000),   # >=365일
    ]
    for start, end, wage in cases:
        inputs = {"avg_monthly_wage": wage, "start_date": start.isoformat(), "end_date": end.isoformat()}
        examples.append(_example(inputs, _compute(start, end, wage)))
    return _context(examples)


def _provide_unemployment_benefit(calc: dict) -> dict:
    """SSOT: app_generator.py:498-557(JS) + registry["unemployment-benefit"]
    (benefit_amounts/benefit_days_table). daily_benefit=clamp(wage*0.6, min, max),
    benefit_days=연령대×가입기간 구간표 조회, employment_months<6이면 전액 0."""
    reg = (load_registry().get("unemployment-benefit") or {})
    ba = reg.get("benefit_amounts") or {}
    daily_max = int(ba.get("daily_max", 66_000))
    min_wage = int(ba.get("min_wage_hourly", 10_030))
    daily_min = round(min_wage * 8 * 0.8)
    bdt = reg.get("benefit_days_table") or {}
    under_50 = bdt.get("under_50") or []
    age_50_plus = bdt.get("age_50_plus") or []

    def _days_for(months: int, table: list) -> int:
        for row in table:
            lo, hi = row["months_lo"], row.get("months_hi")
            if months >= lo and (hi is None or months < hi):
                return row["days"]
        return table[-1]["days"] if table else 0

    def _compute(avg_daily_wage: float, age: int, employment_months: int) -> dict:
        if employment_months < 6:
            return {"daily_benefit": 0, "benefit_days": 0, "total_benefit": 0}
        raw_daily = avg_daily_wage * 0.6
        daily_benefit = min(max(raw_daily, daily_min), daily_max)
        table = age_50_plus if age >= 50 else under_50
        benefit_days = _days_for(employment_months, table)
        return {
            "daily_benefit": daily_benefit,
            "benefit_days": benefit_days,
            "total_benefit": daily_benefit * benefit_days,
        }

    # 임계값을 레지스트리 라이브 값 기준으로 산출 — 요율이 바뀌어도 각 예시가
    # 항상 목표 분기(하한/정상/상한)에 들어가도록 algebraic 하게 wage를 역산한다.
    excluded_wage = round(daily_min / 0.6)
    lower_wage = round((daily_min / 0.6) * 0.8)
    normal_wage = round(((daily_min + daily_max) / 2) / 0.6)
    upper_wage = round((daily_max / 0.6) * 1.3)

    cases = [
        (excluded_wage, 30, 3),     # 6개월 미만 → 수급 불가
        (lower_wage, 30, 24),       # 하한 클램프
        (normal_wage, 35, 24),      # 정상(클램프 없음)
        (upper_wage, 55, 48),       # 상한 클램프
    ]
    examples = [
        _example({"avg_daily_wage": w, "age": a, "employment_months": m}, _compute(w, a, m))
        for w, a, m in cases
    ]

    facts = []
    for group_name, table in (("under_50", under_50), ("age_50_plus", age_50_plus)):
        for row in table:
            facts.append({
                "age_group": group_name,
                "employment_months_lo": row["months_lo"],
                "employment_months_hi": row.get("months_hi"),
                "benefit_days": row["days"],
            })
    return _context(examples, facts)


def _provide_real_estate_brokerage_fee(calc: dict) -> dict:
    """SSOT: app_generator.py:610-645(JS). registry 미사용 — 요율/한도표가 JS 코드에
    직접 리터럴로 존재하는 유일한 케이스(STEP130/131 확인). 따라서 이 표는 이 provider
    안에서만 transcribe하며, app_generator.py의 실제 리터럴이 바뀌면 이 provider도
    함께 갱신해야 한다(유지보수 주의사항으로 최종 보고에 명시)."""
    # (deal_type, lo, hi(None=무제한), rate, cap(None=무제한))
    _BRACKETS = [
        (1, 0, 50_000_000, 0.006, 250_000),
        (1, 50_000_000, 200_000_000, 0.005, 800_000),
        (1, 200_000_000, 900_000_000, 0.004, None),
        (1, 900_000_000, 1_200_000_000, 0.005, None),
        (1, 1_200_000_000, 1_500_000_000, 0.006, None),
        (1, 1_500_000_000, None, 0.007, None),
        (2, 0, 50_000_000, 0.005, 200_000),
        (2, 50_000_000, 100_000_000, 0.004, 300_000),
        (2, 100_000_000, 600_000_000, 0.003, None),
        (2, 600_000_000, 1_200_000_000, 0.004, None),
        (2, 1_200_000_000, 1_500_000_000, 0.005, None),
        (2, 1_500_000_000, None, 0.006, None),
    ]

    def _bracket_for(deal_type: int, amount: int):
        for dt, lo, hi, rate, cap in _BRACKETS:
            if dt == deal_type and amount >= lo and (hi is None or amount < hi):
                return rate, cap
        raise ValueError("no matching bracket")

    def _compute(deal_type: int, deal_amount: int) -> dict:
        rate, cap = _bracket_for(deal_type, deal_amount)
        raw_fee = deal_amount * rate
        fee = min(raw_fee, cap) if cap is not None else raw_fee
        return {"brokerage_fee": round(fee)}

    cases = [
        (1, 500_000_000),   # 매매·교환, cap 없는 구간(uncapped 대표)
        (2, 300_000_000),   # 임대차, cap 없는 구간(uncapped 대표)
        (1, 45_000_000),    # cap-binding(raw=270,000 > cap=250,000)
    ]
    examples = [
        _example({"deal_type": dt, "deal_amount": amt}, _compute(dt, amt))
        for dt, amt in cases
    ]
    facts = [
        {"deal_type": dt, "amount_lo": lo, "amount_hi": hi, "rate": rate, "cap": cap}
        for dt, lo, hi, rate, cap in _BRACKETS
    ]
    return _context(examples, facts)


def _provide_parental_leave_benefit(calc: dict) -> dict:
    """SSOT: app_generator.py:693-778(JS). CALCMATE-BLOG-QUALITY-STEP129에서
    modules/parental_leave_calculator.py가 실제 JS와 입력필드명·registry 경로·출력
    구조가 전부 달라(DIVERGED) 재사용 불가로 확정됨 — 이 provider는 그 Python 모듈을
    전혀 사용하지 않고 JS 로직을 그대로 이식한다(STEP131에서 재설계 확정)."""
    plb = (load_registry().get("육아휴직_급여_계산기") or {}).get("parental_leave_benefit") or {}
    min_insured = int(plb.get("min_insured_days", 180))
    gen = plb.get("general") or {}
    gen_rate = float(gen.get("rate", 0.80))
    gen_ceil = int(gen.get("ceiling", 1_500_000))
    gen_floor = int(gen.get("floor", 700_000))
    sp = plb.get("special_6plus6") or {}
    sp_rate = float(sp.get("rate", 1.00))
    sp_max_mo = int(sp.get("max_months", 6))
    sp_ceils = list(sp.get("monthly_ceilings") or [2_000_000, 2_500_000, 3_000_000, 3_500_000, 4_000_000, 4_500_000])

    def _compute(monthly_wage: float, insured_days: int, use_6plus6: int, leave_month: int) -> dict:
        if insured_days < min_insured:
            return {"monthly_allowance": 0}
        is_special = use_6plus6 >= 1 and 1 <= leave_month <= sp_max_mo
        if is_special:
            raw = monthly_wage * sp_rate
            ceiling = sp_ceils[leave_month - 1]
        else:
            raw = monthly_wage * gen_rate
            ceiling = gen_ceil
        applied = min(max(raw, gen_floor), ceiling)
        return {"monthly_allowance": applied}

    # 클램프 경계를 registry 라이브 값에서 대수적으로 역산(레지스트리 변경에도 분기 유지).
    baseline_wage = round((gen_floor + gen_ceil) / 2 / gen_rate)
    upper_wage = round((gen_ceil / gen_rate) * 1.3)
    lower_wage = round((gen_floor / gen_rate) * 0.5)
    sp_month3_wage = round((sp_ceils[2] / sp_rate) * 0.6)

    cases = [
        # (label, monthly_wage, insured_days, use_6plus6, leave_month)
        ("insured_days_below_180", baseline_wage, 150, 0, 3),
        ("general_baseline", baseline_wage, 200, 0, 3),
        ("general_upper_clamp", upper_wage, 200, 0, 3),
        ("general_lower_clamp", lower_wage, 200, 0, 3),
        ("special_6plus6_month3", sp_month3_wage, 200, 1, 3),
        ("special_to_general_month7_transition", baseline_wage, 200, 1, 7),
    ]
    examples = []
    for _label, wage, insured_days, use6, month in cases:
        inputs = {
            "monthly_wage": wage, "insured_days": insured_days,
            "use_6plus6": use6, "leave_month": month,
        }
        examples.append(_example(inputs, _compute(wage, insured_days, use6, month)))
    return _context(examples)


def _provide_car_acquisition_tax(calc: dict) -> dict:
    """SSOT: app_generator.py:1018-1071(JS). registry 미사용 — RATE_MAP이 JS 코드에
    직접 리터럴로 존재(real-estate-brokerage-fee와 동일한 유지보수 주의사항 적용)."""
    _RATE_MAP = {1: 0.07, 2: 0.04, 3: 0.04, 4: 0.05, 5: 0.02}
    _CAR_TYPE_LABEL = {1: "비영업승용", 2: "경차", 3: "영업용", 4: "승합·화물·특수", 5: "이륜차"}
    _ECO_TYPE_LABEL = {0: "일반", 1: "전기", 2: "수소"}

    def _compute(car_price: int, car_type: int, eco_type: int) -> dict | None:
        is_light = car_type == 2
        is_eco = eco_type in (1, 2)
        if is_light and is_eco:
            return None  # production JS와 동일 — 계산 불가(감면 중복 미확정)
        rate = _RATE_MAP[car_type]
        standard = round(car_price * rate)
        if is_light:
            exemption = min(standard, 750_000)
        elif is_eco:
            exemption = min(standard, 1_400_000)
        else:
            exemption = 0
        final_tax = max(0, standard - exemption)
        return {
            "standard_acquisition_tax": standard,
            "exemption_amount": exemption,
            "acquisition_tax": final_tax,
        }

    cases = [
        (1, 0, 30_000_000),   # 일반 승용, 무감면
        (2, 0, 20_000_000),   # 경차 감면(부분 — 한도 750,000 적용)
        (1, 1, 50_000_000),   # 비경차 친환경 감면(전기)
        (4, 0, 40_000_000),   # 다른 요율(승합·화물·특수) 대표
    ]
    examples = []
    for car_type, eco_type, price in cases:
        inputs = {"car_price": price, "car_type": car_type, "eco_type": eco_type}
        result = _compute(price, car_type, eco_type)
        examples.append(_example(inputs, result))

    facts = [
        {"car_type": k, "label": _CAR_TYPE_LABEL[k], "rate": v} for k, v in _RATE_MAP.items()
    ] + [
        {"eco_type": k, "label": v} for k, v in _ECO_TYPE_LABEL.items()
    ] + [
        {"constraint": "car_type=2(경차)이면서 eco_type이 1(전기) 또는 2(수소)인 조합은 "
                        "감면 중복 적용 법령 근거가 확정되지 않아 계산 자체가 제공되지 않는다"
                        "(app_generator.py 실제 production 로직 — 결과 없음/None)."}
    ]
    return _context(examples, facts)


def _provide_military_discharge_date(calc: dict) -> dict:
    """SSOT: modules/app_factory.py:786-811(_build_tier2b_app가 생성하는 JS, "Tier2-B").
    discharge_date/total_days는 오늘 날짜와 무관하게 deterministic하다. remaining_days/
    progress_pct는 실제 JS가 'today = new Date()'를 암묵적으로 참조하므로(STEP131에서
    확인된 determinism 문제), 이 provider는 reference_date를 명시적 입력으로 받아
    example_context에 함께 기록한다(암묵적 today 사용 금지)."""
    _MONTHS = {"army": 18, "marine": 18, "navy": 20, "air_force": 21, "social_service": 21}
    _NAMES = {"army": "육군", "marine": "해병대", "navy": "해군", "air_force": "공군", "social_service": "사회복무요원"}

    def _discharge(enlistment: date, branch: str) -> date:
        return enlistment + relativedelta(months=_MONTHS[branch]) - relativedelta(days=1)

    def _compute_discharge_only(enlistment: date, branch: str) -> dict:
        discharge = _discharge(enlistment, branch)
        total = (discharge - enlistment).days + 1
        return {"discharge_date": discharge.isoformat(), "total_days": total}

    def _compute_with_reference(enlistment: date, branch: str, reference_date: date) -> dict:
        discharge = _discharge(enlistment, branch)
        total = (discharge - enlistment).days + 1
        remaining = (discharge - reference_date).days
        served = min(max((reference_date - enlistment).days, 0), total)
        progress = min(max(round(served / total * 100), 0), 100)
        return {
            "discharge_date": discharge.isoformat(),
            "total_days": total,
            "remaining_days": remaining,
            "progress_pct": progress,
        }

    enlistment = date(2026, 1, 15)
    branch = "army"

    example_1 = _example(
        {"enlistment_date": enlistment.isoformat(), "branch": branch},
        _compute_discharge_only(enlistment, branch),
    )

    reference_date = date.today()
    example_2 = _example(
        {
            "enlistment_date": enlistment.isoformat(), "branch": branch,
            "reference_date": reference_date.isoformat(),
        },
        _compute_with_reference(enlistment, branch, reference_date),
    )
    example_2["_note"] = (
        "remaining_days/progress_pct는 reference_date(" + reference_date.isoformat() +
        ") 기준으로 계산됨 — production 웹앱은 조회 시점의 실제 오늘 날짜를 사용하므로 "
        "본문 생성 시점의 실제 날짜와 다르면 이 두 값만 달라질 수 있음(discharge_date/"
        "total_days는 날짜 무관 고정값)."
    )

    facts = [
        {"service": svc, "months": months, "name": _NAMES[svc]}
        for svc, months in _MONTHS.items()
    ]
    return _context([example_1, example_2], facts)


# ---------------------------------------------------------------------------
# Provider registry — 14개 active calculator와 정확히 1:1
# ---------------------------------------------------------------------------

PROVIDERS = {
    "jeonse-vs-monthly": _provide_jeonse_vs_monthly,
    "weekly-holiday-allowance": _provide_weekly_holiday_allowance,
    "annual-leave-allowance": _provide_annual_leave_allowance,
    "freelancer-tax-3p3": _provide_freelancer_tax_3p3,
    "bmi-calculator": _provide_bmi_calculator,
    "four-insurances": _provide_four_insurances,
    "annual-leave-remaining": _provide_annual_leave_remaining,
    "연말정산_환급액_계산기": _provide_yearend_tax_refund,
    "severance-pay": _provide_severance_pay,
    "unemployment-benefit": _provide_unemployment_benefit,
    "real-estate-brokerage-fee": _provide_real_estate_brokerage_fee,
    "육아휴직_급여_계산기": _provide_parental_leave_benefit,
    "자동차_취등록세_계산기": _provide_car_acquisition_tax,
    "military-discharge-date": _provide_military_discharge_date,
}


def build_example_context(calc: dict) -> dict | None:
    """calc(계산기 행 dict)에 등록된 provider가 있으면 example_context를 만들어
    반환하고, 없으면 명시적으로 None을 반환한다(암묵적 fallback 금지 — STEP127/132
    지시에 따라 'formula가 있으니 알아서 계산' 같은 자동 추론을 하지 않는다)."""
    slug = calc.get("slug", "")
    provider = PROVIDERS.get(slug)
    if provider is None:
        return None
    return provider(calc)
