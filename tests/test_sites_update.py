# -*- coding: utf-8 -*-
"""tests/test_sites_update.py — STEP P2-07: Site Management Update/Override/
Reset React/FastAPI 이관 검증.

dashboard.py "💾 수정 저장"(dashboard.py:1369-1373)과 "⚙️ Site Settings
(Override)"(dashboard.py:1072-1166)와 동일한 실행 의미를 검증한다. 실제 운영
DB/secrets.yaml/config.yaml은 이 파일의 어떤 테스트에서도 건드리지 않는다 —
전부 isolated tmp_path에서만 실행한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "sites-update-test-viewer-token"
ADMIN_TOKEN = "sites-update-test-admin-token"


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
    만든다(운영 DB 아님) — 이 site_id를 대상으로 Update/Override를 검증한다."""
    from adapters.db.factory import get_db_adapter
    from repositories.site_repository import SiteRepository
    from modules.site_wizard import create_site

    cfg = _isolated_cfg(tmp_path)
    ok, msg = create_site(cfg, "계산기", {
        "site_name": overrides.pop("site_name", "픽스처사이트"),
        "domain": overrides.pop("domain", "fixture.example.com"),
    })
    assert ok, msg
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    row = next(r for r in repo.get_all() if r.get("domain") == "fixture.example.com" or r.get("site_name"))
    return row.get("site_id", "")


# ══════════════════════════════════════════════════════════════════════════
# 인증 — GET detail / PUT / override / override reset
# ══════════════════════════════════════════════════════════════════════════

def test_get_detail_without_auth_returns_401():
    r = _client().get("/api/sites/whatever")
    assert r.status_code == 401


def test_get_detail_as_viewer_returns_403():
    r = _client().get("/api/sites/whatever", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_put_update_without_auth_returns_401():
    r = _client().put("/api/sites/whatever", json={})
    assert r.status_code == 401


def test_put_update_as_viewer_returns_403():
    r = _client().put("/api/sites/whatever", json={}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_override_without_auth_returns_401():
    r = _client().post("/api/sites/whatever/override", json={})
    assert r.status_code == 401


def test_override_as_viewer_returns_403():
    r = _client().post("/api/sites/whatever/override", json={}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_override_reset_without_auth_returns_401():
    r = _client().post("/api/sites/whatever/override/reset")
    assert r.status_code == 401


def test_override_reset_as_viewer_returns_403():
    r = _client().post("/api/sites/whatever/override/reset", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# GET detail
# ══════════════════════════════════════════════════════════════════════════

def test_get_detail_returns_200_for_existing_site(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["site_id"] == site_id
    assert data["site_name"] == "픽스처사이트"
    # 주의(발견사항): site_wizard.create_site()는 research_ai/writing_ai/
    # review_ai를 DEFAULT_AI 값으로 채워서 저장한다(빈 문자열이 아님) — Override
    # UI의 "빈 값=Global 상속" 문구와 달리, 생성 직후에도 이미 기본 프로필 값이
    # 들어있다(원본의 기존 동작, 이번 STEP에서 변경하지 않음).
    assert data["research_ai"] == "gemini_flash"
    assert data["writing_ai"] == "gpt4o"
    assert data["review_ai"] == "claude_sonnet"
    # 그 외 9개 필드는 create_site()가 아예 채우지 않으므로 진짜 빈 값이어야 한다.
    for f in ("wordpress_url", "site_tags", "seo_keyword_count", "seo_length",
              "daily_override", "image_mode", "telegram_enabled", "analytics_enabled"):
        assert data[f] == ""
    assert data["calc_active"] == []


def test_get_detail_returns_404_for_missing_site(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().get("/api/sites/does-not-exist", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# PUT 기본 정보 수정
# ══════════════════════════════════════════════════════════════════════════

def test_put_update_valid_changes_name_domain_category(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().put(f"/api/sites/{site_id}",
                       json={"site_name": "변경된이름", "domain": "changed.example.com", "category": "새카테고리"},
                       headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True

    r2 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    data = r2.json()["data"]
    assert data["site_name"] == "변경된이름"
    assert data["domain"] == "changed.example.com"


def test_put_update_unknown_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().put(f"/api/sites/{site_id}", json={"site_name": "x", "not_a_field": "y"},
                       headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_put_update_invalid_type_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().put(f"/api/sites/{site_id}", json={"site_name": 12345}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_put_update_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().put("/api/sites/does-not-exist", json={"site_name": "x"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_put_update_never_touches_override_fields(monkeypatch, tmp_path):
    """기본 정보 수정은 site_name/domain/site_tags(category)만 바꾸고 Override
    12개 필드에는 영향을 주지 않아야 한다(원본과 동일 — 별개의 저장 호출)."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    _client().post(f"/api/sites/{site_id}/override", json={"research_ai": "gpt4o"}, headers=_auth(ADMIN_TOKEN))
    _client().put(f"/api/sites/{site_id}", json={"site_name": "새이름", "domain": "d.com"}, headers=_auth(ADMIN_TOKEN))
    r = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["research_ai"] == "gpt4o"  # PUT 이후에도 유지되어야 함


# ══════════════════════════════════════════════════════════════════════════
# Override 저장
# ══════════════════════════════════════════════════════════════════════════

def test_override_save_sets_all_twelve_fields(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    payload = {
        "research_ai": "gemini_pro", "writing_ai": "gpt4o", "review_ai": "claude_opus",
        "wordpress_url": "http://override.example.com", "site_tags": "override태그",
        "seo_keyword_count": "7", "seo_length": "2000", "daily_override": "5",
        "image_mode": "openai", "telegram_enabled": "ON", "analytics_enabled": "OFF",
        "calc_active": ["계산기A", "계산기B"],
    }
    r = _client().post(f"/api/sites/{site_id}/override", json=payload, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    for k, v in payload.items():
        assert data[k] == v, f"{k} 저장 결과 불일치: {data[k]!r} != {v!r}"


def test_override_save_read_back_via_get_detail(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    _client().post(f"/api/sites/{site_id}/override", json={"daily_override": "9"}, headers=_auth(ADMIN_TOKEN))
    r = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["daily_override"] == "9"


def test_override_invalid_image_mode_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/override", json={"image_mode": "not-a-real-mode"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_override_invalid_telegram_enabled_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/override", json={"telegram_enabled": "maybe"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_override_invalid_research_ai_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/override", json={"research_ai": "not-a-real-profile"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_override_unknown_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/override", json={"not_a_real_field": "x"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_override_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/override", json={}, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_override_does_not_expose_or_touch_features_field(monkeypatch, tmp_path):
    """features 필드는 원본에서 읽기 전용 표시일 뿐 저장 대상이 아니다 — 이번
    STEP의 Override 저장 endpoint도 features를 요청/응답 어디에도 포함하지
    않아야 한다."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    r = _client().post(f"/api/sites/{site_id}/override", json={"research_ai": "gpt4o", "features": {"x": 1}},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422  # extra="forbid"이므로 features는 알 수 없는 필드로 거부됨


# ══════════════════════════════════════════════════════════════════════════
# Override 초기화(Reset)
# ══════════════════════════════════════════════════════════════════════════

def test_reset_clears_nine_fields_but_preserves_core_fields(monkeypatch, tmp_path):
    """Reset은 wordpress_url/site_tags(코어 필드)를 보존하고, 나머지 9개
    필드만 빈 문자열로 되돌린다(원본 dashboard.py:1161-1164 그대로 재현)."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    _client().post(f"/api/sites/{site_id}/override", json={
        "research_ai": "gpt4o", "writing_ai": "gemini_pro", "review_ai": "claude_opus",
        "wordpress_url": "http://keep-me.example.com", "site_tags": "keep-me-tag",
        "seo_keyword_count": "7", "seo_length": "2000", "daily_override": "5",
        "image_mode": "openai", "telegram_enabled": "ON", "analytics_enabled": "OFF",
        "calc_active": ["계산기A"],
    }, headers=_auth(ADMIN_TOKEN))

    r = _client().post(f"/api/sites/{site_id}/override/reset", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    for f in ("research_ai", "writing_ai", "review_ai", "seo_keyword_count", "seo_length",
              "daily_override", "image_mode", "telegram_enabled", "analytics_enabled"):
        assert data[f] == "", f"{f}가 초기화되지 않음: {data[f]!r}"
    assert data["calc_active"] == []
    # 코어 필드는 보존되어야 한다.
    assert data["wordpress_url"] == "http://keep-me.example.com"
    assert data["site_tags"] == "keep-me-tag"


def test_reset_missing_site_returns_404(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/does-not-exist/override/reset", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# Secret 미노출
# ══════════════════════════════════════════════════════════════════════════

def test_update_override_responses_never_contain_secret_looking_strings(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    responses = [
        _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN)),
        _client().put(f"/api/sites/{site_id}", json={"site_name": "x", "domain": "y.com"}, headers=_auth(ADMIN_TOKEN)),
        _client().post(f"/api/sites/{site_id}/override", json={"wordpress_url": "http://x.example.com"}, headers=_auth(ADMIN_TOKEN)),
        _client().post(f"/api/sites/{site_id}/override/reset", headers=_auth(ADMIN_TOKEN)),
    ]
    for r in responses:
        text = r.text
        for forbidden in ("password", "passwd", "app_password", "api_key", "apikey", "token",
                          "access_token", "refresh_token", "client_secret", "private_key", "secret"):
            assert forbidden not in text, f"{r.request.method} {r.request.url}의 응답에 '{forbidden}' 포함됨"


def test_update_and_override_never_touch_secrets_or_config_yaml(monkeypatch, tmp_path):
    """Update/Override/Reset은 sites DB row만 변경해야 한다 — secrets.yaml/
    config.yaml 파일 자체가 생성/변경되지 않아야 한다."""
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)
    secrets_path = tmp_path / "config" / "secrets.yaml"
    config_path = tmp_path / "config" / "config.yaml"
    before_secrets = secrets_path.read_bytes() if secrets_path.exists() else None
    before_config = config_path.read_bytes() if config_path.exists() else None

    _client().put(f"/api/sites/{site_id}", json={"site_name": "x", "domain": "y.com"}, headers=_auth(ADMIN_TOKEN))
    _client().post(f"/api/sites/{site_id}/override", json={"research_ai": "gpt4o"}, headers=_auth(ADMIN_TOKEN))
    _client().post(f"/api/sites/{site_id}/override/reset", headers=_auth(ADMIN_TOKEN))

    after_secrets = secrets_path.read_bytes() if secrets_path.exists() else None
    after_config = config_path.read_bytes() if config_path.exists() else None
    assert before_secrets == after_secrets
    assert before_config == after_config


def test_service_source_never_touches_secrets_or_config_files():
    import ast
    import inspect
    from api.services import site_service
    for fn in (site_service.update_site_basic, site_service.save_override, site_service.reset_override,
               site_service.get_site):
        source = inspect.getsource(fn)
        assert "secrets.yaml" not in source
        assert "config.yaml" not in source
        assert "_secrets_path" not in source
        assert "save_wp_profile" not in source


# ══════════════════════════════════════════════════════════════════════════
# isolated E2E 시나리오(§15) — Create fixture → GET → PUT → GET → Override →
# GET → Reset → GET → 원래 상태 확인
# ══════════════════════════════════════════════════════════════════════════

def test_full_isolated_scenario_create_get_update_override_reset(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    site_id = _seed_site(tmp_path)

    r1 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r1.json()["data"]["site_name"] == "픽스처사이트"
    # create_site()가 채워둔 기본 프로필(발견사항, 위 test_get_detail 참고).
    assert r1.json()["data"]["research_ai"] == "gemini_flash"

    r2 = _client().put(f"/api/sites/{site_id}", json={"site_name": "수정됨", "domain": "updated.example.com"},
                        headers=_auth(ADMIN_TOKEN))
    assert r2.json()["success"] is True

    r3 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r3.json()["data"]["site_name"] == "수정됨"
    assert r3.json()["data"]["domain"] == "updated.example.com"

    r4 = _client().post(f"/api/sites/{site_id}/override", json={"research_ai": "claude_haiku", "daily_override": "3"},
                         headers=_auth(ADMIN_TOKEN))
    assert r4.json()["success"] is True

    r5 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    assert r5.json()["data"]["research_ai"] == "claude_haiku"
    assert r5.json()["data"]["daily_override"] == "3"

    r6 = _client().post(f"/api/sites/{site_id}/override/reset", headers=_auth(ADMIN_TOKEN))
    assert r6.json()["success"] is True

    r7 = _client().get(f"/api/sites/{site_id}", headers=_auth(ADMIN_TOKEN))
    data = r7.json()["data"]
    assert data["research_ai"] == ""
    assert data["daily_override"] == ""
    # PUT으로 바꾼 site_name/domain은 Override reset과 무관하게 그대로 유지되어야 한다.
    assert data["site_name"] == "수정됨"
    assert data["domain"] == "updated.example.com"


# ══════════════════════════════════════════════════════════════════════════
# write route 확인
# ══════════════════════════════════════════════════════════════════════════

def test_only_expected_write_routes_added_for_site_detail():
    """STEP P2-08에서 Activate/Deactivate/Archive/Restore POST 4개가, STEP
    P2-09에서 DELETE 1개(Hard Delete)와 POST 1개(Clone)가 require_admin()
    뒤에서 정당하게 추가되었다(이 파일의 P2-07 구현은 변경하지 않음 — 이
    fixture만 최신 route 집합에 맞춰 갱신한다)."""
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
