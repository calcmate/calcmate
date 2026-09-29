# -*- coding: utf-8 -*-
"""tests/test_review_center.py — Phase3-3 검토센터 핵심 로직 테스트

검증 범위:
  - extract_checklist(): 규칙 기반 항목 추출 (D-2 카테고리 로직 포함)
  - detect_tier2b_keywords(): Tier2-B 키워드 감지
  - check_slug_conflict(): slug 중복 감지
  - pre_build_qa(): 6단계 QA (결함 있는 계산기로 실패 감지)
  - promote_to_ready() 체크리스트 검증 (미완료 시 차단)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules.review_center import extract_checklist, detect_tier2b_keywords, CRITICAL_CATEGORIES


# ─────────────────────────────────────────────────────────────
# 1. extract_checklist — 항목 추출 로직
# ─────────────────────────────────────────────────────────────

def _make_app(formula=None, legal_refs=None, category="", compute_rules=None,
              input_schema=None, seo_title=None, faq=None):
    return {
        "formula": formula or "",
        "legal_refs": legal_refs or [],
        "category": category,
        "compute_rules": compute_rules or {},
        "input_schema": input_schema or {},
        "seo_title": seo_title or "",
        "faq": faq or [],
    }


def test_formula_accuracy_extracted_for_tier2a():
    """Tier2-A + formula 있으면 formula_accuracy 항목 추출."""
    app = _make_app(formula="gross * 0.033")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]
    assert "formula_accuracy" in ids, f"formula_accuracy 누락. 항목: {ids}"


def test_formula_accuracy_not_extracted_for_tier2b():
    """Tier2-B에서는 formula_accuracy 항목을 추출하지 않음."""
    app = _make_app(formula="days * rate", input_schema={"start_date": {"type": "date"}})
    items = extract_checklist(app, tier="Tier2-B", category="병역/공무")
    ids = [i["id"] for i in items]
    assert "formula_accuracy" not in ids, "Tier2-B에서 formula_accuracy 추출됨 (오류)"


def test_legal_basis_critical_for_critical_category():
    """법령 카테고리 계산기에서 legal_basis는 🔴 필수."""
    for cat in ["세금/세법", "노동/고용법", "복지/사회보험", "병역/공무", "세금/정부혜택"]:
        app = _make_app(formula="a * b", category=cat)
        items = extract_checklist(app, tier="Tier2-A", category=cat)
        lb = next((i for i in items if i["id"] == "legal_basis"), None)
        assert lb is not None, f"legal_basis 없음 (category={cat})"
        assert lb["severity"] == "critical", f"severity가 critical이 아님 (category={cat}): {lb['severity']}"


def test_legal_basis_advisory_for_noncritical_category():
    """순수 산술/부동산 카테고리에서 legal_basis는 🟡 권장."""
    app = _make_app(formula="a * b", category="부동산/임대")
    items = extract_checklist(app, tier="Tier2-A", category="부동산/임대")
    lb = next((i for i in items if i["id"] == "legal_basis"), None)
    assert lb is not None, "legal_basis 없음"
    assert lb["severity"] == "advisory", f"severity가 advisory가 아님: {lb['severity']}"


def test_legal_basis_critical_when_no_category():
    """카테고리 미지정(None/빈문자열)이면 legal_basis는 보수적으로 🔴 필수."""
    for cat in ["", None]:
        app = _make_app(formula="a * b", category=cat or "")
        items = extract_checklist(app, tier="Tier2-A", category=cat or "")
        lb = next((i for i in items if i["id"] == "legal_basis"), None)
        assert lb is not None
        assert lb["severity"] == "critical", f"빈 카테고리에서 critical이 아님: {lb['severity']}"


def test_legal_refs_empty_shows_warning():
    """legal_refs 미입력 시 display_value에 경고 표시."""
    app = _make_app(formula="a * b", legal_refs=[], category="세금/세법")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    lb = next((i for i in items if i["id"] == "legal_basis"), None)
    assert lb is not None
    assert "미입력" in lb["display_value"] or "⚠️" in lb["display_value"], \
        f"경고 표시 없음: {lb['display_value']}"


def test_legal_refs_present_shows_refs():
    """legal_refs 있을 시 display_value에 ref 값 표시."""
    app = _make_app(formula="a * b", legal_refs=["소득세법 제127조"], category="세금/세법")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    lb = next((i for i in items if i["id"] == "legal_basis"), None)
    assert lb is not None
    assert "소득세법" in lb["display_value"], f"법령 내용 미표시: {lb['display_value']}"


def test_rate_constant_extracted_for_decimal_in_formula():
    """공식에 소수점 상수가 있으면 rate_constant 추출."""
    app = _make_app(formula="income * 0.033", category="세금/세법")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]
    assert "rate_constant" in ids, "rate_constant 누락"
    rc = next(i for i in items if i["id"] == "rate_constant")
    assert "0.033" in rc["display_value"], f"상수 미표시: {rc['display_value']}"


def test_no_rate_constant_for_integer_only_formula():
    """소수점 없는 정수만 있는 공식은 rate_constant 추출 안 함."""
    app = _make_app(formula="a * 100 / 12", category="세금/세법")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]
    assert "rate_constant" not in ids, "정수만 있는데 rate_constant 추출됨"


def test_base_year_only_for_critical_category():
    """🔴 카테고리만 base_year 추출, 🟡 카테고리는 추출 안 함."""
    # 🔴 카테고리
    app_crit = _make_app(formula="a * b", category="노동/고용법")
    items_crit = extract_checklist(app_crit, tier="Tier2-A", category="노동/고용법")
    assert "base_year" in [i["id"] for i in items_crit], "🔴 카테고리에서 base_year 누락"
    # 🟡 카테고리
    app_adv = _make_app(formula="a * b", category="부동산/임대")
    items_adv = extract_checklist(app_adv, tier="Tier2-A", category="부동산/임대")
    assert "base_year" not in [i["id"] for i in items_adv], "🟡 카테고리에서 base_year 추출됨"


def test_default_values_extracted_when_present():
    """input_schema에 default 있으면 default_values 추출."""
    app = _make_app(input_schema={"rate": {"type": "number", "default": 4.75}},
                    formula="a * b", category="부동산/임대")
    items = extract_checklist(app, tier="Tier2-A", category="부동산/임대")
    ids = [i["id"] for i in items]
    assert "default_values" in ids, "default_values 누락"


def test_seo_faq_advisory():
    """seo_title/faq가 있으면 🟡 권장 항목으로 추출."""
    app = _make_app(formula="a * b", seo_title="테스트 계산기",
                    faq=[{"q": "Q1", "a": "A1"}], category="부동산/임대")
    items = extract_checklist(app, tier="Tier2-A", category="부동산/임대")
    adv_ids = [i["id"] for i in items if i.get("severity") == "advisory"]
    assert "seo_title" in adv_ids, "seo_title advisory 항목 누락"
    assert "faq_content" in adv_ids, "faq_content advisory 항목 누락"


def test_all_items_unchecked_by_default():
    """추출된 모든 항목은 초기에 checked=False."""
    app = _make_app(formula="income * 0.033", legal_refs=[], category="세금/세법",
                    seo_title="테스트", faq=[{"q": "Q", "a": "A"}])
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    assert items, "항목이 없음"
    for item in items:
        assert not item["checked"], f"'{item['id']}' 항목이 초기에 checked=True"
        assert item["checked_by"] is None
        assert item["checked_at"] is None


# ─────────────────────────────────────────────────────────────
# 1-b. formula_cap 항목 추출 (HOLD-3 수정 연동)
# ─────────────────────────────────────────────────────────────

def test_formula_cap_extracted_when_min_max_present():
    """formula에 min()/max()가 있으면 formula_cap 🔴 항목 추출."""
    app = _make_app(
        formula="15 + min(max(0, (years_of_service - 1) // 2), 10)",
        category="노동/고용법",
        input_schema={"years_of_service": {"type": "number"}},
    )
    items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
    ids = [i["id"] for i in items]
    assert "formula_cap" in ids, f"formula_cap 누락. 항목: {ids}"
    cap = next(i for i in items if i["id"] == "formula_cap")
    assert cap["severity"] == "critical", f"formula_cap이 critical이 아님: {cap['severity']}"
    assert "min" in cap["display_value"] or "max" in cap["display_value"], \
        f"display_value에 cap 함수 미표시: {cap['display_value']}"
    # display_value에 실제 formula 문자열 포함 확인
    assert "years_of_service" in cap["display_value"], "display_value에 formula 미포함"


def test_formula_cap_not_extracted_when_no_cap_function():
    """min()/max() 없는 formula에서는 formula_cap 미발생."""
    app = _make_app(formula="income * 0.033", category="세금/세법")
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]
    assert "formula_cap" not in ids, "min/max 없는데 formula_cap 추출됨"


def test_formula_cap_not_extracted_for_date_based():
    """date_based 계산기에서는 formula_cap 미발생."""
    app = _make_app(formula="min(a, b)", category="노동/고용법")
    app["compute_type"] = "date_based"
    items = extract_checklist(app, tier="Tier2-B", category="노동/고용법")
    ids = [i["id"] for i in items]
    assert "formula_cap" not in ids, "date_based에서 formula_cap 추출됨"


def test_formula_cap_and_legal_basis_are_independent():
    """formula_cap과 legal_basis는 독립적으로 각각 추출되어야 한다."""
    app = _make_app(
        formula="15 + min(max(0, (years_of_service - 1) // 2), 10)",
        category="노동/고용법",
        legal_refs=["근로기준법 제60조"],
        input_schema={"years_of_service": {"type": "number"}},
    )
    items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
    ids = [i["id"] for i in items]
    assert "formula_cap" in ids, "formula_cap 누락"
    assert "legal_basis" in ids, "legal_basis 누락"
    # 각각 checked=False로 독립 초기화
    cap = next(i for i in items if i["id"] == "formula_cap")
    lb = next(i for i in items if i["id"] == "legal_basis")
    assert not cap["checked"], "formula_cap이 checked=True로 초기화됨"
    assert not lb["checked"], "legal_basis가 checked=True로 초기화됨"


def test_formula_cap_with_dict_formula():
    """dict formula에서도 min()/max() 감지 및 formula_cap 추출."""
    import json
    app = _make_app(category="노동/고용법")
    app["formula"] = json.dumps({
        "total_days": "15 + min(max(0, (years_of_service - 1) // 2), 10)",
        "remaining_days": "15 + min(max(0, (years_of_service - 1) // 2), 10) - used_days",
    })
    app["input_schema"] = {"years_of_service": {"type": "number"}, "used_days": {"type": "number"}}
    items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
    ids = [i["id"] for i in items]
    assert "formula_cap" in ids, f"dict formula에서 formula_cap 누락. 항목: {ids}"


# ─────────────────────────────────────────────────────────────
# 2. detect_tier2b_keywords
# ─────────────────────────────────────────────────────────────

def test_detect_tier2b_keywords_positive():
    """날짜 키워드 포함 시 True."""
    assert detect_tier2b_keywords("군인 전역일 계산기"), "전역일 감지 실패"
    assert detect_tier2b_keywords("D-Day 계산기"), "d-day 감지 실패"
    assert detect_tier2b_keywords("복무 기간 계산"), "기간 감지 실패"


def test_detect_tier2b_keywords_negative():
    """일반 계산기 이름에서 False."""
    assert not detect_tier2b_keywords("원천징수 계산기"), "원천징수에서 오탐"
    assert not detect_tier2b_keywords("퇴직금 계산기"), "퇴직금에서 오탐"
    assert not detect_tier2b_keywords("전세 vs 월세 비교"), "전세vs월세에서 오탐"


# ─────────────────────────────────────────────────────────────
# 3. check_slug_conflict — 기존 9개 계산기 slug와 충돌 감지
# ─────────────────────────────────────────────────────────────

def test_slug_conflict_with_existing_registry():
    """기존 9개 계산기 slug와 충돌 시 True 반환."""
    from modules.config_loader import load_config
    cfg = load_config()
    from modules.review_center import check_slug_conflict
    # 기존 계산기 slug
    for known_slug in ["severance-pay", "freelancer-tax-3p3", "jeonse-vs-monthly"]:
        _, conflict, msg = check_slug_conflict(known_slug, cfg)
        assert conflict, f"'{known_slug}' 중복 감지 실패"
        assert known_slug in msg, f"에러 메시지에 slug 없음: {msg}"


def test_slug_no_conflict_for_new():
    """새 slug는 충돌 없음."""
    from modules.config_loader import load_config
    cfg = load_config()
    from modules.review_center import check_slug_conflict
    _, conflict, _ = check_slug_conflict("this-slug-does-not-exist-xyz-999", cfg)
    assert not conflict, "존재하지 않는 slug가 충돌로 감지됨"


# ─────────────────────────────────────────────────────────────
# 4. pre_build_qa — 결함 있는 계산기로 실패 감지
# ─────────────────────────────────────────────────────────────

def test_pre_build_qa_step1_fails_when_no_input_schema():
    """input_schema 없으면 Step 1 실패."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa
    cfg = load_config()
    bad_calc = {"slug": "test-bad", "input_schema": {}, "output_schema": {"result": {}}, "formula": "1+1"}
    results = pre_build_qa(bad_calc, cfg)
    step1 = next(r for r in results if r["step"] == 1)
    assert not step1["passed"], "input_schema 없는데 Step 1 통과"


def test_pre_build_qa_step2_fails_when_no_output_schema():
    """output_schema 없으면 Step 2 실패."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa
    cfg = load_config()
    bad_calc = {
        "slug": "test-bad",
        "input_schema": {"a": {"type": "number"}},
        "output_schema": {},
        "formula": "a * 2",
    }
    results = pre_build_qa(bad_calc, cfg)
    step2 = next(r for r in results if r["step"] == 2)
    assert not step2["passed"], "output_schema 없는데 Step 2 통과"


def test_pre_build_qa_jeonse_all_pass():
    """jeonse-vs-monthly: 기존 정상 계산기로 6단계 전체 통과."""
    from modules.config_loader import load_config
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules.review_center import pre_build_qa
    cfg = load_config()
    calcs = {c["slug"]: c for c in CalculatorRepository(get_db_adapter(cfg)).get_all()}
    jeonse = calcs.get("jeonse-vs-monthly")
    if jeonse is None:
        return  # DB에 없으면 스킵
    results = pre_build_qa(jeonse, cfg)
    failed = [r for r in results if not r["passed"] and not r["skipped"]]
    assert not failed, f"jeonse-vs-monthly QA 실패: {[(r['step'], r['detail']) for r in failed]}"


def test_pre_build_qa_date_based_skips_steps_345():
    """date_based 계산기는 Step 3~5가 skip (D-4)."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa
    cfg = load_config()
    date_calc = {
        "slug": "test-date",
        "compute_type": "date_based",
        "input_schema": {"start_date": {"type": "date"}},
        "output_schema": {"end_date": {"label": "종료일"}},
        "formula": "",
    }
    results = pre_build_qa(date_calc, cfg)
    for step_num in [3, 4, 5]:
        step = next(r for r in results if r["step"] == step_num)
        assert step["skipped"], f"date_based에서 Step {step_num}이 skip되지 않음"


# ─────────────────────────────────────────────────────────────
# 4-1. IRP-27 — pre_build_qa Step 6 CODE_BASED_SLUGS 오탐 제거
#
# IRP-26 진단: CODE_BASED_SLUGS(실제 계산이 DB formula가 아니라 _compute_js()의
# slug 조건부 분기로 수행되는 계산기)는 Step 6이 DB formula를 execute_formula()로
# 직접 실행하려다 formula가 비어있으면(falsy) 오탐 FAIL, stale-but-실행가능한
# formula가 남아있으면 틀린 값으로도 우연히 PASS — 어느 쪽도 실제 계산 정확성과
# 무관했다. IRP-27에서 is_date_based와 동일한 방식으로 skip 처리했다.
# ─────────────────────────────────────────────────────────────

def test_a_code_based_slug_step6_skipped_not_executed():
    """Test A — CODE_BASED_SLUGS 대상(자동차_취등록세_계산기, 실제 DB formula={})은
    Step 6이 execute_formula()를 호출하지 않고 skip되어야 하며, 이 때문에
    qa_ok=False가 되는 오탐이 발생하지 않아야 한다."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa, CODE_BASED_SLUGS
    cfg = load_config()
    assert "자동차_취등록세_계산기" in CODE_BASED_SLUGS, "이 테스트의 전제(allowlist 등록)가 깨짐"

    car_calc = {
        "slug": "자동차_취등록세_계산기",
        "input_schema": {
            "car_price": "number",
            "car_type": "select:1=비영업승용,2=경차,3=영업용,4=승합·화물·특수,5=이륜차",
            "eco_type": "select:0=일반,1=전기,2=수소",
        },
        "output_schema": {
            "acquisition_tax": "number", "standard_acquisition_tax": "number",
            "exemption_amount": "number",
        },
        "formula": "{}",   # 실제 DB 상태와 동일(코드 분기가 계산 권위, formula는 비어있음)
    }
    results = pre_build_qa(car_calc, cfg)
    step6 = next(r for r in results if r["step"] == 6)
    assert step6["skipped"] is True, f"CODE_BASED_SLUGS인데 Step 6이 skip되지 않음: {step6}"
    assert step6["passed"] is True, f"skip된 Step 6은 passed=True여야 함: {step6}"
    assert "execute_formula" not in step6["detail"], "Step 6 detail에 execute_formula 실행 흔적이 남음"
    assert "계산 결과 이상" not in step6["detail"], (
        f"IRP-26에서 확인된 옛 오탐('계산 결과 이상: {{}}')이 재발함: {step6}")

    # qa_ok 전체가 아니라 "Step 6이 원인인 실패가 없는지"만 정확히 확인한다 —
    # Step 10(FAQ/본문 금칙 문구)은 이 계산기의 실제 Registry forbidden_phrases와
    # 관련된 별개 항목이라 IRP-27(Formula Gate 오탐 제거) 범위 밖이다.
    other_failures = [r for r in results if r["step"] != 6 and not (r["passed"] or r["skipped"])]
    if other_failures:
        assert all(r["step"] != 6 for r in other_failures)


def test_b_normal_formula_calculator_step6_still_executes():
    """Test B — CODE_BASED_SLUGS에 없는 일반 formula 계산기는 기존처럼 Step 6이
    execute_formula()를 실제로 호출해 검증해야 한다(skip되면 안 됨)."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa, CODE_BASED_SLUGS
    cfg = load_config()
    normal_calc = {
        "slug": "test-normal-formula-calc",
        "input_schema": {"a": {"type": "number"}, "b": {"type": "number"}},
        "output_schema": {"total": {"label": "합계"}},
        "formula": {"total": "a + b"},
    }
    assert normal_calc["slug"] not in CODE_BASED_SLUGS
    results = pre_build_qa(normal_calc, cfg)
    step6 = next(r for r in results if r["step"] == 6)
    assert step6["skipped"] is False, f"일반 formula 계산기인데 Step 6이 skip됨: {step6}"
    assert step6["passed"], f"정상 formula(a+b)인데 Step 6 실패: {step6}"
    assert "계산 성공" in step6["detail"]


def test_c_date_based_step6_skip_unaffected_by_irp27():
    """Test C — 날짜형 계산기는 IRP-27 이후에도 기존과 동일하게 Step 6이 skip되어야
    한다(is_date_based 조건은 변경하지 않음, OR로만 조건 추가됐으므로 회귀 없어야 함)."""
    from modules.config_loader import load_config
    from modules.review_center import pre_build_qa
    cfg = load_config()
    date_calc = {
        "slug": "test-date",
        "compute_type": "date_based",
        "input_schema": {"start_date": {"type": "date"}},
        "output_schema": {"end_date": {"label": "종료일"}},
        "formula": "",
    }
    results = pre_build_qa(date_calc, cfg)
    step6 = next(r for r in results if r["step"] == 6)
    assert step6["skipped"] is True, f"날짜형 계산기의 Step 6 skip이 회귀됨: {step6}"
    assert step6["passed"] is True


# ─────────────────────────────────────────────────────────────
# 5. promote_to_ready 체크리스트 검증
# ─────────────────────────────────────────────────────────────

def test_promote_to_ready_blocks_when_checklist_incomplete():
    """
    체크리스트 미완료 계산기에 대해 promote_to_ready()가 실패를 반환하는지.
    Registry v3에 HOLD + 미완료 checklist가 있는 경우를 mocking으로 검증.
    """
    from modules.app_factory import promote_to_ready
    from unittest.mock import patch

    mock_v3 = {
        "test-hold-calc": {
            "source": "app_factory",
            "status": "HOLD",
            "category": "세금/세법",
            "review_checklist": [
                {"id": "formula_accuracy", "severity": "critical", "label": "계산 공식", "checked": False},
                {"id": "legal_basis", "severity": "critical", "label": "법적 근거", "checked": True},
            ],
        }
    }

    with patch("modules.registry_loader.load_registry_v3", return_value=mock_v3):
        ok, msg = promote_to_ready("test-hold-calc")
    assert not ok, "미완료 체크리스트인데 promote 성공"
    assert "미완료" in msg or "필수" in msg, f"에러 메시지 부적절: {msg}"


# ── CA-2-6-1: check_hold_rules() HOLD-1 pending_validation 테스트 ────────────

from modules.app_factory import build_contract as _af_build_contract
from modules.app_factory import check_hold_rules as _af_check_hold_rules


def test_hold1_fires_for_pending_validation(monkeypatch):
    """formula_status='pending_validation' → HOLD-1 발동 (미확정 상태)."""
    monkeypatch.setattr(
        "modules.registry_loader.load_legal_master",
        lambda: {},
    )
    contract = _af_build_contract("x", "X", formula="a + b")
    assert contract["formula_status"] == "pending_validation"
    result = _af_check_hold_rules(contract)
    assert result["held"] is True
    assert "HOLD-1" in result["rules"]


def test_hold1_silent_for_operator_confirmed(monkeypatch):
    """formula_status='operator_confirmed' → HOLD-1 발동 안 됨."""
    monkeypatch.setattr(
        "modules.registry_loader.load_legal_master",
        lambda: {},
    )
    contract = _af_build_contract(
        "x", "X", formula="a + b", formula_status="operator_confirmed"
    )
    result = _af_check_hold_rules(contract)
    assert "HOLD-1" not in result["rules"]


# ─────────────────────────────────────────────────────────────
# 6. STEP 15-H — HTML 입력 필드 ↔ JS 입력 키 일치 검사
# ─────────────────────────────────────────────────────────────
from modules.review_center import _html_js_input_consistency, _faq_forbidden_phrase_check


def _html_input(field: str) -> str:
    return f'<input class="sm-input" id="in_{field}" name="in_{field}">'


def _js_read_line(field: str) -> str:
    return f'  var {field} = inputs["{field}"] || 0;\n'


def test_html_js_consistency_pass_when_keys_match():
    html = _html_input("months_of_service") + _html_input("used_days")
    js = _js_read_line("months_of_service") + _js_read_line("used_days")
    passed, detail = _html_js_input_consistency(html, js)
    assert passed is True
    assert "months_of_service" in detail


def test_html_js_consistency_fail_on_field_name_mismatch():
    """STEP 15-E 사고 재현: HTML=years_of_service, JS=months_of_service."""
    html = _html_input("years_of_service") + _html_input("used_days")
    js = _js_read_line("months_of_service") + _js_read_line("used_days")
    passed, detail = _html_js_input_consistency(html, js)
    assert passed is False
    assert "years_of_service" in detail
    assert "months_of_service" in detail


def test_html_js_consistency_fail_when_js_reads_extra_field():
    html = _html_input("months_of_service") + _html_input("used_days")
    js = (_js_read_line("months_of_service") + _js_read_line("used_days")
          + _js_read_line("nonexistent_field"))
    passed, detail = _html_js_input_consistency(html, js)
    assert passed is False
    assert "nonexistent_field" in detail


def test_html_js_consistency_ignores_output_fields():
    """id="out_*"(출력 표시용)는 in_* 정규식에 안 걸려 false positive 없음."""
    html = (_html_input("months_of_service") + _html_input("used_days")
            + '<span id="out_total_days"></span><span id="out_remaining_days"></span>')
    js = _js_read_line("months_of_service") + _js_read_line("used_days")
    passed, detail = _html_js_input_consistency(html, js)
    assert passed is True


# ─────────────────────────────────────────────────────────────
# 7. STEP 15-H — FAQ/본문 금칙 문구 검사
# ─────────────────────────────────────────────────────────────

def test_faq_forbidden_phrase_none_registered_skips(monkeypatch):
    monkeypatch.setattr("modules.registry_loader.load_registry", lambda: {})
    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda: {})
    monkeypatch.setattr("modules.registry_loader.load_legal_master", lambda: {})
    (passed, skipped), detail = _faq_forbidden_phrase_check({"slug": "no-such-calc"}, "<p>안녕</p>")
    assert passed is True and skipped is True


def test_faq_forbidden_phrase_detected_via_old_registry(monkeypatch):
    monkeypatch.setattr(
        "modules.registry_loader.load_registry",
        lambda: {"unemployment-benefit": {"forbidden_phrases": ["받을 수 있습니다"]}},
    )
    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda: {})
    monkeypatch.setattr("modules.registry_loader.load_legal_master", lambda: {})
    (passed, skipped), detail = _faq_forbidden_phrase_check(
        {"slug": "unemployment-benefit"}, "<p>실업급여를 받을 수 있습니다.</p>"
    )
    assert passed is False and skipped is False
    assert "받을 수 있습니다" in detail


def test_faq_forbidden_phrase_passes_when_absent(monkeypatch):
    monkeypatch.setattr(
        "modules.registry_loader.load_registry",
        lambda: {"unemployment-benefit": {"forbidden_phrases": ["받을 수 있습니다"]}},
    )
    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda: {})
    monkeypatch.setattr("modules.registry_loader.load_legal_master", lambda: {})
    (passed, skipped), detail = _faq_forbidden_phrase_check(
        {"slug": "unemployment-benefit"}, "<p>수급 요건 충족 시 지급됩니다.</p>"
    )
    assert passed is True and skipped is False


def test_faq_forbidden_phrase_via_v3_legal_refs(monkeypatch):
    """v3 registry(legal_refs) → legal_master 엔티티 경유 금칙 문구 탐지."""
    monkeypatch.setattr("modules.registry_loader.load_registry", lambda: {})
    monkeypatch.setattr(
        "modules.registry_loader.load_registry_v3",
        lambda: {"annual-leave-remaining": {"legal_refs": ["labor_standards_act_60"]}},
    )
    monkeypatch.setattr(
        "modules.registry_loader.load_legal_master",
        lambda: {"labor_standards_act_60": {
            "forbidden_phrases": ["법정 연차가 부여되지 않으나"]
        }},
    )
    (passed, skipped), detail = _faq_forbidden_phrase_check(
        {"slug": "annual-leave-remaining"},
        "<p>근속 1년 미만의 경우 법정 연차가 부여되지 않으나 회사 정책에 따릅니다.</p>",
    )
    assert passed is False and skipped is False
    assert "법정 연차가 부여되지 않으나" in detail


# ─────────────────────────────────────────────────────────────
# 7-1. IRP-29 — 자동차_취등록세_계산기 forbidden_phrases 최소 수정 검증
#
# IRP-28 진단: docs/legal_master/tax.yaml의 local_tax_act_12.forbidden_phrases가
# 단어 1개("등록세")라 계산기 자신의 정상 서비스명("취등록세")과 legal_master
# 자신의 reviewer_expectation이 요구하는 올바른 부정 설명("등록세라는 별도 세목이
# 존재하지 않는다")까지 걸러내는 과잉 차단이었다. IRP-29에서 문장형 2개
# ("등록세를 별도로 납부"/"등록세가 별도로 부과")로 교체했다 — 아래는 실제
# Registry(mock 아님)를 그대로 읽어 검증한다.
# ─────────────────────────────────────────────────────────────

def _car_tax_forbidden_check(html_fragment: str):
    from modules.registry_loader import invalidate
    invalidate()   # 이번 STEP에서 방금 수정한 legal_master 파일을 캐시 없이 새로 읽음
    return _faq_forbidden_phrase_check({"slug": "자동차_취등록세_계산기"}, html_fragment)


def test_a_car_tax_normal_service_name_not_blocked():
    """Test A — 정상 서비스명 '자동차 취등록세 계산기'는 forbidden phrase에 걸리지 않아야 한다."""
    (passed, skipped), detail = _car_tax_forbidden_check("<h1>자동차 취등록세 계산기</h1>")
    assert passed is True and skipped is False, f"정상 서비스명이 오탐 차단됨: {detail}"


def test_b_car_tax_correct_negation_explanation_not_blocked():
    """Test B — '등록세는 더 이상 별도 세목이 아니다'라는 법적으로 올바른 설명은
    forbidden phrase에 걸리지 않아야 한다(legal_master 자신의 reviewer_expectation이
    요구하는 문구)."""
    for html in (
        "<p>등록세는 왜 별도로 계산하지 않나요? 현재는 등록세라는 별도의 세목이 존재하지 않습니다.</p>",
        "<p>취득세와 등록세가 취득세로 통합되었습니다.</p>",
    ):
        (passed, skipped), detail = _car_tax_forbidden_check(html)
        assert passed is True and skipped is False, f"올바른 부정 설명이 오탐 차단됨: {html!r} → {detail}"


def test_c_car_tax_wrong_separate_payment_claim_is_blocked():
    """Test C — '등록세를 별도로 납부해야 한다'는 폐기된 법령을 전제한 잘못된 주장은
    반드시 차단돼야 한다(forbidden phrase의 실제 목적)."""
    (passed, skipped), detail = _car_tax_forbidden_check("<p>등록세를 별도로 납부해야 합니다.</p>")
    assert passed is False and skipped is False
    assert "등록세를 별도로 납부" in detail

    (passed2, skipped2), detail2 = _car_tax_forbidden_check("<p>등록세가 별도로 부과됩니다.</p>")
    assert passed2 is False and skipped2 is False
    assert "등록세가 별도로 부과" in detail2


# ─────────────────────────────────────────────────────────────
# 7. STEP 28-129 — input_validation_review 체크리스트 항목
# ─────────────────────────────────────────────────────────────

def test_input_validation_review_present_without_compute_rules():
    """compute_rules 없음(app dict에 키 자체가 없음) → input_validation_review가
    반드시 생성되고, 검증 규칙 없음을 나타내는 문구를 표시해야 한다."""
    app = {
        "formula": "gross * 0.033", "legal_refs": [], "category": "세금/세법",
        "input_schema": {}, "seo_title": "", "faq": [],
    }
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ivr = next((i for i in items if i["id"] == "input_validation_review"), None)
    assert ivr is not None, "input_validation_review 누락"
    assert ivr["severity"] == "critical"
    assert ivr["checked"] is False
    assert ivr["label"] == "입력값 검증 정책 확인"
    assert "설정된 입력값 검증 규칙 없음" in ivr["display_value"]


def test_input_validation_review_present_with_empty_dict_compute_rules():
    """compute_rules = {} (빈 dict)도 '없음'과 동일하게 취급되어야 한다."""
    app = _make_app(formula="a * b", compute_rules={})
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ivr = next((i for i in items if i["id"] == "input_validation_review"), None)
    assert ivr is not None
    assert "설정된 입력값 검증 규칙 없음" in ivr["display_value"]


def test_input_validation_review_present_with_compute_rules():
    """compute_rules가 있으면 input_validation_review와 edge_cases가 모두 존재하고,
    서로 다른 ID를 가지며, edge_cases의 기존 동작이 그대로 유지되어야 한다."""
    app = _make_app(formula="car_price * 0.07",
                     compute_rules={"non_negative_inputs": ["car_price"]})
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]

    assert "input_validation_review" in ids
    assert "edge_cases" in ids
    assert ids.count("input_validation_review") == 1
    assert ids.count("edge_cases") == 1

    ivr = next(i for i in items if i["id"] == "input_validation_review")
    assert ivr["severity"] == "critical"
    assert "non_negative_inputs" in ivr["display_value"]

    # edge_cases 기존 동작(회귀) — display_value/auto_source/severity 불변
    ec = next(i for i in items if i["id"] == "edge_cases")
    assert ec["severity"] == "critical"
    assert ec["auto_source"] == "compute_rules"
    assert ec["display_value"] == str({"non_negative_inputs": ["car_price"]})[:300]


def test_input_validation_review_id_distinct_from_edge_cases():
    """두 항목의 ID가 절대 같아지지 않아야 한다(설계 요구사항)."""
    app = _make_app(formula="a * b", compute_rules={"positive_inputs": ["a"]})
    items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
    ids = [i["id"] for i in items]
    assert "input_validation_review" != "edge_cases"
    assert ids.count("input_validation_review") == 1
    assert ids.count("edge_cases") == 1


# ─────────────────────────────────────────────────────────────
# 8. STEP 28-129 — promote_to_ready() READY Gate 정책 (실제 checklist 데이터 사용,
#    파일 I/O만 tmp_path로 격리 — Gate 판정 로직 자체는 mock하지 않는다)
# ─────────────────────────────────────────────────────────────

def _write_af_yaml(reg_dir, yaml_name, slug, entry):
    import yaml as _yaml
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / f"{yaml_name}.yaml").write_text(
        _yaml.dump({slug: entry}, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_promote_to_ready_blocks_when_input_validation_review_unchecked(tmp_path, monkeypatch):
    """compute_rules 없음 + input_validation_review 미체크 → READY 차단.
    실제 promote_to_ready() 코드 경로를 그대로 실행하되, 레지스트리 파일 위치만
    tmp_path로 격리해 실제 docs/registry/*.yaml에는 어떤 쓰기도 발생하지 않는다."""
    from modules import app_factory as AF

    entry = {
        "source": "app_factory", "status": "HOLD", "category": "세금/세법",
        "review_checklist": [
            {"id": "formula_accuracy", "severity": "critical", "label": "계산 공식", "checked": True},
            {"id": "input_validation_review", "severity": "critical",
             "label": "입력값 검증 정책 확인", "checked": False},
        ],
    }
    _write_af_yaml(tmp_path, "labor_af", "diag-ready-test-1", entry)

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=False: {"diag-ready-test-1": entry})
    monkeypatch.setattr(AF, "_REG_DIR", tmp_path)

    ok, msg = AF.promote_to_ready("diag-ready-test-1")
    assert not ok, "input_validation_review 미체크인데 READY 승격됨"
    assert "입력값 검증 정책 확인" in msg or "필수" in msg


def test_promote_to_ready_succeeds_when_input_validation_review_checked(tmp_path, monkeypatch):
    """compute_rules 없음 + input_validation_review 체크 완료 + 다른 critical 없음
    → READY 가능. 다른 critical 항목이 전혀 없는 최소 fixture 사용."""
    from modules import app_factory as AF

    entry = {
        "source": "app_factory", "status": "HOLD", "category": "세금/세법",
        "review_checklist": [
            {"id": "input_validation_review", "severity": "critical",
             "label": "입력값 검증 정책 확인", "checked": True},
        ],
    }
    _write_af_yaml(tmp_path, "labor_af", "diag-ready-test-2", entry)

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=False: {"diag-ready-test-2": entry})
    monkeypatch.setattr(AF, "_REG_DIR", tmp_path)
    monkeypatch.setattr("modules.registry_loader.invalidate", lambda: None)

    ok, msg = AF.promote_to_ready("diag-ready-test-2")
    assert ok, f"input_validation_review 체크 완료인데 READY 승격 실패: {msg}"

    # 실제 파일도 tmp_path 안에서만 갱신되었는지 확인(레포 파일 무변경 보장의 이중 확인)
    written = (tmp_path / "labor_af.yaml").read_text(encoding="utf-8")
    assert "status: READY" in written


def test_promote_to_ready_blocks_when_edge_cases_unchecked_even_if_ivr_checked(tmp_path, monkeypatch):
    """compute_rules 있음 + input_validation_review 체크 + edge_cases 미체크
    → 여전히 READY 차단(edge_cases도 critical이므로)."""
    from modules import app_factory as AF

    entry = {
        "source": "app_factory", "status": "HOLD", "category": "세금/세법",
        "review_checklist": [
            {"id": "input_validation_review", "severity": "critical",
             "label": "입력값 검증 정책 확인", "checked": True},
            {"id": "edge_cases", "severity": "critical",
             "label": "예외조건 처리 확인", "checked": False},
        ],
    }
    _write_af_yaml(tmp_path, "labor_af", "diag-ready-test-3", entry)

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=False: {"diag-ready-test-3": entry})
    monkeypatch.setattr(AF, "_REG_DIR", tmp_path)

    ok, msg = AF.promote_to_ready("diag-ready-test-3")
    assert not ok, "edge_cases 미체크인데 READY 승격됨"


def test_promote_to_ready_succeeds_when_both_checked(tmp_path, monkeypatch):
    """compute_rules 있음 + input_validation_review 체크 + edge_cases 체크 →
    다른 critical 항목이 없다면 READY 가능."""
    from modules import app_factory as AF

    entry = {
        "source": "app_factory", "status": "HOLD", "category": "세금/세법",
        "review_checklist": [
            {"id": "input_validation_review", "severity": "critical",
             "label": "입력값 검증 정책 확인", "checked": True},
            {"id": "edge_cases", "severity": "critical",
             "label": "예외조건 처리 확인", "checked": True},
        ],
    }
    _write_af_yaml(tmp_path, "labor_af", "diag-ready-test-4", entry)

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=False: {"diag-ready-test-4": entry})
    monkeypatch.setattr(AF, "_REG_DIR", tmp_path)
    monkeypatch.setattr("modules.registry_loader.invalidate", lambda: None)

    ok, msg = AF.promote_to_ready("diag-ready-test-4")
    assert ok, f"모두 체크했는데 READY 승격 실패: {msg}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
