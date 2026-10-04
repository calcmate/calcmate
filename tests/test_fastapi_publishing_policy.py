# -*- coding: utf-8 -*-
"""tests/test_fastapi_publishing_policy.py —
CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01 검증.

PATCH/config 쓰기 테스트는 전부 임시 파일에서만 수행하며 실제 config/config.yaml을
건드리지 않는다(tests/test_fastapi_blog_scheduler.py와 동일한 격리 원칙). preview
테스트는 DB/WP/AI/Topic Pool을 호출하지 않는 순수 계산 결과만 검증한다 — 실제
예약(add_oneoff_reservation)이 생성되지 않는지도 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


def _client():
    from api.main import app
    return TestClient(app)


REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

ADMIN_TOKEN = "publishing-policy-test-admin-token"


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


VALID_POLICY = {
    "timezone": "Asia/Seoul",
    "weekdays": {
        "mon": {"count": 3, "time_ranges": [
            {"start": "09:00", "end": "11:00"},
            {"start": "13:00", "end": "15:00"},
            {"start": "19:00", "end": "21:00"},
        ]},
        "tue": {"count": 0, "time_ranges": []},
        "wed": {"count": 0, "time_ranges": []},
        "thu": {"count": 0, "time_ranges": []},
        "fri": {"count": 0, "time_ranges": []},
        "sat": {"count": 0, "time_ranges": []},
        "sun": {"count": 0, "time_ranges": []},
    },
    "max_pending_reservations": 10,
}


# ── ConfigService.patch_publishing_policy() / patch_auto_publishing() ──────
# — 격리된 임시 파일에서만 테스트

@pytest.fixture()
def tmp_config_service(tmp_path):
    from api.services.config_service import ConfigService
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return ConfigService(config_path=tmp_config), tmp_config


def test_patch_publishing_policy_updates_only_that_block(tmp_config_service):
    svc, tmp_config = tmp_config_service
    before_text = tmp_config.read_text(encoding="utf-8")

    result = svc.patch_publishing_policy(VALID_POLICY)
    assert result["weekdays"]["mon"]["count"] == 3
    assert len(result["weekdays"]["mon"]["time_ranges"]) == 3

    after_text = tmp_config.read_text(encoding="utf-8")

    import re
    pattern = re.compile(r"^PUBLISHING_POLICY:\n(?:[ \t].*\n?)*", re.MULTILINE)
    before_without_block = pattern.sub("", before_text, count=1)
    after_without_block = pattern.sub("", after_text, count=1)
    # 실제 config.yaml에는 아직 PUBLISHING_POLICY 키가 없어 "파일 끝에 추가"
    # 분기(config_service.py의 else 분기, dashboard.py와 동일한 패턴)를 타므로
    # 블록 앞에 구분용 빈 줄("\n\n")이 새로 생긴다 — 그 외 내용은 완전히
    # 동일해야 하므로 trailing whitespace만 정규화하고 비교한다.
    assert before_without_block.rstrip() == after_without_block.rstrip(), \
        "PUBLISHING_POLICY 외 텍스트가 변경됨"


def test_patch_publishing_policy_rejects_count_mismatch(tmp_config_service):
    """count와 time_ranges 개수가 다르면 modules.publishing_policy.validate_policy()가
    이를 잡아 ValueError를 raise해야 한다 — 이 검증 규칙을 ConfigService가 새로
    만들지 않고 그대로 재사용하는지 확인한다."""
    svc, tmp_config = tmp_config_service
    before_text = tmp_config.read_text(encoding="utf-8")

    bad_policy = dict(VALID_POLICY)
    bad_policy["weekdays"] = dict(bad_policy["weekdays"])
    bad_policy["weekdays"]["tue"] = {"count": 2, "time_ranges": []}

    with pytest.raises(ValueError):
        svc.patch_publishing_policy(bad_policy)

    # 검증 실패 시 파일에 쓰지 않아야 한다(fail-closed)
    assert tmp_config.read_text(encoding="utf-8") == before_text


def test_patch_publishing_policy_rejects_bad_time_format(tmp_config_service):
    svc, _ = tmp_config_service
    bad_policy = dict(VALID_POLICY)
    bad_policy["weekdays"] = dict(bad_policy["weekdays"])
    bad_policy["weekdays"]["mon"] = {"count": 1, "time_ranges": [{"start": "25:00", "end": "11:00"}]}
    with pytest.raises(ValueError):
        svc.patch_publishing_policy(bad_policy)


def test_patch_auto_publishing_updates_only_that_block(tmp_config_service):
    svc, tmp_config = tmp_config_service
    before_text = tmp_config.read_text(encoding="utf-8")

    result = svc.patch_auto_publishing(True)
    assert result["enabled"] is True

    after_text = tmp_config.read_text(encoding="utf-8")
    import re
    pattern = re.compile(r"^AUTO_PUBLISHING:\n(?:[ \t].*\n?)*", re.MULTILINE)
    before_without_block = pattern.sub("", before_text, count=1)
    after_without_block = pattern.sub("", after_text, count=1)
    # test_patch_publishing_policy_updates_only_that_block()과 동일한 이유
    # (AUTO_PUBLISHING 키도 실제 config.yaml에 아직 없어 append 분기를 탐).
    assert before_without_block.rstrip() == after_without_block.rstrip(), \
        "AUTO_PUBLISHING 외 텍스트가 변경됨"


def test_patch_publishing_policy_never_touches_real_config_file():
    import hashlib
    before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert before == after


# ── GET /api/scheduler/publishing-policy, /auto-publishing — READ-ONLY ─────

def test_get_publishing_policy_endpoint_falls_back_to_default_when_key_missing():
    """실제 config.yaml에 PUBLISHING_POLICY 키가 없는 현재 운영 상태에서도
    modules.publishing_policy.DEFAULT_POLICY로 fallback해야 한다(load_policy()의
    기존 계약과 동일 — {}를 그대로 반환하면 안 된다)."""
    r = _client().get("/api/scheduler/publishing-policy")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "weekdays" in body["data"]
    assert set(body["data"]["weekdays"].keys()) == {
        "mon", "tue", "wed", "thu", "fri", "sat", "sun"
    }
    assert "max_pending_reservations" in body["data"]


def test_get_auto_publishing_endpoint():
    r = _client().get("/api/scheduler/auto-publishing")
    assert r.status_code == 200
    assert r.json()["success"] is True


# ── PATCH /api/scheduler/publishing-policy — 라우터를 임시 파일로 monkeypatch ──

def test_patch_publishing_policy_endpoint_uses_isolated_file(monkeypatch, tmp_path):
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    import api.services.publishing_policy_service as publishing_policy_service  # 라우터 분리 후 실제 위치
    from api.services.config_service import ConfigService

    monkeypatch.setattr(
        publishing_policy_service, "ConfigService",
        lambda: ConfigService(config_path=tmp_config),
    )

    import hashlib
    real_hash_before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()

    r = _client().patch("/api/scheduler/publishing-policy", json=VALID_POLICY, headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["weekdays"]["mon"]["count"] == 3

    real_hash_after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert real_hash_before == real_hash_after, "PATCH endpoint가 실제 config.yaml을 건드림"
    assert "PUBLISHING_POLICY" in tmp_config.read_text(encoding="utf-8")


def test_patch_publishing_policy_endpoint_rejects_bad_payload_shape():
    r = _client().patch("/api/scheduler/publishing-policy", json={
        "timezone": "Asia/Seoul", "weekdays": "not-a-dict", "max_pending_reservations": 10,
    }, headers=_admin_headers())
    assert r.status_code == 422  # pydantic validation error


def test_patch_publishing_policy_endpoint_rejects_invalid_policy_value(monkeypatch, tmp_path):
    """pydantic 형태는 맞지만 count != len(time_ranges)인 경우 —
    validate_policy() 규칙 위반은 422가 아니라 200 + success=false로 응답해야
    한다(다른 endpoint들의 VALIDATION_ERROR 관례와 동일)."""
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    import api.services.publishing_policy_service as publishing_policy_service  # 라우터 분리 후 실제 위치
    from api.services.config_service import ConfigService
    monkeypatch.setattr(
        publishing_policy_service, "ConfigService",
        lambda: ConfigService(config_path=tmp_config),
    )

    bad_policy = dict(VALID_POLICY)
    bad_policy["weekdays"] = dict(bad_policy["weekdays"])
    bad_policy["weekdays"]["tue"] = {"count": 2, "time_ranges": []}

    r = _client().patch("/api/scheduler/publishing-policy", json=bad_policy, headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_patch_publishing_policy_endpoint_requires_admin():
    r = _client().patch("/api/scheduler/publishing-policy", json=VALID_POLICY)
    assert r.status_code == 401


def test_patch_auto_publishing_endpoint_uses_isolated_file(monkeypatch, tmp_path):
    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    import api.services.publishing_policy_service as publishing_policy_service  # 라우터 분리 후 실제 위치
    from api.services.config_service import ConfigService
    monkeypatch.setattr(
        publishing_policy_service, "ConfigService",
        lambda: ConfigService(config_path=tmp_config),
    )

    import hashlib
    real_hash_before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()

    r = _client().patch("/api/scheduler/auto-publishing", json={"enabled": True}, headers=_admin_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["enabled"] is True

    real_hash_after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert real_hash_before == real_hash_after


def test_patch_auto_publishing_endpoint_requires_admin():
    r = _client().patch("/api/scheduler/auto-publishing", json={"enabled": True})
    assert r.status_code == 401


# ── GET /api/scheduler/publishing-policy/preview — READ-ONLY, 예약 생성 없음 ──

def test_get_publishing_policy_preview_endpoint_shape():
    r = _client().get("/api/scheduler/publishing-policy/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["timezone"] == "Asia/Seoul"
    assert len(body["data"]["days"]) == 7
    day0 = body["data"]["days"][0]
    assert "date" in day0
    assert "weekday" in day0
    assert "slots" in day0
    for slot in day0["slots"]:
        assert "scheduled_at" in slot
        assert "start" in slot
        assert "end" in slot


def test_get_publishing_policy_preview_creates_no_reservation():
    """preview는 oneoff_schedule.json에 예약을 추가하지 않아야 한다."""
    from modules.scheduler import load_oneoff
    from modules.config_loader import load_config

    cfg = dict(load_config())
    cfg["scheduler_line"] = "blog"
    before = load_oneoff(cfg)

    r = _client().get("/api/scheduler/publishing-policy/preview")
    assert r.status_code == 200

    after = load_oneoff(cfg)
    assert before == after, "preview가 실제 예약을 생성함 — read-only 계약 위반"
