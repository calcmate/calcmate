# -*- coding: utf-8 -*-
"""tests/test_sites_status.py — STEP P2-08: Site Management Activate/
Deactivate/Archive/Restore React/FastAPI 이관 검증.

dashboard.py "▶ 활성화/⏸ 비활성화"(dashboard.py:1374-1379), "🗑️ 삭제(보관
이동)"(dashboard.py:1380-1385), "♻️ 복구"(dashboard.py:1398-1401)와 동일한
실행 의미를 검증한다. 실제 운영 DB/secrets.yaml/config.yaml은 이 파일의 어떤
테스트에서도 건드리지 않는다 — 전부 isolated tmp_path에서만 실행한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "sites-status-test-viewer-token"
ADMIN_TOKEN = "sites-status-test-admin-token"


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


def _isolated_cfg(tmp_path):
    return {"_root": str(tmp_path), "DB_ADAPTER": "sqlite", "SQLITE_PATH": "data/blog_auto.db"}


def _mock_isolated(monkeypatch, tmp_path):
    cfg = _isolated_cfg(tmp_path)
    monkeypatch.setattr("api.services.site_service.load_config", lambda: dict(cfg))
    return cfg


def _seed_site(tmp_path, **overrides):
    """isolated DB에 site_wizard.create_site()로 실제 fixture 사이트 1건을
    만든다(운영 DB 아님) — 이 site_id를 대상으로 상태 전이를 검증한다."""
    from adapters.db.factory import get_db_adapter
    from repositories.site_repository import SiteRepository
    from modules.site_wizard import create_site

    cfg = _isolated_cfg(tmp_path)
    site_name = overrides.pop("site_name", "상태픽스처사이트")
    domain = overrides.pop("domain", "status-fixture.example.com")
    ok, msg = create_site(cfg, "계산기", {"site_name": site_name, "domain": domain})
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


# ══════════════════════════════════════════════════════════════════════════
# 인증 — activate / deactivate / archive / restore
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action", ["activate", "deactivate", "archive", "restore"])
def test_status_action_without_auth_returns_401(action):
    r = _client().post(f"/api/sites/whatever/{action}")
    assert r.status_code == 401


@pytest.mark.parametrize("action", ["activate", "deactivate", "archive", "restore"])
def test_status_action_as_viewer_returns_403(action):
    r = _client().post(f"/api/sites/whatever/{action}", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


@pytest.mark.parametrize("action", ["activate", "deactivate", "archive", "restore"])
def test_status_action_as_admin_on_existing_site_succeeds(monkeypatch, tmp_path, action):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/{action}", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# Activate / Deactivate — status만 변경, 다른 필드는 불변
# ══════════════════════════════════════════════════════════════════════════

def test_activate_sets_status_active_and_touches_no_other_field(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    before = _row(tmp_path, site_id)

    r = _client().post(f"/api/sites/{site_id}/deactivate", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["status"] == "inactive"
    r = _client().post(f"/api/sites/{site_id}/activate", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "active"

    after = _row(tmp_path, site_id)
    for field in ("site_name", "domain", "site_type", "site_tags", "deleted_at"):
        assert before.get(field, "") == after.get(field, ""), f"{field}가 변경됨"


def test_deactivate_sets_status_inactive_and_touches_no_other_field(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    before = _row(tmp_path, site_id)

    r = _client().post(f"/api/sites/{site_id}/deactivate", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "inactive"

    after = _row(tmp_path, site_id)
    for field in ("site_name", "domain", "site_type", "site_tags", "deleted_at"):
        assert before.get(field, "") == after.get(field, ""), f"{field}가 변경됨"


def test_activate_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/activate", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_deactivate_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/deactivate", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# Archive — status="archived" + deleted_at 설정(soft delete), 다른 필드 불변
# ══════════════════════════════════════════════════════════════════════════

def test_archive_sets_status_archived_and_deleted_at(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    before = _row(tmp_path, site_id)
    assert not before.get("deleted_at")

    r = _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "archived"

    after = _row(tmp_path, site_id)
    assert after.get("status") == "archived"
    assert after.get("deleted_at"), "deleted_at이 설정되지 않음"
    for field in ("site_name", "domain", "site_type", "site_tags"):
        assert before.get(field, "") == after.get(field, ""), f"{field}가 변경됨"


def test_archive_is_soft_delete_row_still_present(monkeypatch, tmp_path):
    """Archive는 row를 삭제하지 않는다 — Hard Delete와 구분되는 soft delete."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))
    assert _row(tmp_path, site_id) is not None


def test_archive_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/archive", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# Restore — status="inactive"(항상, "active" 아님) + deleted_at="" 복원
# ══════════════════════════════════════════════════════════════════════════

def test_restore_sets_status_inactive_not_active(monkeypatch, tmp_path):
    """원본 dashboard.py:1399가 하드코딩한 그대로 — 복구 후 상태는 항상
    "inactive"다("active"로 복구되지 않는다). 보관 전 상태를 기억하지 않는다."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    _client().post(f"/api/sites/{site_id}/activate", headers=_auth(ADMIN_TOKEN))  # active로 만든 뒤 보관
    _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))

    r = _client().post(f"/api/sites/{site_id}/restore", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "inactive"


def test_restore_clears_deleted_at_and_preserves_other_fields(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    before = _row(tmp_path, site_id)
    _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))

    r = _client().post(f"/api/sites/{site_id}/restore", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200

    after = _row(tmp_path, site_id)
    assert after.get("deleted_at", "") == "", "deleted_at이 복원되지 않음"
    for field in ("site_name", "domain", "site_type", "site_tags"):
        assert before.get(field, "") == after.get(field, ""), f"{field}가 변경됨"


def test_restore_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/restore", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# Secret 미노출 + secrets.yaml/config.yaml 불변
# ══════════════════════════════════════════════════════════════════════════

def test_status_action_responses_never_contain_secret_looking_strings(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    responses = [
        _client().post(f"/api/sites/{site_id}/activate", headers=_auth(ADMIN_TOKEN)),
        _client().post(f"/api/sites/{site_id}/deactivate", headers=_auth(ADMIN_TOKEN)),
        _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN)),
        _client().post(f"/api/sites/{site_id}/restore", headers=_auth(ADMIN_TOKEN)),
    ]
    for r in responses:
        text = r.text
        for forbidden in ("password", "passwd", "app_password", "api_key", "apikey", "token",
                          "access_token", "refresh_token", "client_secret", "private_key", "secret"):
            assert forbidden not in text, f"{r.request.method} {r.request.url}의 응답에 '{forbidden}' 포함됨"


def test_status_actions_never_touch_secrets_or_config_yaml(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    secrets_path = tmp_path / "config" / "secrets.yaml"
    config_path = tmp_path / "config" / "config.yaml"
    before_secrets = secrets_path.read_bytes() if secrets_path.exists() else None
    before_config = config_path.read_bytes() if config_path.exists() else None

    _client().post(f"/api/sites/{site_id}/activate", headers=_auth(ADMIN_TOKEN))
    _client().post(f"/api/sites/{site_id}/deactivate", headers=_auth(ADMIN_TOKEN))
    _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))
    _client().post(f"/api/sites/{site_id}/restore", headers=_auth(ADMIN_TOKEN))

    after_secrets = secrets_path.read_bytes() if secrets_path.exists() else None
    after_config = config_path.read_bytes() if config_path.exists() else None
    assert before_secrets == after_secrets
    assert before_config == after_config


def test_service_source_never_touches_secrets_or_config_files():
    import inspect
    from api.services import site_service
    for fn in (site_service.activate_site, site_service.deactivate_site,
               site_service.archive_site, site_service.restore_site):
        source = inspect.getsource(fn)
        assert "secrets.yaml" not in source
        assert "config.yaml" not in source
        assert "_secrets_path" not in source
        assert "save_wp_profile" not in source


# ══════════════════════════════════════════════════════════════════════════
# 범위 보호 — calculators/articles/Registry/registry_auto/HOLD/pending_posts/
# cost_state가 변경되지 않았는지 확인(실 운영 데이터가 아니라 isolated
# tmp_path 안에서 이 서비스 함수들이 그런 파일/테이블을 아예 참조하지 않는지를
# 소스 레벨로 확인한다 — Update/Override와 동일한 방식).
# ══════════════════════════════════════════════════════════════════════════

def test_service_source_never_references_out_of_scope_data():
    import inspect
    from api.services import site_service
    for fn in (site_service.activate_site, site_service.deactivate_site,
               site_service.archive_site, site_service.restore_site):
        source = inspect.getsource(fn)
        for forbidden in ("calculators", "articles", "registry", "HOLD", "pending_posts", "cost_state"):
            assert forbidden not in source, f"{fn.__name__}가 범위 밖 데이터({forbidden})를 참조함"


# ══════════════════════════════════════════════════════════════════════════
# isolated E2E 시나리오(STEP 9) — fixture 생성 → GET → Activate → GET →
# Deactivate → GET → Archive → GET → Restore → GET → 필드 관계 확인
# ══════════════════════════════════════════════════════════════════════════

def test_full_isolated_scenario_activate_deactivate_archive_restore(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)

    r1 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r1.json()["data"]["status"] == "active"  # site_wizard.save()의 기본값(재확인)

    r2 = _client().post(f"/api/sites/{site_id}/activate", headers=_auth(ADMIN_TOKEN))
    assert r2.json()["data"]["status"] == "active"

    r3 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r3.json()["data"]["status"] == "active"

    r4 = _client().post(f"/api/sites/{site_id}/deactivate", headers=_auth(ADMIN_TOKEN))
    assert r4.json()["data"]["status"] == "inactive"

    r5 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r5.json()["data"]["status"] == "inactive"

    r6 = _client().post(f"/api/sites/{site_id}/archive", headers=_auth(ADMIN_TOKEN))
    assert r6.json()["data"]["status"] == "archived"

    r7 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r7.json()["data"]["status"] == "archived"
    assert _row(tmp_path, site_id).get("deleted_at")

    r8 = _client().post(f"/api/sites/{site_id}/restore", headers=_auth(ADMIN_TOKEN))
    assert r8.json()["data"]["status"] == "inactive"

    r9 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r9.json()["data"]["status"] == "inactive"
    assert _row(tmp_path, site_id).get("deleted_at", "") == ""
    # site_name/domain은 상태 전이 전체와 무관하게 그대로 유지되어야 한다.
    assert r9.json()["data"]["site_name"] == "상태픽스처사이트"


# ══════════════════════════════════════════════════════════════════════════
# write route 확인
# ══════════════════════════════════════════════════════════════════════════

def test_only_expected_write_routes_added_for_status_actions():
    """STEP P2-09에서 DELETE 1개(Hard Delete)와 POST 1개(Clone)가
    require_admin() 뒤에서 정당하게 추가되었다(이 파일의 P2-08 구현은
    변경하지 않음 — 이 fixture만 최신 route 집합에 맞춰 갱신한다)."""
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    pairs = {(r.path, m) for r in routes for m in r.methods if r.path.startswith("/api/sites/{site_id}")}
    assert pairs == {
        ("/api/sites/{site_id}", "GET"),
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
