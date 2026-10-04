# -*- coding: utf-8 -*-
"""tests/test_fastapi_calculator_checklist_write.py — STEP 4-H-2 Calculator
Legal Hold 체크리스트 조회/수정(GET/PATCH) endpoint 검증.

이 파일의 단위 테스트는 실제 DB/Production Registry(docs/registry/*.yaml)를
절대 건드리지 않는다. modules.app_factory.get_af_checklist()/
save_af_checklist()의 실제 로직은 그대로 실행하되(재구현하지 않음), 읽기/쓰기
대상 디렉터리(_REG_DIR)만 tmp_path로 격리한다 — STEP 4-H-1과 동일한 격리 방식
(registry_loader.py와 app_factory.py가 각각 별도의 _REG_DIR 모듈 변수를 가짐).
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from _route_utils import write_routes

VIEWER_TOKEN = "step4h2-test-viewer-token"
ADMIN_TOKEN = "step4h2-test-admin-token"

CALC_ROW = {
    "id": "calc_test_h2",
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
      label: 계산 공식 정확성
      display_value: 'x'
      auto_source: formula_field
      checked: false
      checked_by: null
      checked_at: null
    - id: c2
      severity: advisory
      label: 참고 문구 확인
      display_value: ''
      auto_source: null
      checked: true
      checked_by: operator
      checked_at: '2026-01-01T00:00:00Z'
non-app-factory-calc:
  source: seed
  status: READY
  category: ''
  review_checklist: []
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
    """DB를 절대 건드리지 않는 in-memory 대체. checklist 경로는 DB를 전혀
    쓰지 않으므로 update/save는 호출되면 즉시 실패시켜 실측으로 증명한다."""

    def __init__(self, rows):
        self._rows = {r["slug"]: dict(r) for r in rows}

    def get_by_slug(self, slug):
        r = self._rows.get(slug)
        return dict(r) if r else None

    def get_all(self):
        return [dict(r) for r in self._rows.values()]

    def update(self, *a, **kw):
        raise AssertionError("checklist 경로에서 DB update가 호출되면 안 된다")

    def save(self, *a, **kw):
        raise AssertionError("checklist 경로에서 DB save가 호출되면 안 된다")


@pytest.fixture
def fake_registry(tmp_path, monkeypatch):
    import modules.registry_loader as registry_loader
    import modules.app_factory as app_factory
    import api.services.calculator_service as svc

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    (reg_dir / "labor_af.yaml").write_text(REGISTRY_YAML, encoding="utf-8")

    monkeypatch.setattr(registry_loader, "_REG_DIR", reg_dir)
    monkeypatch.setattr(app_factory, "_REG_DIR", reg_dir)
    registry_loader.invalidate()

    slugs = ["test-calculator", "non-app-factory-calc"]
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
        raise AssertionError("Calculator checklist 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


def _read_checklist(reg_dir, slug):
    data = yaml.safe_load((reg_dir / "labor_af.yaml").read_text(encoding="utf-8"))
    return data[slug]["review_checklist"]


def _read_status(reg_dir, slug):
    data = yaml.safe_load((reg_dir / "labor_af.yaml").read_text(encoding="utf-8"))
    return data[slug]["status"]


# ══════════════════════════════════════════════════════════════════════════
# GET
# ══════════════════════════════════════════════════════════════════════════

def test_get_checklist_for_existing_calculator(fake_registry):
    r = _client().get("/api/calculators/test-calculator/checklist")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["slug"] == "test-calculator"
    items = body["data"]["items"]
    assert [i["id"] for i in items] == ["c1", "c2"]
    assert items[0]["severity"] == "critical"
    assert items[0]["checked"] is False
    assert items[1]["checked"] is True
    assert items[1]["checked_by"] == "operator"


def test_get_checklist_unknown_calculator_returns_404(fake_registry):
    r = _client().get("/api/calculators/does-not-exist/checklist")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_get_checklist_as_viewer_allowed(fake_registry):
    r = _client().get("/api/calculators/test-calculator/checklist", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_get_checklist_as_admin_allowed(fake_registry):
    r = _client().get("/api/calculators/test-calculator/checklist", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# PATCH 인증
# ══════════════════════════════════════════════════════════════════════════

def test_patch_checklist_without_auth_returns_401(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
    )
    assert r.status_code == 401
    assert _read_checklist(fake_registry, "test-calculator")[0]["checked"] is False


def test_patch_checklist_as_viewer_returns_403(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(VIEWER_TOKEN),
    )
    assert r.status_code == 403
    assert _read_checklist(fake_registry, "test-calculator")[0]["checked"] is False


# ══════════════════════════════════════════════════════════════════════════
# PATCH 정상 동작
# ══════════════════════════════════════════════════════════════════════════

def test_patch_checklist_as_admin_succeeds_and_sets_actor(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    updated = {i["id"]: i for i in body["data"]["items"]}
    assert updated["c1"]["checked"] is True
    assert updated["c1"]["checked_by"] is not None
    assert updated["c1"]["checked_at"] is not None

    persisted = {i["id"]: i for i in _read_checklist(fake_registry, "test-calculator")}
    assert persisted["c1"]["checked"] is True
    assert persisted["c1"]["checked_by"] is not None


def test_patch_checklist_uncheck_clears_checked_by_and_at(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c2", "checked": False}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    persisted = {i["id"]: i for i in _read_checklist(fake_registry, "test-calculator")}
    assert persisted["c2"]["checked"] is False
    assert persisted["c2"]["checked_by"] is None
    assert persisted["c2"]["checked_at"] is None


def test_patch_checklist_does_not_change_untouched_items(fake_registry, monkeypatch):
    """c1만 patch해도 c2의 checked_by/checked_at/label 등은 그대로 보존되어야 한다."""
    _block_external_http(monkeypatch)
    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    persisted = {i["id"]: i for i in _read_checklist(fake_registry, "test-calculator")}
    assert persisted["c2"]["checked"] is True
    assert persisted["c2"]["checked_by"] == "operator"
    assert persisted["c2"]["checked_at"] == "2026-01-01T00:00:00Z"
    assert persisted["c2"]["label"] == "참고 문구 확인"


def test_patch_checklist_resending_same_value_is_a_noop_for_actor_fields(fake_registry, monkeypatch):
    """이미 checked=True인 c2를 다시 checked=True로 보내면 checked_by/at이
    바뀌지 않아야 한다(dashboard.py의 '값이 실제로 바뀐 항목만 갱신' 규칙과 동일)."""
    _block_external_http(monkeypatch)
    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c2", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    persisted = {i["id"]: i for i in _read_checklist(fake_registry, "test-calculator")}
    assert persisted["c2"]["checked_by"] == "operator"
    assert persisted["c2"]["checked_at"] == "2026-01-01T00:00:00Z"


# ══════════════════════════════════════════════════════════════════════════
# PATCH 입력 검증
# ══════════════════════════════════════════════════════════════════════════

def test_patch_checklist_missing_checked_field_returns_422(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1"}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_checklist_empty_items_returns_422(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": []},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_checklist_unknown_top_level_field_rejected(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}], "force": True},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_checklist_unknown_item_field_rejected(fake_registry, monkeypatch):
    """severity/label/display_value 등은 App Factory가 자동 생성하는 필드이므로
    클라이언트가 직접 덮어쓸 수 없어야 한다(§6)."""
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True, "severity": "advisory"}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_patch_checklist_unknown_item_id_returns_400(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "does-not-exist", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    assert _read_checklist(fake_registry, "test-calculator")[0]["checked"] is False


def test_patch_checklist_non_app_factory_calculator_returns_400(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/non-app-factory-calc/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 400
    assert _read_status(fake_registry, "non-app-factory-calc") == "READY"


def test_patch_checklist_unknown_calculator_returns_404(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/does-not-exist/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Audit
# ══════════════════════════════════════════════════════════════════════════

def test_audit_event_recorded_on_successful_checklist_patch(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "calculator_checklist_update"
    assert events[0].actor_role == "admin"
    assert events[0].resource_id == "test-calculator"
    assert events[0].result == "success"


def test_no_audit_event_on_checklist_patch_failure(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "does-not-exist", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert get_audit_events() == []


def test_no_audit_event_on_401_or_403(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
    )  # 401
    _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(VIEWER_TOKEN),
    )  # 403
    assert get_audit_events() == []


# ══════════════════════════════════════════════════════════════════════════
# DB 무영향 (실측)
# ══════════════════════════════════════════════════════════════════════════

def test_checklist_patch_never_touches_db(fake_registry, monkeypatch):
    """fake_registry의 _FakeRepo.update/save는 호출되면 즉시 AssertionError를
    던지도록 만들어져 있다 — 예외가 없다는 것 자체가 DB write 0회의 증거다."""
    _block_external_http(monkeypatch)
    r = _client().patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200  # _FakeRepo.update/save가 호출됐다면 여기 도달하지 못했을 것


# ══════════════════════════════════════════════════════════════════════════
# Route surface / 회귀
# ══════════════════════════════════════════════════════════════════════════

def test_no_external_http_on_any_checklist_path(fake_registry, monkeypatch):
    _block_external_http(monkeypatch)
    c = _client()
    c.get("/api/calculators/test-calculator/checklist")
    c.patch("/api/calculators/test-calculator/checklist", json={"items": [{"id": "c1", "checked": True}]})  # 401
    c.patch(
        "/api/calculators/test-calculator/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(VIEWER_TOKEN),
    )  # 403
    c.patch(
        "/api/calculators/does-not-exist/checklist",
        json={"items": [{"id": "c1", "checked": True}]},
        headers=_auth(ADMIN_TOKEN),
    )  # 404


def test_existing_calculator_routes_unaffected(fake_registry):
    """STEP 4-G formula / STEP 4-H-1 promote가 checklist 추가로 영향받지 않는지 확인."""
    r = _client().get("/api/calculators/test-calculator/formula")
    assert r.status_code == 200


def test_calculators_has_exactly_the_four_write_routes():
    """STEP 4-H-5: generate POST, P0-2: build/deploy POST가 require_admin() 뒤에서
    정당하게 추가되어 이제 6개다."""
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
