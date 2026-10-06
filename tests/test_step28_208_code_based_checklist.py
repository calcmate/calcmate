# -*- coding: utf-8 -*-
"""tests/test_step28_208_code_based_checklist.py — STEP 28-208

DB formula가 비어 있고 실제 계산이 modules/app_generator.py의 slug 조건부
코드 분기로 구현된 계산기(현재 자동차_취등록세_계산기)에서도 formula_accuracy/
rate_constant critical checklist가 코드 구현 근거로 생성되는지 검증한다.
DB/Registry에는 접근하지 않고 순수 dict만 사용한다(tests/test_review_center.py와
동일한 패턴).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.review_center import extract_checklist, CODE_BASED_SLUGS


def _make_app(slug="", formula=None, legal_refs=None, category="", compute_rules=None,
              input_schema=None, seo_title=None, faq=None):
    return {
        "slug": slug,
        "formula": formula or "",
        "legal_refs": legal_refs or [],
        "category": category,
        "compute_rules": compute_rules or {},
        "input_schema": input_schema or {},
        "seo_title": seo_title or "",
        "faq": faq or [],
    }


# ── A. 자동차 code-based checklist 생성 ────────────────────────────
def test_a1_formula_accuracy_generated_for_code_based_slug_with_empty_formula():
    app = _make_app(slug="자동차_취등록세_계산기", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    fa = next((i for i in items if i["id"] == "formula_accuracy"), None)
    assert fa is not None, "code-based 계산기의 formula_accuracy가 생성되지 않음"
    assert fa["severity"] == "critical"
    assert fa["auto_source"] == "code_branch_field"


def test_a2_rate_constant_generated_for_code_based_slug_with_empty_formula():
    app = _make_app(slug="자동차_취등록세_계산기", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    rc = next((i for i in items if i["id"] == "rate_constant"), None)
    assert rc is not None, "code-based 계산기의 rate_constant가 생성되지 않음"
    assert rc["severity"] == "critical"
    assert rc["auto_source"] == "code_branch_constants"


# ── B. 근거 내용 확인 ────────────────────────────────────────────
def test_b1_formula_accuracy_display_value_references_code_and_tests():
    app = _make_app(slug="자동차_취등록세_계산기", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    fa = next(i for i in items if i["id"] == "formula_accuracy")
    assert "app_generator.py" in fa["display_value"]
    assert "test_step28_193_car_tax_compute.py" in fa["display_value"]
    assert "test_car_tax_input_validation.py" in fa["display_value"]


def test_b2_rate_constant_display_value_references_rate_map_and_legal_master():
    app = _make_app(slug="자동차_취등록세_계산기", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    rc = next(i for i in items if i["id"] == "rate_constant")
    assert "RATE_MAP" in rc["display_value"]
    assert "750,000" in rc["display_value"]
    assert "1,400,000" in rc["display_value"]
    assert "local_tax_act_12" in rc["display_value"]
    assert "local_tax_special_act_67" in rc["display_value"]
    assert "local_tax_special_act_66_4" in rc["display_value"]


# ── C. 기존 formula 보유 calculator 회귀 ─────────────────────────
def test_c1_formula_based_calculator_unaffected_by_code_based_branch():
    """formula가 있는 계산기는 is_code_based 분기와 무관하게 기존 동작 그대로."""
    app = _make_app(slug="freelancer-tax-3p3", formula="gross_income * 0.033", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    fa = next(i for i in items if i["id"] == "formula_accuracy")
    assert fa["auto_source"] == "formula_field"
    assert fa["display_value"] == "gross_income * 0.033"
    rc = next(i for i in items if i["id"] == "rate_constant")
    assert rc["auto_source"] == "formula_constants"
    assert "0.033" in rc["display_value"]


# ── D. allowlist 보호 — 목록에 없는 계산기는 code-based 취급 안 됨 ──
def test_d1_empty_formula_non_allowlisted_slug_gets_no_formula_accuracy():
    app = _make_app(slug="어떤_다른_계산기", formula="", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    ids = [i["id"] for i in items]
    assert "formula_accuracy" not in ids
    assert "rate_constant" not in ids


def test_d2_empty_formula_dict_non_allowlisted_slug_gets_no_formula_accuracy():
    app = _make_app(slug="다른_슬러그", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-A", category="세금")
    ids = [i["id"] for i in items]
    assert "formula_accuracy" not in ids
    assert "rate_constant" not in ids


def test_d3_allowlist_contains_only_car_tax_currently():
    """IRP-11: 연금저축·IRP 세액공제 계산기도 slug 조건부 코드 분기로 구현되어(IRP-04)
    allowlist에 추가됨. IRP-24: irp-tax-credit-v2(신규 생성, Contract formula가
    IfExp 포함으로 거부됨)도 동일 사유로 추가됨. Loan도 custom compute이므로 추가됨.
    이 테스트는 "현재 시점 스냅샷"이 의도한 대로 자라는지 확인하는 것이지
    allowlist가 영원히 고정 크기여야 한다는 뜻이 아니다."""
    assert CODE_BASED_SLUGS == frozenset({
        "자동차_취등록세_계산기", "연금저축_irp_세액공제_계산기", "irp-tax-credit-v2",
        "loan-repayment-calculator",
    })


# ── E. 날짜 기반(is_date_based) 계산기 보호 ──────────────────────
def test_e1_date_based_code_based_slug_still_excluded():
    """Tier2-B(날짜 기반)이면 code-based allowlist에 있어도 formula_accuracy를 생성하지 않는다."""
    app = _make_app(slug="자동차_취등록세_계산기", formula="{}", category="세금")
    items = extract_checklist(app, tier="Tier2-B", category="세금")
    ids = [i["id"] for i in items]
    assert "formula_accuracy" not in ids
    assert "rate_constant" not in ids
