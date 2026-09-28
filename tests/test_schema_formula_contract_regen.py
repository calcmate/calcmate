# -*- coding: utf-8 -*-
"""tests/test_schema_formula_contract_regen.py — Schema↔Formula Contract 최소 보완

재현 시나리오(React Dashboard 실측):
  AI가 input_schema와 formula를 한 번에 생성하면서 formula가 schema에 없는
  변수(예: deductible_contribution)를 참조 → Hard Gate validate_formula() FAIL.

이번 STEP의 구조 보완(modules/app_factory.py _suggest_spec):
  - Hard Gate 자체는 약화하지 않는다(validate_formula 무수정).
  - 검증 실패 시 [2-A] '확정 schema 유지 + formula 전용 재생성'을 우선 시도하고
    (실패 원인 + 허용 변수 목록을 프롬프트에 전달), schema는 이 응답에서 절대
    갱신하지 않는다(금지: schema에 임의 변수 자동 추가).
  - [2-A]가 실패한 경우에만 [2-B] 기존 전체 재설계 1회로 폴백한다.

실제 AI API 호출 없음 — modules.app_factory._chat을 monkeypatch/patch로 mock.
실제 DB/Registry 접근 없음 — _suggest_spec() 단독 호출 + generate_app() 통합
테스트는 CalculatorRepository만 mock한다.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import modules.app_factory as af_mod
from modules.formula_engine import validate_formula

# ── 재현 시나리오: 복합 조건 계산기 (연금저축/IRP 세액공제) ──────────────────
INPUTS = {
    "pension_savings_amount": "number",
    "irp_amount": "number",
    "annual_income": "number",
}
OUTPUTS = {
    "deductible_amount": "number",
    "expected_tax_credit": "number",
}
LABELS = {
    "pension_savings_amount": "연금저축 납입액",
    "irp_amount": "IRP 납입액",
    "annual_income": "연 소득",
    "deductible_amount": "공제 대상 금액",
    "expected_tax_credit": "예상 세액공제액",
}

# 잘못된 formula — schema에 없는 변수 deductible_contribution 참조 (실측 실패 재현)
BAD_FORMULA = {
    "deductible_amount": "min(deductible_contribution * 0.15, 4000000)",
    "expected_tax_credit": "round(deductible_contribution * 0.12)",
}

# 유효한 formula — schema에 실제 존재하는 변수만 사용 (다른 출력키 참조 금지 준수)
VALID_FORMULA = {
    "deductible_amount": (
        "min(pension_savings_amount * 0.15, 4000000)"
        " + min(irp_amount * 0.15, 1800000)"
    ),
    "expected_tax_credit": (
        "round((min(pension_savings_amount * 0.15, 4000000)"
        " + min(irp_amount * 0.15, 1800000)) * 0.12)"
    ),
}

# formula 전용 재설계 응답 — schema를 몰래 확장하려는 유혹 envelope
# (input_schema에 deductible_contribution/extra_field를 추가) — 코드가 formula만
# 추출하고 schema는 1차 응답 그대로 유지해야 한다(금지 3 검증).
SNEAKY_ENVELOPE = {
    "calculator_type": "연금저축 세액공제 계산기",
    "input_schema": dict(INPUTS, deductible_contribution="number", extra_field="number"),
    "output_schema": OUTPUTS,
    "formula": VALID_FORMULA,
    "labels": LABELS,
}

# [2-A] formula 재설계가 "또 실패"하는 유혹 envelope — 여전히 미등록 변수 참조
BAD_ENVELOPE = {
    "calculator_type": "연금저축 세액공제 계산기",
    "input_schema": dict(INPUTS, deductible_contribution="number", extra_field="number"),
    "output_schema": OUTPUTS,
    "formula": BAD_FORMULA,
    "labels": LABELS,
}


def _chat_tuple(payload):
    """_chat()이 반환하는 (text, model, tokens) 재현 — dict → JSON 문자열."""
    return (json.dumps(payload, ensure_ascii=False), "mock-model", 120)


def _spec_payload(formula=BAD_FORMULA, inputs=None, outputs=None):
    """총괄(스펙) 1차 응답 재현."""
    return {
        "calculator_type": "연금저축 세액공제 계산기",
        "input_schema": inputs or INPUTS,
        "output_schema": outputs or OUTPUTS,
        "formula": formula,
        "labels": LABELS,
    }


# ══════════════════════════════════════════════════════════════════════════
# 공통 실행 헬퍼
# ══════════════════════════════════════════════════════════════════════════

def _run_suggest(monkeypatch, responses):
    calls = []

    def _fake_chat(*a, **k):
        calls.append(a)
        assert len(calls) <= len(responses), f"_chat 과다 호출: {len(calls)} > {len(responses)}"
        return responses[len(calls) - 1]

    monkeypatch.setattr("modules.app_factory._chat", _fake_chat)
    spec, steps = af_mod._suggest_spec(
        cfg={}, name="연금저축 세액공제 계산기", category="세금/정부혜택",
        desc="연금저축/IRP 납입액 기준 세액공제 계산", tier=1,
        existing=[], _contract=None,
    )
    return spec, steps, calls


# ══════════════════════════════════════════════════════════════════════════
# Case A — 모두 실패 시 최종 _formula_valid=False (미채택)
# ══════════════════════════════════════════════════════════════════════════

def test_case_a_all_retries_fail_formula_never_adopted(monkeypatch):
    responses = [
        _chat_tuple(_spec_payload(formula=BAD_FORMULA)),      # 1) 총괄(스펙)
        _chat_tuple(BAD_ENVELOPE),                             # 2) [2-A] formula 재설계(여전히 bad)
        _chat_tuple(_spec_payload(formula=BAD_FORMULA)),      # 3) [2-B] 전체 재설계(역시 bad)
    ]
    spec, steps, calls = _run_suggest(monkeypatch, responses)
    assert len(calls) == 3
    assert spec["_formula_valid"] is False
    assert "deductible_contribution" in spec["_formula_msg"]
    # schema는 1차 응답 그대로(몰래 확장 미반영)
    assert set(spec["input_schema"].keys()) == set(INPUTS.keys())
    labels = [s[0] for s in steps]
    assert labels == ["총괄(스펙)", "총괄(formula 재설계)", "총괄(재시도)"]


# ══════════════════════════════════════════════════════════════════════════
# Case B — schema에 존재하는 변수만 사용하면 추가 호출 없이 PASS
# ══════════════════════════════════════════════════════════════════════════

def test_case_b_valid_formula_first_try_no_regen(monkeypatch):
    responses = [_chat_tuple(_spec_payload(formula=VALID_FORMULA))]
    spec, steps, calls = _run_suggest(monkeypatch, responses)
    assert len(calls) == 1
    assert spec["_formula_valid"] is True
    assert spec["formula"] == VALID_FORMULA
    labels = [s[0] for s in steps]
    assert labels == ["총괄(스펙)"]  # 재설계/재시도 없음


# ══════════════════════════════════════════════════════════════════════════
# Case C — schema 고정 + formula 전용 재생성 (핵심)
# ══════════════════════════════════════════════════════════════════════════

def test_case_c_schema_fixed_formula_only_regen(monkeypatch):
    """1차 bad formula → [2-A]에서 formula만 교체된다.
    재설계 응답이 schema를 몰래 확장(SNEAKY_ENVELOPE)해도 schema는 불변이다."""
    responses = [
        _chat_tuple(_spec_payload(formula=BAD_FORMULA)),  # 1) 총괄(스펙) — bad
        _chat_tuple(SNEAKY_ENVELOPE),                      # 2) [2-A] — formula만 채택
    ]
    spec, steps, calls = _run_suggest(monkeypatch, responses)
    assert len(calls) == 2                      # [2-B] 전체 재설계로 가지 않음
    assert spec["_formula_valid"] is True
    assert spec["_formula_msg"] == "OK"
    # schema 불변 — 몰래 추가된 deductible_contribution/extra_field 미반영
    assert set(spec["input_schema"].keys()) == set(INPUTS.keys())
    assert set(spec["output_schema"].keys()) == set(OUTPUTS.keys())
    # formula만 교체됨
    assert spec["formula"] == VALID_FORMULA
    labels = [s[0] for s in steps]
    assert labels == ["총괄(스펙)", "총괄(formula 재설계)"]
    assert "총괄(재시도)" not in labels


def test_case_c2_regen_as_formula_only_json_envelope(monkeypatch):
    """[2-A] 응답이 {'formula': <단일 문자열 식>} envelope 형태여도 처리된다."""
    good_single = "round(min(pension_savings_amount * 0.15, 4000000) + min(irp_amount * 0.15, 1800000))"
    single_outputs = {"deductible_amount": "number"}
    responses = [
        _chat_tuple(_spec_payload(formula=BAD_FORMULA, outputs=single_outputs)),
        _chat_tuple({"formula": good_single}),   # [2-A] envelope — formula 문자열
    ]
    spec, steps, calls = _run_suggest(monkeypatch, responses)
    assert len(calls) == 2
    assert spec["_formula_valid"] is True
    assert spec["formula"] == good_single
    assert set(spec["input_schema"].keys()) == set(INPUTS.keys())


def test_case_c3_regen_as_bare_expression_string(monkeypatch):
    """[2-A] 응답이 비JSON 단일 산술 표현식 문자열이어도 formula로 채택된다
    (parse_json_lenient는 JSON 객체만 반환하므로 원문을 후보로 사용해야 한다)."""
    good_single = "min(pension_savings_amount * 0.15, 4000000) + min(irp_amount * 0.15, 1800000)"
    single_outputs = {"deductible_amount": "number"}
    responses = [
        _chat_tuple(_spec_payload(formula="deductible_contribution * 0.15", outputs=single_outputs)),
        (good_single, "mock-model", 120),       # [2-A] — 비JSON 순수 수식 문자열
    ]
    spec, steps, calls = _run_suggest(monkeypatch, responses)
    assert len(calls) == 2
    assert spec["_formula_valid"] is True
    assert spec["formula"] == good_single
    assert set(spec["input_schema"].keys()) == set(INPUTS.keys())


# ══════════════════════════════════════════════════════════════════════════
# Case D — generate_app() 통합 (React /api/calculators/generate가 실제로 타는 경로)
# ══════════════════════════════════════════════════════════════════════════

def test_generate_app_pipeline_recovers_with_schema_fixed(monkeypatch):
    """generate_app() 전체 파이프라인에서 1차 spec의 bad formula가 [2-A]
    formula 전용 재생성으로 복구되고, 결과 app의 schema/formula가 정상인지."""
    with patch("modules.app_factory.CalculatorRepository") as MockRepo:
        MockRepo.return_value.get_all.return_value = []
        responses = [
            _chat_tuple(_spec_payload(formula=BAD_FORMULA)),   # 1) 총괄(스펙) — bad
            _chat_tuple(SNEAKY_ENVELOPE),                       # 2) [2-A] formula만 교체
            ("<html></html>", "mock-code", 10),                 # 3) 코드 생성
            (json.dumps({"seo_title": "t", "seo_desc": "d", "faq": [], "blog_draft": ""},
                        ensure_ascii=False), "mock-model", 10),  # 4) SEO/FAQ
            (json.dumps({"image_prompt_thumbnail": "", "image_prompt_body": ""},
                        ensure_ascii=False), "mock-model", 10),  # 5) 이미지 프롬프트
        ]
        calls = []

        def _fake_chat(*a, **k):
            calls.append(a)
            assert len(calls) <= len(responses), f"_chat 과다 호출: {len(calls)}"
            return responses[len(calls) - 1]

        monkeypatch.setattr("modules.app_factory._chat", _fake_chat)
        app = af_mod.generate_app(
            cfg={}, name="연금저축 세액공제 계산기", category="세금/정부혜택",
            desc="연금저축/IRP 납입액 기준 세액공제 계산", tier=1, _contract=None,
        )
    assert app["_formula_valid"] is True
    assert app["formula"] == VALID_FORMULA
    # schema 불변(1차 응답 유지) — 몰래 확장 변수 미반영
    assert set(app["input_schema"].keys()) == set(INPUTS.keys())
    assert set(app["output_schema"].keys()) == set(OUTPUTS.keys())
    assert app["_formula_msg"] == "OK"
