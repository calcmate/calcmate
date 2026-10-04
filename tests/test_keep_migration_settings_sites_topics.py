# -*- coding: utf-8 -*-
"""tests/test_keep_migration_settings_sites_topics.py —
CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01 검증.

대상: GET/PATCH /api/settings/operations, POST /api/settings/telegram/test,
GET /api/sites/export, POST /api/scheduler/topics/{id}/wp-check|revert-candidate.

격리 원칙(운영 데이터 무접촉):
  - ConfigService는 tmp_path의 임시 config.yaml만 쓴다(기존 test_settings_image_google.py
    패턴). 실제 config/config.yaml은 테스트 전후 해시가 같아야 한다.
  - Telegram(telegram_ops.notify), WP 대조(check_published_topic_wp_status), Topic 전이
    (topic_pool.transition_status), sites 저장소(SiteRepository)는 전부 mock — 실제
    Telegram 발송/WP GET/DB write 없음.
  - CALCMATE_DASHBOARD_LOCAL_MODE를 지워 실제 인증(401/403) 경로를 검증한다.
  - TestClient를 context manager 없이 써 lifespan(worker 기동)을 실행하지 않는다.
"""
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

VIEWER_TOKEN = "keep-mig-viewer-token"
ADMIN_TOKEN = "keep-mig-admin-token"
REAL_CONFIG = ROOT / "config" / "config.yaml"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    before = _sha(REAL_CONFIG)
    yield
    clear_audit_events()
    assert _sha(REAL_CONFIG) == before, "실제 config.yaml이 변경되었습니다"


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "EXISTING_UNRELATED_KEY: keep-me\n"
        "ORCHESTRATOR_PROVIDER: openai\n"
        "MODEL_ORCHESTRATOR: gpt-4o\n"
        "PLANNER_PROVIDER: gemini\n"
        "MODEL_PLANNER: gemini-2.5-flash\n"
        "WRITER_PROVIDER: openai\n"
        "MODEL_WRITER: gpt-4o-mini\n"
        "EDITOR_PROVIDER: claude\n"
        "MODEL_EDITOR: claude-sonnet-4-6\n"
        "MODEL_CLEANER: gpt-4o\n"
        "MODEL_EDITOR_FALLBACK: gpt-4o\n"
        "ADSENSE_MODE: pre\n"
        "DLQ_THRESHOLD: 3\n"
        "AUTO_TOPIC_EXPANSION: true\n"
        "ENABLE_STRATEGY_ROOM: true\n"
        "TELEGRAM_CHAT_ID: '-100saved'\n"
        "TELEGRAM_EVENTS:\n"
        "  error: true\n"
        "  budget: false\n",
        encoding="utf-8",
    )
    import api.services.config_service as svc_mod

    def _forced_init(self, config_path=None):
        self._config_path = config_path or cfg_path

    monkeypatch.setattr(svc_mod.ConfigService, "__init__", _forced_init)
    return cfg_path


@pytest.fixture
def sent(monkeypatch):
    """telegram_ops.notify mock — 실제 Telegram 발송 차단."""
    calls = []
    import modules.telegram_ops as tops
    monkeypatch.setattr(tops, "notify", lambda cfg, msg: calls.append((dict(cfg), msg)))
    import modules.telegram_notifier as tn
    monkeypatch.setattr(tn, "send", lambda *a, **k: pytest.fail("real telegram send"))
    return calls


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ── Operations settings ───────────────────────────────────────────────────

def test_operations_get_returns_flat_keys_and_merged_events(isolated_config):
    r = _client().get("/api/settings/operations", headers=_auth(ADMIN_TOKEN))
    d = r.json()["data"]
    assert d["PLANNER_PROVIDER"] == "gemini" and d["MODEL_WRITER"] == "gpt-4o-mini"
    assert d["DLQ_THRESHOLD"] == 3 and d["ADSENSE_MODE"] == "pre"
    assert d["TELEGRAM_EVENTS"]["budget"] is False
    assert d["TELEGRAM_EVENTS"]["publish_success"] is True  # 미설정 = 기본 ON
    assert "AI_ROLES" not in d


def test_operations_auth_required(isolated_config):
    c = _client()
    assert c.get("/api/settings/operations").status_code == 401
    assert c.get("/api/settings/operations", headers=_auth(VIEWER_TOKEN)).status_code == 403
    assert c.patch("/api/settings/operations", json={"dlq_threshold": 5},
                   headers=_auth(VIEWER_TOKEN)).status_code == 403
    assert _load(isolated_config)["DLQ_THRESHOLD"] == 3


def test_operations_patch_saves_and_preserves_other_keys(isolated_config):
    r = _client().patch("/api/settings/operations", headers=_auth(ADMIN_TOKEN), json={
        "writer_provider": "claude", "model_writer": "claude-haiku-4-5-20251001",
        "model_cleaner": "gpt-4o-mini", "adsense_mode": "post", "dlq_threshold": 7,
        "auto_topic_expansion": False, "telegram_events": {"publish_success": False},
    })
    assert r.json()["success"] is True
    saved = _load(isolated_config)
    assert saved["WRITER_PROVIDER"] == "claude"
    assert saved["MODEL_WRITER"] == "claude-haiku-4-5-20251001"
    assert saved["MODEL_CLEANER"] == "gpt-4o-mini"
    assert saved["ADSENSE_MODE"] == "post" and saved["DLQ_THRESHOLD"] == 7
    assert saved["AUTO_TOPIC_EXPANSION"] is False
    assert saved["ENABLE_STRATEGY_ROOM"] is True
    assert saved["TELEGRAM_EVENTS"]["publish_success"] is False
    assert saved["TELEGRAM_EVENTS"]["budget"] is False  # 요청에 없는 이벤트 보존
    assert saved["EXISTING_UNRELATED_KEY"] == "keep-me"
    assert saved["PLANNER_PROVIDER"] == "gemini"


@pytest.mark.parametrize("payload", [
    {"model_writer": "claude-sonnet-4-6"},           # openai provider + claude model
    {"editor_provider": "gemini"},                    # 기존 claude 모델은 gemini 프리셋 아님
    {"model_editor_fallback": "claude-sonnet-4-6"},   # openai 프리셋만 허용
    {"telegram_events": {"unknown_event": True}},
])
def test_operations_patch_rejects_out_of_preset_and_keeps_file(isolated_config, payload):
    before = isolated_config.read_bytes()
    r = _client().patch("/api/settings/operations", headers=_auth(ADMIN_TOKEN), json=payload)
    body = r.json()
    assert body["success"] is False and body["error"]["code"] == "VALIDATION_ERROR"
    assert isolated_config.read_bytes() == before


@pytest.mark.parametrize("payload", [
    {"dlq_threshold": 11}, {"adsense_mode": "mid"}, {"run_mode": "x"},
    {"orchestrator_provider": "mistral"},
])
def test_operations_patch_schema_422(isolated_config, payload):
    before = isolated_config.read_bytes()
    r = _client().patch("/api/settings/operations", headers=_auth(ADMIN_TOKEN), json=payload)
    assert r.status_code == 422
    assert isolated_config.read_bytes() == before


# ── Telegram test ─────────────────────────────────────────────────────────

def test_telegram_test_uses_saved_values(isolated_config, sent, monkeypatch):
    import modules.config_loader as cl
    monkeypatch.setattr(cl, "load_secrets", lambda path=None: {"TELEGRAM_BOT_TOKEN": "saved-token"})
    r = _client().post("/api/settings/telegram/test", headers=_auth(ADMIN_TOKEN), json={})
    assert r.json()["success"] is True
    assert sent == [({"TELEGRAM_BOT_TOKEN": "saved-token", "TELEGRAM_CHAT_ID": "-100saved"},
                     "✅ CalcMate 텔레그램 연결 테스트 — 정상")]


def test_telegram_test_body_overrides_saved(isolated_config, sent, monkeypatch):
    import modules.config_loader as cl
    monkeypatch.setattr(cl, "load_secrets", lambda path=None: {"TELEGRAM_BOT_TOKEN": "saved-token"})
    _client().post("/api/settings/telegram/test", headers=_auth(ADMIN_TOKEN),
                   json={"telegram_bot_token": "typed", "telegram_chat_id": "-1typed"})
    assert sent[0][0] == {"TELEGRAM_BOT_TOKEN": "typed", "TELEGRAM_CHAT_ID": "-1typed"}


def test_telegram_test_missing_token_does_not_send(isolated_config, sent, monkeypatch):
    import modules.config_loader as cl
    monkeypatch.setattr(cl, "load_secrets", lambda path=None: {})
    body = _client().post("/api/settings/telegram/test", headers=_auth(ADMIN_TOKEN), json={}).json()
    assert body["success"] is False and body["error"]["code"] == "TELEGRAM_NOT_CONFIGURED"
    assert sent == []


def test_telegram_test_requires_admin(isolated_config, sent):
    r = _client().post("/api/settings/telegram/test", headers=_auth(VIEWER_TOKEN), json={})
    assert r.status_code == 403 and sent == []


# ── Site Export ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_sites(monkeypatch):
    rows = [{"site_id": "s1", "site_name": "A", "domain": "a.test", "site_type": "blog",
             "site_tags": "tag", "wordpress_url": "https://a.test", "wordpress_profile_id": "p1",
             "calc_active": "[]", "wp_app_password": "LEAK", "api_token": "LEAK",
             "client_secret": "LEAK", "openai_key": "LEAK"}]
    import api.services.site_service as ss

    class _Repo:
        def __init__(self, *a, **k):
            pass

        def get_all(self):
            return [dict(r) for r in rows]

    monkeypatch.setattr(ss, "load_config", lambda *a, **k: {})
    monkeypatch.setattr(ss, "get_db_adapter", lambda cfg: None)
    monkeypatch.setattr(ss, "SiteRepository", _Repo)
    return rows


def test_sites_export_returns_raw_rows_without_secret_columns(fake_sites):
    r = _client().get("/api/sites/export", headers=_auth(ADMIN_TOKEN))
    sites = r.json()["data"]["sites"]
    assert len(sites) == 1
    row = sites[0]
    assert row["site_tags"] == "tag" and row["wordpress_url"] == "https://a.test"
    assert row["wordpress_profile_id"] == "p1"
    assert "LEAK" not in str(sites)


def test_sites_export_route_not_captured_by_site_id_and_requires_admin(fake_sites, monkeypatch):
    import api.services.site_service as ss
    monkeypatch.setattr(ss, "get_site", lambda site_id: pytest.fail(f"captured by /{{site_id}}: {site_id}"))
    c = _client()
    assert c.get("/api/sites/export", headers=_auth(VIEWER_TOKEN)).status_code == 403
    assert c.get("/api/sites/export", headers=_auth(ADMIN_TOKEN)).json()["success"] is True


# ── Topic ↔ WP reconciliation ─────────────────────────────────────────────

@pytest.fixture
def topic_mocks(monkeypatch):
    import api.services.topic_reconciliation_service as trs
    state = {"check": {"status": "MISMATCH", "topic_id": "t1", "wp_post_id": 9,
                       "wp_status": "trash", "expected_wp_status": "publish",
                       "reservation_mode": "publish"},
             "transitions": [], "checks": 0, "raise": None}

    def _check(cfg, topic_id):
        state["checks"] += 1
        return dict(state["check"], topic_id=topic_id)

    def _transition(cfg, topic_id, to_status, *, actor, reason, manual=False):
        if state["raise"]:
            raise state["raise"]
        state["transitions"].append((topic_id, to_status, actor, reason, manual))
        return {"topic_id": topic_id, "status": to_status}

    monkeypatch.setattr(trs, "load_config", lambda *a, **k: {"_marker": "cfg"})
    monkeypatch.setattr(trs, "check_published_topic_wp_status", _check)
    monkeypatch.setattr(trs.topic_pool, "transition_status", _transition)
    return state


def test_topic_wp_check_delegates(topic_mocks):
    body = _client().post("/api/scheduler/topics/t1/wp-check", headers=_auth(ADMIN_TOKEN)).json()
    assert body["success"] is True and body["data"]["status"] == "MISMATCH"
    assert topic_mocks["checks"] == 1 and topic_mocks["transitions"] == []


def test_topic_revert_requires_confirm(topic_mocks):
    body = _client().post("/api/scheduler/topics/t1/revert-candidate", headers=_auth(ADMIN_TOKEN),
                          json={}).json()
    assert body["error"]["code"] == "CONFIRM_REQUIRED"
    assert topic_mocks["checks"] == 0 and topic_mocks["transitions"] == []


@pytest.mark.parametrize("status", ["MATCH", "UNEXPECTED_PUBLISHED", "WP_CHECK_ERROR",
                                    "WP_POST_ID_UNAVAILABLE", "TOPIC_NOT_PUBLISHED"])
def test_topic_revert_refused_when_not_revertable(topic_mocks, status):
    topic_mocks["check"]["status"] = status
    body = _client().post("/api/scheduler/topics/t1/revert-candidate", headers=_auth(ADMIN_TOKEN),
                          json={"confirm": True}).json()
    assert body["error"]["code"] == "NOT_REVERTABLE"
    assert topic_mocks["transitions"] == []


@pytest.mark.parametrize("status", ["MISMATCH", "WP_POST_NOT_FOUND"])
def test_topic_revert_transitions_with_original_args(topic_mocks, status):
    topic_mocks["check"]["status"] = status
    body = _client().post("/api/scheduler/topics/t1/revert-candidate", headers=_auth(ADMIN_TOKEN),
                          json={"confirm": True}).json()
    assert body["success"] is True and body["data"]["status"] == "candidate"
    assert topic_mocks["transitions"] == [
        ("t1", "candidate", "dashboard_operator", f"wp_reconciliation_{status}", True)]


def test_topic_revert_transition_error_reported(topic_mocks):
    topic_mocks["raise"] = ValueError("bad transition")
    body = _client().post("/api/scheduler/topics/t1/revert-candidate", headers=_auth(ADMIN_TOKEN),
                          json={"confirm": True}).json()
    assert body["error"]["code"] == "TRANSITION_FAILED"


def test_topic_endpoints_require_admin(topic_mocks):
    c = _client()
    assert c.post("/api/scheduler/topics/t1/wp-check").status_code == 401
    assert c.post("/api/scheduler/topics/t1/wp-check", headers=_auth(VIEWER_TOKEN)).status_code == 403
    assert c.post("/api/scheduler/topics/t1/revert-candidate", headers=_auth(VIEWER_TOKEN),
                  json={"confirm": True}).status_code == 403
    assert topic_mocks["checks"] == 0 and topic_mocks["transitions"] == []
