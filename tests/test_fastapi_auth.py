# -*- coding: utf-8 -*-
"""tests/test_fastapi_auth.py — STEP 18-Q 인증/권한 최소 구조 검증.

이번 STEP은 실제 Publish/Trash/Scheduler 쓰기 동작을 절대 호출하지 않는다.
검증 대상은 순수하게 api/auth/* 의 인증 dependency 체인과, 그 체인을 실제
HTTP 요청 경로에서 확인하기 위한 두 GET 진단 endpoint(/api/auth/me,
/api/auth/admin-check)뿐이다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException
from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

VIEWER_TOKEN = "step18q-test-viewer-token"
ADMIN_TOKEN = "step18q-test-admin-token"

# STEP 18-Q 시점엔 2개였다. STEP 18-R에서 Publish Edit/Trash/Restore 3개가
# require_admin() 뒤에서 정당하게 추가되어 5개, STEP 4-F에서 Settings General
# PATCH가 동일하게 require_admin() 뒤에서 추가되어 이제 6개가 맞다.
EXPECTED_WRITE_ROUTES = frozenset({
    ("/api/scheduler/blog/config", "PATCH"),
    ("/api/scheduler/blog/run-once", "POST"),
    ("/api/publish/{article_id}/edit", "POST"),
    ("/api/trash/{article_id}", "POST"),
    ("/api/trash/{article_id}/restore", "POST"),
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
    # STEP S5: Cost Manager 수동 재개 / Retry Queue 수동 재시도 POST 2개가
    # require_admin() 뒤에서 정당하게 추가됨.
    ("/api/costs/resume", "POST"),
    ("/api/costs/retry", "POST"),
    # STEP S6: Retry Queue 수동 제거 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/costs/remove", "POST"),
    # STEP S8: Strategy Room 실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/strategy-room/run", "POST"),
    # STEP S10: Content Sync 수동 실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/scheduler/content-sync/run-once", "POST"),
    # STEP S11: Quick Action 「계산기 생성」 수동 실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/scheduler/calculator/run-once", "POST"),
    # STEP S12: Quick Action 「파이프라인 실행(전량)」 수동 실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/scheduler/pipeline/run-once", "POST"),
    # STEP S13: Quick Action 「▶ 실행」(통합 실행) 수동 실행 POST가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/scheduler/integrated/run-once", "POST"),
    # STEP P2-06: Site Management 생성/Import POST 2개가 require_admin() 뒤에서 정당하게 추가됨.
    ("/api/sites", "POST"),
    ("/api/sites/import", "POST"),
    # STEP P2-07: 사이트 기본 정보 수정/Override 저장·초기화가 require_admin() 뒤에서 정당하게 추가됨.
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


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    """모든 테스트가 동일한 테스트 전용 토큰을 사용하도록 격리한다.
    실제 토큰 값은 저장소에 없다 — 여기서만 임시로 설정한다."""
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Authentication ───────────────────────────────────────────────────────

def test_missing_credentials_returns_401():
    r = _client().get("/api/auth/me")
    assert r.status_code == 401


def test_invalid_credentials_returns_401():
    r = _client().get("/api/auth/me", headers=_auth("not-a-real-token"))
    assert r.status_code == 401


def test_empty_bearer_token_returns_401():
    r = _client().get("/api/auth/me", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_malformed_authorization_header_returns_401():
    r = _client().get("/api/auth/me", headers={"Authorization": VIEWER_TOKEN})  # "Bearer " 접두사 없음
    assert r.status_code == 401


def test_valid_viewer_authenticated():
    r = _client().get("/api/auth/me", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["role"] == "viewer"


def test_valid_admin_authenticated():
    r = _client().get("/api/auth/me", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "admin"


# ── Authorization ────────────────────────────────────────────────────────

def test_viewer_cannot_admin_action():
    r = _client().get("/api/auth/admin-check", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_admin_can_admin_action():
    r = _client().get("/api/auth/admin-check", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["admin"] is True


def test_no_credentials_on_admin_action_is_401_not_403():
    """인증 자체가 안 된 경우 403이 아니라 401이어야 한다(순서: 인증 → 권한)."""
    r = _client().get("/api/auth/admin-check")
    assert r.status_code == 401


# ── §8/§9: dependency 자체를 직접 호출해 격리 검증(실제 endpoint 미실행) ────

def test_require_authenticated_dependency_rejects_anonymous_directly():
    from api.auth.dependencies import require_authenticated
    from api.auth.models import CurrentUser

    with pytest.raises(HTTPException) as exc:
        require_authenticated(CurrentUser.anonymous())
    assert exc.value.status_code == 401


def test_require_admin_dependency_rejects_viewer_directly():
    from api.auth.dependencies import require_admin
    from api.auth.models import CurrentUser, Role

    viewer = CurrentUser(id="dev-viewer", role=Role.VIEWER, authenticated=True)
    with pytest.raises(HTTPException) as exc:
        require_admin(viewer)
    assert exc.value.status_code == 403


def test_require_admin_dependency_accepts_admin_directly():
    from api.auth.dependencies import require_admin
    from api.auth.models import CurrentUser, Role

    admin = CurrentUser(id="dev-admin", role=Role.ADMIN, authenticated=True)
    result = require_admin(admin)
    assert result.role == Role.ADMIN


def test_planned_write_endpoint_policy_requires_admin_for_all_three():
    """§9: Publish/Trash 미래 write endpoint 정책이 전부 admin을 요구하는지,
    그리고 이 정책이 실제 등록된 route가 아직 아님을 함께 확인한다."""
    from api.auth.service import PLANNED_WRITE_ENDPOINT_POLICY
    from api.auth.models import Role

    expected_keys = {
        "POST /api/publish/{id}/edit",
        "POST /api/trash/{id}",
        "POST /api/trash/{id}/restore",
    }
    assert set(PLANNED_WRITE_ENDPOINT_POLICY.keys()) == expected_keys
    assert all(role == Role.ADMIN for role in PLANNED_WRITE_ENDPOINT_POLICY.values())

    # 정책은 존재하지만 실제 route로는 아직 등록되지 않았어야 한다.
    from api.main import app
    registered = {(r.path, m) for r in collect_routes(app) for m in r.methods}
    assert ("/api/publish/{id}/edit", "POST") not in registered
    assert ("/api/trash/{id}", "POST") not in registered
    assert ("/api/trash/{id}/restore", "POST") not in registered


# ── Token leakage(§11) ────────────────────────────────────────────────────

def test_token_not_leaked_in_response_body():
    r = _client().get("/api/auth/me", headers=_auth(VIEWER_TOKEN))
    assert VIEWER_TOKEN not in r.text


def test_token_not_leaked_in_401_error_body():
    r = _client().get("/api/auth/me", headers=_auth("some-invalid-token-xyz"))
    assert "some-invalid-token-xyz" not in r.text


def test_token_not_leaked_in_403_error_body():
    r = _client().get("/api/auth/admin-check", headers=_auth(VIEWER_TOKEN))
    assert VIEWER_TOKEN not in r.text


def test_token_not_present_in_audit_event_dataclass_fields():
    """AuditEvent 구조 자체에 토큰을 담을 필드가 없는지 확인(모델 레벨 방지)."""
    from api.auth.models import AuditEvent
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(AuditEvent)}
    assert "token" not in field_names
    assert "authorization" not in field_names
    assert "credential" not in field_names
    assert field_names == {"actor_id", "actor_role", "action", "resource", "resource_id", "result", "timestamp"}


def test_audit_event_recording_does_not_touch_pipeline_log():
    from pathlib import Path
    from api.auth.models import AuditEvent
    from api.auth.service import record_audit_event, get_audit_events

    pipeline_log = Path(__file__).resolve().parent.parent / "data" / "logs" / "pipeline.log"
    before_size = pipeline_log.stat().st_size if pipeline_log.exists() else None

    record_audit_event(AuditEvent(
        actor_id="dev-admin", actor_role="admin", action="publish.edit",
        resource="article", resource_id="test-id-not-real", result="simulated",
    ))
    events = get_audit_events()
    assert len(events) == 1
    assert events[0].resource_id == "test-id-not-real"

    after_size = pipeline_log.stat().st_size if pipeline_log.exists() else None
    assert before_size == after_size


def test_authenticate_token_does_not_log(caplog):
    """토큰 검증 과정에서 어떤 로거로도 토큰 문자열이 기록되지 않는지 확인."""
    import logging
    from api.auth.service import authenticate_token

    with caplog.at_level(logging.DEBUG):
        authenticate_token(ADMIN_TOKEN)
        authenticate_token("invalid-xyz-token")

    for record in caplog.records:
        assert ADMIN_TOKEN not in record.getMessage()
        assert "invalid-xyz-token" not in record.getMessage()


# ── §12: Write surface 절대 증가 금지 ─────────────────────────────────────

def test_write_surface_is_exactly_the_expected_five():
    from api.main import app
    actual = frozenset(write_routes(app))
    assert actual == EXPECTED_WRITE_ROUTES, f"write surface가 변경됨: {sorted(actual)}"


def test_no_write_routes_under_auth_itself():
    """/api/auth 자체는 진단용 GET 2개뿐이며 어떤 write route도 없다(STEP 18-Q/18-R
    모두에서 유지). Publish/Trash의 write 3개는 STEP 18-R에서 정당하게 존재하므로
    이 파일에서는 더 이상 0을 기대하지 않는다 — 그 검증은
    tests/test_fastapi_publish_write.py가 전담한다."""
    from api.main import app
    assert write_routes(app, prefix="/api/auth") == []


def test_auth_get_routes_are_registered():
    from api.main import app
    found = {(r.path, m) for r in collect_routes(app) for m in r.methods}
    assert ("/api/auth/me", "GET") in found
    assert ("/api/auth/admin-check", "GET") in found


# ── §7: 기존 GET API는 인증을 강제하지 않는다 ─────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/health/details",
    "/api/dashboard/status",
    "/api/scheduler/blog/status",
    "/api/scheduler/calculator/status",
    "/api/scheduler/content-sync/status",
    "/api/calculators",
    "/api/publish",
    "/api/publish/articles",
    "/api/trash",
    "/api/logs/errors",
    "/api/logs/recent",
    # STEP S4: /api/costs는 require_admin으로 전환되어 더 이상 이 목록에 없다
    # (tests/test_cost_monitor.py가 그 인증 요구사항을 전담 검증한다).
    "/api/pipeline/status",
    "/api/settings",
    "/api/settings/general",
])
def test_existing_get_routes_remain_unauthenticated(path):
    r = _client().get(path)
    assert r.status_code == 200


# ── §15: 외부 호출/Publisher 미호출 확인 ──────────────────────────────────

def test_auth_flow_makes_no_external_http_calls(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("인증 처리 중 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)

    c = _client()
    c.get("/api/auth/me", headers=_auth(ADMIN_TOKEN))
    c.get("/api/auth/admin-check", headers=_auth(ADMIN_TOKEN))
    c.get("/api/auth/me")  # 401 경로도 포함


def test_auth_flow_does_not_call_publisher(monkeypatch):
    import modules.publisher as publisher

    def _boom(*a, **kw):
        raise AssertionError("인증 처리 중 modules.publisher가 호출되면 안 된다")

    for fn in ("publish", "update_post", "delete_post", "restore_post", "get_post"):
        if hasattr(publisher, fn):
            monkeypatch.setattr(publisher, fn, _boom)

    c = _client()
    c.get("/api/auth/me", headers=_auth(ADMIN_TOKEN))
    c.get("/api/auth/admin-check", headers=_auth(ADMIN_TOKEN))
