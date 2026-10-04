"""tests/test_publishing_policy_source.py
CALCMATE-DASHBOARD-SCHEDULE-UI-API-FIX-IMPLEMENT-01

GET /api/scheduler/publishing-policy의 source("config" | "default") 필드 검증.
ConfigService는 전부 tmp_path의 임시 config.yaml로 monkeypatch한다 — 실제
config/config.yaml은 읽기(해시 비교)만 하고 절대 쓰지 않는다(autouse guard).
관리자 권한은 dependency override로 주입한다(CALCMATE_DASHBOARD_LOCAL_MODE 불필요).
"""
import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REAL_CONFIG = ROOT / "config" / "config.yaml"

import api.services.publishing_policy_service as pps  # noqa: E402
from api.services.config_service import ConfigService  # noqa: E402
from modules import publishing_policy as PP  # noqa: E402

SAVED_POLICY = {
    "timezone": "Asia/Seoul",
    "weekdays": {
        "mon": {"count": 0, "time_ranges": []},
        "tue": {"count": 0, "time_ranges": []},
        "wed": {"count": 0, "time_ranges": []},
        "thu": {"count": 0, "time_ranges": []},
        "fri": {"count": 1, "time_ranges": [{"start": "07:00", "end": "07:30"}]},
        "sat": {"count": 0, "time_ranges": []},
        "sun": {"count": 0, "time_ranges": []},
    },
    "max_pending_reservations": 10,
}


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _real_config_untouched():
    before = _sha(REAL_CONFIG)
    yield
    assert _sha(REAL_CONFIG) == before, "실제 config/config.yaml이 변경됨"


@pytest.fixture
def tmp_cfg(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("BLOG_SCHEDULE:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(pps, "ConfigService", lambda: ConfigService(config_path=cfg))
    return cfg


def _write_policy(cfg_path, policy):
    ConfigService(config_path=cfg_path).patch_publishing_policy(policy)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    from api.auth.dependencies import require_admin
    from api.auth.models import CurrentUser, Role
    app.dependency_overrides[require_admin] = lambda: CurrentUser(
        id="test-admin", role=Role.ADMIN, authenticated=True)
    try:
        yield TestClient(app)          # lifespan 미실행(context manager 미사용) → worker 미기동
    finally:
        app.dependency_overrides.pop(require_admin, None)


# 1 ─ 섹션 없음 → default
def test_1_missing_section_is_default(tmp_cfg):
    policy, source = pps.get_policy_with_source()
    assert source == "default"
    assert policy == PP.DEFAULT_POLICY


# 2 ─ 섹션 있음 → config
def test_2_saved_section_is_config(tmp_cfg):
    _write_policy(tmp_cfg, SAVED_POLICY)
    policy, source = pps.get_policy_with_source()
    assert source == "config"
    assert policy["weekdays"]["fri"] == SAVED_POLICY["weekdays"]["fri"]


# 3 ─ 빈 섹션 → default
def test_3_empty_section_is_default(tmp_cfg):
    tmp_cfg.write_text("PUBLISHING_POLICY: {}\n", encoding="utf-8")
    _, source = pps.get_policy_with_source()
    assert source == "default"


# 4 ─ DEFAULT_POLICY 원본 불변 (반환값을 변경해도, GET을 거쳐도)
def test_4_default_policy_not_mutated(tmp_cfg, client):
    snapshot = copy.deepcopy(PP.DEFAULT_POLICY)
    policy, _ = pps.get_policy_with_source()
    assert policy is not PP.DEFAULT_POLICY
    policy["source"] = "x"
    policy["weekdays"]["mon"]["count"] = 99
    client.get("/api/scheduler/publishing-policy")
    assert PP.DEFAULT_POLICY == snapshot
    assert "source" not in PP.DEFAULT_POLICY
    assert PP.validate_policy(PP.DEFAULT_POLICY) == []


# 5 ─ GET endpoint에 source 포함, 기존 필드 유지
@pytest.mark.parametrize("saved,expected", [(False, "default"), (True, "config")])
def test_5_get_endpoint_has_source_and_existing_fields(tmp_cfg, client, saved, expected):
    if saved:
        _write_policy(tmp_cfg, SAVED_POLICY)
    body = client.get("/api/scheduler/publishing-policy").json()
    assert body["success"] is True
    data = body["data"]
    assert data["source"] == expected
    assert set(data) == {"timezone", "weekdays", "max_pending_reservations", "source"}
    assert set(data["weekdays"]) == set(PP.WEEKDAYS)


# 6 ─ preview는 기존대로 동작 (source가 검증에 섞이지 않음)
@pytest.mark.parametrize("saved", [False, True])
def test_6_preview_still_works(tmp_cfg, client, saved):
    if saved:
        _write_policy(tmp_cfg, SAVED_POLICY)
    body = client.get("/api/scheduler/publishing-policy/preview?days=7").json()
    assert body["success"] is True, body
    assert "source" not in body["data"]


# 7 ─ PATCH 계약: 응답에 source 없음, source를 보내면 기존처럼 거부(extra=forbid)
def test_7_patch_contract_unchanged(tmp_cfg, client):
    r = client.patch("/api/scheduler/publishing-policy", json=SAVED_POLICY)
    body = r.json()
    assert r.status_code == 200 and body["success"] is True
    assert "source" not in body["data"]
    assert body["data"]["weekdays"]["fri"]["count"] == 1
    r2 = client.patch("/api/scheduler/publishing-policy", json={**SAVED_POLICY, "source": "config"})
    assert r2.status_code == 422
    # PATCH 후 GET은 config로 전환
    assert client.get("/api/scheduler/publishing-policy").json()["data"]["source"] == "config"
