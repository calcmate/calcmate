# -*- coding: utf-8 -*-
"""tests/test_fastapi_calculator_formula_write.py — STEP 4-G Calculator Formula
GET/PATCH endpoint 검증.

이 파일의 단위 테스트는 실제 DB/Registry/WordPress를 절대 건드리지 않는다.
calculator_service._repo_and_cfg()와 _registry()를 in-memory fake로 대체해
격리한다(기존 test_fastapi_publish_write.py의 fake_articles 패턴과 동일 철학).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

VIEWER_TOKEN = "step4g-test-viewer-token"
ADMIN_TOKEN = "step4g-test-admin-token"

CALC_ROW = {
    "id": "calc_test_001",
    "slug": "test-calculator",
    "name": "테스트 계산기",
    "status": "active",
    "formula": "monthly_salary * years",
    "input_schema": {"monthly_salary": "number", "years": "number"},
    "updated_at": "2026-01-01T00:00:00",
}
V3_REGISTRY = {"test-calculator": {"status": "READY", "source": "seed"}}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


class _FakeRepo:
    """in-memory Calculator 저장소. 실제 DB adapter를 절대 사용하지 않는다."""

    def __init__(self, rows):
        self._rows = {r["id"]: dict(r) for r in rows}

    def get_by_slug(self, slug):
        for r in self._rows.values():
            if r.get("slug") == slug:
                return dict(r)
        return None

    def get_by_id(self, calc_id):
        r = self._rows.get(calc_id)
        return dict(r) if r else None

    def get_all(self):
        return [dict(r) for r in self._rows.values()]

    def update(self, calc_id, data):
        assert calc_id in self._rows, "존재하지 않는 id에 update 시도"
        self._rows[calc_id].update(data)
        self._rows[calc_id]["updated_at"] = "2026-01-02T00:00:00"


@pytest.fixture
def fake_calculators(monkeypatch):
    """calculator_service._repo_and_cfg()/_registry()를 격리한다 — 실제
    get_db_adapter/load_registry_v3/secrets.yaml에 절대 접근하지 않는다.

    modules.formula_engine.save_formula()는 자체적으로 새 _repo(cfg)(=실제
    get_db_adapter)를 만드는 구조라, service 레이어의 repo만 바꿔서는 격리되지
    않는다(실제 운영에서는 cfg가 진짜 config라 문제없이 동작하지만, 테스트에서는
    실제 DB 접근을 완전히 차단하기 위해 save_formula 자체를 이 fake repo로
    연결한다 — validate_formula는 순수 함수라 그대로 둔다)."""
    import api.services.calculator_service as svc
    import modules.formula_engine as fe

    repo = _FakeRepo([CALC_ROW])
    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (repo, {}))
    monkeypatch.setattr(svc, "_registry", lambda: dict(V3_REGISTRY))

    def _fake_save_formula(cfg, calculator_id, formula):
        import json as _json
        val = formula if isinstance(formula, str) else _json.dumps(formula, ensure_ascii=False)
        repo.update(calculator_id, {"formula": val})

    monkeypatch.setattr(fe, "save_formula", _fake_save_formula)
    return repo


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("Calculator formula 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


# ══════════════════════════════════════════════════════════════════════════
# GET
# ══════════════════════════════════════════════════════════════════════════

def test_get_formula_ok(fake_calculators):
    r = _client().get("/api/calculators/test-calculator/formula")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["formula"] == "monthly_salary * years"
    assert body["data"]["input_schema"] == {"monthly_salary": "number", "years": "number"}


def test_get_formula_not_found(fake_calculators):
    r = _client().get("/api/calculators/does-not-exist/formula")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_get_formula_response_schema_has_no_internal_paths_or_secrets(fake_calculators):
    r = _client().get("/api/calculators/test-calculator/formula")
    data = r.json()["data"]
    assert set(data.keys()) == {"slug", "name", "formula", "input_schema", "updated_at"}
    text = r.text
    assert "secrets.yaml" not in text
    assert "config.yaml" not in text
    assert "APP_PASSWORD" not in text


# ══════════════════════════════════════════════════════════════════════════
# PATCH 인증/권한
# ══════════════════════════════════════════════════════════════════════════

def test_patch_without_auth_returns_401(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula", json={"formula": "x * 2"}
    )
    assert r.status_code == 401
    assert fake_calculators.get_by_slug("test-calculator")["formula"] == "monthly_salary * years"


def test_patch_as_viewer_returns_403(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "x * 2"},
        headers=_auth(VIEWER_TOKEN),
    )
    assert r.status_code == 403
    assert fake_calculators.get_by_slug("test-calculator")["formula"] == "monthly_salary * years"


def test_patch_as_admin_succeeds(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "monthly_salary * years * 2"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["formula"] == "monthly_salary * years * 2"


# ══════════════════════════════════════════════════════════════════════════
# PATCH validation
# ══════════════════════════════════════════════════════════════════════════

def test_patch_valid_formula_saves(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "min(monthly_salary, years)"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    assert fake_calculators.get_by_slug("test-calculator")["formula"] == "min(monthly_salary, years)"


def test_patch_invalid_formula_rejected_with_400_and_preserves_existing(fake_calculators, monkeypatch):
    """§9: 검증 실패 시 저장을 시도하지 않으므로 기존 formula가 유지된다."""
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "monthly_salary + undefined_variable"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    assert fake_calculators.get_by_slug("test-calculator")["formula"] == "monthly_salary * years"


def test_patch_disallowed_syntax_rejected_with_400(fake_calculators, monkeypatch):
    """ast 화이트리스트 밖 구문(예: attribute/subscript/lambda)은 거부된다."""
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "__import__('os').system('x')"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    assert fake_calculators.get_by_slug("test-calculator")["formula"] == "monthly_salary * years"


def test_patch_unknown_field_rejected_with_422(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "x", "not_a_real_field": "x"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_invalid_type_rejected_with_422(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": 12345},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_empty_formula_rejected_with_422(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": ""},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_unknown_calculator_returns_404(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/does-not-exist/formula",
        json={"formula": "x"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# 부분 업데이트 / 다른 필드 보존
# ══════════════════════════════════════════════════════════════════════════

def test_patch_preserves_other_fields(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "years * 12"},
        headers=_auth(ADMIN_TOKEN),
    )
    row = fake_calculators.get_by_slug("test-calculator")
    assert row["formula"] == "years * 12"
    assert row["name"] == "테스트 계산기"
    assert row["status"] == "active"
    assert row["input_schema"] == {"monthly_salary": "number", "years": "number"}


# ══════════════════════════════════════════════════════════════════════════
# Audit
# ══════════════════════════════════════════════════════════════════════════

def test_audit_event_recorded_on_successful_patch(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "years * 12"},
        headers=_auth(ADMIN_TOKEN),
    )
    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "calculator_formula_patch"
    assert events[0].actor_role == "admin"
    assert events[0].resource_id == "test-calculator"
    assert events[0].result == "success"


def test_no_audit_event_on_validation_failure(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/calculators/test-calculator/formula",
        json={"formula": "undefined_variable"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert get_audit_events() == []


# ══════════════════════════════════════════════════════════════════════════
# 운영 보호 — 이 STEP은 DB/Registry/WordPress를 원천적으로 건드릴 수 없는 구조다.
# fake_calculators fixture가 실제 get_db_adapter/load_registry_v3를 완전히
# 대체하므로, "실제 Registry/DB 미변경"은 아키텍처상 자명하다(별도 assert 불필요).
# WordPress는 이 라우터 경로에 애초에 관련 코드가 없다 — _block_external_http로
# 모든 HTTP 메서드를 강제 차단해 실측으로도 확인한다(위 각 테스트에 이미 적용).
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Route surface / 회귀
# ══════════════════════════════════════════════════════════════════════════

def test_no_external_http_on_any_formula_path(fake_calculators, monkeypatch):
    _block_external_http(monkeypatch)
    c = _client()
    c.get("/api/calculators/test-calculator/formula")
    c.patch("/api/calculators/test-calculator/formula", json={"formula": "x"})  # 401
    c.patch("/api/calculators/test-calculator/formula", json={"formula": "x"}, headers=_auth(VIEWER_TOKEN))  # 403
    c.patch("/api/calculators/test-calculator/formula", json={"formula": "years * 2"}, headers=_auth(ADMIN_TOKEN))  # 200


def test_existing_calculator_get_routes_still_unauthenticated(fake_calculators):
    r = _client().get("/api/calculators")
    assert r.status_code == 200
    r2 = _client().get("/api/calculators/test-calculator")
    assert r2.status_code == 200
    r3 = _client().get("/api/calculators/test-calculator/content")
    assert r3.status_code == 200
    r4 = _client().get("/api/calculators/test-calculator/status")
    assert r4.status_code == 200


def test_calculators_has_only_the_formula_promote_checklist_and_generate_write_routes():
    """STEP 4-H-1: promote POST, STEP 4-H-2: checklist PATCH, STEP 4-H-5:
    generate POST, P0-2: build/deploy POST가 require_admin() 뒤에서 정당하게
    추가되어 이제 6개다."""
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert write_paths == [
        ("/api/calculators/ai/suggest-formula", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/ai/suggest-idea", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/ai/suggest-mode", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/ai/suggest-spec", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/ai/suggest-tier", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/ai/tier2b-keywords", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/generate", "POST"),
        ("/api/calculators/generate/contract", "POST"),
        ("/api/calculators/generate/contract/slug-check", "POST"),
        ("/api/calculators/generate/contract/slug-suggest", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/generate/contract/validate", "POST"),
        ("/api/calculators/generate/contract/{job_id}/confirm-formula", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/generate/contract/{job_id}/save", "POST"),
        ("/api/calculators/generate/preview", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/generate/preview/{job_id}/discard", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/generate/preview/{job_id}/save", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/{slug}/build", "POST"),
        ("/api/calculators/{slug}/checklist", "PATCH"),
        ("/api/calculators/{slug}/content/body", "POST"),
        ("/api/calculators/{slug}/content/faq", "POST"),
        ("/api/calculators/{slug}/content/generate", "POST"),
        ("/api/calculators/{slug}/content/image", "POST"),
        ("/api/calculators/{slug}/content/seo", "POST"),
        ("/api/calculators/{slug}/delete/confirm", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/{slug}/delete/prepare", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
        ("/api/calculators/{slug}/deploy", "POST"),
        ("/api/calculators/{slug}/formula", "PATCH"),
        ("/api/calculators/{slug}/promote", "POST"),
        ("/api/calculators/{slug}/review/approve", "POST"),
        ("/api/calculators/{slug}/review/unapprove", "POST"),
        ("/api/calculators/{slug}/status", "POST"),  # C-TEST-CONTRACT-FIX-02: 이관 추가분
    ]
