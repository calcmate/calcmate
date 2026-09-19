# -*- coding: utf-8 -*-
"""
tests/test_calculator_g_calc_integration.py — CALCMATE-BLOG-QUALITY-STEP140

content/calculator/example_builder.py::build_example_context()의 verified_examples가
modules/content_integrity.py::check_g_calc()까지 실제로 연결되어 calculator 생성
경로(auto_generate_all)에서 논블로킹으로 실행되는지 검증한다.

LLM/DB/WP를 실제로 호출하지 않는다(monkeypatch로 전부 대체).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.content_integrity import check_g_calc, _format_krw
from content.calculator.example_builder import build_example_context
from content.calculator import prompt as PM
import content.calculator.writer as writer_mod


_JEONSE_CALC = {
    "slug": "jeonse-vs-monthly", "name": "전세 vs 월세 비교 계산기", "category": "부동산/임대",
    "formula": (
        '{"jeonse_opp_cost": "(jeonse_deposit - wolse_deposit) * rate / 100 / 12", '
        '"wolse_to_jeonse_equiv": "wolse_deposit + wolse_amount * 1200 / rate", '
        '"monthly_savings": "wolse_amount - (jeonse_deposit - wolse_deposit) * rate / 100 / 12"}'
    ),
    "input_schema": (
        '{"jeonse_deposit": "number", "wolse_deposit": "number", '
        '"wolse_amount": "number", "rate": "number"}'
    ),
    "output_schema": (
        '{"jeonse_opp_cost": "number", "wolse_to_jeonse_equiv": "number", '
        '"monthly_savings": "number"}'
    ),
}


def _patch_generation(monkeypatch, article_html: str):
    """auto_generate_all()의 LLM 단계(SEO/FAQ/본문/이미지/Reviewer)를 전부 대체한다.
    check_g_calc/check_g_legal_current 등 게이트 로직 자체는 건드리지 않는다."""
    monkeypatch.setattr(writer_mod, "_seo_pair", lambda cfg, calc: {"seo_title": "t", "seo_description": "d"})
    monkeypatch.setattr(writer_mod, "generate_faq", lambda cfg, calc, example_context=None: [])
    monkeypatch.setattr(writer_mod, "generate_article", lambda *a, **kw: article_html)
    monkeypatch.setattr(writer_mod, "_image_pair", lambda cfg, calc: {"body": "", "thumbnail": ""})


# ── TEST A: builder → verified_examples → check_g_calc 실제 경로 ────────────

def test_a_builder_verified_examples_reach_check_g_calc():
    """G-CALC이 실제로 기대하는 표기(_format_krw)를 그대로 써서, builder의
    verified_examples 값이 G-CALC까지 손실 없이 전달·인식되는지 확인한다
    (독립적으로 별도 반올림 로직을 만들지 않음 — G-CALC 자신의 포맷터 재사용)."""
    ctx = build_example_context(_JEONSE_CALC)
    assert ctx is not None and ctx.get("verified_examples")
    result = ctx["verified_examples"][0]["result"]
    body = (
        f"<p>전세 기회비용은 {_format_krw(int(result['jeonse_opp_cost']))[0]}, "
        f"월세 환산액은 {_format_krw(int(result['wolse_to_jeonse_equiv']))[0]}, "
        f"월 절감액은 {_format_krw(int(result['monthly_savings']))[0]}입니다.</p>"
    )
    fails = check_g_calc(body, ctx)
    assert fails == []


# ── TEST B: 올바른 금액 → G-CALC failure = 0 ─────────────────────────────────

def test_b_correct_amounts_pass():
    """jeonse-vs-monthly는 result에 3개 금액이 있어 그중 하나만 언급하면 나머지
    2개가 '미등장'으로 정당하게 FAIL되므로(G-CALC의 설계된 동작), 단일 출력
    계산기(annual-leave-allowance)로 '언급된 금액=결과 전체'인 단순 케이스를 검증한다."""
    calc = {
        "slug": "annual-leave-allowance", "name": "연차수당 계산기", "category": "노무/급여",
        "formula": "daily_wage * unused_days",
        "input_schema": '{"daily_wage": "number", "unused_days": "number"}',
        "output_schema": '{"annual_leave_allowance": "number"}',
    }
    ctx = build_example_context(calc)
    result = ctx["verified_examples"][0]["result"]
    amount = result["annual_leave_allowance"]
    body = f"<p>연차수당은 {_format_krw(int(amount))[0]}입니다.</p>"
    fails = check_g_calc(body, ctx)
    assert len([f for f in fails if f["gate"] == "G-CALC"]) == 0


# ── TEST C: 잘못된 금액 → G-CALC failure > 0, generation은 중단되지 않음 ────

def test_c_wrong_amount_fails_but_generation_continues(monkeypatch):
    ctx = build_example_context(_JEONSE_CALC)
    wrong_body = "<p>전세 기회비용은 1원이고 월세 환산액은 2원이며 월 절감액은 3원입니다.</p>"

    # 순수 함수 직접 검증: FAIL > 0
    fails = check_g_calc(wrong_body, ctx)
    assert len(fails) > 0
    assert all(f["gate"] == "G-CALC" for f in fails)

    # auto_generate_all() 경로에서도 예외 없이 끝까지 실행되는지 확인(논블로킹)
    _patch_generation(monkeypatch, wrong_body)
    calc = dict(_JEONSE_CALC)
    result = writer_mod.auto_generate_all({}, calc, save=False, auto_review=False, example_context=ctx)

    assert result["article_content"] == wrong_body
    assert result["_g_calc_passed"] is False
    assert len(result["_g_calc_failures"]) > 0
    # generation 자체는 예외 없이 완주해 result를 반환함(abort 없음)


# ── TEST D: intent가 PM._get_intent_from_category(calc)와 동일하게 전달됨 ───

def test_d_intent_forwarded_from_shared_helper(monkeypatch):
    captured = {}

    def _spy_check_g_calc(article, example_context=None, intent=None):
        captured["intent"] = intent
        return []

    # writer.py는 함수 내부에서 매번 `from modules.content_integrity import check_g_calc`를
    # 로컬 import하므로, 실제로 spy하려면 content_integrity 모듈 자체의 속성을 바꿔야 한다.
    import modules.content_integrity as CI
    monkeypatch.setattr(CI, "check_g_calc", _spy_check_g_calc)

    _patch_generation(monkeypatch, "<p>본문</p>")
    calc = dict(_JEONSE_CALC)
    writer_mod.auto_generate_all({}, calc, save=False, auto_review=False, example_context=None)

    expected_intent = PM._get_intent_from_category(calc)
    assert captured["intent"] == expected_intent


# ── TEST E: example_context=None → G-CALC no-op ────────────────────────────

def test_e_none_context_is_noop():
    fails = check_g_calc("<p>아무 금액 없음</p>", None)
    assert fails == []


def test_e_none_context_through_auto_generate_all(monkeypatch):
    _patch_generation(monkeypatch, "<p>본문</p>")
    calc = dict(_JEONSE_CALC)
    result = writer_mod.auto_generate_all({}, calc, save=False, auto_review=False, example_context=None)
    assert result["_g_calc_passed"] is True
    assert result["_g_calc_failures"] == []


# ── TEST F: Golden10 보호(DB write/publish 미발생) — 실제 Golden10 slug 사용 ──

def test_f_golden10_no_db_write_via_save_false(monkeypatch):
    """save=False이면 G-CALC 연결 여부와 무관하게 DB update 함수 자체가 호출되지 않는다."""
    called = {"get_db_adapter": False}
    monkeypatch.setattr("adapters.db.factory.get_db_adapter",
                         lambda cfg: called.__setitem__("get_db_adapter", True))
    _patch_generation(monkeypatch, "<p>본문</p>")
    calc = dict(_JEONSE_CALC)
    ctx = build_example_context(calc)
    writer_mod.auto_generate_all({}, calc, save=False, auto_review=False, example_context=ctx)
    assert called["get_db_adapter"] is False


# ── CALCMATE-BLOG-QUALITY-STEP149: ANY COMPLETE Contract v1 신규 테스트 ──────
#
# STEP148 Implementation Specification의 테스트 매트릭스를 그대로 구현한다.
# 기존 test_a~f 및 test_phase5e_integrity.py::TestGCalc는 전부 단일-example
# fixture만 사용하므로(ALL semantics == ANY COMPLETE semantics when n=1),
# 여기서는 다중-example(n>=2) 시나리오만 추가한다.

def _multi_ctx(*results: dict) -> dict:
    """여러 개의 result를 가진 verified_examples로 example_context를 만든다."""
    return {"verified_examples": [{"inputs": {}, "result": r} for r in results]}


# Test 1 (Case A): example[0] complete, example[1] absent → PASS
def test_1_first_example_complete_second_absent_passes():
    ctx = _multi_ctx({"amount": 1_100_000}, {"amount": 9_900_000})
    body = f"<p>지급액은 {_format_krw(1_100_000)[0]}입니다. 다른 이야기는 없습니다.</p>"
    fails = check_g_calc(body, ctx)
    assert fails == []


# Test 2 (Case B): example[0] absent, example[1] complete → PASS (마지막 example 완전)
def test_2_last_example_complete_first_absent_passes():
    ctx = _multi_ctx({"amount": 1_100_000}, {"amount": 9_900_000})
    body = f"<p>지급액은 {_format_krw(9_900_000)[0]}입니다. 다른 이야기는 없습니다.</p>"
    fails = check_g_calc(body, ctx)
    assert fails == []


# Test 3: example[0] partial(일부만 언급), example[1] complete → PASS
def test_3_partial_first_complete_second_passes():
    ctx = _multi_ctx(
        {"a": 1_100_000, "b": 2_200_000},   # 2개 필드 중 1개만 등장 예정 → 불완전
        {"amount": 9_900_000},               # 완전 등장 예정
    )
    body = (
        f"<p>첫 번째 예시 중 일부 {_format_krw(1_100_000)[0]}만 언급합니다. "
        f"두 번째 예시는 {_format_krw(9_900_000)[0]}입니다.</p>"
    )
    fails = check_g_calc(body, ctx)
    assert fails == []


# Test 4: 모든 example이 부분적으로만(불완전하게) 등장 → EXAMPLE_MISSING
def test_4_all_examples_partial_fails():
    ctx = _multi_ctx(
        {"a": 1_100_000, "b": 2_200_000},
        {"c": 3_300_000, "d": 4_400_000},
    )
    body = (
        f"<p>{_format_krw(1_100_000)[0]}과 {_format_krw(3_300_000)[0]}만 "
        f"본문에 등장합니다(각 example의 두 번째 필드는 미등장).</p>"
    )
    fails = check_g_calc(body, ctx)
    assert len(fails) > 0
    assert all(f["gate"] == "G-CALC" for f in fails)


# Test 5: 모든 example이 완전히 미등장 → EXAMPLE_MISSING
def test_5_all_examples_absent_fails():
    ctx = _multi_ctx({"amount": 1_100_000}, {"amount": 9_900_000})
    body = "<p>금액 이야기가 전혀 없는 본문입니다.</p>"
    fails = check_g_calc(body, ctx)
    assert len(fails) > 0
    assert all(f["gate"] == "G-CALC" for f in fails)


# Test 6 (Case E, 의도된 동작): example[0] complete+correct,
# example[1] present-but-wrong-value → PASS.
# CALC_VALUE_VALIDATION은 Contract v1 범위 밖이므로, "다른 example의 값이
# 틀렸다"는 사실은 검출하지 않는다(STEP147/148에서 명시적으로 결정됨).
def test_6_first_complete_second_wrong_value_passes():
    ctx = _multi_ctx({"amount": 1_100_000}, {"amount": 9_900_000})
    body = (
        f"<p>지급액은 {_format_krw(1_100_000)[0]}입니다. "
        f"두 번째 사례는 잘못된 값인 1원으로 잘못 기재되어 있습니다.</p>"
    )
    fails = check_g_calc(body, ctx)
    assert fails == []


# Test 7: 모든 example이 non-checkable(0원/소액) → NO_CHECKABLE_VALUE([] 반환)
def test_7_all_examples_non_checkable_returns_empty():
    ctx = _multi_ctx({"amount": 0}, {"ratio": 9_000})
    body = "<p>이 계산기는 조건 미충족 시 0원입니다.</p>"
    fails = check_g_calc(body, ctx)
    assert fails == []


# ── 금액 표기 포맷 테스트(기존 포맷 무회귀 + 신규 공백 변형 + 억 단위 미지원 확인) ──

def test_format_comma_won_passes():
    ctx = _multi_ctx({"amount": 1_100_000})
    fails = check_g_calc("<p>지급액은 1,100,000원입니다.</p>", ctx)
    assert fails == []


def test_format_man_won_no_space_passes():
    ctx = _multi_ctx({"amount": 1_100_000})
    fails = check_g_calc("<p>지급액은 110만원입니다.</p>", ctx)
    assert fails == []


def test_format_yak_man_won_passes():
    ctx = _multi_ctx({"amount": 1_100_000})
    fails = check_g_calc("<p>지급액은 약 110만원입니다.</p>", ctx)
    assert fails == []


def test_format_man_won_space_passes():
    ctx = _multi_ctx({"amount": 1_100_000})
    fails = check_g_calc("<p>지급액은 110만 원입니다.</p>", ctx)
    assert fails == []


def test_format_raw_won_space_new_variant_passes():
    """CALCMATE-BLOG-QUALITY-STEP149에서 신규 추가된 '원' 앞 공백 표기 지원 확인."""
    ctx = _multi_ctx({"amount": 1_100_000})
    fails = check_g_calc("<p>지급액은 1,100,000 원입니다.</p>", ctx)
    assert fails == []


def test_format_eok_unit_not_supported():
    """'억' 단위 표기는 이번 Contract v1 범위에서 명시적으로 미지원임을 확인한다
    (STEP146/147/148에서 DEFERRED로 결정 — 회귀가 아니라 의도된 제약)."""
    ctx = _multi_ctx({"amount": 220_000_000})
    fails = check_g_calc("<p>취득세는 2억 2,000만원입니다.</p>", ctx)
    assert len(fails) > 0
    assert all(f["gate"] == "G-CALC" for f in fails)


# ── Duplicate Value 테스트: 자동차_취등록세_계산기 (Level 0 substring matching 유지 확인) ──

def test_duplicate_value_car_acquisition_tax_level0_behavior_unchanged():
    """자동차_취등록세_계산기는 STEP146 감사에서 2/4 example이 내부적으로 중복된
    금액(standard_acquisition_tax == acquisition_tax)을 갖는 것으로 확인된 유일한
    계산기다. 이 테스트는 그 한계를 '고치는' 것이 아니라, ANY COMPLETE 구현 이후에도
    기존 Level 0(단순 substring 매칭) 동작이 그대로 유지됨을 확인한다: 중복 값 하나만
    본문에 등장해도 해당 example의 서로 다른 두 필드가 모두 '충족'된 것으로 오인되어
    PASS 처리된다(의도된 제약 — CALC_VALUE_VALIDATION 범위 밖)."""
    calc = {"slug": "자동차_취등록세_계산기", "name": "자동차 취등록세 계산기", "category": "부동산/기타"}
    ctx = build_example_context(calc)
    assert ctx is not None and len(ctx["verified_examples"]) == 4

    result_0 = ctx["verified_examples"][0]["result"]
    assert result_0["standard_acquisition_tax"] == result_0["acquisition_tax"]
    amount = result_0["acquisition_tax"]

    # 값 하나만 한 번 언급 — 실제로는 두 개의 서로 다른 필드(과세표준/최종세액)를
    # 검증해야 하지만, Level 0 substring 매칭은 이를 구분하지 못하고 두 필드 모두
    # '등장함'으로 처리한다.
    body = f"<p>취등록세 관련 금액은 {_format_krw(amount)[0]} 하나뿐입니다.</p>"
    fails = check_g_calc(body, ctx)
    assert fails == []
