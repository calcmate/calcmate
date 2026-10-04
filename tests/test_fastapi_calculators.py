# -*- coding: utf-8 -*-
"""tests/test_fastapi_calculators.py — STEP 18-F Calculator 조회 API 검증.

전부 READ-ONLY. 생성/삭제/배포 endpoint가 존재하지 않는지도 함께 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes


def _client():
    from api.main import app
    return TestClient(app)


def test_get_calculators_list():
    r = _client().get("/api/calculators")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert isinstance(body["data"]["calculators"], list)


def test_calculator_list_matches_registry_v3_count():
    """API가 반환하는 목록 개수 == Registry v3(docs/registry/*.yaml)에 등록된 slug 개수
    중 DB에도 존재하는 것 — dashboard.py의 계산기 관리 탭과 동일한 필터."""
    from modules.registry_loader import load_registry_v3
    from api.services import calculator_service

    v3_reg = load_registry_v3(force=True)
    calcs = calculator_service.list_calculators()

    # API가 반환한 모든 slug는 반드시 Registry v3에 존재해야 한다(필터가 실제로 적용됐는지).
    for c in calcs:
        assert c["slug"] in v3_reg

    r = _client().get("/api/calculators")
    body = r.json()
    assert len(body["data"]["calculators"]) == len(calcs)


def test_get_calculator_detail_for_first_item():
    calcs = _client().get("/api/calculators").json()["data"]["calculators"]
    assert len(calcs) > 0, "실제 등록된 계산기가 1개 이상 있어야 이 테스트가 유효함"
    slug = calcs[0]["slug"]

    r = _client().get(f"/api/calculators/{slug}")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["slug"] == slug


def test_get_calculator_detail_not_found():
    r = _client().get("/api/calculators/this-slug-does-not-exist-xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_get_calculator_content_shape_and_truncation():
    calcs = _client().get("/api/calculators").json()["data"]["calculators"]
    slug = calcs[0]["slug"]

    r = _client().get(f"/api/calculators/{slug}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("seo_title", "seo_description", "faq", "article_content", "article_length", "article_truncated"):
        assert key in data
    assert len(data["article_content"]) <= 2000
    assert isinstance(data["article_length"], int)


def test_get_calculator_content_not_found():
    r = _client().get("/api/calculators/this-slug-does-not-exist-xyz/content")
    assert r.json()["success"] is False


def test_get_calculator_status_shape():
    calcs = _client().get("/api/calculators").json()["data"]["calculators"]
    slug = calcs[0]["slug"]

    r = _client().get(f"/api/calculators/{slug}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("db_status", "registry_status", "is_legal_hold", "has_content",
                "has_static_site", "static_files", "published_url", "is_deployed"):
        assert key in data


def test_get_calculator_status_not_found():
    r = _client().get("/api/calculators/this-slug-does-not-exist-xyz/status")
    assert r.json()["success"] is False


# ── 쓰기 endpoint 범위 확인 ────────────────────────────────────────────

def test_only_the_formula_promote_checklist_and_generate_write_endpoints_are_registered():
    """STEP 18-N: tests/_route_utils.collect_routes()로 nested router까지 재귀
    수집해 검사한다(app.routes 얕은 순회는 이 FastAPI 버전에서 하위 route를
    찾지 못해 vacuously PASS하는 문제가 있었음 — STEP 18-M에서 발견).

    STEP 4-G: Calculator Formula PATCH, STEP 4-H-1: promote POST, STEP 4-H-2:
    checklist PATCH, STEP 4-H-5: generate POST, P0-2: build/deploy POST, P0-4:
    콘텐츠 생성 5개가 각각 require_admin() 뒤에서 정당하게 추가되어 이제 11개다
    — 그 외에는 없어야 한다."""
    from api.main import app
    paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert paths == [
        # APP-FACTORY-02: App Factory AI 추천 6종(require_admin)
        ("/api/calculators/ai/suggest-formula", "POST"),
        ("/api/calculators/ai/suggest-idea", "POST"),
        ("/api/calculators/ai/suggest-mode", "POST"),
        ("/api/calculators/ai/suggest-spec", "POST"),
        ("/api/calculators/ai/suggest-tier", "POST"),
        ("/api/calculators/ai/tier2b-keywords", "POST"),
        ("/api/calculators/generate", "POST"),
        ("/api/calculators/generate/contract", "POST"),
        ("/api/calculators/generate/contract/slug-check", "POST"),
        ("/api/calculators/generate/contract/slug-suggest", "POST"),  # APP-FACTORY-02
        ("/api/calculators/generate/contract/validate", "POST"),
        ("/api/calculators/generate/contract/{job_id}/confirm-formula", "POST"),  # APP-FACTORY-02
        ("/api/calculators/generate/contract/{job_id}/save", "POST"),
        # SMALL-GAPS-02: Mode A 생성 → 검토 → 저장/폐기(require_admin)
        ("/api/calculators/generate/preview", "POST"),
        ("/api/calculators/generate/preview/{job_id}/discard", "POST"),
        ("/api/calculators/generate/preview/{job_id}/save", "POST"),
        ("/api/calculators/{slug}/build", "POST"),
        ("/api/calculators/{slug}/checklist", "PATCH"),
        ("/api/calculators/{slug}/content/body", "POST"),
        ("/api/calculators/{slug}/content/faq", "POST"),
        ("/api/calculators/{slug}/content/generate", "POST"),
        ("/api/calculators/{slug}/content/image", "POST"),
        ("/api/calculators/{slug}/content/seo", "POST"),
        ("/api/calculators/{slug}/delete/confirm", "POST"),  # GAP-02
        ("/api/calculators/{slug}/delete/prepare", "POST"),  # GAP-02
        ("/api/calculators/{slug}/deploy", "POST"),
        ("/api/calculators/{slug}/formula", "PATCH"),
        ("/api/calculators/{slug}/promote", "POST"),
        ("/api/calculators/{slug}/review/approve", "POST"),
        ("/api/calculators/{slug}/review/unapprove", "POST"),
        ("/api/calculators/{slug}/status", "POST"),  # GAP-01
    ], f"Calculator 쓰기 endpoint가 예상과 다름: {paths}"


def test_no_db_write_functions_called(monkeypatch):
    """조회 API 호출 과정에서 CalculatorRepository의 쓰기 메서드가 절대 호출되지 않는지 확인."""
    from repositories.calculator_repository import CalculatorRepository

    def _boom(*a, **kw):
        raise AssertionError("쓰기 메서드가 호출되면 안 된다")

    for method in ("save", "create", "update", "delete", "upsert_by_slug", "update_generated", "publish"):
        monkeypatch.setattr(CalculatorRepository, method, _boom)

    c = _client()
    calcs = c.get("/api/calculators").json()["data"]["calculators"]
    assert len(calcs) > 0
    slug = calcs[0]["slug"]
    assert c.get(f"/api/calculators/{slug}").status_code == 200
    assert c.get(f"/api/calculators/{slug}/content").status_code == 200
    assert c.get(f"/api/calculators/{slug}/status").status_code == 200


def test_no_registry_write_functions_called(monkeypatch):
    """조회 API 호출 과정에서 registry_loader의 쓰기 함수가 절대 호출되지 않는지 확인."""
    import modules.registry_loader as registry_loader

    def _boom(*a, **kw):
        raise AssertionError("registry write 함수가 호출되면 안 된다")

    monkeypatch.setattr(registry_loader, "add_auto_entry", _boom)
    monkeypatch.setattr(registry_loader, "remove_auto_entry", _boom)

    c = _client()
    calcs = c.get("/api/calculators").json()["data"]["calculators"]
    slug = calcs[0]["slug"]
    assert c.get(f"/api/calculators/{slug}/status").status_code == 200
