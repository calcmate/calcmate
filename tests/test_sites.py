# -*- coding: utf-8 -*-
"""tests/test_sites.py — STEP P2-04: Site Management 조회(READ-ONLY) React/
FastAPI 이관 검증.

dashboard.py "🌐 사이트 관리" 탭(dashboard.py:1012-1453)의 사이트 목록 표시만
검증한다. 이 파일의 테스트는 GET /api/sites(get_sites()/_project())만 다루며,
실제 write 함수는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상
monkeypatch로 대체하거나, 존재 자체를 호출하지 않았음을 구조적으로 검증한다.

STEP P2-06에서 site_service.py에 create_site()/import_sites()(정당한 write)가
추가되었다 — 그 검증은 이 파일이 아니라 tests/test_sites_create.py에서 한다.
이 파일의 write-route 관련 테스트 3개는 P2-06 반영을 위해 갱신되었다(POST 자체가
0개여야 한다는 예전 전제 대신, 딱 2개의 정당한 POST만 있어야 한다는 것으로).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "sites-test-viewer-token"
ADMIN_TOKEN = "sites-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


class _FakeRepo:
    """SiteRepository를 대체하는 가짜 — get_all()/get_wp_config()만 흉내낸다."""
    def __init__(self, rows, wp_configs=None, wp_raises=False):
        self._rows = rows
        self._wp_configs = wp_configs or {}
        self._wp_raises = wp_raises

    def get_all(self):
        return self._rows

    def get_wp_config(self, site_id):
        if self._wp_raises:
            raise RuntimeError("secrets.yaml corrupt")
        return self._wp_configs.get(site_id, {
            "WORDPRESS_URL": "", "WORDPRESS_USERNAME": "", "WORDPRESS_APP_PASSWORD": "",
        })


def _mock_repo(monkeypatch, rows, wp_configs=None, wp_raises=False):
    fake = _FakeRepo(rows, wp_configs, wp_raises)
    monkeypatch.setattr("api.services.site_service.load_config", lambda: {"FAKE": True})
    monkeypatch.setattr("api.services.site_service.get_db_adapter", lambda cfg: object())
    monkeypatch.setattr("api.services.site_service.SiteRepository", lambda db, cfg: fake)
    return fake


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_sites_without_auth_returns_401():
    r = _client().get("/api/sites")
    assert r.status_code == 401


def test_sites_as_viewer_returns_403():
    r = _client().get("/api/sites", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_sites_as_admin_returns_200(monkeypatch):
    _mock_repo(monkeypatch, [])
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 목록 shape / 계산식
# ══════════════════════════════════════════════════════════════════════════

def test_site_list_shape_and_platforms_parsed(monkeypatch):
    rows = [{
        "site_id": "site_1", "site_name": "테스트 사이트", "domain": "example.com",
        "site_type": "custom", "status": "active",
        "platforms": '["WordPress", "Calculator"]',
    }]
    _mock_repo(monkeypatch, rows, wp_configs={"site_1": {
        "WORDPRESS_URL": "http://x.test", "WORDPRESS_USERNAME": "admin", "WORDPRESS_APP_PASSWORD": "secretpw",
    }})
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    sites = r.json()["data"]["sites"]
    assert sites == [{
        "site_id": "site_1", "site_name": "테스트 사이트", "domain": "example.com",
        "site_type": "custom", "status": "active",
        "platforms": ["WordPress", "Calculator"],
        "wordpress_configured": True,
    }]


def test_platforms_field_absent_defaults_to_empty_list(monkeypatch):
    """create_site()로 생성된 site row에는 'platforms' 컬럼 자체가 없을 수 있다
    (5단계 마법사를 거치지 않은 경우) — 추측으로 채우지 않고 빈 배열이어야 한다."""
    rows = [{"site_id": "site_2", "site_name": "레거시", "domain": "legacy.com",
             "site_type": "policy", "status": "active"}]
    _mock_repo(monkeypatch, rows)
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["sites"][0]["platforms"] == []


def test_malformed_platforms_json_falls_back_to_empty_list(monkeypatch):
    rows = [{"site_id": "site_3", "site_name": "손상됨", "domain": "broken.com",
             "site_type": "custom", "status": "active", "platforms": "{not valid json"}]
    _mock_repo(monkeypatch, rows)
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["sites"][0]["platforms"] == []


def test_wordpress_configured_false_when_credentials_incomplete(monkeypatch):
    rows = [{"site_id": "site_4", "site_name": "부분설정", "domain": "partial.com",
             "site_type": "custom", "status": "active"}]
    _mock_repo(monkeypatch, rows, wp_configs={"site_4": {
        "WORDPRESS_URL": "http://x.test", "WORDPRESS_USERNAME": "", "WORDPRESS_APP_PASSWORD": "",
    }})
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["sites"][0]["wordpress_configured"] is False


def test_empty_sites_returns_empty_list_not_error(monkeypatch):
    """실제 현재 환경(sites 테이블 없음)과 동일한 상태 — 200 + 빈 배열이어야 한다."""
    _mock_repo(monkeypatch, [])
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["sites"] == []


def test_wp_config_source_error_does_not_crash_whole_response(monkeypatch):
    rows = [{"site_id": "site_5", "site_name": "정상", "domain": "ok.com",
             "site_type": "custom", "status": "active"}]
    _mock_repo(monkeypatch, rows, wp_raises=True)
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    site = r.json()["data"]["sites"][0]
    assert site["wordpress_configured"] is False
    assert site["site_name"] == "정상"


# ══════════════════════════════════════════════════════════════════════════
# 민감정보 미노출
# ══════════════════════════════════════════════════════════════════════════

def test_response_never_contains_secret_values(monkeypatch):
    rows = [{"site_id": "site_6", "site_name": "시크릿테스트", "domain": "mysite-example.com",
             "site_type": "custom", "status": "active", "platforms": '["WordPress"]'}]
    _mock_repo(monkeypatch, rows, wp_configs={"site_6": {
        "WORDPRESS_URL": "http://real-wp.example",
        "WORDPRESS_USERNAME": "realuser123",
        "WORDPRESS_APP_PASSWORD": "super-secret-app-password-xyz",
    }})
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    body_text = r.text
    for forbidden in (
        "realuser123", "super-secret-app-password-xyz", "real-wp.example",
        "password", "passwd", "secret", "api_key", "apikey", "token",
        "access_token", "refresh_token", "client_secret", "private_key",
    ):
        assert forbidden not in body_text, f"응답에 민감할 수 있는 문자열 '{forbidden}'이 포함됨"


# ══════════════════════════════════════════════════════════════════════════
# READ-ONLY 보장 + write route 부재
# ══════════════════════════════════════════════════════════════════════════

def test_get_sites_function_source_never_calls_write_functions():
    """STEP P2-06에서 site_service.py에 create_site()/import_sites()(정당한 write)가
    추가되었으므로, "모듈 전체가 write를 호출하지 않는다"는 이 테스트의 예전
    전제는 더 이상 유효하지 않다 — 이제는 get_sites()/_project()(조회 전용 경로)
    함수 자체만 떼어내어 write 관련 이름을 호출하지 않는지 확인한다."""
    import ast
    import inspect
    from api.services import site_service

    forbidden_calls = {
        "create_site", "update_site", "delete_site", "set_site_status",
        "save", "insert", "update", "delete", "upsert", "dump", "save_wp_profile",
    }
    for fn in (site_service.get_sites, site_service._project):
        source = inspect.getsource(fn)
        tree = ast.parse(source)
        called_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)
        assert called_names & forbidden_calls == set(), f"{fn.__name__}이 write 함수를 호출함: {called_names & forbidden_calls}"


def test_repository_write_methods_never_called(monkeypatch):
    """실제 SiteRepository를 흉내내되 write 메서드가 호출되면 즉시 실패하는
    스텁으로 교체해, 조회 API 호출 과정에서 write가 절대 발생하지 않음을 증명."""
    class _WriteGuardRepo:
        def __init__(self, db, cfg):
            pass
        def get_all(self):
            return [{"site_id": "s1", "site_name": "n", "domain": "d",
                      "site_type": "custom", "status": "active"}]
        def get_wp_config(self, site_id):
            return {"WORDPRESS_URL": "", "WORDPRESS_USERNAME": "", "WORDPRESS_APP_PASSWORD": ""}
        def save(self, *a, **k):
            raise AssertionError("save()가 호출되면 안 된다")
        def update(self, *a, **k):
            raise AssertionError("update()가 호출되면 안 된다")
        def delete(self, *a, **k):
            raise AssertionError("delete()가 호출되면 안 된다")
        def save_wp_profile(self, *a, **k):
            raise AssertionError("save_wp_profile()이 호출되면 안 된다")

    monkeypatch.setattr("api.services.site_service.load_config", lambda: {"FAKE": True})
    monkeypatch.setattr("api.services.site_service.get_db_adapter", lambda cfg: object())
    monkeypatch.setattr("api.services.site_service.SiteRepository", _WriteGuardRepo)
    r = _client().get("/api/sites", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200


def test_only_expected_post_routes_under_sites():
    """STEP P2-06에서 POST /api/sites(생성)와 POST /api/sites/import가, STEP
    P2-07에서 POST /api/sites/{site_id}/override와
    POST /api/sites/{site_id}/override/reset이, STEP P2-08에서 Activate/
    Deactivate/Archive/Restore POST 4개가, STEP P2-09에서 Clone POST 1개가
    정당하게 추가되었다 — 그 외의 POST는 이번 STEP 범위 밖이므로 여전히
    없어야 한다."""
    from _route_utils import write_routes
    from api.main import app
    posts = {(p, m) for p, m in write_routes(app, prefix="/api/sites") if m == "POST"}
    assert posts == {
        ("/api/sites", "POST"),
        ("/api/sites/import", "POST"),
        # SITE-PAGE-DEPLOYMENT-02: 사이트 공통 페이지 미리보기/로컬 저장/배포(require_admin)
        ("/api/sites/pages/preview", "POST"),
        ("/api/sites/pages/save", "POST"),
        ("/api/sites/pages/deploy", "POST"),
        ("/api/sites/rebuild", "POST"),  # GAP-03 전체 정적 사이트 재빌드(require_admin)
        ("/api/sites/{site_id}/override", "POST"),
        ("/api/sites/{site_id}/override/reset", "POST"),
        ("/api/sites/{site_id}/activate", "POST"),
        ("/api/sites/{site_id}/deactivate", "POST"),
        ("/api/sites/{site_id}/archive", "POST"),
        ("/api/sites/{site_id}/restore", "POST"),
        ("/api/sites/{site_id}/clone", "POST"),
    }


def test_no_put_route_under_sites_collection():
    """STEP P2-07에서 PUT /api/sites/{site_id}(개별 사이트 수정)가 정당하게
    추가되었다 — 다만 컬렉션 경로(/api/sites) 자체에는 여전히 PUT이 없어야 한다."""
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    assert not any(r.path == "/api/sites" and "PUT" in r.methods for r in routes)


def test_no_patch_route_under_sites():
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    assert not any(r.path == "/api/sites" and "PATCH" in r.methods for r in routes)


def test_no_delete_route_under_sites():
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    assert not any(r.path == "/api/sites" and "DELETE" in r.methods for r in routes)


def test_no_unexpected_write_routes_under_sites():
    """STEP P2-06 이전에는 GET만 있었다. STEP P2-06에서 POST 2개(생성/Import),
    STEP P2-07에서 PUT 1개(개별 사이트 수정)와 POST 2개(Override 저장/초기화),
    STEP P2-08에서 POST 4개(Activate/Deactivate/Archive/Restore), STEP P2-09
    에서 DELETE 1개(Hard Delete)와 POST 1개(Clone)가 정당하게 추가되어 이제
    이 11개만 존재한다. 그 외 PATCH 및 그 외 POST/PUT/DELETE는 여전히
    없어야 한다."""
    from _route_utils import write_routes
    from api.main import app
    assert set(write_routes(app, prefix="/api/sites")) == {
        ("/api/sites", "POST"),
        ("/api/sites/import", "POST"),
        # SITE-PAGE-DEPLOYMENT-02: 사이트 공통 페이지 미리보기/로컬 저장/배포(require_admin)
        ("/api/sites/pages/preview", "POST"),
        ("/api/sites/pages/save", "POST"),
        ("/api/sites/pages/deploy", "POST"),
        ("/api/sites/rebuild", "POST"),  # GAP-03 전체 정적 사이트 재빌드(require_admin)
        ("/api/sites/{site_id}", "PUT"),
        ("/api/sites/{site_id}/override", "POST"),
        ("/api/sites/{site_id}/override/reset", "POST"),
        ("/api/sites/{site_id}/activate", "POST"),
        ("/api/sites/{site_id}/deactivate", "POST"),
        ("/api/sites/{site_id}/archive", "POST"),
        ("/api/sites/{site_id}/restore", "POST"),
        ("/api/sites/{site_id}", "DELETE"),
        ("/api/sites/{site_id}/clone", "POST"),
    }
