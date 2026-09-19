# -*- coding: utf-8 -*-
"""
tests/test_calculator_wp_publish.py — modules/calculator_wp_publish.py 검증

CalcMate 계산기 slug -> WordPress 신규 글 게시 wrapper(publish_calculator_post)가:
  - calculator 미존재/category 없음/WP category 미존재 시 WP POST를 절대 호출하지
    않고 명확한 오류를 반환하는지
  - 정상 경로에서 publisher.publish()에 category_name/comment_status="closed"가
    정확히 전달되어 실제 WP POST payload에 반영되는지
를 실제 WP 네트워크 호출 없이(requests.get/post 전부 monkeypatch) 검증한다.
"""
import inspect
import re
from unittest.mock import MagicMock

import pytest

from modules import calculator_wp_publish as cwp
from modules import publisher


CFG = {
    "WORDPRESS_URL": "http://wp.test",
    "WORDPRESS_USERNAME": "tester",
    "WORDPRESS_APP_PASSWORD": "app-pw",
    "DB_ADAPTER": "dual",
}


def _fake_calc(category="노무/급여", slug="severance-pay"):
    return {"id": "calc_1", "slug": slug, "name": "테스트 계산기",
            "category": category, "faq": "[]"}


def _patch_content_generation(monkeypatch, calc, captured_auto_generate: dict = None):
    """calculator 조회 + 콘텐츠 생성 부분만 대체 — WP 게시 로직(publisher)은 건드리지 않는다.

    auto_generate_all mock은 CALCMATE-BLOG-QUALITY-STEP133(Phase B)에서
    calculator_wp_publish.py가 example_context= 키워드 인자를 실제로 전달하도록
    바뀌었으므로, 그 인자를 명시적으로 받아 captured_auto_generate에 기록한다
    (**kwargs로 숨기지 않고 실제 프로덕션 시그니처와 동일하게 example_context를
    명시 파라미터로 선언 — STEP133 STEP5 지시)."""
    monkeypatch.setattr(cwp, "get_db_adapter", lambda cfg: object())
    monkeypatch.setattr(cwp, "CalculatorRepository",
                         lambda db: MagicMock(get_by_slug=lambda slug: calc))

    def _fake_auto_generate_all(cfg, c, save=False, example_context=None):
        if captured_auto_generate is not None:
            captured_auto_generate["example_context"] = example_context
            captured_auto_generate["calc"] = c
        return {
            "seo_title": "테스트 제목", "seo_description": "테스트 설명",
            "article_content": "<p>본문</p>", "faq": "[]",
        }

    monkeypatch.setattr(cwp, "auto_generate_all", _fake_auto_generate_all)
    monkeypatch.setattr(cwp, "build_blog_html",
                         lambda article, faq, calc_slug="", calc_name="": "<p>조립된 본문</p>")


class _FakeCategoriesResp:
    status_code = 200

    def __init__(self, categories):
        self._categories = categories

    def json(self):
        return self._categories


class _FakePostResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"id": 999, "link": "http://wp.test/p/999", "status": "publish"}


def _patch_wp_get_categories(monkeypatch, categories):
    monkeypatch.setattr(
        publisher.requests, "get",
        lambda url, params=None, auth=None, timeout=None: _FakeCategoriesResp(categories))


def _patch_wp_post_capture(monkeypatch, captured: dict):
    def fake_post(url, json=None, auth=None, timeout=None):
        captured["payload"] = json
        captured["called"] = True
        return _FakePostResp()
    monkeypatch.setattr(publisher.requests, "post", fake_post)


def _patch_wp_post_should_not_be_called(monkeypatch, captured: dict):
    def fake_post(*a, **k):
        captured["called"] = True
        raise AssertionError("WP POST가 호출되어서는 안 되는 경로에서 호출됨")
    monkeypatch.setattr(publisher.requests, "post", fake_post)


# ── 테스트 1: 정상 계산기(severance-pay, category=노무/급여) ──────────────
def test_case1_normal_calculator_passes_category_and_comment_status(monkeypatch):
    calc = _fake_calc(category="노무/급여", slug="severance-pay")
    _patch_content_generation(monkeypatch, calc)
    _patch_wp_get_categories(monkeypatch, [{"id": 4, "name": "노무/급여"}])
    captured = {"called": False}
    _patch_wp_post_capture(monkeypatch, captured)
    monkeypatch.setattr(publisher, "is_wordpress_ready", lambda cfg: True)

    res = cwp.publish_calculator_post("severance-pay", CFG)

    assert captured["called"] is True
    assert captured["payload"]["categories"] == [4]
    assert captured["payload"]["comment_status"] == "closed"
    assert res.get("status") == "published"


# ── 테스트 2: 잘못된 slug ──────────────────────────────────────────────
def test_case2_calculator_not_found(monkeypatch):
    monkeypatch.setattr(cwp, "get_db_adapter", lambda cfg: object())
    monkeypatch.setattr(cwp, "CalculatorRepository",
                         lambda db: MagicMock(get_by_slug=lambda slug: None))
    captured = {"called": False}
    _patch_wp_post_should_not_be_called(monkeypatch, captured)

    res = cwp.publish_calculator_post("no-such-slug", CFG)

    assert res == {"success": False, "error": "calculator_not_found", "slug": "no-such-slug"}
    assert captured["called"] is False


# ── 테스트 3: category 없음 ────────────────────────────────────────────
def test_case3_category_missing(monkeypatch):
    calc = _fake_calc(category="", slug="no-category-calc")
    monkeypatch.setattr(cwp, "get_db_adapter", lambda cfg: object())
    monkeypatch.setattr(cwp, "CalculatorRepository",
                         lambda db: MagicMock(get_by_slug=lambda slug: calc))
    captured = {"called": False}
    _patch_wp_post_should_not_be_called(monkeypatch, captured)

    res = cwp.publish_calculator_post("no-category-calc", CFG)

    assert res == {"success": False, "error": "category_missing", "slug": "no-category-calc"}
    assert captured["called"] is False


# ── 테스트 4: WP에 존재하지 않는 category ──────────────────────────────
def test_case4_wp_category_not_found(monkeypatch):
    calc = _fake_calc(category="존재하지않는카테고리", slug="ghost-calc")
    _patch_content_generation(monkeypatch, calc)
    _patch_wp_get_categories(monkeypatch, [{"id": 4, "name": "노무/급여"}])  # 일치 없음
    captured = {"called": False}
    _patch_wp_post_should_not_be_called(monkeypatch, captured)
    monkeypatch.setattr(publisher, "is_wordpress_ready", lambda cfg: True)

    res = cwp.publish_calculator_post("ghost-calc", CFG)

    assert res["success"] is False
    assert res["error"] == "category_not_found:존재하지않는카테고리"
    assert captured["called"] is False


# ── 테스트 5: comment_status는 호출자가 지정하지 않아도 항상 closed ───────
def test_case5_comment_status_always_closed_without_caller_specifying(monkeypatch):
    calc = _fake_calc(category="노무/급여", slug="severance-pay")
    _patch_content_generation(monkeypatch, calc)
    _patch_wp_get_categories(monkeypatch, [{"id": 4, "name": "노무/급여"}])
    captured = {"called": False}
    _patch_wp_post_capture(monkeypatch, captured)
    monkeypatch.setattr(publisher, "is_wordpress_ready", lambda cfg: True)

    # 호출부는 comment_status를 전혀 지정하지 않는다(slug, cfg만 전달).
    cwp.publish_calculator_post("severance-pay", CFG)

    assert captured["payload"]["comment_status"] == "closed"


# ── 테스트 6: 인증정보 하드코딩 없음 ───────────────────────────────────
def test_case6_no_hardcoded_credentials_in_wrapper_source():
    src = inspect.getsource(cwp)
    # 이 wrapper는 WP를 직접 호출하지 않는다 — requests import 자체가 없어야 한다
    # (publisher.publish()에 전부 위임).
    assert "import requests" not in src
    assert "requests.post" not in src
    assert "requests.get" not in src
    # 과거 BMI 스크립트 패턴(username/password 평문 리터럴 대입) 재현 여부 확인
    assert not re.search(r'password\s*=\s*["\']', src, re.IGNORECASE)
    assert not re.search(r'username\s*=\s*["\'][^"\']+["\']', src, re.IGNORECASE)
    # 실제 자격증명 리터럴 대입(딕셔너리 키 참조/주석상의 설정키 이름 언급은 허용)
    assert not re.search(r'app_password["\']?\s*[:=]\s*["\'][^"\']+["\']', src, re.IGNORECASE)


# ── 테스트 7~10: CALCMATE-BLOG-QUALITY-STEP133 Phase B — deterministic builder 연결 ──

def test_case7_builder_context_reaches_auto_generate_all(monkeypatch):
    """등록된 slug(severance-pay)이면 build_example_context()의 실제 반환값이
    auto_generate_all(example_context=...)까지 그대로 전달되는지 확인한다."""
    calc = _fake_calc(category="노무/급여", slug="severance-pay")
    captured = {}
    _patch_content_generation(monkeypatch, calc, captured_auto_generate=captured)
    _patch_wp_get_categories(monkeypatch, [{"id": 4, "name": "노무/급여"}])
    wp_captured = {"called": False}
    _patch_wp_post_capture(monkeypatch, wp_captured)
    monkeypatch.setattr(publisher, "is_wordpress_ready", lambda cfg: True)

    from content.calculator.example_builder import build_example_context
    expected_context = build_example_context(calc)

    cwp.publish_calculator_post("severance-pay", CFG)

    assert "example_context" in captured
    assert captured["example_context"] == expected_context
    assert expected_context is not None
    assert "verified_examples" in expected_context and "facts" in expected_context


def test_case8_unregistered_slug_passes_none_without_fallback(monkeypatch):
    """provider registry에 없는 slug는 build_example_context()가 None을 반환하고,
    calculator_wp_publish.py는 그 None을 그대로 전달할 뿐 임의 계산/fallback을
    만들지 않는다(STEP132 'unregistered slug returns None' 계약 유지 확인)."""
    calc = _fake_calc(category="노무/급여", slug="no-such-provider-slug")
    captured = {}
    _patch_content_generation(monkeypatch, calc, captured_auto_generate=captured)
    _patch_wp_get_categories(monkeypatch, [{"id": 4, "name": "노무/급여"}])
    wp_captured = {"called": False}
    _patch_wp_post_capture(monkeypatch, wp_captured)
    monkeypatch.setattr(publisher, "is_wordpress_ready", lambda cfg: True)

    res = cwp.publish_calculator_post("no-such-provider-slug", CFG)

    assert captured.get("example_context") is None
    # WP payload/게시 결과 자체는 손상되지 않아야 한다(정상 게시 흐름 유지).
    assert wp_captured["called"] is True
    assert res.get("status") == "published"


def test_case9_failure_paths_never_call_builder(monkeypatch):
    """calculator_not_found/category_missing 경로는 auto_generate_all()을 아예
    호출하지 않으므로 builder도 호출되지 않아야 한다(기존 fail-closed 계약 유지)."""
    calls = {"count": 0}
    import content.calculator.example_builder as eb
    original = eb.build_example_context

    def _counting(calc):
        calls["count"] += 1
        return original(calc)

    monkeypatch.setattr(cwp, "build_example_context", _counting)
    monkeypatch.setattr(cwp, "get_db_adapter", lambda cfg: object())
    monkeypatch.setattr(cwp, "CalculatorRepository",
                         lambda db: MagicMock(get_by_slug=lambda slug: None))

    res = cwp.publish_calculator_post("no-such-slug", CFG)

    assert res == {"success": False, "error": "calculator_not_found", "slug": "no-such-slug"}
    assert calls["count"] == 0


def test_case10_real_provider_value_matches_example_builder_directly():
    """production calculator(jeonse-vs-monthly)에 대해 calculator_wp_publish.py가
    사용하는 것과 동일한 build_example_context() 함수를 직접 호출해, STEP132에서
    검증된 deterministic 값과 이 STEP에서 연결에 쓰인 함수가 동일한 객체인지
    교차검증한다(별도 재구현/복사가 아님을 함수 identity로 증명)."""
    from content.calculator import example_builder as eb
    assert cwp.build_example_context is eb.build_example_context

    # provider는 calc['formula']를 실제로 execute_formula()에 넘겨 계산하므로,
    # STEP132에서 검증된 production formula 문자열을 그대로 채운 calc로 재현한다.
    real_formula = (
        '{"jeonse_opp_cost": "(jeonse_deposit - wolse_deposit) * rate / 100 / 12", '
        '"wolse_to_jeonse_equiv": "wolse_deposit + wolse_amount * 1200 / rate", '
        '"monthly_savings": "wolse_amount - (jeonse_deposit - wolse_deposit) * rate / 100 / 12"}'
    )
    output_schema = (
        '{"jeonse_opp_cost": "number", "wolse_to_jeonse_equiv": "number", '
        '"monthly_savings": "number"}'
    )
    calc = {"slug": "jeonse-vs-monthly", "formula": real_formula, "output_schema": output_schema}
    ctx = eb.build_example_context(calc)
    result = ctx["verified_examples"][0]["result"]
    assert result["jeonse_opp_cost"] == pytest.approx(708_333, abs=1)
    assert result["wolse_to_jeonse_equiv"] == pytest.approx(222_000_000, abs=1)
    assert result["monthly_savings"] == pytest.approx(91_667, abs=1)
