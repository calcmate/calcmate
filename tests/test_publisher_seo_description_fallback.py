# -*- coding: utf-8 -*-
"""
tests/test_publisher_seo_description_fallback.py — P6B-5

modules/publisher.py:_wordpress_api()의 excerpt payload 구성이
meta_description(Legacy M1 경로) → seo_description(Blog/Calculator Line 경로)
순서로 fallback 하는지 검증한다(P6B-1 데이터 유실 버그 수정 확인).
"""
import pytest

from modules import publisher


CFG = {
    "WORDPRESS_URL": "http://wp.test",
    "WORDPRESS_USERNAME": "tester",
    "WORDPRESS_APP_PASSWORD": "app-pw",
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"id": 1, "link": "http://wp.test/p/1", "status": "publish", "date": "2026-08-22T00:00:00"}


def _capture_payload(monkeypatch):
    captured = {}

    def fake_post(url, json=None, auth=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(json)

    monkeypatch.setattr(publisher.requests, "post", fake_post)
    return captured


# ── Case A~D: excerpt fallback 로직 ──

def test_case_a_legacy_meta_description_preserved(monkeypatch):
    """meta_description(Legacy)이 있으면 그대로 사용, seo_description 무시."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "meta_description": "레거시 설명", "seo_description": "블로그 설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert captured["payload"]["excerpt"] == "레거시 설명"


def test_case_b_blog_seo_description_used_when_no_meta_description(monkeypatch):
    """meta_description이 없으면 seo_description을 사용(Blog/Calculator Line 정상 전달)."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "seo_description": "블로그 설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert captured["payload"]["excerpt"] == "블로그 설명"


def test_case_c_neither_key_present_returns_empty(monkeypatch):
    """둘 다 없으면 빈 문자열, 예외 발생하지 않음(기존 동작과 동일)."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert captured["payload"]["excerpt"] == ""


def test_case_d_empty_meta_description_falls_back_to_seo_description(monkeypatch):
    """meta_description이 빈 문자열이면 없는 것으로 취급하고 seo_description 사용."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "meta_description": "", "seo_description": "블로그 설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert captured["payload"]["excerpt"] == "블로그 설명"


# ── STEP5: WP REST payload 필드 검증(실제 API 호출 없음, requests.post mock) ──

def test_payload_excerpt_field_is_wordpress_native_field(monkeypatch):
    """description 값이 WordPress REST가 인식하는 'excerpt' 필드로 전달됨을 확인."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "seo_description": "블로그 설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    payload = captured["payload"]
    assert "excerpt" in payload
    assert payload["excerpt"] == "블로그 설명"
    # title 필드는 기존 로직 그대로 영향받지 않아야 한다
    assert payload["title"] == "제목"


def test_payload_no_network_call_made_beyond_mocked_post(monkeypatch):
    """이 테스트는 requests.post를 완전히 대체하므로 실제 WordPress에 요청을 보내지 않는다."""
    calls = []

    def fake_post(url, json=None, auth=None, timeout=None):
        calls.append(url)
        return _FakeResponse(json)

    monkeypatch.setattr(publisher.requests, "post", fake_post)
    seo = {"seo_title": "제목", "seo_description": "블로그 설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert len(calls) == 1
    assert calls[0].startswith("http://wp.test")


# ── STEP125: WP POST payload slug 지원(하위호환 조건부 추가) ──

def test_slug_present_included_in_payload(monkeypatch):
    """seo에 slug가 있으면 payload에 그대로 포함된다."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "seo_description": "설명", "slug": "severance-pay"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert captured["payload"]["slug"] == "severance-pay"


def test_slug_absent_payload_unchanged_backward_compatible(monkeypatch):
    """기존 호출자(main.py/retry_queue.py)처럼 slug를 전달하지 않으면
    payload에 'slug' 키 자체가 생기지 않아 기존 동작과 완전히 동일하다."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "seo_description": "설명"}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert "slug" not in captured["payload"]


def test_slug_empty_string_not_included(monkeypatch):
    """slug가 빈 문자열이면(조건부 로직) payload에 포함되지 않는다."""
    captured = _capture_payload(monkeypatch)
    seo = {"seo_title": "제목", "seo_description": "설명", "slug": ""}
    publisher._wordpress_api(seo, "<p>본문</p>", {}, CFG)
    assert "slug" not in captured["payload"]
