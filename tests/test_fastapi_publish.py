# -*- coding: utf-8 -*-
"""tests/test_fastapi_publish.py — STEP 18-P Article Publish/Trash 조회 API 검증.

이 파일이 검증하는 GET 3종(get_all_articles/get_publish_articles/get_trash_articles)은
여전히 완전히 READ-ONLY이며 modules.publisher를 호출하지 않는다. STEP 18-R에서
같은 라우터/서비스 파일에 Edit/Trash/Restore write 함수 3개가 정당하게 추가됐으므로
(admin 인증 뒤에서만), 이 파일의 "쓰기 endpoint가 없다"류 단언은 "GET 3종은 여전히
쓰기를 하지 않는다"로, "write surface = 2"류 단언은 test_fastapi_publish_write.py
(STEP 18-R)의 5개 기준으로 갱신한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import write_routes, collect_routes

# STEP 18-R 기준(§14) — 기존 2개 + Publish Edit/Trash/Restore 3개 = 5개.
# STEP 4-F에서 Settings General PATCH가 require_admin() 뒤에서 정당하게 추가되어 6개.
EXPECTED_WRITE_ROUTES = frozenset({
    ("/api/scheduler/blog/config", "PATCH"),
    ("/api/scheduler/blog/run-once", "POST"),
    ("/api/publish/{article_id}/edit", "POST"),
    ("/api/trash/{article_id}", "POST"),
    ("/api/trash/{article_id}/restore", "POST"),
    ("/api/settings/general", "PATCH"),
    ("/api/settings/image-google", "PATCH"),
    ("/api/calculators/{slug}/formula", "PATCH"),
    ("/api/calculators/{slug}/promote", "POST"),
    ("/api/calculators/{slug}/checklist", "PATCH"),
    ("/api/calculators/generate", "POST"),
    ("/api/calculators/{slug}/build", "POST"),
    ("/api/calculators/{slug}/deploy", "POST"),
    ("/api/calculators/{slug}/content/seo", "POST"),
    ("/api/calculators/{slug}/content/faq", "POST"),
    ("/api/calculators/{slug}/content/body", "POST"),
    ("/api/calculators/{slug}/content/image", "POST"),
    ("/api/calculators/{slug}/content/generate", "POST"),
    ("/api/calculators/generate/contract", "POST"),
    ("/api/calculators/generate/contract/slug-check", "POST"),
    ("/api/calculators/generate/contract/validate", "POST"),
    ("/api/calculators/generate/contract/{job_id}/save", "POST"),
    ("/api/calculators/{slug}/review/approve", "POST"),
    ("/api/calculators/{slug}/review/unapprove", "POST"),
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
# STEP 18-P 조회 3종 외에 이 STEP에서 정당하게 존재하는 Publish/Trash write route.
KNOWN_PUBLISH_TRASH_WRITE_ROUTES = frozenset({
    ("/api/publish/{article_id}/edit", "POST"),
    ("/api/trash/{article_id}", "POST"),
    ("/api/trash/{article_id}/restore", "POST"),
})


def _client():
    from api.main import app
    return TestClient(app)


# ── §5/§12: 기본 조회 동작 ────────────────────────────────────────────────

def test_get_publish_overview():
    r = _client().get("/api/publish")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert "total" in data
    assert "by_status" in data
    assert "articles" in data
    assert isinstance(data["articles"], list)
    assert data["total"] == len(data["articles"])
    assert sum(data["by_status"].values()) == data["total"]


def test_get_publish_articles():
    r = _client().get("/api/publish/articles")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert "articles" in data
    # dashboard.py 발행 목록 탭과 동일한 상태값 필터만 통과해야 한다.
    for a in data["articles"]:
        assert a["status"] in ("발행완료", "검수대기", "수정됨")


def test_get_trash():
    r = _client().get("/api/trash")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert "articles" in data
    for a in data["articles"]:
        assert a["status"] == "휴지통"


def test_publish_articles_are_real_db_data_not_fabricated():
    """실제 DB의 articles 테이블 카운트와 API 응답이 구조적으로 일치하는지 확인
    (하드코딩된 값이 아니라 실제 데이터를 읽었는지 실증)."""
    from modules.config_loader import load_config
    from modules.dashboard_cache import read as cache_read

    rows = cache_read(load_config(), "articles")
    expected_total = len(rows)
    expected_publish = len([r for r in rows if r.get("상태값") in ("발행완료", "검수대기", "수정됨")])
    expected_trash = len([r for r in rows if r.get("상태값") == "휴지통"])

    overview = _client().get("/api/publish").json()["data"]
    publish_list = _client().get("/api/publish/articles").json()["data"]
    trash_list = _client().get("/api/trash").json()["data"]

    assert overview["total"] == expected_total
    assert publish_list["total"] == expected_publish
    assert trash_list["total"] == expected_trash


def test_article_fields_only_use_real_columns():
    """§2: 존재하지 않는 컬럼을 추측해 만들지 않았는지 — 응답 필드가 실제
    schema에서 확인된 컬럼(ID/최종추천제목/상태값/발행일시/발행 URL/wp_post_id)
    기반의 값만 담고 있는지 필드 집합으로 확인한다."""
    r = _client().get("/api/publish")
    data = r.json()["data"]
    if data["articles"]:
        keys = set(data["articles"][0].keys())
        assert keys == {"id", "title", "status", "published_at", "url", "wp_post_id"}


# ── §6/§12: 신규 write endpoint가 없는지(기존 route collector 재사용) ─────────

def test_publish_or_trash_write_endpoints_are_exactly_the_known_step18r_set():
    """STEP 18-P 시점엔 0개였다. STEP 18-R에서 admin 전용 Edit/Trash/Restore 3개가
    정당하게 추가됐으므로, 그 3개 외에 예기치 않은 추가 write route가 없는지만 확인한다."""
    app_ = __import__("api.main", fromlist=["app"]).app
    write_paths = frozenset(write_routes(app_, prefix="/api/publish") + write_routes(app_, prefix="/api/trash"))
    assert write_paths == KNOWN_PUBLISH_TRASH_WRITE_ROUTES, f"예기치 않은 write endpoint: {write_paths - KNOWN_PUBLISH_TRASH_WRITE_ROUTES}"


def test_overall_write_surface_is_exactly_five():
    """STEP 18-R §14에서 확정한 write surface(5개)가 정확히 그대로인지 확인한다."""
    app_ = __import__("api.main", fromlist=["app"]).app
    actual = frozenset(write_routes(app_))
    assert actual == EXPECTED_WRITE_ROUTES, f"write surface가 변경됨: {sorted(actual)}"


def test_publish_and_trash_get_routes_are_registered():
    """collector가 실제로 새 route를 찾아내는지 증명 — 이 테스트가 실패하면
    라우터가 등록되지 않았거나 collector가 다시 얕은 순회로 퇴행한 것이다."""
    app_ = __import__("api.main", fromlist=["app"]).app
    found = {(r.path, m) for r in collect_routes(app_) for m in r.methods}
    assert ("/api/publish", "GET") in found
    assert ("/api/publish/articles", "GET") in found
    assert ("/api/trash", "GET") in found


# ── §13: ArticleRepository 쓰기 메서드가 호출되지 않는지 ─────────────────────

def test_no_article_repository_write_methods_called(monkeypatch):
    from repositories.article_repository import ArticleRepository

    def _boom(*a, **kw):
        raise AssertionError("ArticleRepository 쓰기 메서드가 호출되면 안 된다")

    for method in ("save", "create", "update", "update_status", "append_history", "delete", "publish"):
        if hasattr(ArticleRepository, method):
            monkeypatch.setattr(ArticleRepository, method, _boom)

    c = _client()
    for path in ("/api/publish", "/api/publish/articles", "/api/trash"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.json()["success"] is True


# ── §14: modules.publisher(WordPress REST) 함수가 호출되지 않는지 ────────────

def test_no_publisher_functions_called(monkeypatch):
    import modules.publisher as publisher

    def _boom(*a, **kw):
        raise AssertionError("modules.publisher 함수가 호출되면 안 된다 — WordPress 호출 금지")

    for fn in ("publish", "update_post", "delete_post", "restore_post", "get_post"):
        if hasattr(publisher, fn):
            monkeypatch.setattr(publisher, fn, _boom)

    c = _client()
    for path in ("/api/publish", "/api/publish/articles", "/api/trash"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.json()["success"] is True


def test_publish_router_still_does_not_import_publisher_directly():
    """라우터는 여전히 modules.publisher를 직접 import하지 않는다 — 실제 호출은
    항상 publish_service 계층을 통해서만 이뤄진다(계층 분리 유지)."""
    import ast
    import inspect
    from api.routers import publish as publish_router

    def _imports_publisher(module) -> bool:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any("publisher" in a.name for a in node.names):
                return True
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if "publisher" in mod or any(a.name == "publisher" for a in node.names):
                    return True
        return False

    assert _imports_publisher(publish_router) is False


def test_publish_service_only_imports_publisher_inside_write_functions():
    """STEP 18-R: publish_service.py는 이제 modules.publisher를 정당하게 import한다
    (Edit/Trash/Restore 구현에 필수). 다만 READ-ONLY 함수(get_all_articles/
    get_publish_articles/get_trash_articles/_articles/_summarize)의 AST 서브트리에는
    publisher 참조가 전혀 없어야 한다 — import는 오직 admin 전용 write 함수
    (edit_article/trash_article/restore_article) 안에만 있어야 한다."""
    import ast
    import inspect
    from api.services import publish_service

    READ_ONLY_FUNCS = {"_articles", "_summarize", "get_all_articles", "get_publish_articles", "get_trash_articles"}
    WRITE_FUNCS = {"edit_article", "trash_article", "restore_article"}

    tree = ast.parse(inspect.getsource(publish_service))

    def _mentions_publisher(node) -> bool:
        for n in ast.walk(node):
            if isinstance(n, ast.Import) and any("publisher" in a.name for a in n.names):
                return True
            if isinstance(n, ast.Name) and n.id == "publisher":
                return True
        return False

    found_in_read, found_in_write = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name in READ_ONLY_FUNCS and _mentions_publisher(node):
                found_in_read.append(node.name)
            if node.name in WRITE_FUNCS and _mentions_publisher(node):
                found_in_write.append(node.name)

    assert found_in_read == [], f"READ-ONLY 함수가 publisher를 참조함: {found_in_read}"
    assert set(found_in_write) == WRITE_FUNCS, f"write 함수 중 publisher를 쓰지 않는 것이 있음: {WRITE_FUNCS - set(found_in_write)}"


# ── §15: 외부 HTTP 호출 차단 ──────────────────────────────────────────────

def test_publish_endpoints_make_no_external_http_calls(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("Publish/Trash 조회 중 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)

    c = _client()
    for path in ("/api/publish", "/api/publish/articles", "/api/trash"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.json()["success"] is True


# ── XSS/보안: 시크릿 마스킹 재사용 확인 ───────────────────────────────────

def test_publish_service_reuses_existing_mask_secrets():
    from api.services.log_service import mask_secrets
    import api.services.publish_service as publish_service_module
    assert publish_service_module.mask_secrets is mask_secrets
