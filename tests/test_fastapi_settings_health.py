# -*- coding: utf-8 -*-
"""tests/test_fastapi_settings_health.py — STEP 18-M Settings/Health 조회 API 검증.

전부 READ-ONLY. Settings에는 Blog Schedule 외 쓰기 endpoint가 없어야 하고,
Health details는 외부 서비스를 호출하지 않고 로컬 상태만 조회해야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

# STEP 18-N: route 순회 로직은 tests/_route_utils.py 하나에만 두고 재사용한다
# (여러 테스트 파일에 중복 구현하지 않는다).
from _route_utils import collect_routes, write_routes


def _client():
    from api.main import app
    return TestClient(app)


# ── Settings 조회 ────────────────────────────────────────────────────────

def test_get_all_settings():
    r = _client().get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    for section in ("BLOG_SCHEDULE", "PUBLISH_SCHEDULE", "CALC_WEBAPP_SCHEDULE", "CONTENT_SYNC"):
        assert section in body["data"]


def test_get_settings_blog_schedule():
    r = _client().get("/api/settings/BLOG_SCHEDULE")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "enabled" in body["data"]
    assert "mode" in body["data"]
    assert "publish_slots" in body["data"]


def test_get_settings_calc_webapp_schedule():
    r = _client().get("/api/settings/CALC_WEBAPP_SCHEDULE")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "enabled" in body["data"]


def test_get_settings_content_sync():
    r = _client().get("/api/settings/CONTENT_SYNC")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "enabled" in body["data"]


def test_get_settings_publish_schedule():
    r = _client().get("/api/settings/PUBLISH_SCHEDULE")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "enabled" in body["data"]


def test_get_settings_rejects_unknown_section():
    r = _client().get("/api/settings/NOT_A_REAL_SECTION")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SECTION_NOT_ALLOWED"


def test_settings_has_only_the_general_write_endpoint():
    """§2: Blog Schedule PATCH(/api/scheduler/blog/config)는 여전히 이 라우터 밖에 있다.
    이 라우터(/api/settings) 하위에서는 STEP 4-F의 PATCH /general과 STEP P2-14의
    PATCH /image-google 2개만 쓰기가 허용되며, 그 외 어떤 section도 PATCH/PUT/
    POST로 수정할 수 없어야 한다."""
    from api.main import app
    write_paths = write_routes(app, prefix="/api/settings")
    assert write_paths == [
        ("/api/settings/general", "PATCH"),
        ("/api/settings/image-google", "PATCH"),
    ], (
        f"/api/settings 하위 쓰기 endpoint가 예상과 다름: {write_paths}"
    )


def test_settings_does_not_leak_secret_suffixed_keys():
    """ConfigService의 기존 마스킹 규칙(_KEY/_TOKEN/_PASSWORD/_SECRET)이 그대로 적용되는지
    구조적으로 확인 — 4개 section 자체에는 원래 secret 키가 없지만, 마스킹 함수 재사용을
    보장하기 위해 ConfigService.get_section 경로를 그대로 쓰는지 확인한다."""
    from api.services.config_service import ConfigService
    import api.routers.settings as settings_module
    assert settings_module.ConfigService is ConfigService


# ── Blog Scheduler 설정 기능 유지(회귀) ─────────────────────────────────

def test_blog_scheduler_settings_and_calculator_formula_are_the_only_patch_paths():
    """STEP 4-F 이전엔 PATCH가 /api/scheduler/blog/config 하나였다. STEP 4-F에서
    /api/settings/general PATCH가, STEP 4-G에서 /api/calculators/{slug}/formula
    PATCH가, STEP 4-H-2에서 /api/calculators/{slug}/checklist PATCH가 각각
    require_admin() 뒤에서 정당하게 추가되어 4개, STEP P2-14에서 /api/settings/
    image-google PATCH가 추가되어 5개, CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-
    REACT-CONNECTION-IMPLEMENT-01에서 /api/scheduler/publishing-policy,
    /api/scheduler/auto-publishing PATCH 2개가 require_admin() 뒤에서 정당하게
    추가되어 이제 7개다."""
    from api.main import app
    patch_paths = sorted(r.path for r in collect_routes(app) if "PATCH" in r.methods)
    assert patch_paths == [
        "/api/calculators/{slug}/checklist",
        "/api/calculators/{slug}/formula",
        "/api/scheduler/auto-publishing",
        "/api/scheduler/blog/config",
        "/api/scheduler/publishing-policy",
        "/api/settings/general",
        "/api/settings/image-google",
    ]


def test_only_the_known_post_endpoints_exist():
    """STEP 18-M 시점엔 POST가 blog run-once 하나뿐이었다. STEP 18-R에서
    Publish/Trash/Restore 3개가 정당하게 추가되어 4개, STEP 4-H-1에서
    Calculator promote POST가 정당하게 추가되어 5개, STEP 4-H-5에서
    Calculator 생성(Mode A) POST가 정당하게 추가되어 6개, P0-2에서 Calculator
    build/deploy POST 2개가 정당하게 추가되어 8개, P0-4에서 Calculator 콘텐츠
    생성(SEO/FAQ/본문/이미지/전체) POST 5개가 정당하게 추가되어 13개, P0-5에서
    Mode B(Contract 기반 생성) POST 4개가 정당하게 추가되어 17개, STEP S1에서
    Human Review Approval POST 2개가 정당하게 추가되어 19개, STEP S3에서
    실질 헬스체크 재실행 POST 1개가 require_admin() 뒤에서 정당하게 추가되어 20개,
    STEP S5에서 Cost Manager 수동 재개 / Retry Queue 수동 재시도 POST 2개가
    require_admin() 뒤에서 정당하게 추가되어 22개, STEP S6에서 Retry Queue
    수동 제거 POST 1개가 require_admin() 뒤에서 정당하게 추가되어 23개, STEP S8에서
    Strategy Room 실행 POST 1개가 require_admin() 뒤에서 정당하게 추가되어 24개,
    STEP S10에서 Content Sync 수동 실행 POST 1개가 require_admin() 뒤에서
    정당하게 추가되어 25개, STEP S11에서 Dashboard Quick Action 「계산기 생성」
    수동 실행 POST 1개가 추가되어 26개, STEP S12에서 Dashboard Quick Action
    「파이프라인 실행(전량)」 수동 실행 POST 1개가 추가되어 27개, STEP S13에서
    Dashboard Quick Action 「▶ 실행」(통합 실행) 수동 실행 POST 1개가 추가되어
    28개, STEP P2-06에서 Site Management 생성/Import POST 2개가 추가되어 30개,
    STEP P2-07에서 Site Settings Override 저장/초기화 POST 2개가(PUT은 이
    테스트가 세지 않음) require_admin() 뒤에서 정당하게 추가되어 32개, STEP
    P2-08에서 Activate/Deactivate/Archive/Restore POST 4개가 require_admin()
    뒤에서 정당하게 추가되어 36개, STEP P2-09에서 Clone POST 1개가(DELETE는
    이 테스트가 세지 않음) require_admin() 뒤에서 정당하게 추가되어 이제
    37개가 맞다 — 그 외 예기치 않은 POST가 없는지만 확인한다."""
    from api.main import app
    post_paths = {r.path for r in collect_routes(app) if "POST" in r.methods}
    assert post_paths == {
        "/api/scheduler/blog/run-once",
        "/api/publish/{article_id}/edit",
        "/api/trash/{article_id}",
        "/api/trash/{article_id}/restore",
        "/api/calculators/{slug}/promote",
        "/api/calculators/generate",
        "/api/calculators/{slug}/build",
        "/api/calculators/{slug}/deploy",
        "/api/calculators/{slug}/content/seo",
        "/api/calculators/{slug}/content/faq",
        "/api/calculators/{slug}/content/body",
        "/api/calculators/{slug}/content/image",
        "/api/calculators/{slug}/content/generate",
        "/api/calculators/generate/contract",
        "/api/calculators/generate/contract/slug-check",
        "/api/calculators/generate/contract/validate",
        "/api/calculators/generate/contract/{job_id}/save",
        "/api/calculators/{slug}/review/approve",
        "/api/calculators/{slug}/review/unapprove",
        "/api/health/external/run",
        "/api/costs/resume",
        "/api/costs/retry",
        "/api/costs/remove",
        "/api/strategy-room/run",
        "/api/scheduler/content-sync/run-once",
        "/api/scheduler/calculator/run-once",
        "/api/scheduler/pipeline/run-once",
        "/api/scheduler/integrated/run-once",
        "/api/sites",
        "/api/sites/import",
        "/api/sites/{site_id}/override",
        "/api/sites/{site_id}/override/reset",
        "/api/sites/{site_id}/activate",
        "/api/sites/{site_id}/deactivate",
        "/api/sites/{site_id}/archive",
        "/api/sites/{site_id}/restore",
        "/api/sites/{site_id}/clone",
    }


# ── Health ───────────────────────────────────────────────────────────────

def test_get_health():
    r = _client().get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


def test_get_health_details():
    r = _client().get("/api/health/details")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["application"]["fastapi"] == "healthy"
    for name in ("blog", "calculator", "content_sync"):
        assert name in data["schedulers"]
        for key in ("enabled", "running", "thread_alive"):
            assert key in data["schedulers"][name]
    for name in ("database", "config", "registry", "labor_af", "pipeline_log"):
        assert name in data["data"]
        assert isinstance(data["data"][name], bool)


def test_health_details_matches_real_data_file_existence():
    """실제 프로젝트 루트 파일 존재 여부와 API 응답이 일치하는지 확인(하드코딩된
    해시나 boolean이 아니라 실제 Path.exists()를 반영해야 한다)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    expected = {
        "database": (root / "data" / "blog_auto.db").exists(),
        "config": (root / "config" / "config.yaml").exists(),
        "registry": (root / "docs" / "registry_auto.yaml").exists(),
        "labor_af": (root / "docs" / "registry" / "labor_af.yaml").exists(),
        "pipeline_log": (root / "data" / "logs" / "pipeline.log").exists(),
    }
    r = _client().get("/api/health/details")
    data = r.json()["data"]["data"]
    for name, exists in expected.items():
        assert data[name] is exists


def test_health_details_no_write_endpoints():
    """STEP S3: /api/health/external/run(POST)이 require_admin() 뒤에서 정당하게
    추가되어, 더 이상 /api/health 하위 write endpoint가 0개는 아니다 — 그 하나
    외에는 여전히 쓰기 endpoint가 없어야 한다(details/external은 GET만)."""
    from api.main import app
    write_paths = write_routes(app, prefix="/api/health")
    assert write_paths == [("/api/health/external/run", "POST")]


def test_health_details_does_not_call_external_services(monkeypatch):
    """외부 서비스 호출 함수가 절대 호출되지 않는지 확인. requests 모듈 자체를
    막아서, 만에 하나 외부 HTTP 호출이 섞여 있으면 즉시 실패하도록 한다."""
    import requests

    def _boom(*a, **kw):
        raise AssertionError("health/details가 외부 HTTP 호출을 시도했다")

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)

    r = _client().get("/api/health/details")
    assert r.status_code == 200
    assert r.json()["success"] is True
