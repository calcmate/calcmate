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


def _patch_content_generation(monkeypatch, calc):
    """calculator 조회 + 콘텐츠 생성 부분만 대체 — WP 게시 로직(publisher)은 건드리지 않는다."""
    monkeypatch.setattr(cwp, "get_db_adapter", lambda cfg: object())
    monkeypatch.setattr(cwp, "CalculatorRepository",
                         lambda db: MagicMock(get_by_slug=lambda slug: calc))
    monkeypatch.setattr(cwp, "auto_generate_all",
                         lambda cfg, c, save=False: {
                             "seo_title": "테스트 제목", "seo_description": "테스트 설명",
                             "article_content": "<p>본문</p>", "faq": "[]"})
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
