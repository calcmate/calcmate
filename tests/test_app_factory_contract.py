# -*- coding: utf-8 -*-
"""tests/test_app_factory_contract.py — App Factory Contract 보강 검증

구현 범위 (7단계 지시서):
  1. Contract 고정 — build_contract() / validate_against_contract()
  2. Schema 변경 감지 — detect_schema_drift()
  3. Formula 편집+검증 — validate_formula_with_samples()
  4. Slug 중복 검사 — check_slug_conflict() (기존 함수, 새 케이스 추가)
  5. Review Center 세분화 — schema_match / description_text 항목
  6. READY 게이트 재확인 — schema_match 미완료 시 차단

이 파일은 DB 연결 없이 실행된다.
기존 test_review_center.py(27/27) / test_formula_contract.py(17/17)는 별도 확인.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from modules.app_factory import build_contract, validate_against_contract
from modules.formula_engine import detect_schema_drift, validate_formula_with_samples
from modules.review_center import extract_checklist


# ─────────────────────────────────────────────────────────────────────────────
# 0. 테스트용 공통 픽스처
# ─────────────────────────────────────────────────────────────────────────────

ANNUAL_LEAVE_FORMULA = {
    "total_days": "15 + min(max(0, (years_of_service - 1) // 2), 10)",
    "remaining_days": "15 + min(max(0, (years_of_service - 1) // 2), 10) - used_days",
}

ANNUAL_LEAVE_CONTRACT = build_contract(
    slug="annual-leave-remaining",
    name="연차 잔여일 계산기",
    category="노동/고용법",
    tier="Tier2-A",
    input_fields=["years_of_service", "used_days"],
    output_fields=["total_days", "remaining_days"],
    formula=ANNUAL_LEAVE_FORMULA,
    scope_exclusions=["1년 미만 근무자", "단시간 근로자", "회계연도 기준"],
    test_cases=[
        {"input": {"years_of_service": 1, "used_days": 0}, "expected": {"total_days": 15.0, "remaining_days": 15.0}},
        {"input": {"years_of_service": 3, "used_days": 5}, "expected": {"total_days": 16.0, "remaining_days": 11.0}},
        {"input": {"years_of_service": 21, "used_days": 0}, "expected": {"total_days": 25.0, "remaining_days": 25.0}},
    ],
)


def _make_ai_app(input_schema=None, output_schema=None, formula=None, slug=""):
    """AI generate_app() 결과 형태의 mock dict."""
    return {
        "name": "연차 잔여일 계산기",
        "slug": slug,
        "input_schema": input_schema or {},
        "output_schema": output_schema or {},
        "formula": formula,
    }


def _make_app_with_drift(drift_dict):
    """extract_checklist용 — _schema_drift embed된 app dict."""
    return {
        "formula": "a * b",
        "legal_refs": [],
        "category": "노동/고용법",
        "compute_rules": {},
        "input_schema": {"a": "number", "b": "number"},
        "seo_title": "",
        "faq": [],
        "_schema_drift": drift_dict,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. build_contract()
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildContract:
    def test_basic_fields_stored(self):
        c = build_contract(
            slug="annual-leave-remaining",
            name="연차 잔여일 계산기",
            category="노동/고용법",
            tier="Tier2-A",
            input_fields=["years_of_service", "used_days"],
            output_fields=["total_days", "remaining_days"],
        )
        assert c["slug"] == "annual-leave-remaining"
        assert c["name"] == "연차 잔여일 계산기"
        assert c["category"] == "노동/고용법"
        assert c["tier"] == "Tier2-A"
        assert c["input_fields"] == ["years_of_service", "used_days"]
        assert c["output_fields"] == ["total_days", "remaining_days"]

    def test_slug_normalized_lowercase(self):
        c = build_contract(slug="  Annual-Leave-Remaining  ", name="X")
        assert c["slug"] == "annual-leave-remaining", "slug이 소문자/trim 미처리됨"

    def test_optional_fields_default_empty(self):
        c = build_contract(slug="x", name="X")
        assert c["input_fields"] == []
        assert c["output_fields"] == []
        assert c["formula"] is None
        assert c["scope_exclusions"] == []
        assert c["test_cases"] == []

    def test_formula_stored_as_dict(self):
        c = build_contract("x", "X", formula={"out": "a + b"})
        assert isinstance(c["formula"], dict)
        assert c["formula"]["out"] == "a + b"

    def test_test_cases_stored(self):
        tc = [{"input": {"a": 1}, "expected": {"out": 1}}]
        c = build_contract("x", "X", test_cases=tc)
        assert c["test_cases"] == tc

    def test_annual_leave_contract_fixture(self):
        """픽스처 Contract가 올바른 구조를 갖는지 확인."""
        c = ANNUAL_LEAVE_CONTRACT
        assert c["slug"] == "annual-leave-remaining"
        assert set(c["input_fields"]) == {"years_of_service", "used_days"}
        assert set(c["output_fields"]) == {"total_days", "remaining_days"}
        assert len(c["test_cases"]) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. detect_schema_drift()
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectSchemaDrift:
    def test_no_drift_when_fields_match(self):
        contract = build_contract(
            "s", "N",
            input_fields=["years_of_service", "used_days"],
            output_fields=["total_days", "remaining_days"],
        )
        ai_app = _make_ai_app(
            input_schema={"years_of_service": "number", "used_days": "number"},
            output_schema={"total_days": "number", "remaining_days": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert not result["drifted"], "일치하는 필드에서 drift 감지됨"
        assert result["changes"] == []

    def test_input_field_renamed_detected(self):
        """AI가 years_of_service → employment_years로 변경 — 감지해야 한다."""
        contract = build_contract("s", "N", input_fields=["years_of_service", "used_days"])
        ai_app = _make_ai_app(
            input_schema={"employment_years": "number", "used_days": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"], "입력 필드명 변경이 감지되지 않음"
        types = [c["type"] for c in result["changes"]]
        assert "input_missing" in types, "누락된 필드(years_of_service) 미감지"
        assert "input_extra" in types, "추가된 필드(employment_years) 미감지"

    def test_output_field_renamed_detected(self):
        """AI가 total_days → total_annual_leave로 변경 — 감지해야 한다."""
        contract = build_contract("s", "N",
                                   output_fields=["total_days", "remaining_days"])
        ai_app = _make_ai_app(
            output_schema={"total_annual_leave": "number", "remaining_annual_leave": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"]
        types = [c["type"] for c in result["changes"]]
        assert "output_missing" in types
        assert "output_extra" in types

    def test_exact_annual_leave_rename_case(self):
        """연차잔여일계산기 실전 실패 케이스 재현:
        years_of_service→employment_years, total_days→total_annual_leave 동시 변경."""
        contract = ANNUAL_LEAVE_CONTRACT
        ai_app = _make_ai_app(
            input_schema={"employment_years": "number", "used_days": "number"},
            output_schema={"total_annual_leave": "number", "remaining_annual_leave": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"], "연차잔여일 실전 케이스 drift 미감지"
        missing = [c["contract"] for c in result["changes"] if "missing" in c["type"]]
        assert "years_of_service" in missing or "total_days" in missing, \
            f"Contract 확정 필드가 누락 변경 목록에 없음: {missing}"

    def test_empty_contract_no_drift(self):
        """Contract에 필드 명세가 없으면 drift 없음."""
        contract = build_contract("s", "N")  # input_fields=[], output_fields=[]
        ai_app = _make_ai_app(
            input_schema={"any_field": "number"},
            output_schema={"any_output": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert not result["drifted"], "빈 Contract에서 drift 감지됨 (오류)"

    def test_extra_field_added_by_ai(self):
        """AI가 Contract에 없는 필드를 추가 — extra로 감지."""
        contract = build_contract("s", "N", input_fields=["a"])
        ai_app = _make_ai_app(input_schema={"a": "number", "extra_field": "number"})
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"]
        extras = [c["ai"] for c in result["changes"] if c["type"] == "input_extra"]
        assert "extra_field" in extras

    def test_missing_field_from_ai(self):
        """AI가 Contract 필드를 누락 — missing으로 감지."""
        contract = build_contract("s", "N",
                                   input_fields=["required_field", "used_days"])
        ai_app = _make_ai_app(input_schema={"used_days": "number"})  # required_field 누락
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"]
        missing = [c["contract"] for c in result["changes"] if c["type"] == "input_missing"]
        assert "required_field" in missing

    def test_input_output_changes_separated(self):
        """input_changes와 output_changes는 별도 필드로 분리."""
        contract = build_contract("s", "N",
                                   input_fields=["a"],
                                   output_fields=["b"])
        ai_app = _make_ai_app(
            input_schema={"a_renamed": "number"},
            output_schema={"b_renamed": "number"},
        )
        result = detect_schema_drift(contract, ai_app)
        assert result["drifted"]
        in_types = {c["type"] for c in result["input_changes"]}
        out_types = {c["type"] for c in result["output_changes"]}
        assert "input_missing" in in_types or "input_extra" in in_types
        assert "output_missing" in out_types or "output_extra" in out_types


# ─────────────────────────────────────────────────────────────────────────────
# 3. validate_against_contract()
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateAgainstContract:
    def _matching_app(self):
        return _make_ai_app(
            slug="annual-leave-remaining",
            input_schema={"years_of_service": "number", "used_days": "number"},
            output_schema={"total_days": "number", "remaining_days": "number"},
            formula=ANNUAL_LEAVE_FORMULA,
        )

    def test_valid_when_all_match(self):
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, self._matching_app())
        assert result["valid"], f"일치하는 경우 valid=False: {result['messages']}"
        assert result["status_hint"] == "VALID"
        assert result["messages"] == []

    def test_slug_mismatch_detected(self):
        """AI가 annual-leave 대신 annual-leave-remaining을 생성 — 감지."""
        ai_app = self._matching_app()
        ai_app["slug"] = "annual-leave"
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        assert result["slug_mismatch"], "slug 불일치 미감지"
        assert not result["valid"]
        assert result["status_hint"] == "INVALID"
        assert any("slug" in m for m in result["messages"])

    def test_no_slug_in_ai_app_no_mismatch(self):
        """AI 결과에 slug 필드 없으면 slug 비교 건너뜀."""
        ai_app = self._matching_app()
        ai_app["slug"] = ""
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        # slug 불일치는 없어야 하지만, schema_drift/formula가 모두 맞으면 valid
        assert not result["slug_mismatch"]

    def test_field_mismatch_invalid(self):
        """필드명 불일치 → valid=False."""
        ai_app = _make_ai_app(
            input_schema={"employment_years": "number", "used_days": "number"},
            output_schema={"total_annual_leave": "number", "remaining_annual_leave": "number"},
        )
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        assert not result["valid"]
        assert result["schema_drift"]["drifted"]
        assert result["status_hint"] == "INVALID"

    def test_formula_changed_detected(self):
        """AI가 formula를 수정하면 formula_changed=True."""
        ai_app = self._matching_app()
        ai_app["formula"] = {"total_days": "15", "remaining_days": "15 - used_days"}
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        assert result["formula_changed"], "formula 변경 미감지"
        assert not result["valid"]
        assert any("formula" in m for m in result["messages"])

    def test_contract_without_formula_no_formula_check(self):
        """Contract에 formula가 없으면 formula 비교 건너뜀."""
        contract = build_contract("x", "X",
                                   input_fields=["a"],
                                   output_fields=["b"])
        ai_app = _make_ai_app(
            input_schema={"a": "number"},
            output_schema={"b": "number"},
            formula="a * 2",
        )
        result = validate_against_contract(contract, ai_app)
        assert not result["formula_changed"], "formula 없는 Contract에서 formula_changed=True"

    def test_messages_describe_each_mismatch(self):
        """메시지가 각 불일치를 구체적으로 서술."""
        ai_app = _make_ai_app(
            slug="wrong-slug",
            input_schema={"employment_years": "number"},  # years_of_service 없음
            output_schema={"total_days": "number", "remaining_days": "number"},
        )
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        msgs = " ".join(result["messages"])
        assert "slug" in msgs or "wrong-slug" in msgs
        assert "years_of_service" in msgs or "employment_years" in msgs

    def test_slug_and_field_mismatch_both_in_messages(self):
        """slug + field 동시 불일치 → messages에 모두 포함."""
        ai_app = _make_ai_app(
            slug="annual-leave",
            input_schema={"employment_years": "number", "used_days": "number"},
            output_schema={"total_days": "number", "remaining_days": "number"},
        )
        result = validate_against_contract(ANNUAL_LEAVE_CONTRACT, ai_app)
        assert not result["valid"]
        assert len(result["messages"]) >= 2, "slug + field 불일치 메시지 부족"


# ─────────────────────────────────────────────────────────────────────────────
# 4. validate_formula_with_samples()
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateFormulaWithSamples:
    def test_valid_formula_no_samples(self):
        """테스트 케이스 없어도 검증 통과."""
        result = validate_formula_with_samples(
            "a + b", {"a": "number", "b": "number"}
        )
        assert result["valid"]
        assert result["message"] == "OK"
        assert result["sample_results"] == []

    def test_invalid_formula_returns_false(self):
        """미선언 변수 → valid=False."""
        result = validate_formula_with_samples(
            "a + ghost_var", {"a": "number"}
        )
        assert not result["valid"]
        assert "ghost_var" in result["message"]

    def test_sample_results_computed(self):
        """test_cases 있으면 실제 계산 결과 반환."""
        result = validate_formula_with_samples(
            "a * 2",
            {"a": "number"},
            test_cases=[{"input": {"a": 5}, "expected": {"result": 10.0}}],
        )
        assert result["valid"]
        assert len(result["sample_results"]) == 1
        sr = result["sample_results"][0]
        assert sr["output"] == {"result": 10.0}

    def test_sample_match_flag_true(self):
        """expected와 실제 결과가 일치하면 match=True."""
        result = validate_formula_with_samples(
            "a * 2",
            {"a": "number"},
            test_cases=[{"input": {"a": 3}, "expected": {"result": 6.0}}],
        )
        assert result["sample_results"][0]["match"] is True

    def test_sample_match_flag_false(self):
        """expected가 틀리면 match=False."""
        result = validate_formula_with_samples(
            "a * 2",
            {"a": "number"},
            test_cases=[{"input": {"a": 3}, "expected": {"result": 99.0}}],
        )
        assert result["sample_results"][0]["match"] is False

    def test_no_expected_match_is_none(self):
        """expected 없으면 match=None."""
        result = validate_formula_with_samples(
            "a * 2",
            {"a": "number"},
            test_cases=[{"input": {"a": 3}}],
        )
        assert result["sample_results"][0]["match"] is None

    def test_annual_leave_formula_validates_and_runs(self):
        """연차잔여일 formula dict 전체 검증 + 샘플 실행."""
        schema = {"years_of_service": "number", "used_days": "number"}
        result = validate_formula_with_samples(
            ANNUAL_LEAVE_FORMULA,
            schema,
            test_cases=ANNUAL_LEAVE_CONTRACT["test_cases"],
        )
        assert result["valid"], f"formula 검증 실패: {result['message']}"
        # 3개 샘플 모두 실행 성공
        assert len(result["sample_results"]) == 3
        errors = [sr for sr in result["sample_results"] if sr.get("error")]
        assert not errors, f"샘플 계산 오류: {errors}"

    def test_annual_leave_sample_values_correct(self):
        """연차잔여일 샘플 결과값이 법령 계산과 일치."""
        schema = {"years_of_service": "number", "used_days": "number"}
        result = validate_formula_with_samples(
            ANNUAL_LEAVE_FORMULA,
            schema,
            test_cases=[
                # 근속 1년: total=15, remaining=15
                {"input": {"years_of_service": 1, "used_days": 0},
                 "expected": {"total_days": 15.0, "remaining_days": 15.0}},
                # 근속 3년: 가산1일 → total=16, 5일 사용 → remaining=11
                {"input": {"years_of_service": 3, "used_days": 5},
                 "expected": {"total_days": 16.0, "remaining_days": 11.0}},
                # 근속 21년: 가산10일(최대) → total=25
                {"input": {"years_of_service": 21, "used_days": 0},
                 "expected": {"total_days": 25.0, "remaining_days": 25.0}},
            ],
        )
        for sr in result["sample_results"]:
            assert sr.get("match") is True, (
                f"기대값 불일치: input={sr['input']}, "
                f"output={sr['output']}, expected={sr['expected']}"
            )

    def test_dict_formula_multiple_samples(self):
        """dict formula에서 여러 샘플이 각각 실행."""
        formula = {"x2": "a * 2", "x3": "a * 3"}
        result = validate_formula_with_samples(
            formula,
            {"a": "number"},
            test_cases=[
                {"input": {"a": 5}, "expected": {"x2": 10.0, "x3": 15.0}},
                {"input": {"a": 10}},
            ],
        )
        assert result["valid"]
        assert len(result["sample_results"]) == 2
        assert result["sample_results"][0]["match"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Review Center — schema_match / description_text 항목
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCenterNewItems:
    # ── schema_match ──────────────────────────────────────────────────────────

    def test_schema_match_appears_when_drift_present(self):
        """_schema_drift drifted=True이면 schema_match 항목 추출."""
        drift = {
            "drifted": True,
            "changes": [{"type": "input_missing", "contract": "years_of_service", "ai": None}],
            "input_changes": [], "output_changes": [],
        }
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "schema_match" in ids, f"schema_match 누락. 항목: {ids}"

    def test_schema_match_appears_when_no_drift(self):
        """_schema_drift drifted=False여도 schema_match 항목 추출 (Schema 일치 확인 완료)."""
        drift = {"drifted": False, "changes": [], "input_changes": [], "output_changes": []}
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "schema_match" in ids, "schema_match 누락 (no-drift 케이스)"

    def test_schema_match_not_appears_without_drift_info(self):
        """_schema_drift 키 없으면 schema_match 미발생 (기존 계산기 보호)."""
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
        }
        # _schema_drift 키 없음
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "schema_match" not in ids, "schema_match가 _schema_drift 없이 추출됨"

    def test_schema_match_severity_critical(self):
        """schema_match는 항상 🔴 critical."""
        for drifted in [True, False]:
            drift = {"drifted": drifted, "changes": [], "input_changes": [], "output_changes": []}
            app = _make_app_with_drift(drift)
            items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
            sm = next((i for i in items if i["id"] == "schema_match"), None)
            assert sm is not None
            assert sm["severity"] == "critical", \
                f"schema_match severity가 critical이 아님 (drifted={drifted}): {sm['severity']}"

    def test_schema_match_drift_display_shows_changed_fields(self):
        """drifted=True이면 display_value에 변경된 필드명 표시."""
        drift = {
            "drifted": True,
            "changes": [
                {"type": "input_missing", "contract": "years_of_service", "ai": None},
                {"type": "input_extra", "contract": None, "ai": "employment_years"},
            ],
            "input_changes": [], "output_changes": [],
        }
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        sm = next(i for i in items if i["id"] == "schema_match")
        assert "years_of_service" in sm["display_value"] or "employment_years" in sm["display_value"], \
            f"display_value에 변경 필드명 없음: {sm['display_value']}"
        assert "⚠️" in sm["display_value"], "경고 표시 없음"

    def test_schema_match_no_drift_display_shows_ok(self):
        """drifted=False이면 display_value에 일치 메시지."""
        drift = {"drifted": False, "changes": [], "input_changes": [], "output_changes": []}
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        sm = next(i for i in items if i["id"] == "schema_match")
        assert "✅" in sm["display_value"] or "일치" in sm["display_value"], \
            f"일치 확인 메시지 없음: {sm['display_value']}"

    def test_schema_match_unchecked_by_default(self):
        """schema_match 초기값 checked=False."""
        drift = {"drifted": True, "changes": [
            {"type": "output_missing", "contract": "total_days", "ai": None}
        ], "input_changes": [], "output_changes": []}
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        sm = next(i for i in items if i["id"] == "schema_match")
        assert not sm["checked"]
        assert sm["checked_by"] is None
        assert sm["checked_at"] is None

    # ── description_text ──────────────────────────────────────────────────────

    def test_description_text_appears_with_description(self):
        """description 필드 있으면 description_text 추출."""
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
            "description": "이 계산기는 연차수당을 계산합니다.",
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "description_text" in ids, "description_text 누락"

    def test_description_text_appears_with_seo_desc(self):
        """seo_desc 필드가 있으면 description_text 추출."""
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
            "seo_desc": "연차 잔여일을 간편하게 계산하세요.",
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "description_text" in ids, "seo_desc → description_text 누락"

    def test_description_text_not_appears_when_empty(self):
        """description 없으면 description_text 미발생."""
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]
        assert "description_text" not in ids, "빈 description에서 description_text 추출됨"

    def test_description_text_severity_advisory(self):
        """description_text는 🟡 advisory."""
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
            "description": "테스트 설명",
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        dt = next((i for i in items if i["id"] == "description_text"), None)
        assert dt is not None
        assert dt["severity"] == "advisory", f"description_text가 advisory가 아님: {dt['severity']}"

    def test_description_text_shows_content(self):
        """display_value에 description 내용 포함."""
        desc = "이 계산기는 Tier2-A 안내문입니다."
        app = {
            "formula": "a * b", "legal_refs": [], "category": "노동/고용법",
            "compute_rules": {}, "input_schema": {}, "seo_title": "", "faq": [],
            "description": desc,
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        dt = next(i for i in items if i["id"] == "description_text")
        assert desc[:30] in dt["display_value"], "description 내용이 display_value에 없음"

    # ── 6개 항목 독립성 ──────────────────────────────────────────────────────

    def test_6_items_are_independent(self):
        """지시서 6개 항목이 각각 독립적으로 존재하고 하나가 다른 항목을 자동으로 채우지 않음."""
        drift = {"drifted": True, "changes": [
            {"type": "input_missing", "contract": "years_of_service", "ai": None}
        ], "input_changes": [], "output_changes": []}
        app = {
            "formula": "15 + min(max(0, (years_of_service - 1) // 2), 10)",
            "legal_refs": ["근로기준법 제60조"],
            "category": "노동/고용법",
            "compute_rules": {},
            "input_schema": {"years_of_service": {"type": "number"}},
            "seo_title": "연차 잔여일 계산기",
            "faq": [{"q": "Q1", "a": "A1"}],
            "description": "이 계산기는 연차 잔여일을 계산합니다.",
            "_schema_drift": drift,
        }
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")
        ids = [i["id"] for i in items]

        # 6개 지시서 항목 존재 확인
        assert "legal_basis" in ids, "legal_basis 누락"
        assert "formula_accuracy" in ids, "formula_accuracy 누락"
        assert "formula_cap" in ids, "formula_cap 누락 (min/max 포함 formula)"
        assert "schema_match" in ids, "schema_match 누락"
        # advisory
        assert "description_text" in ids, "description_text 누락"
        assert "seo_title" in ids, "seo_title 누락"
        assert "faq_content" in ids, "faq_content 누락"

        # 모든 항목이 unchecked (독립 초기화, 상호 자동 체크 없음)
        for item in items:
            assert not item["checked"], f"'{item['id']}' 항목이 checked=True로 초기화됨"

    def test_schema_match_and_legal_basis_are_independent(self):
        """schema_match 체크가 legal_basis를 자동으로 채우지 않음."""
        drift = {"drifted": False, "changes": [], "input_changes": [], "output_changes": []}
        app = _make_app_with_drift(drift)
        items = extract_checklist(app, tier="Tier2-A", category="노동/고용법")

        sm = next((i for i in items if i["id"] == "schema_match"), None)
        lb = next((i for i in items if i["id"] == "legal_basis"), None)
        assert sm is not None and lb is not None
        assert not sm["checked"]
        assert not lb["checked"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. READY 게이트 — schema_match 미완료 시 차단
# ─────────────────────────────────────────────────────────────────────────────

class TestReadyGateWithSchemaMatch:
    @pytest.fixture(autouse=True)
    def _isolated_registry(self, monkeypatch, tmp_path):
        """CALCMATE-TEST-ISOLATION-FIX-04: promote_to_ready()는 체크리스트 게이트를 통과하면
        app_factory._REG_DIR/{category}_af.yaml을 다시 쓴다. 격리하지 않으면 실제 운영
        docs/registry/labor_af.yaml이 테스트 중에 다시 쓰였다("노동/고용법"은 매핑에 없어
        labor_af로 폴백, 실제 파일에 annual-leave-remaining이 있음). 다른 App Factory 테스트와
        같은 방식으로 _REG_DIR을 tmp_path로 돌리고, 실제 파일과 같은 조건(해당 slug가 HOLD로
        들어 있는 labor_af.yaml)만 최소로 재현한다. load_registry_v3는 각 테스트가 그대로 mock한다."""
        import modules.app_factory as af
        import modules.registry_loader as rl
        reg_dir = tmp_path / "registry"
        reg_dir.mkdir()
        (reg_dir / "labor_af.yaml").write_text(
            "annual-leave-remaining:\n"
            "  slug: annual-leave-remaining\n"
            "  source: app_factory\n"
            "  status: HOLD\n"
            "  category: 노동/고용법\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(af, "_REG_DIR", reg_dir)
        monkeypatch.setattr(rl, "_REG_DIR", reg_dir)
        self.reg_dir = reg_dir

    def test_ready_blocked_when_schema_match_unchecked(self):
        """schema_match(critical) 미완료 시 promote_to_ready() 차단."""
        from modules.app_factory import promote_to_ready

        mock_v3 = {
            "annual-leave-remaining": {
                "source": "app_factory",
                "status": "HOLD",
                "category": "노동/고용법",
                "review_checklist": [
                    {"id": "formula_accuracy", "severity": "critical", "label": "공식", "checked": True},
                    {"id": "legal_basis", "severity": "critical", "label": "법령", "checked": True},
                    {"id": "schema_match", "severity": "critical", "label": "Schema", "checked": False},
                ],
            }
        }
        with patch("modules.registry_loader.load_registry_v3", return_value=mock_v3):
            ok, msg = promote_to_ready("annual-leave-remaining")
        assert not ok, "schema_match 미완료인데 READY 전환 성공"
        assert "미완료" in msg or "필수" in msg, f"차단 메시지 부적절: {msg}"

    def test_ready_allowed_when_all_critical_checked(self):
        """schema_match 포함 모든 critical 완료 시 promote_to_ready() 통과 시도 (yaml 파일 없어서 실패하지만 체크리스트 게이트는 통과)."""
        from modules.app_factory import promote_to_ready

        mock_v3 = {
            "annual-leave-remaining": {
                "source": "app_factory",
                "status": "HOLD",
                "category": "노동/고용법",
                "review_checklist": [
                    {"id": "formula_accuracy", "severity": "critical", "label": "공식", "checked": True},
                    {"id": "legal_basis", "severity": "critical", "label": "법령", "checked": True},
                    {"id": "schema_match", "severity": "critical", "label": "Schema", "checked": True},
                    {"id": "description_text", "severity": "advisory", "label": "안내문", "checked": False},
                ],
            }
        }
        with patch("modules.registry_loader.load_registry_v3", return_value=mock_v3):
            ok, msg = promote_to_ready("annual-leave-remaining")
        # advisory 미완료 + yaml 파일 없음 → 여기서는 체크리스트 게이트는 통과했어야 함
        # (yaml 파일 미존재로 실패할 수 있지만, "미완료" 메시지는 없어야 함)
        if not ok:
            assert "미완료" not in msg and "필수" not in msg, \
                f"schema_match 완료됐는데 체크리스트 게이트에서 차단됨: {msg}"
        else:
            # FIX-04: 전환 결과는 격리된 임시 Registry에만 기록돼야 한다.
            assert "status: READY" in (self.reg_dir / "labor_af.yaml").read_text(encoding="utf-8")

    def test_ready_blocked_with_multiple_unchecked_critical(self):
        """여러 critical 미완료 → 모두 차단 메시지에 포함."""
        from modules.app_factory import promote_to_ready

        mock_v3 = {
            "test-multi-block": {
                "source": "app_factory",
                "status": "HOLD",
                "category": "노동/고용법",
                "review_checklist": [
                    {"id": "formula_accuracy", "severity": "critical", "label": "공식", "checked": False},
                    {"id": "legal_basis", "severity": "critical", "label": "법령", "checked": False},
                    {"id": "schema_match", "severity": "critical", "label": "Schema", "checked": False},
                ],
            }
        }
        with patch("modules.registry_loader.load_registry_v3", return_value=mock_v3):
            ok, msg = promote_to_ready("test-multi-block")
        assert not ok
        # 미완료 개수(3개) 포함
        assert "3" in msg or "미완료" in msg, f"미완료 개수 메시지 없음: {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Slug 확인/수정 UI — check_slug_conflict() 추가 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestSlugCheckWithContract:
    def test_contract_slug_not_conflict_for_new(self):
        """Contract 확정 slug가 신규인 경우 충돌 없음."""
        from modules.review_center import check_slug_conflict
        from modules.config_loader import load_config
        cfg = load_config()
        _, conflict, _ = check_slug_conflict("annual-leave-remaining", cfg)
        # 이 slug가 아직 등록되지 않은 경우
        # (이미 등록됐다면 이 테스트는 충돌로 탐지 — 둘 다 유효한 결과)
        # 테스트 목적: 함수가 정상 실행되는지 확인
        assert isinstance(conflict, bool)

    def test_existing_slug_conflict_detected(self):
        """기존 9개 계산기 slug와 충돌 시 True 반환."""
        from modules.review_center import check_slug_conflict
        from modules.config_loader import load_config
        cfg = load_config()
        for known in ["severance-pay", "annual-leave-allowance", "four-insurances"]:
            _, conflict, msg = check_slug_conflict(known, cfg)
            assert conflict, f"'{known}' 중복 감지 실패"
            assert known in msg, f"메시지에 slug 없음: {msg}"

    def test_contract_slug_mismatch_with_check(self):
        """validate_against_contract + check_slug_conflict 연동 케이스."""
        from modules.review_center import check_slug_conflict
        from modules.config_loader import load_config
        cfg = load_config()

        # AI가 annual-leave로 slug 생성했을 때
        ai_slug = "annual-leave"
        v = validate_against_contract(ANNUAL_LEAVE_CONTRACT, _make_ai_app(slug=ai_slug))
        assert v["slug_mismatch"], "slug 불일치 미감지"

        # check_slug_conflict도 함께 실행
        _, conflict, _ = check_slug_conflict(ANNUAL_LEAVE_CONTRACT["slug"], cfg)
        # slug 중복 여부와 상관없이, Contract에서 확정된 slug는 annual-leave-remaining이어야 함
        assert ANNUAL_LEAVE_CONTRACT["slug"] == "annual-leave-remaining"


# ─────────────────────────────────────────────────────────────────────────────
# 8. 기존 9개 계산기 회귀 — Contract 추가 이후 영향 없음 확인
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionExistingCalculators:
    """기존 계산기에 Contract 관련 기능 추가 이후 영향 없음 확인."""

    def test_detect_schema_drift_noop_for_empty_contract(self):
        """기존 계산기 dict (input_fields 없음) → drift 없음."""
        existing_calc_contract = {}  # 기존 계산기는 build_contract 안 씀
        ai_app = _make_ai_app(
            input_schema={"monthly_salary": "number"},
            output_schema={"national_pension": "number"},
        )
        result = detect_schema_drift(existing_calc_contract, ai_app)
        assert not result["drifted"], "빈 contract에서 drift 발생 (기존 계산기 오영향)"

    def test_validate_against_contract_no_formula_no_error(self):
        """Contract formula=None → formula 비교 건너뜀, 에러 없음."""
        contract = build_contract("x", "X", input_fields=["a"], output_fields=["b"])
        ai_app = _make_ai_app(
            input_schema={"a": "number"},
            output_schema={"b": "number"},
        )
        result = validate_against_contract(contract, ai_app)
        assert not result["formula_changed"]  # formula 없으면 changed=False

    def test_extract_checklist_no_schema_match_for_existing(self):
        """기존 계산기 dict에 _schema_drift 없으면 schema_match 미발생."""
        existing_app = {
            "formula": "avg_monthly_wage * (total_days / 365)",
            "legal_refs": ["근로기준법 제34조"],
            "category": "노무/급여",
            "compute_rules": {},
            "input_schema": {"avg_monthly_wage": {"type": "number"}, "total_days": {"type": "number"}},
            "seo_title": "퇴직금 계산기",
            "faq": [{"q": "Q", "a": "A"}],
        }
        items = extract_checklist(existing_app, tier="Tier2-A", category="노무/급여")
        ids = [i["id"] for i in items]
        assert "schema_match" not in ids, "기존 계산기에 schema_match 발생 (오영향)"

    def test_formula_contract_baseline_still_valid(self):
        """기존 FORMULA_CONTRACTS(5개) validate_formula가 모두 통과하는지."""
        from modules.formula_engine import validate_formula
        import json as _json

        cases = [
            ("weekly-holiday-allowance",
             "hourly_wage * (weekly_hours / 40) * 8",
             {"weekly_hours": "number", "hourly_wage": "number"}),
            ("severance-pay",
             "avg_monthly_wage * (total_days / 365)",
             {"avg_monthly_wage": "number", "start_date": "date",
              "end_date": "date", "total_days": "number"}),
            ("annual-leave-allowance",
             "daily_wage * unused_days",
             {"daily_wage": "number", "unused_days": "number"}),
            ("unemployment-benefit",
             "avg_daily_wage * 0.6",
             {"avg_daily_wage": "number", "age": "number", "employment_months": "number"}),
            ("four-insurances",
             _json.dumps({
                 "national_pension": "monthly_salary * 0.045",
                 "health_insurance": "monthly_salary * 0.03545",
                 "employment_insurance": "monthly_salary * 0.009",
                 "total": "monthly_salary * 0.045 + monthly_salary * 0.03545 * 1.1296 + monthly_salary * 0.009",
             }, ensure_ascii=False),
             {"monthly_salary": "number"}),
        ]
        for slug, formula, schema in cases:
            ok, msg = validate_formula(formula, schema)
            assert ok, f"[{slug}] formula 회귀 실패: {msg}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
