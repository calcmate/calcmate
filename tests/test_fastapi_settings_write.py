# -*- coding: utf-8 -*-
"""tests/test_fastapi_settings_write.py — STEP 4-F General Settings 저장 API 검증.

이 파일의 단위 테스트는 실제 secrets.yaml/config.yaml을 절대 건드리지 않는다.
ConfigService의 파일 접근을 pytest tmp_path로 만든 임시 config.yaml로 격리한다.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

VIEWER_TOKEN = "step4f-test-viewer-token"
ADMIN_TOKEN = "step4f-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """실제 config/secrets.yaml을 절대 건드리지 않도록, 임시 디렉터리에 최소
    config.yaml을 만들고 ConfigService가 항상 이 경로를 쓰도록 강제한다."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "WORDPRESS_URL: http://existing.test\n"
        "WORDPRESS_USERNAME: existing-user\n"
        "DAILY_AI_BUDGET: 5\n"
        "MONTHLY_AI_BUDGET: 100\n"
        "AI_ROLES:\n"
        "  writer:\n"
        "    provider: openai\n"
        "    model: gpt-4o\n"
        "  review:\n"
        "    provider: openai\n"
        "    model: gpt-4o\n",
        encoding="utf-8",
    )
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(
        "OPENAI_API_KEY: existing-openai-key\n"
        "WORDPRESS_APP_PASSWORD: existing-app-password\n"
        "TELEGRAM_CHAT_ID: '-100existing-secret'\n",
        encoding="utf-8",
    )

    import api.services.config_service as svc_mod

    def _forced_init(self, config_path=None):
        self._config_path = config_path or cfg_path

    monkeypatch.setattr(svc_mod.ConfigService, "__init__", _forced_init)
    return cfg_path, secrets_path


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("Settings 저장 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


# ══════════════════════════════════════════════════════════════════════════
# GET /api/settings/general
# ══════════════════════════════════════════════════════════════════════════

def test_get_general_settings_ok(isolated_config):
    r = _client().get("/api/settings/general")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["WORDPRESS_URL"] == "http://existing.test"
    assert body["data"]["DAILY_AI_BUDGET"] == 5


def test_get_general_settings_never_leaks_secret_plaintext(isolated_config):
    r = _client().get("/api/settings/general")
    body = r.json()
    assert body["data"]["OPENAI_API_KEY"] == {"configured": True}
    assert body["data"]["WORDPRESS_APP_PASSWORD"] == {"configured": True}
    assert "existing-openai-key" not in r.text
    assert "existing-app-password" not in r.text


def test_get_general_settings_unconfigured_secret_reports_false(isolated_config):
    r = _client().get("/api/settings/general")
    body = r.json()
    # secrets.yaml에 없는 CLAUDE/GEMINI/TELEGRAM_BOT_TOKEN은 configured=False
    assert body["data"]["CLAUDE_API_KEY"] == {"configured": False}
    assert body["data"]["GEMINI_API_KEY"] == {"configured": False}
    assert body["data"]["TELEGRAM_BOT_TOKEN"] == {"configured": False}


# ══════════════════════════════════════════════════════════════════════════
# PATCH 인증/권한
# ══════════════════════════════════════════════════════════════════════════

def test_patch_without_auth_returns_401(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch("/api/settings/general", json={"telegram_chat_id": "x"})
    assert r.status_code == 401
    # 파일이 변경되지 않았어야 한다
    cfg_path, _ = isolated_config
    assert "existing" in cfg_path.read_text(encoding="utf-8")


def test_patch_as_viewer_returns_403(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general", json={"telegram_chat_id": "x"}, headers=_auth(VIEWER_TOKEN)
    )
    assert r.status_code == 403


def test_patch_as_admin_succeeds(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"telegram_chat_id": "-100999"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    # TELEGRAM_CHAT_ID는 secret(ab9ac26) — 응답은 configured 상태만, 원문은 없음
    assert body["data"]["TELEGRAM_CHAT_ID"] == {"configured": True}
    assert "-100999" not in r.text


# ══════════════════════════════════════════════════════════════════════════
# TELEGRAM_CHAT_ID secret ownership (CALCMATE-TELEGRAM-CHAT-ID-SECRET-FIX-01)
# ══════════════════════════════════════════════════════════════════════════

def test_get_never_exposes_raw_telegram_chat_id(isolated_config):
    r = _client().get("/api/settings/general")
    assert r.json()["data"]["TELEGRAM_CHAT_ID"] == {"configured": True}
    assert "-100existing-secret" not in r.text


def test_get_reports_chat_id_unconfigured_when_secret_missing(isolated_config):
    _, secrets_path = isolated_config
    secrets_path.write_text("OPENAI_API_KEY: existing-openai-key\n", encoding="utf-8")
    r = _client().get("/api/settings/general")
    assert r.json()["data"]["TELEGRAM_CHAT_ID"] == {"configured": False}


def test_patch_chat_id_saved_to_secrets_not_config(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    cfg_path, secrets_path = isolated_config
    r = _client().patch("/api/settings/general", json={"telegram_chat_id": "-100new"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.json()["success"] is True
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert secrets["TELEGRAM_CHAT_ID"] == "-100new"
    assert secrets["OPENAI_API_KEY"] == "existing-openai-key"  # 다른 secret 보존
    assert "TELEGRAM_CHAT_ID" not in yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "-100new" not in cfg_path.read_text(encoding="utf-8")


def test_patch_other_public_field_does_not_recreate_chat_id_in_config(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    cfg_path, _ = isolated_config
    _client().patch("/api/settings/general", json={"daily_ai_budget": 7}, headers=_auth(ADMIN_TOKEN))
    assert "TELEGRAM_CHAT_ID" not in yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


def test_runtime_reads_chat_id_from_secrets_and_secrets_win(isolated_config):
    """load_config()가 쓰는 merge_secrets() 계약 그대로: config에 없어도 secrets에서
    읽고, 둘 다 있으면 secrets가 이긴다."""
    from modules.config_loader import merge_secrets
    cfg_path, _ = isolated_config
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "TELEGRAM_CHAT_ID" not in raw
    assert merge_secrets(dict(raw), str(cfg_path))["TELEGRAM_CHAT_ID"] == "-100existing-secret"
    assert merge_secrets({**raw, "TELEGRAM_CHAT_ID": "x"}, str(cfg_path))["TELEGRAM_CHAT_ID"] == "-100existing-secret"


def test_split_secrets_routes_chat_id_to_secrets():
    from modules.config_loader import SECRET_KEYS, split_secrets
    assert "TELEGRAM_CHAT_ID" in SECRET_KEYS
    public, secret = split_secrets({"TELEGRAM_CHAT_ID": "-1", "DAILY_AI_BUDGET": 5})
    assert secret == {"TELEGRAM_CHAT_ID": "-1"} and public == {"DAILY_AI_BUDGET": 5}


def test_tracked_config_has_no_telegram_chat_id():
    """tracked config/config.yaml은 Chat ID 저장소가 아니다(ab9ac26)."""
    from pathlib import Path
    real_cfg = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
    assert "TELEGRAM_CHAT_ID" not in (yaml.safe_load(real_cfg.read_text(encoding="utf-8")) or {})


# ══════════════════════════════════════════════════════════════════════════
# 부분 업데이트 / 기존 값 보존
# ══════════════════════════════════════════════════════════════════════════

def test_partial_update_preserves_other_fields(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    _client().patch(
        "/api/settings/general",
        json={"daily_ai_budget": 9},
        headers=_auth(ADMIN_TOKEN),
    )
    r = _client().get("/api/settings/general")
    data = r.json()["data"]
    assert data["DAILY_AI_BUDGET"] == 9
    # PATCH하지 않은 필드는 그대로 유지
    assert data["WORDPRESS_URL"] == "http://existing.test"
    assert data["MONTHLY_AI_BUDGET"] == 100


def test_existing_secret_survives_unrelated_patch(isolated_config, monkeypatch):
    """§6: 기존 secret이 있는 상태에서 다른 설정만 바꿔도 그 secret이 삭제되지 않는다."""
    _block_external_http(monkeypatch)
    _client().patch(
        "/api/settings/general",
        json={"telegram_chat_id": "-100111"},
        headers=_auth(ADMIN_TOKEN),
    )
    _, secrets_path = isolated_config
    raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert raw.get("OPENAI_API_KEY") == "existing-openai-key"
    assert raw.get("WORDPRESS_APP_PASSWORD") == "existing-app-password"


def test_empty_string_does_not_delete_existing_secret(isolated_config, monkeypatch):
    """§6: 빈 문자열을 보내도 기존 secret이 삭제되지 않는다."""
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"openai_api_key": ""},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    _, secrets_path = isolated_config
    raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert raw.get("OPENAI_API_KEY") == "existing-openai-key"


def test_new_secret_actually_saved(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"claude_api_key": "brand-new-claude-key"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    _, secrets_path = isolated_config
    raw = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert raw.get("CLAUDE_API_KEY") == "brand-new-claude-key"
    # 응답 본문에는 절대 원문이 노출되지 않는다
    assert "brand-new-claude-key" not in r.text


def test_ai_roles_partial_update_preserves_other_roles(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"ai_roles": {"writer": {"provider": "claude", "model": "claude-sonnet-4-6"}}},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["AI_ROLES"]["writer"] == {"provider": "claude", "model": "claude-sonnet-4-6"}
    # 요청에 없던 review 역할은 그대로 유지
    assert data["AI_ROLES"]["review"] == {"provider": "openai", "model": "gpt-4o"}


# ══════════════════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════════════════

def test_unknown_field_rejected_with_422(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"not_a_real_field": "x"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_invalid_type_rejected_with_422(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"daily_ai_budget": "not-a-number"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_out_of_range_budget_rejected_with_422(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"daily_ai_budget": 0},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_unknown_ai_role_rejected_with_422(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"ai_roles": {"not_a_role": {"provider": "openai", "model": "gpt-4o"}}},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_unknown_ai_provider_rejected_with_422(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/settings/general",
        json={"ai_roles": {"writer": {"provider": "not-a-provider", "model": "x"}}},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# Route surface / 회귀
# ══════════════════════════════════════════════════════════════════════════

def test_general_route_registered_before_dynamic_section_route():
    """"/general"이 "/{section}" 동적 라우트에 가려지지 않는지 확인한다."""
    from api.main import app
    r = _client().get("/api/settings/general")
    assert r.status_code == 200
    assert r.json()["error"] is None  # SECTION_NOT_ALLOWED로 빠지지 않았어야 함


def test_existing_get_settings_routes_still_unauthenticated(isolated_config):
    r = _client().get("/api/settings")
    assert r.status_code == 200
    r2 = _client().get("/api/settings/BLOG_SCHEDULE")
    assert r2.status_code == 200


def test_no_external_http_on_any_settings_path(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    c = _client()
    c.get("/api/settings/general")
    c.patch("/api/settings/general", json={"telegram_chat_id": "x"})  # 401
    c.patch("/api/settings/general", json={"telegram_chat_id": "x"}, headers=_auth(VIEWER_TOKEN))  # 403
    c.patch("/api/settings/general", json={"telegram_chat_id": "x"}, headers=_auth(ADMIN_TOKEN))  # 200


def test_audit_event_recorded_on_successful_patch(isolated_config, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/settings/general", json={"telegram_chat_id": "x"}, headers=_auth(ADMIN_TOKEN)
    )
    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "settings_patch_general"
    assert events[0].actor_role == "admin"
    assert events[0].result == "success"
