# -*- coding: utf-8 -*-
"""tests/test_step18s_integration_readiness.py — STEP 18-S 실제 통합검증
환경 준비상태 진단 (READ-ONLY).

이 파일은 실제 WordPress Write API를 호출하지 않는다(§4 — STEP 18-R에서 이미
salarymate.test:80 ConnectionRefusedError를 확인했으므로 재시도하지 않는다).
네트워크 연결 시도조차 하지 않는다 — WORDPRESS_URL 문자열 파싱만으로 환경을
판정한다. Trash/Restore의 "성공 경로"는 전부 modules.publisher를 monkeypatch한
mock으로만 검증하며, 어떤 실제 DB row도 만들거나 저장하지 않는다(가짜 in-memory
row만 사용, STEP 18-R의 fake_articles fixture와 동일한 패턴).
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

# RFC 2606 예약 TLD(.test/.example/.invalid/.localhost) + 사설/루프백 호스트.
RESERVED_TEST_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")

EXPECTED_WRITE_ROUTES = frozenset({
    ("/api/scheduler/blog/config", "PATCH"),
    ("/api/scheduler/blog/run-once", "POST"),
    ("/api/publish/{article_id}/edit", "POST"),
    ("/api/trash/{article_id}", "POST"),
    ("/api/trash/{article_id}/restore", "POST"),
    # STEP 4-F: Settings General PATCH가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/settings/general", "PATCH"),
    ("/api/settings/image-google", "PATCH"),
    # STEP 4-G: Calculator Formula PATCH가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/formula", "PATCH"),
    # STEP 4-H-1: Calculator promote POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/promote", "POST"),
    # STEP 4-H-2: Calculator checklist PATCH가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/checklist", "PATCH"),
    # STEP 4-H-5: Calculator 생성(Mode A) POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/generate", "POST"),
    # P0-2: Calculator build/deploy POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/build", "POST"),
    ("/api/calculators/{slug}/deploy", "POST"),
    # P0-4: Calculator 콘텐츠 생성(SEO/FAQ/본문/이미지/전체) POST 5개가 require_admin()
    # 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/content/seo", "POST"),
    ("/api/calculators/{slug}/content/faq", "POST"),
    ("/api/calculators/{slug}/content/body", "POST"),
    ("/api/calculators/{slug}/content/image", "POST"),
    ("/api/calculators/{slug}/content/generate", "POST"),
    # P0-5: Mode B(Contract 기반 생성) POST 4개가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/generate/contract", "POST"),
    ("/api/calculators/generate/contract/slug-check", "POST"),
    ("/api/calculators/generate/contract/validate", "POST"),
    ("/api/calculators/generate/contract/{job_id}/save", "POST"),
    # STEP S1: Human Review Approval POST 2개가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/calculators/{slug}/review/approve", "POST"),
    ("/api/calculators/{slug}/review/unapprove", "POST"),
    # STEP S3: 실질 헬스체크(외부 서비스) 재실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/health/external/run", "POST"),
    ("/api/costs/resume", "POST"),
    ("/api/costs/retry", "POST"),
    ("/api/costs/remove", "POST"),
    ("/api/strategy-room/run", "POST"),
    ("/api/scheduler/content-sync/run-once", "POST"),
    ("/api/scheduler/calculator/run-once", "POST"),
    ("/api/scheduler/pipeline/run-once", "POST"),
    ("/api/scheduler/integrated/run-once", "POST"),
    ("/api/sites", "POST"),
    ("/api/sites/import", "POST"),
    ("/api/sites/{site_id}", "PUT"),
    ("/api/sites/{site_id}/override", "POST"),
    ("/api/sites/{site_id}/override/reset", "POST"),
    ("/api/sites/{site_id}/activate", "POST"),
    ("/api/sites/{site_id}/deactivate", "POST"),
    ("/api/sites/{site_id}/archive", "POST"),
    ("/api/sites/{site_id}/restore", "POST"),
    ("/api/sites/{site_id}", "DELETE"),
    ("/api/sites/{site_id}/clone", "POST"),
    # CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01:
    # Publishing Policy/Auto Publishing PATCH 2개가 require_admin() 뒤에서
    # 정당하게 추가됨(§WRITE-SURFACE-FIX-01).
    ("/api/scheduler/publishing-policy", "PATCH"),
    ("/api/scheduler/auto-publishing", "PATCH"),
})

FAKE_PUBLISHED_ROW = {
    "ID": "s18s-published-1", "최종추천제목": "진단용 발행글", "상태값": "발행완료",
    "발행일시": "2026-01-01 00:00:00", "발행 URL": "http://salarymate.test/x/", "wp_post_id": "999101",
}
FAKE_TRASHED_ROW = {
    "ID": "s18s-trashed-1", "최종추천제목": "진단용 휴지통글", "상태값": "휴지통",
    "발행일시": "2026-01-01 00:00:00", "발행 URL": "", "wp_post_id": "999102",
}


def _client():
    from api.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", "s18s-viewer")
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", "s18s-admin")
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture
def fake_articles(monkeypatch):
    import api.services.publish_service as svc
    rows = [FAKE_PUBLISHED_ROW, FAKE_TRASHED_ROW]
    monkeypatch.setattr(svc, "_articles", lambda: rows)
    return rows


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
# §2/§3: WORDPRESS_URL 출처 및 환경 판정 (문자열 파싱만, 네트워크 호출 없음)
# ══════════════════════════════════════════════════════════════════════════

def _wordpress_url() -> str:
    from modules.config_loader import load_config
    cfg = load_config()
    return (cfg.get("WORDPRESS_URL") or "").strip()


def test_wordpress_url_is_read_from_config_not_hardcoded():
    """publisher.py 어디에도 URL이 하드코딩되어 있지 않고 cfg["WORDPRESS_URL"]만
    사용하는지 소스에서 확인한다(AST 기준, credential 값은 다루지 않음)."""
    import ast
    import inspect
    import modules.publisher as publisher

    tree = ast.parse(inspect.getsource(publisher))
    literal_urls = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "://" in n.value
    ]
    assert literal_urls == [], f"publisher.py에 하드코딩된 URL 리터럴 발견: {literal_urls}"


def test_wordpress_url_hostname_scheme_port():
    """§3: hostname/scheme/port만 확인한다. credential은 다루지 않는다(URL 자체에
    없음 — 인증은 별도 WORDPRESS_USERNAME/APP_PASSWORD를 통해서만 이뤄진다)."""
    url = _wordpress_url()
    parsed = urlparse(url)
    assert parsed.scheme in ("http", "https")
    assert parsed.hostname, "hostname이 비어있음"
    # port 확인만(값 자체를 assert하지 않고 존재 형태만 기록) — 없으면 scheme 기본 포트.
    _ = parsed.port


def test_wordpress_url_is_reserved_test_domain():
    """salarymate.test는 RFC 2606 예약 .test TLD다 — 실제 공인 인터넷에 존재할 수
    없는 로컬 개발용 도메인이므로 REAL_INTEGRATION_ENV = NO로 판정한다."""
    url = _wordpress_url()
    hostname = (urlparse(url).hostname or "").lower()
    is_reserved = hostname.endswith(RESERVED_TEST_SUFFIXES) or hostname in LOOPBACK_HOSTS
    assert hostname == "salarymate.test"
    assert is_reserved is True, f"REAL_INTEGRATION_ENV 판정 대상 hostname이 예상과 다름: {hostname}"


def test_no_network_call_made_during_diagnosis(monkeypatch):
    """§4: 이 진단 과정 자체가 어떤 네트워크 호출도 만들지 않는지 확인한다
    (requests/socket 둘 다 차단)."""
    import requests
    import socket

    def _boom(*a, **kw):
        raise AssertionError("진단 중 네트워크 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    url = _wordpress_url()
    hostname = (urlparse(url).hostname or "").lower()
    assert hostname == "salarymate.test"


# ══════════════════════════════════════════════════════════════════════════
# §5: Publisher 함수 구조(signature) 확인 — 실행하지 않음
# ══════════════════════════════════════════════════════════════════════════

def test_publisher_function_signatures_match_documented_contract():
    import inspect
    import modules.publisher as publisher

    sig_update = inspect.signature(publisher.update_post)
    assert list(sig_update.parameters) == ["cfg", "wp_post_id", "title", "content", "excerpt"]

    sig_get = inspect.signature(publisher.get_post)
    assert list(sig_get.parameters) == ["cfg", "wp_post_id"]

    sig_delete = inspect.signature(publisher.delete_post)
    assert list(sig_delete.parameters) == ["cfg", "wp_post_id", "force"]
    assert sig_delete.parameters["force"].default is False

    sig_restore = inspect.signature(publisher.restore_post)
    assert list(sig_restore.parameters) == ["cfg", "wp_post_id"]


# ══════════════════════════════════════════════════════════════════════════
# §6/§7: Trash → Restore 상태 흐름(코드 레벨, 실제 저장 없음)
# ══════════════════════════════════════════════════════════════════════════

def test_trash_flow_publisher_before_repository_write(monkeypatch, fake_articles):
    """Trash 성공 전에는 update_status가 절대 호출되지 않고, get_post → delete_post →
    update_status("휴지통") → append_history 순서가 정확히 지켜지는지 확인한다."""
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    order = []
    monkeypatch.setattr(publisher, "get_post", lambda *a, **kw: (order.append("get_post"), {"success": True, "status": "publish", "title": "t", "link": "l"})[1])
    monkeypatch.setattr(publisher, "delete_post", lambda cfg, wp_id, force=False: (order.append(f"delete_post(force={force})"), {"success": True, "wp_post_id": wp_id, "wp_status": "trash", "force": False})[1])
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: order.append(f"update_status({status})"))
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: order.append(f"append_history({event})"))

    r = _client().post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "TRASH"}, headers=_auth("s18s-admin"))
    assert r.status_code == 200
    assert order == ["get_post", "delete_post(force=False)", "update_status(휴지통)", "append_history(trash)"]


def test_restore_flow_requires_local_trash_status_before_publisher_call(monkeypatch, fake_articles):
    """Restore 대상은 로컬 상태값이 '휴지통'이어야 한다 — 아니면 publisher를
    호출하기도 전에 400으로 거부되어야 한다(로컬 게이트가 WP 호출보다 먼저)."""
    import modules.publisher as publisher

    def _boom(*a, **kw):
        raise AssertionError("휴지통이 아닌 article에 대해 publisher가 호출됨")

    monkeypatch.setattr(publisher, "restore_post", _boom)
    r = _client().post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}/restore", json={"confirmation": "RESTORE"}, headers=_auth("s18s-admin"))
    assert r.status_code == 400


def test_restore_flow_publisher_before_repository_write(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    order = []
    monkeypatch.setattr(publisher, "restore_post", lambda cfg, wp_id: (order.append("restore_post"), {"success": True, "wp_post_id": wp_id, "wp_status": "publish", "already_restored": False, "title": "t", "link": "l"})[1])
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: order.append(f"update_status({status})"))
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: order.append(f"append_history({event})"))

    r = _client().post(f"/api/trash/{FAKE_TRASHED_ROW['ID']}/restore", json={"confirmation": "RESTORE"}, headers=_auth("s18s-admin"))
    assert r.status_code == 200
    assert order == ["restore_post", "update_status(발행완료)", "append_history(restore)"]


# ══════════════════════════════════════════════════════════════════════════
# §7: A/B/C 실제 검증 가능성 판정
# ══════════════════════════════════════════════════════════════════════════

def test_readiness_a_admin_token_usable():
    """A: admin token 메커니즘이 실제로 동작하는지(환경변수 설정 시 인증 통과)."""
    r = _client().get("/api/auth/me", headers=_auth("s18s-admin"))
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "admin"


def test_readiness_b_wordpress_unreachable_per_step18r():
    """B: STEP 18-R에서 이미 실측된 salarymate.test:80 ConnectionRefusedError를
    재확인(재시도 없이 hostname 판정만으로) — REAL_INTEGRATION_ENV = NO."""
    hostname = (urlparse(_wordpress_url()).hostname or "").lower()
    assert hostname == "salarymate.test"  # STEP 18-R에서 도달 불가 실측된 그 호스트와 동일


def test_readiness_c_real_articles_with_wp_post_id_exist():
    """C: 실제 DB에 wp_post_id가 있는 article이 존재하는지(진짜 데이터, mock 아님)."""
    from modules.config_loader import load_config
    from modules.dashboard_cache import read as cache_read

    rows = cache_read(load_config(), "articles")
    with_wp_id = [r for r in rows if str(r.get("wp_post_id", "") or "").strip()]
    assert len(with_wp_id) > 0, "wp_post_id가 있는 실제 article이 하나도 없음"


# ══════════════════════════════════════════════════════════════════════════
# §10: 실패 경로 — publisher/repository 호출 0 확인(핵심만 재확인, 상세는
# STEP 18-R의 tests/test_fastapi_publish_write.py가 24개로 이미 전담)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("token,expected_status", [(None, 401), ("s18s-viewer", 403)])
def test_unauthorized_or_forbidden_calls_zero_side_effects(token, expected_status, monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    def _boom(*a, **kw):
        raise AssertionError("인증/권한 실패 경로에서 side effect가 발생함")

    for fn in ("update_post", "delete_post", "restore_post", "get_post"):
        monkeypatch.setattr(publisher, fn, _boom)
    monkeypatch.setattr(ArticleRepository, "update_status", _boom)
    monkeypatch.setattr(ArticleRepository, "append_history", _boom)

    headers = _auth(token) if token else {}
    r = _client().post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "TRASH"}, headers=headers)
    assert r.status_code == expected_status


def test_confirmation_mismatch_zero_side_effects(monkeypatch, fake_articles):
    import modules.publisher as publisher

    def _boom(*a, **kw):
        raise AssertionError("confirmation 불일치인데 publisher가 호출됨")

    for fn in ("delete_post", "get_post"):
        monkeypatch.setattr(publisher, fn, _boom)
    r = _client().post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "WRONG"}, headers=_auth("s18s-admin"))
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# §11: Write surface — 이번 STEP에서 추가/삭제 없음
# ══════════════════════════════════════════════════════════════════════════

def test_write_surface_unchanged_at_five():
    app = __import__("api.main", fromlist=["app"]).app
    assert frozenset(write_routes(app)) == EXPECTED_WRITE_ROUTES


# ══════════════════════════════════════════════════════════════════════════
# §12: Audit — mock 성공/실패 둘 다 기록되고 credential 필드가 없는지
# ══════════════════════════════════════════════════════════════════════════

def test_audit_recorded_for_mock_trash_success_without_credentials(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository
    from api.auth.service import get_audit_events

    monkeypatch.setattr(publisher, "get_post", lambda *a, **kw: {"success": True, "status": "publish", "title": "t", "link": "l"})
    monkeypatch.setattr(publisher, "delete_post", lambda *a, **kw: {"success": True, "wp_post_id": "999101", "wp_status": "trash", "force": False})
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: None)
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: None)

    _client().post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "TRASH"}, headers=_auth("s18s-admin"))
    events = get_audit_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.action == "trash"
    assert ev.result == "success"
    payload = f"{ev.actor_id}{ev.actor_role}{ev.action}{ev.resource}{ev.resource_id}{ev.result}"
    for secret_word in ("s18s-admin", "token", "Authorization", "password", "secret", "credential"):
        assert secret_word.lower() not in payload.lower()


# ══════════════════════════════════════════════════════════════════════════
# §14: 외부 호출 전체 차단 확인(진단 테스트 스위트 전체)
# ══════════════════════════════════════════════════════════════════════════

def test_entire_diagnosis_suite_makes_no_external_http_calls(monkeypatch, fake_articles):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("진단 테스트 도중 외부 HTTP 호출 발생")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)

    c = _client()
    c.get("/api/auth/me", headers=_auth("s18s-admin"))
    c.post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "WRONG"}, headers=_auth("s18s-admin"))
    c.post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}/restore", json={"confirmation": "RESTORE"})  # anonymous
