# -*- coding: utf-8 -*-
"""
modules/calculator_seed.py — SalaryMate 초기 데이터 시드 (v12.0)

app_templates 5종 + calculators 5종 샘플을 Repository 경유로 등록한다.
중복(이름 기준)은 건너뛴다(멱등). gspread/Drive 직접 호출 없음.
"""
import json

from adapters.db.factory import get_db_adapter, get_template_storage_adapter
from repositories.calculator_repository import CalculatorRepository
from repositories.template_repository import TemplateRepository
from .calculator_template_engine import build_calculator_html
from .logger import get_logger

LOG = get_logger()

# ── 작업9: 앱 템플릿 5종 ───────────────────────────────────────────
APP_TEMPLATES = [
    {"template_name": "기본형", "template_type": "calculator_basic",
     "desc": "단일 입력→단일 결과 기본 계산기"},
    {"template_name": "리포트형", "template_type": "calculator_report",
     "desc": "결과 + 상세 리포트/해설 제공"},
    {"template_name": "비교형", "template_type": "calculator_compare",
     "desc": "두 조건을 비교 계산"},
    {"template_name": "위저드형", "template_type": "calculator_wizard",
     "desc": "단계별 입력 위저드"},
    {"template_name": "진단형", "template_type": "calculator_diagnosis",
     "desc": "입력 기반 진단/등급 산출"},
]

# ── 초기 계산기 7종 ───────────────────────────────────────
SAMPLE_CALCULATORS = [
    {
        "name": "주휴수당 계산기", "slug": "weekly-holiday-allowance", "category": "노무/급여",
        "calculator_type": "calculator_basic",
        "seo_title": "2026 주휴수당 계산기 | 자동 계산",
        "seo_desc": "주휴수당 지급 기준과 계산 방법을 확인하고 자동 계산기로 바로 계산하세요.",
        "formula": "주15시간 이상 근무 시 (1일 소정근로시간 × 시급)",
        "input_schema": {"hourly_wage": "number", "weekly_hours": "number"},
        "output_schema": {"weekly_allowance": "number"},
        "faq": [{"q": "주휴수당은 누구나 받나요?", "a": "주 15시간 이상 근무하고 소정근로일을 개근하면 받습니다."},
                {"q": "알바도 받을 수 있나요?", "a": "조건을 충족하면 아르바이트도 받을 수 있습니다."}],
    },
    {
        "name": "퇴직금 계산기", "slug": "severance-pay", "category": "노무/급여",
        "calculator_type": "calculator_report",
        "seo_title": "2026 퇴직금 계산기 | 입사일·퇴사일로 정확 계산",
        "seo_desc": "입사일과 퇴사일을 입력하면 퇴직금을 자동으로 계산해 드립니다. 근로기준법 기준.",
        "formula": "avg_monthly_wage * (total_days / 365)",
        "input_schema": {"avg_monthly_wage": "number", "start_date": "date", "end_date": "date"},
        "output_schema": {"severance_pay": "number"},
        "faq": [{"q": "퇴직금 지급 기준은?", "a": "계속근로 1년 이상이면 지급 대상입니다."}],
    },
    {
        "name": "연차수당 계산기", "slug": "annual-leave-allowance", "category": "노무/급여",
        "calculator_type": "calculator_basic",
        "seo_title": "2026 연차수당 계산기 | 미사용 연차 자동 계산",
        "seo_desc": "미사용 연차에 대한 연차수당을 자동으로 계산해 보세요.",
        "formula": "1일 통상임금 × 미사용 연차일수",
        "input_schema": {"daily_wage": "number", "unused_days": "number"},
        "output_schema": {"annual_leave_allowance": "number"},
        "faq": [{"q": "연차수당은 언제 받나요?", "a": "연차 사용기간 종료 후 미사용분에 대해 지급됩니다."}],
    },
    {
        "name": "실업급여 계산기", "slug": "unemployment-benefit", "category": "고용/보험",
        "calculator_type": "calculator_report",
        "seo_title": "2026 실업급여 계산기 | 수급액 자동 계산",
        "seo_desc": "평균임금과 고용기간으로 실업급여 예상 수급액을 계산해 보세요.",
        "formula": "1일 구직급여 = 이직 전 평균임금의 60% (상·하한 적용)",
        "input_schema": {"avg_daily_wage": "number", "age": "number", "employment_months": "number"},
        "output_schema": {"daily_benefit": "number", "total_benefit": "number"},
        "faq": [{"q": "실업급여 수급 조건은?", "a": "비자발적 이직 + 피보험단위기간 180일 이상 등 요건이 필요합니다."}],
    },
    {
        "name": "4대보험 계산기", "slug": "four-insurances", "category": "고용/보험",
        "calculator_type": "calculator_compare",
        "seo_title": "2026 4대보험 계산기 | 보험료 자동 계산",
        "seo_desc": "월급여 기준 국민연금·건강보험·고용보험 등 4대보험료를 자동 계산합니다.",
        "formula": "월급여 × 각 보험 요율(근로자 부담분)",
        "input_schema": {"monthly_salary": "number"},
        "output_schema": {"national_pension": "number", "health_insurance": "number",
                          "employment_insurance": "number", "total": "number"},
        "faq": [{"q": "4대보험은 의무인가요?", "a": "상시근로자는 원칙적으로 가입 의무가 있습니다."}],
    },
    {
        "name": "연말정산 환급액 계산기", "slug": "연말정산_환급액_계산기", "category": "세금/정부혜택",
        "calculator_type": "calculator_report",
        "seo_title": "2026 연말정산 환급액 계산기 | 예상 환급금 자동 계산",
        "seo_desc": "연봉·공제항목으로 연말정산 예상 환급액(또는 추가납부세액)을 자동 계산해 보세요.",
        "formula": "estimated_refund = paid_tax - income_tax_after_deduction",
        "input_schema": {"total_salary": "number", "family_count": "number", "paid_tax": "number"},
        "output_schema": {"estimated_refund": "number"},
        "faq": [
            {"q": "연말정산 환급은 언제 받나요?", "a": "다음 해 2월 급여와 함께 환급(또는 추가납부)됩니다."},
            {"q": "이 계산기 결과는 정확한가요?", "a": "참고용 예상치이며 실제 결과는 국세청 홈택스와 다를 수 있습니다."},
        ],
    },
    {
        "name": "육아휴직 급여 계산기", "slug": "육아휴직_급여_계산기", "category": "노무/급여/보험",
        "calculator_type": "calculator_report",
        "seo_title": "2026 육아휴직 급여 계산기 | 월 지급액 자동 계산",
        "seo_desc": "육아휴직 급여 월 지급액을 고용보험법 기준으로 자동 계산합니다. 6+6 특례 포함.",
        "formula": "",
        "input_schema": {"monthly_wage": "number", "insured_days": "number",
                         "use_6plus6": "boolean", "leave_month": "number"},
        "output_schema": {"monthly_allowance": "number"},
        "faq": [
            {"q": "육아휴직 급여 수급 조건은?", "a": "30일 이상 육아휴직 + 피보험단위기간 180일 이상이어야 합니다."},
            {"q": "6+6 특례란?", "a": "부모 모두 육아휴직 시 최초 6개월 급여를 상향 지원하는 제도입니다."},
        ],
    },
    {
        "name": "프리랜서 3.3% 원천징수 계산기", "slug": "freelancer-tax-3p3", "category": "세금/정부혜택",
        "calculator_type": "calculator_basic",
        "seo_title": "2026 프리랜서 3.3% 원천징수 계산기 | 실수령액 자동 계산",
        "seo_desc": "프리랜서·강사·작가 인적용역 수입의 원천징수세액(3.3%)과 실수령액을 자동 계산합니다. 소득세 3% + 지방소득세 0.3%",
        "formula": "gross_income * 0.033",
        "input_schema": {"gross_income": "number"},
        "output_schema": {"withholding_tax": "number", "net_income": "number"},
        "faq": [
            {"q": "3.3%는 어디서 나온 숫자인가요?",
             "a": "소득세법 제127조에 따른 원천징수세율 3%(소득세)에 지방소득세 0.3%를 더한 값입니다."},
            {"q": "원천징수를 하면 세금 신고를 안 해도 되나요?",
             "a": "아닙니다. 원천징수는 선납 개념이며, 이 금액은 최종 세액이 아닙니다. 매년 5월 종합소득세 신고를 통해 정산해야 합니다. 과납이면 환급, 부족이면 추가 납부합니다."},
            {"q": "125만원 미만 용역비는 원천징수가 면제된다는데 사실인가요?",
             "a": "개인에게 지급하는 인적용역비(사업소득)는 금액 무관하게 3.3% 원천징수 대상입니다. 125만원 면제 기준은 일부 기타소득에 적용되며 프리랜서 사업소득과는 다릅니다."},
            {"q": "부가가치세(VAT)는 이 계산에 포함되나요?",
             "a": "포함되지 않습니다. 부가가치세 과세 사업자라면 공급가(본 계산기 입력값)에 VAT 10%를 별도로 청구합니다. 원천징수는 VAT 제외 공급가 기준으로 계산합니다."},
            {"q": "직장인이 프리랜서 부업을 하면 어떻게 되나요?",
             "a": "근로소득과 합산하여 다음 해 5월에 종합소득세 신고를 해야 합니다. 부업 수입에서 원천징수된 3.3%는 기납부세액으로 차감됩니다."},
        ],
    },
]


def seed_templates(cfg: dict) -> int:
    repo = TemplateRepository(get_template_storage_adapter(cfg))
    existing = {str(t.get("template_name", "")).strip() for t in repo.get_all()}
    cnt = 0
    for t in APP_TEMPLATES:
        if t["template_name"] in existing:
            continue
        html = build_calculator_html(t["template_name"],
                                     {"value": "number"}, {"result": "number"})
        repo.save({
            "template_name": t["template_name"],
            "template_type": t["template_type"],
            "html_template": html,
            "seo_template": json.dumps({"desc": t["desc"]}, ensure_ascii=False),
            "faq_template": "[]",
            "status": "active",
        })
        cnt += 1
    LOG.info("app_templates 시드: %d종 등록", cnt)
    return cnt


def seed_calculators(cfg: dict) -> int:
    db = get_db_adapter(cfg)
    repo = CalculatorRepository(db)
    existing = {str(c.get("name", "")).strip() for c in repo.get_all()}
    cnt = 0
    for c in SAMPLE_CALCULATORS:
        if c["name"] in existing:
            continue
        repo.upsert_by_slug({
            "name": c["name"], "slug": c["slug"], "category": c["category"],
            "calculator_type": c["calculator_type"],
            "seo_title": c["seo_title"], "seo_desc": c["seo_desc"],
            "formula": c["formula"],
            "faq": json.dumps(c["faq"], ensure_ascii=False),
            "input_schema": json.dumps(c["input_schema"], ensure_ascii=False),
            "output_schema": json.dumps(c["output_schema"], ensure_ascii=False),
            "status": "active",
        })
        cnt += 1
    LOG.info("calculators 시드: %d종 등록", cnt)
    return cnt


def seed_all(cfg: dict) -> dict:
    return {"templates": seed_templates(cfg), "calculators": seed_calculators(cfg)}
