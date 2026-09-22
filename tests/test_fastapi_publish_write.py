# -*- coding: utf-8 -*-
"""tests/test_fastapi_publish_write.py — STEP 18-R Publish Edit/Trash/Restore
write endpoint 보안·순서 검증.

이 파일의 단위 테스트는 실제 WordPress 호출과 실제 DB 변경을 절대 하지 않는다
(§15). 실제 1회 통합 검증은 이 테스트 파일이 아니라 STEP 18-R 최종 보고서의
"실제 통합 검증" 섹션에서 별도로, 이 모든 단위 테스트가 PASS한 뒤에만 수행한다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

VIEWER_TOKEN = "step18r-test-viewer-token"
ADMIN_TOKEN = "step18r-test-admin-token"

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
    "ID": "test-article-published-1",
    "최종추천제목": "테스트 발행글",
    "상태값": "발행완료",
    "발행일시": "2026-01-01 00:00:00",
    "발행 URL": "http://salarymate.test/test-article/",
    "wp_post_id": "999001",
}
FAKE_TRASHED_ROW = {
    "ID": "test-article-trashed-1",
    "최종추천제목": "테스트 휴지통글",
    "상태값": "휴지통",
    "발행일시": "2026-01-01 00:00:00",
    "발행 URL": "",
    "wp_post_id": "999002",
}
FAKE_NO_WPID_ROW = {
    "ID": "test-article-no-wpid",
    "최종추천제목": "wp_post_id 없는 글",
    "상태값": "발행완료",
    "발행일시": "2026-01-01 00:00:00",
    "발행 URL": "",
    "wp_post_id": "",
}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture
def fake_articles(monkeypatch):
    """실제 DB/캐시를 건드리지 않고 publish_service._articles()가 반환하는
    행을 통제한다 — 실제 데이터 유무(예: 현재 휴지통 0건)와 무관하게 테스트가
    재현 가능하도록 한다."""
    import api.services.publish_service as svc
    rows = [FAKE_PUBLISHED_ROW, FAKE_TRASHED_ROW, FAKE_NO_WPID_ROW]
    monkeypatch.setattr(svc, "_articles", lambda: rows)
    return rows


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_publisher(monkeypatch):
    import modules.publisher as publisher

    def _boom(*a, **kw):
        raise AssertionError("modules.publisher가 호출되면 안 되는 경로에서 호출됨")

    for fn in ("update_post", "delete_post", "restore_post", "get_post"):
        monkeypatch.setattr(publisher, fn, _boom)


def _block_repo_writes(monkeypatch):
    from repositories.article_repository import ArticleRepository

    def _boom(*a, **kw):
        raise AssertionError("ArticleRepository 쓰기 메서드가 호출되면 안 되는 경로에서 호출됨")

    monkeypatch.setattr(ArticleRepository, "update_status", _boom)
    monkeypatch.setattr(ArticleRepository, "append_history", _boom)


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("외부 HTTP 호출 발생")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


# ══════════════════════════════════════════════════════════════════════════
# §15: Authentication — anonymous → 401 (publisher/repo/외부 호출 0)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/publish/any-id/edit", {"title": "x"}),
    ("POST", "/api/trash/any-id", {"confirmation": "TRASH"}),
    ("POST", "/api/trash/any-id/restore", {"confirmation": "RESTORE"}),
])
def test_anonymous_returns_401_with_zero_side_effects(method, path, body, monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    _block_external_http(monkeypatch)
    r = _client().request(method, path, json=body)
    assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# §15: Authorization — viewer → 403 (publisher/repo/외부 호출 0)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/publish/any-id/edit", {"title": "x"}),
    ("POST", "/api/trash/any-id", {"confirmation": "TRASH"}),
    ("POST", "/api/trash/any-id/restore", {"confirmation": "RESTORE"}),
])
def test_viewer_returns_403_with_zero_side_effects(method, path, body, monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    _block_external_http(monkeypatch)
    r = _client().request(method, path, json=body, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# admin + 404 (없는 리소스, publisher/repo 호출 0)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/publish/does-not-exist/edit", {"title": "x"}),
    ("POST", "/api/trash/does-not-exist", {"confirmation": "TRASH"}),
    ("POST", "/api/trash/does-not-exist/restore", {"confirmation": "RESTORE"}),
])
def test_admin_unknown_article_returns_404_with_zero_side_effects(method, path, body, monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    _block_external_http(monkeypatch)
    r = _client().request(method, path, json=body, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# admin + validation 실패(400) — publisher/repo 호출 0
# ══════════════════════════════════════════════════════════════════════════

def test_admin_edit_with_no_fields_returns_400(monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    r = _client().post(
        f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400


def test_admin_trash_wrong_confirmation_returns_400(monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    r = _client().post(
        f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "wrong"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400


def test_admin_restore_wrong_confirmation_returns_400(monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    r = _client().post(
        f"/api/trash/{FAKE_TRASHED_ROW['ID']}/restore", json={"confirmation": "wrong"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400


def test_admin_restore_non_trash_article_returns_400(monkeypatch, fake_articles):
    """§7: 휴지통 상태가 아닌 Article에는 Restore를 실행하지 않는다."""
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    r = _client().post(
        f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}/restore", json={"confirmation": "RESTORE"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400


def test_admin_action_on_article_without_wp_post_id_returns_400(monkeypatch, fake_articles):
    _block_publisher(monkeypatch)
    _block_repo_writes(monkeypatch)
    r = _client().post(
        f"/api/publish/{FAKE_NO_WPID_ROW['ID']}/edit", json={"title": "x"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400
    r2 = _client().post(
        f"/api/trash/{FAKE_NO_WPID_ROW['ID']}", json={"confirmation": "TRASH"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r2.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# §17: 성공 경로(mock) — publisher 성공 → repository 상태 업데이트 순서 검증
# ══════════════════════════════════════════════════════════════════════════

def test_admin_edit_success_updates_repo_only_after_publisher_success(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    calls = []
    monkeypatch.setattr(publisher, "update_post", lambda *a, **kw: (
        calls.append("publisher.update_post"),
        {"success": True, "wp_post_id": FAKE_PUBLISHED_ROW["wp_post_id"], "modified": "2026-01-02T00:00:00", "link": "x", "status": "publish"},
    )[1])
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: calls.append(("update_status", aid, status)))
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: calls.append(("append_history", aid, event)))

    r = _client().post(
        f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "새 제목"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert calls[0] == "publisher.update_post"
    assert calls[1] == ("update_status", FAKE_PUBLISHED_ROW["ID"], "수정됨")
    assert calls[2][0] == "append_history"


def test_admin_trash_success_calls_get_post_then_delete_then_repo(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    calls = []
    monkeypatch.setattr(publisher, "get_post", lambda *a, **kw: (calls.append("get_post"), {"success": True, "status": "publish", "title": "t", "link": "l"})[1])

    def _delete(cfg, wp_id, force=False):
        calls.append(("delete_post", force))
        assert force is False  # §6: force=True 절대 금지
        return {"success": True, "wp_post_id": wp_id, "wp_status": "trash", "force": False}

    monkeypatch.setattr(publisher, "delete_post", _delete)
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: calls.append(("update_status", status)))
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: calls.append(("append_history", event)))

    r = _client().post(
        f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "TRASH"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 200
    assert calls[0] == "get_post"
    assert calls[1] == ("delete_post", False)
    assert calls[2] == ("update_status", "휴지통")
    assert calls[3] == ("append_history", "trash")


def test_admin_restore_success_updates_repo(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from repositories.article_repository import ArticleRepository

    calls = []
    monkeypatch.setattr(publisher, "restore_post", lambda *a, **kw: (
        calls.append("restore_post"),
        {"success": True, "wp_post_id": FAKE_TRASHED_ROW["wp_post_id"], "wp_status": "publish", "already_restored": False, "title": "t", "link": "l"},
    )[1])
    monkeypatch.setattr(ArticleRepository, "update_status", lambda self, aid, status, extra=None: calls.append(("update_status", status)))
    monkeypatch.setattr(ArticleRepository, "append_history", lambda self, aid, event, extra=None: calls.append(("append_history", event)))

    r = _client().post(
        f"/api/trash/{FAKE_TRASHED_ROW['ID']}/restore", json={"confirmation": "RESTORE"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 200
    assert calls[0] == "restore_post"
    assert calls[1] == ("update_status", "발행완료")
    assert calls[2] == ("append_history", "restore")


def test_publisher_failure_leaves_repo_completely_untouched(monkeypatch, fake_articles):
    """dashboard.py의 '실패 시 로컬 미변경' 원칙 재확인."""
    import modules.publisher as publisher
    _block_repo_writes(monkeypatch)
    monkeypatch.setattr(publisher, "update_post", lambda *a, **kw: {"success": False, "error": "connection failed"})

    r = _client().post(
        f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "x"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.json()["success"] is False
    # _block_repo_writes가 assert를 발생시키지 않았다는 것 자체가 repo write 미호출의 증거.


# ══════════════════════════════════════════════════════════════════════════
# Audit event
# ══════════════════════════════════════════════════════════════════════════

def test_audit_event_recorded_on_every_admin_attempt_success_or_failure(monkeypatch, fake_articles):
    import modules.publisher as publisher
    from api.auth.service import get_audit_events

    monkeypatch.setattr(publisher, "update_post", lambda *a, **kw: {"success": False, "error": "boom"})
    _client().post(f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "x"}, headers=_auth(ADMIN_TOKEN))

    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "publish_edit"
    assert events[0].actor_role == "admin"
    assert events[0].result == "failed"
    assert events[0].resource_id == FAKE_PUBLISHED_ROW["ID"]


def test_audit_event_not_recorded_for_401_or_403():
    """인증/권한 실패는 라우트 핸들러(및 audit 기록 코드)에 도달하지 못한다."""
    from api.auth.service import get_audit_events

    _client().post(f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "x"})  # anonymous
    assert get_audit_events() == []


# ══════════════════════════════════════════════════════════════════════════
# §14: Write surface 최종 기준 — 정확히 5개
# ══════════════════════════════════════════════════════════════════════════

def test_write_surface_is_exactly_five_routes():
    from api.main import app
    actual = frozenset(write_routes(app))
    assert actual == EXPECTED_WRITE_ROUTES, f"write surface 불일치: {sorted(actual)}"


def test_no_put_or_delete_routes_anywhere():
    """STEP P2-07에서 PUT /api/sites/{site_id}(개별 사이트 수정)가, STEP P2-09에서
    DELETE /api/sites/{site_id}(Hard Delete)가 require_admin() 뒤에서 정당하게
    추가되었다 — 그 외에는 여전히 PUT/DELETE가 없어야 한다."""
    from api.main import app
    routes = collect_routes(app)
    assert [r for r in routes if "PUT" in r.methods] == [
        r for r in routes if r.path == "/api/sites/{site_id}" and "PUT" in r.methods
    ]
    assert [r for r in routes if "DELETE" in r.methods] == [
        r for r in routes if r.path == "/api/sites/{site_id}" and "DELETE" in r.methods
    ]


def test_no_extra_publish_trash_write_routes_beyond_the_three():
    from api.main import app
    w = set(write_routes(app, prefix="/api/publish")) | set(write_routes(app, prefix="/api/trash"))
    assert w == {
        ("/api/publish/{article_id}/edit", "POST"),
        ("/api/trash/{article_id}", "POST"),
        ("/api/trash/{article_id}/restore", "POST"),
    }


# ══════════════════════════════════════════════════════════════════════════
# §18: 외부 HTTP 차단 — 401/403/400/404 경로에서 requests가 전혀 호출되지 않음
# ══════════════════════════════════════════════════════════════════════════

def test_no_external_http_on_any_rejected_path(monkeypatch, fake_articles):
    _block_external_http(monkeypatch)
    c = _client()
    c.post(f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "x"})  # 401
    c.post(f"/api/publish/{FAKE_PUBLISHED_ROW['ID']}/edit", json={"title": "x"}, headers=_auth(VIEWER_TOKEN))  # 403
    c.post("/api/publish/unknown/edit", json={"title": "x"}, headers=_auth(ADMIN_TOKEN))  # 404
    c.post(f"/api/trash/{FAKE_PUBLISHED_ROW['ID']}", json={"confirmation": "nope"}, headers=_auth(ADMIN_TOKEN))  # 400
