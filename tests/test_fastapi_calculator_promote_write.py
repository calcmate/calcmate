# -*- coding: utf-8 -*-
"""tests/test_fastapi_calculator_promote_write.py — STEP 4-H-1 Calculator READY
승인(promote) endpoint 검증.

이 파일의 단위 테스트는 실제 DB/Production Registry(docs/registry/*.yaml)를
절대 건드리지 않는다. modules.app_factory.promote_to_ready()의 실제 로직은
그대로 실행하되(재구현하지 않음), 읽기/쓰기 대상 디렉터리(_REG_DIR)만
tmp_path로 격리한다 — registry_loader.py와 app_factory.py가 각각 별도의
_REG_DIR 모듈 변수를 갖고 있어(읽기/쓰기 경로가 분리) 둘 다 격리해야 한다.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import collect_routes, write_routes

VIEWER_TOKEN = "step4h1-test-viewer-token"
ADMIN_TOKEN = "step4h1-test-admin-token"

CALC_ROW = {
    "id": "calc_test_h1",
    "slug": "test-calculator",
    "name": "테스트 계산기",
    "status": "active",
    "formula": "x",
    "input_schema": {},
    "updated_at": "2026-01-01T00:00:00",
}

REGISTRY_YAML = """\
test-calculator:
  source: app_factory
  status: HOLD
  category: ''
  review_checklist:
    - id: c1
      severity: critical
      checked: true
    - id: c2
      severity: advisory
      checked: false
already-ready-calc:
  source: app_factory
  status: READY
  category: ''
incomplete-calc:
  source: app_factory
  status: HOLD
  category: ''
  review_checklist:
    - id: c1
      severity: critical
      checked: false
non-app-factory-calc:
  source: seed
  status: READY
  category: ''
"""


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


class _FakeRepo:
    """DB를 절대 건드리지 않는 in-memory 대체. get_by_slug만 있으면 충분하다
    (promote_to_ready 자체는 DB를 전혀 쓰지 않으므로 update/insert는 제공하지 않는다
    — 호출되면 즉시 실패시켜 DB write가 0임을 실측으로도 증명한다)."""

    def __init__(self, rows):
        self._rows = {r["slug"]: dict(r) for r in rows}

    def get_by_slug(self, slug):
        r = self._rows.get(slug)
        return dict(r) if r else None

    def get_all(self):
        return [dict(r) for r in self._rows.values()]

    def update(self, *a, **kw):
        raise AssertionError("promote 경로에서 DB update가 호출되면 안 된다")

    def save(self, *a, **kw):
        raise AssertionError("promote 경로에서 DB save가 호출되면 안 된다")


@pytest.fixture
def fake_registry(tmp_path, monkeypatch):
    """registry_loader/app_factory 양쪽의 _REG_DIR을 tmp_path로 격리하고,
    calculator_service의 DB 조회도 fake repo로 대체한다. Production
    docs/registry/*.yaml, 실제 DB에는 어떤 접근도 하지 않는다."""
    import modules.registry_loader as registry_loader
    import modules.app_factory as app_factory
    import api.services.calculator_service as svc

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    (reg_dir / "labor_af.yaml").write_text(REGISTRY_YAML, encoding="utf-8")

    monkeypatch.setattr(registry_loader, "_REG_DIR", reg_dir)
    monkeypatch.setattr(app_factory, "_REG_DIR", reg_dir)
    registry_loader.invalidate()

    slugs = ["test-calculator", "already-ready-calc", "incomplete-calc", "non-app-factory-calc"]
    repo = _FakeRepo([{**CALC_ROW, "slug": s, "id": f"calc_{s}"} for s in slugs])
    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (repo, {}))

    yield reg_dir
    registry_loader.invalidate()


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("Calculator promote 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


def _read_status(reg_dir, slug):
    data = yaml.safe_load((reg_dir / "labor_af.yaml").read_text(encoding="utf-8"))
    return data[slug]["status"]


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_promote_without_auth_returns_401(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post("/api/calculators/test-calculator/promote")
    assert r.status_code == 401
    assert _read_status(fake_registry, "test-calculator") == "HOLD"


def test_promote_as_viewer_returns_403(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/test-calculator/promote", headers=_auth(VIEWER_TOKEN)
    )
    assert r.status_code == 403
    assert _read_status(fake_registry, "test-calculator") == "HOLD"


# ══════════════════════════════════════════════════════════════════════════
# 정상 동작
# ══════════════════════════════════════════════════════════════════════════

def test_promote_as_admin_with_complete_checklist_succeeds(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/test-calculator/promote", headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["slug"] == "test-calculator"
    assert body["data"]["status"] == "READY"
    assert _read_status(fake_registry, "test-calculator") == "READY"


def test_promote_already_ready_is_idempotent_success(fake_registry, monkeypatch):
    """기존 promote_to_ready()의 실제 동작: 이미 READY면 (True, "이미 READY") — 200."""
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/already-ready-calc/promote", headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "READY"
    assert _read_status(fake_registry, "already-ready-calc") == "READY"


# ══════════════════════════════════════════════════════════════════════════
# Checklist 미완료 차단
# ══════════════════════════════════════════════════════════════════════════

def test_promote_incomplete_checklist_returns_400_and_registry_unchanged(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/incomplete-calc/promote", headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400
    assert _read_status(fake_registry, "incomplete-calc") == "HOLD"


def test_promote_non_app_factory_calculator_returns_400_and_unchanged(fake_registry, monkeypatch):
    """기존 계산기(source != app_factory)는 promote 대상이 아니다 — 상태 변경 금지."""
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/non-app-factory-calc/promote", headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 400
    assert _read_status(fake_registry, "non-app-factory-calc") == "READY"


# ══════════════════════════════════════════════════════════════════════════
# Calculator 없음
# ══════════════════════════════════════════════════════════════════════════

def test_promote_unknown_calculator_returns_404(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/does-not-exist/promote", headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Audit
# ══════════════════════════════════════════════════════════════════════════

def test_audit_event_recorded_on_successful_promote(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().post("/api/calculators/test-calculator/promote", headers=_auth(ADMIN_TOKEN))
    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "calculator_promote"
    assert events[0].actor_role == "admin"
    assert events[0].resource_id == "test-calculator"
    assert events[0].result == "success"


def test_no_audit_event_on_checklist_failure(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().post("/api/calculators/incomplete-calc/promote", headers=_auth(ADMIN_TOKEN))
    assert get_audit_events() == []


def test_no_audit_event_on_401_or_403(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().post("/api/calculators/test-calculator/promote")  # 401
    _client().post("/api/calculators/test-calculator/promote", headers=_auth(VIEWER_TOKEN))  # 403
    assert get_audit_events() == []


# ══════════════════════════════════════════════════════════════════════════
# DB 무영향 (실측)
# ══════════════════════════════════════════════════════════════════════════

def test_promote_never_touches_db(fake_registry, monkeypatch):
    """fake_registry의 _FakeRepo.update/save는 호출되면 즉시 AssertionError를
    던지도록 만들어져 있다 — 예외가 없다는 것 자체가 DB write 0회의 증거다."""
    _block_external_http(monkeypatch)
    r = _client().post("/api/calculators/test-calculator/promote", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200  # _FakeRepo.update/save가 호출됐다면 여기 도달하지 못했을 것


# ══════════════════════════════════════════════════════════════════════════
# Route surface / 회귀
# ══════════════════════════════════════════════════════════════════════════

def test_no_external_http_on_any_promote_path(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    c = _client()
    c.post("/api/calculators/test-calculator/promote")  # 401
    c.post("/api/calculators/test-calculator/promote", headers=_auth(VIEWER_TOKEN))  # 403
    c.post("/api/calculators/incomplete-calc/promote", headers=_auth(ADMIN_TOKEN))  # 400
    c.post("/api/calculators/does-not-exist/promote", headers=_auth(ADMIN_TOKEN))  # 404


def test_existing_calculator_routes_unaffected(fake_registry):
    """STEP 4-G의 formula GET/PATCH가 promote 추가로 영향받지 않는지 확인."""
    r = _client().get("/api/calculators/test-calculator/formula")
    assert r.status_code == 200


def test_calculators_has_exactly_formula_promote_checklist_and_generate_write_routes():
    """STEP 4-H-2: checklist PATCH, STEP 4-H-5: generate POST, P0-2: build/deploy
    POST가 require_admin() 뒤에서 정당하게 추가되어 이제 6개다."""
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
