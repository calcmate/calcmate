# -*- coding: utf-8 -*-
"""tests/test_sites_delete_clone.py — STEP P2-09: Site Management Hard
Delete/Clone React/FastAPI 이관 검증.

dashboard.py "⛔ 영구 삭제"(dashboard.py:1402-1409)와 "📑 복제(Clone)"
(dashboard.py:1411-1433)와 동일한 실행 의미를 검증한다. 실제 운영 DB/
secrets.yaml/config.yaml은 이 파일의 어떤 테스트에서도 건드리지 않는다 —
전부 isolated tmp_path에서만 실행한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "sites-delclone-test-viewer-token"
ADMIN_TOKEN = "sites-delclone-test-admin-token"


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


def _delete(client, path, **kw):
    """TestClient.delete()는 이 httpx 버전에서 json= kwarg를 받지 않는다 —
    .request("DELETE", ...)로 우회한다."""
    return client.request("DELETE", path, **kw)


def _isolated_cfg(tmp_path):
    return {"_root": str(tmp_path), "DB_ADAPTER": "sqlite", "SQLITE_PATH": "data/blog_auto.db"}


def _mock_isolated(monkeypatch, tmp_path):
    cfg = _isolated_cfg(tmp_path)
    monkeypatch.setattr("api.services.site_service.load_config", lambda: dict(cfg))
    return cfg


def _seed_site(tmp_path, type_label="계산기", **overrides):
    from adapters.db.factory import get_db_adapter
    from repositories.site_repository import SiteRepository
    from modules.site_wizard import create_site

    cfg = _isolated_cfg(tmp_path)
    site_name = overrides.pop("site_name", "삭제복제픽스처사이트")
    domain = overrides.pop("domain", "delclone-fixture.example.com")
    fields = {"site_name": site_name, "domain": domain, **overrides}
    ok, msg = create_site(cfg, type_label, fields)
    assert ok, msg
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = next(r for r in repo.get_all() if r.get("domain") == domain)
    return row.get("site_id", "")


def _row(tmp_path, site_id):
    from adapters.db.factory import get_db_adapter
    from repositories.site_repository import SiteRepository
    cfg = _isolated_cfg(tmp_path)
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return repo.get_by_id(site_id)


def _all_rows(tmp_path):
    from adapters.db.factory import get_db_adapter
    from repositories.site_repository import SiteRepository
    cfg = _isolated_cfg(tmp_path)
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    return repo.get_all()


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_delete_without_auth_returns_401():
    r = _delete(_client(), "/api/sites/whatever", json={"confirmation": "DELETE"})
    assert r.status_code == 401


def test_delete_as_viewer_returns_403():
    r = _delete(_client(), "/api/sites/whatever", json={"confirmation": "DELETE"}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_clone_without_auth_returns_401():
    r = _client().post("/api/sites/whatever/clone", json={"site_name": "x", "domain": "x.com"})
    assert r.status_code == 401


def test_clone_as_viewer_returns_403():
    r = _client().post("/api/sites/whatever/clone", json={"site_name": "x", "domain": "x.com"},
                        headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# Hard Delete
# ══════════════════════════════════════════════════════════════════════════

def test_delete_as_admin_with_correct_confirmation_succeeds(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _delete(_client(), f"/api/sites/{site_id}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["data"]["deleted"] is True


def test_delete_row_actually_removed_from_db(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    assert _row(tmp_path, site_id) is not None
    _client().request("DELETE", f"/api/sites/{site_id}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    assert _row(tmp_path, site_id) is None


def test_delete_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _delete(_client(), "/api/sites/does-not-exist", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_delete_wrong_confirmation_returns_validation_error_and_does_not_delete(monkeypatch, tmp_path):
    """원본은 텍스트 입력이 정확히 "DELETE"와 일치해야만 실행된다
    (dashboard.py:1403-1410) — 서버도 동일하게 확인한다."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _delete(_client(), f"/api/sites/{site_id}", json={"confirmation": "delete"}, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert _row(tmp_path, site_id) is not None  # 삭제되지 않아야 함


def test_delete_missing_confirmation_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _delete(_client(), f"/api/sites/{site_id}", json={}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_delete_unknown_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _delete(_client(), f"/api/sites/{site_id}", json={"confirmation": "DELETE", "extra": "x"},
                headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_delete_does_not_affect_other_site_rows(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_a = _seed_site(tmp_path, site_name="사이트A", domain="a.example.com")
    site_b = _seed_site(tmp_path, site_name="사이트B", domain="b.example.com")
    _client().request("DELETE", f"/api/sites/{site_a}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    assert _row(tmp_path, site_a) is None
    assert _row(tmp_path, site_b) is not None
    assert _row(tmp_path, site_b).get("site_name") == "사이트B"


def test_delete_leaves_wordpress_profile_orphaned_in_secrets(monkeypatch, tmp_path):
    """발견사항(원본 그대로 재현): delete_site()는 secrets.yaml의
    wordpress_profiles를 전혀 지우지 않는다 — 삭제 후에도 프로필이 고아로
    남는다. 이 STEP에서 새 cleanup을 추가하지 않는다."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path, type_label="블로그", domain="wpblog.example.com",
                          wp_url="https://wpblog.example.com", wp_user="admin", wp_app_password="secret-pw-1")
    secrets_path = tmp_path / "config" / "secrets.yaml"
    before = secrets_path.read_text(encoding="utf-8")
    assert "wp_" in before  # 프로필이 실제로 기록되었는지 확인

    _client().request("DELETE", f"/api/sites/{site_id}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))

    after = secrets_path.read_text(encoding="utf-8")
    assert before == after, "delete_site()가 secrets.yaml을 건드리면 안 된다(원본에 그런 코드가 없음)"


def test_delete_never_touches_config_yaml(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    config_path = tmp_path / "config" / "config.yaml"
    before = config_path.read_bytes() if config_path.exists() else None
    _client().request("DELETE", f"/api/sites/{site_id}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    after = config_path.read_bytes() if config_path.exists() else None
    assert before == after


def test_delete_response_never_contains_secret_looking_strings(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path, type_label="블로그", domain="wpblog2.example.com",
                          wp_url="https://wpblog2.example.com", wp_user="admin", wp_app_password="secret-pw-2")
    r = _client().request("DELETE", f"/api/sites/{site_id}", json={"confirmation": "DELETE"}, headers=_auth(ADMIN_TOKEN))
    text = r.text
    for forbidden in ("password", "passwd", "app_password", "secret-pw-2", "api_key", "apikey", "token"):
        assert forbidden not in text, f"응답에 '{forbidden}' 포함됨"


def _source_body_without_docstring(fn):
    """inspect.getsource()는 docstring도 포함하는데, docstring 설명 문장 안에서
    같은 단어가 우연히 등장할 수 있다(P2-06/P2-07에서 이미 겪은 자체 테스트
    버그와 동일 패턴) — 실제 코드가 그 이름을 "호출/참조"하는지만 보기 위해
    함수 본문에서 첫 docstring 노드를 제거한 소스만 남긴다."""
    import ast
    import inspect
    source = inspect.getsource(fn)
    tree = ast.parse(source)
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant) and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]
    return ast.unparse(func)


def test_service_source_delete_never_touches_out_of_scope_data():
    from api.services import site_service
    source = _source_body_without_docstring(site_service.delete_site_hard)
    for forbidden in ("secrets.yaml", "config.yaml", "_secrets_path", "save_wp_profile",
                       "calculators", "articles", "registry", "HOLD", "pending_posts", "cost_state"):
        assert forbidden not in source, f"delete_site_hard가 범위 밖 데이터({forbidden})를 참조함"


# ══════════════════════════════════════════════════════════════════════════
# Clone
# ══════════════════════════════════════════════════════════════════════════

def test_clone_as_admin_creates_new_site(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본사이트", domain="source.example.com",
                            category="원본태그")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "원본사이트 (복사본)", "domain": "clone.example.com"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True
    data = r.json()["data"]
    assert data["site_name"] == "원본사이트 (복사본)"
    assert data["domain"] == "clone.example.com"
    assert data["site_id"] != source_id


def test_clone_missing_source_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/clone", json={"site_name": "x", "domain": "x.com"},
                        headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_clone_copies_only_tags_and_ai_profiles(monkeypatch, tmp_path):
    """원본 dashboard.py:1425-1430 재확인 — site_tags/research_ai/writing_ai/
    review_ai 4개만 복사되고, 나머지(status/platforms 등)는 create_site()의
    기본값을 따른다(복사되지 않음)."""
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본2", domain="source2.example.com",
                            category="복사될태그", research_ai="claude_opus",
                            writing_ai="gemini_pro", review_ai="claude_haiku")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "원본2 (복사본)", "domain": "clone2.example.com"},
                        headers=_auth(ADMIN_TOKEN))
    cloned_id = r.json()["data"]["site_id"]
    cloned_row = _row(tmp_path, cloned_id)
    assert cloned_row.get("site_tags") == "복사될태그"
    assert cloned_row.get("research_ai") == "claude_opus"
    assert cloned_row.get("writing_ai") == "gemini_pro"
    assert cloned_row.get("review_ai") == "claude_haiku"
    # status는 create_site()의 기본값("active")을 따른다 — 원본 status와 무관.
    assert cloned_row.get("status") == "active"


def test_clone_does_not_modify_source_site(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본3", domain="source3.example.com")
    before = dict(_row(tmp_path, source_id))
    _client().post(f"/api/sites/{source_id}/clone",
                    json={"site_name": "원본3 (복사본)", "domain": "clone3.example.com"},
                    headers=_auth(ADMIN_TOKEN))
    after = dict(_row(tmp_path, source_id))
    assert before == after


def test_clone_duplicate_domain_returns_validation_error(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본4", domain="source4.example.com")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "새이름", "domain": "source4.example.com"},  # 원본과 동일 도메인
                        headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "중복 도메인" in body["error"]["message"]


def test_clone_duplicate_name_returns_validation_error(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본5", domain="source5.example.com")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "원본5", "domain": "different.example.com"},  # 원본과 동일 이름
                        headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "중복 사이트명" in body["error"]["message"]


def test_clone_does_not_copy_wordpress_credentials(monkeypatch, tmp_path):
    """원본은 WordPress 자격증명을 절대 복사하지 않고 항상 새로 입력받는다
    (dashboard.py:1419-1423, "복제 시 재입력" 캡션). Clone 요청에 WP 필드를
    비워서 보내면(needs_wp 유형이라도) 소스의 자격증명이 재사용되지 않고
    create_site()의 필수값 검증을 그대로 통과한다."""
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, type_label="블로그", domain="wpsource.example.com",
                            wp_url="https://wpsource.example.com", wp_user="admin", wp_app_password="orig-secret")
    # WP 필드를 비운 채 clone 요청 — needs_wp 유형(블로그)이므로 원본과 동일하게 실패해야 한다.
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "wp복제", "domain": "wpclone.example.com"},
                        headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "필수값 누락" in body["error"]["message"]


def test_clone_with_fresh_wordpress_credentials_creates_distinct_profile(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, type_label="블로그", domain="wpsource2.example.com",
                            wp_url="https://wpsource2.example.com", wp_user="admin", wp_app_password="orig-secret-2")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "wp복제2", "domain": "wpclone2.example.com",
                              "wp_url": "https://wpclone2.example.com", "wp_user": "clone-admin",
                              "wp_app_password": "clone-secret"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.json()["success"] is True
    cloned_id = r.json()["data"]["site_id"]
    source_row = _row(tmp_path, source_id)
    cloned_row = _row(tmp_path, cloned_id)
    assert source_row.get("wordpress_profile_id") != cloned_row.get("wordpress_profile_id")


def test_clone_unknown_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "x", "domain": "x.com", "status": "archived"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_clone_response_never_contains_secret_looking_strings(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, type_label="블로그", domain="wpsource3.example.com",
                            wp_url="https://wpsource3.example.com", wp_user="admin", wp_app_password="orig-secret-3")
    r = _client().post(f"/api/sites/{source_id}/clone",
                        json={"site_name": "wp복제3", "domain": "wpclone3.example.com",
                              "wp_url": "https://wpclone3.example.com", "wp_user": "clone-admin3",
                              "wp_app_password": "clone-secret-3"},
                        headers=_auth(ADMIN_TOKEN))
    text = r.text
    for forbidden in ("clone-secret-3", "orig-secret-3", "password", "passwd", "app_password",
                       "api_key", "apikey", "token"):
        assert forbidden not in text, f"응답에 '{forbidden}' 포함됨"


def test_clone_never_touches_config_yaml(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="원본6", domain="source6.example.com")
    config_path = tmp_path / "config" / "config.yaml"
    before = config_path.read_bytes() if config_path.exists() else None
    _client().post(f"/api/sites/{source_id}/clone",
                    json={"site_name": "원본6 (복사본)", "domain": "clone6.example.com"},
                    headers=_auth(ADMIN_TOKEN))
    after = config_path.read_bytes() if config_path.exists() else None
    assert before == after


def test_service_source_clone_reuses_create_site_not_reimplemented():
    """clone_site()가 site_wizard.create_site()를 재구현하지 않고 그대로
    호출(재사용)하는지 소스 레벨로 확인한다."""
    import inspect
    from api.services import site_service
    source = inspect.getsource(site_service.clone_site)
    assert "create_site(" in source
    assert "_wizard_create_site(" not in source  # create_site()를 직접 우회해 재구현하지 않음


# ══════════════════════════════════════════════════════════════════════════
# isolated E2E 시나리오 — source 생성 → GET → CLONE → GET source → GET clone
# → source 불변 → clone 필드 비교 → secrets 비교 → DELETE clone → GET 404
# ══════════════════════════════════════════════════════════════════════════

def test_full_isolated_scenario_clone_then_delete(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    source_id = _seed_site(tmp_path, site_name="시나리오원본", domain="scenario-source.example.com",
                            category="시나리오태그", research_ai="gpt4o_mini")

    r1 = _client().get(f"/api/sites/{source_id}", headers=_auth(ADMIN_TOKEN))
    assert r1.json()["data"]["site_name"] == "시나리오원본"

    r2 = _client().post(f"/api/sites/{source_id}/clone",
                         json={"site_name": "시나리오원본 (복사본)", "domain": "scenario-clone.example.com"},
                         headers=_auth(ADMIN_TOKEN))
    assert r2.json()["success"] is True
    clone_id = r2.json()["data"]["site_id"]

    r3 = _client().get(f"/api/sites/{source_id}", headers=_auth(ADMIN_TOKEN))
    assert r3.json()["data"]["site_name"] == "시나리오원본"  # 원본 불변

    r4 = _client().get(f"/api/sites/{clone_id}", headers=_auth(ADMIN_TOKEN))
    assert r4.json()["data"]["site_tags"] == "시나리오태그"
    assert r4.json()["data"]["research_ai"] == "gpt4o_mini"

    r5 = _client().request("DELETE", f"/api/sites/{clone_id}", json={"confirmation": "DELETE"},
                            headers=_auth(ADMIN_TOKEN))
    assert r5.json()["success"] is True

    r6 = _client().get(f"/api/sites/{clone_id}", headers=_auth(ADMIN_TOKEN))
    assert r6.json()["success"] is False
    assert r6.json()["error"]["code"] == "NOT_FOUND"

    r7 = _client().get(f"/api/sites/{source_id}", headers=_auth(ADMIN_TOKEN))
    assert r7.json()["success"] is True  # source는 여전히 존재


# ══════════════════════════════════════════════════════════════════════════
# write route 확인
# ══════════════════════════════════════════════════════════════════════════

def test_only_expected_write_routes_added_for_delete_clone():
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    pairs = {(r.path, m) for r in routes for m in r.methods if r.path.startswith("/api/sites/{site_id}")}
    assert pairs == {
        ("/api/sites/{site_id}", "GET"),
        ("/api/sites/{site_id}", "PUT"),
        ("/api/sites/{site_id}", "DELETE"),
        ("/api/sites/{site_id}/override", "POST"),
        ("/api/sites/{site_id}/override/reset", "POST"),
        ("/api/sites/{site_id}/activate", "POST"),
        ("/api/sites/{site_id}/deactivate", "POST"),
        ("/api/sites/{site_id}/archive", "POST"),
        ("/api/sites/{site_id}/restore", "POST"),
        ("/api/sites/{site_id}/clone", "POST"),
    }
