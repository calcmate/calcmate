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
