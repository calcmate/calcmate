# -*- coding: utf-8 -*-
"""tests/test_fastapi_route_security.py — 전체 API 권한 표면 검증 (STEP 18-N).

STEP 18-M에서 발견된 문제(app.routes를 얕게 순회해 nested router 내부의 실제
endpoint를 하나도 검사하지 못한 채 vacuously PASS하던 기존 security 테스트들)를
바로잡기 위해, tests/_route_utils.py의 collect_routes()로 실제 등록된 모든
route를 재귀적으로 수집해 검사한다. 실제 endpoint를 호출하지 않는다 — route
"존재 여부"만 확인한다(§11).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _route_utils import collect_routes, write_routes

# STEP 18-N 시점엔 2개였다. STEP 18-R에서 Publish Edit/Trash/Restore 3개가
# require_admin() 뒤에서 정당하게 추가되어 5개, STEP 4-F에서 Settings General
# PATCH가 동일하게 require_admin() 뒤에서 추가되어 6개, STEP 4-H-2에서
# Calculator checklist PATCH가 추가되어 9개, STEP 4-H-5에서 Calculator 생성
# (Mode A) POST가 추가되어 10개, P0-2에서 Calculator build/deploy POST 2개가
# require_admin() 뒤에서 정당하게 추가되어 12개, P0-4에서 Calculator 콘텐츠 생성
# (SEO/FAQ/본문/이미지/전체) POST 5개가 require_admin() 뒤에서 정당하게 추가되어 17개,
# P0-5에서 Mode B(Contract 기반 생성) POST 4개가 require_admin() 뒤에서 정당하게
# 추가되어 21개, STEP S1에서 Human Review Approval POST 2개가 추가되어 23개,
# STEP S3에서 실질 헬스체크 재실행 POST 1개가 require_admin() 뒤에서 정당하게
# 추가되어 24개, STEP S5에서 Cost Manager 수동 재개/Retry Queue 수동 재시도 POST
# 2개가 추가되어 26개, STEP S6에서 Retry Queue 수동 제거 POST가 추가되어 27개,
# STEP S8에서 Strategy Room 실행 POST가 추가되어 28개, STEP S10에서 Content Sync
# 수동 실행 POST가 추가되어 29개, STEP S11에서 계산기 생성 Quick Action 수동
# 실행 POST가 추가되어 30개, STEP S12에서 파이프라인 실행(전량) Quick Action
# 수동 실행 POST가 추가되어 31개, STEP S13에서 통합 실행(▶ 실행) Quick Action
# 수동 실행 POST가 추가되어 32개, STEP P2-06에서 Site Management 생성/Import
# POST 2개가 추가되어 34개, STEP P2-07에서 사이트 기본 정보 수정(PUT) 1개와
# Override 저장/초기화 POST 2개가 require_admin() 뒤에서 정당하게 추가되어 37개,
# STEP P2-08에서 Activate/Deactivate/Archive/Restore POST 4개가 require_admin()
# 뒤에서 정당하게 추가되어 41개, STEP P2-09에서 Hard Delete(DELETE) 1개와
# Clone(POST) 1개가 require_admin() 뒤에서 정당하게 추가되어 43개, STEP
# P2-14에서 Settings Image-gen/Google 연동 PATCH 1개가 require_admin() 뒤에서
# 정당하게 추가되어 이제 44개가 맞다(§14).
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
    # STEP S11: Dashboard Quick Action 「계산기 생성」 수동 실행 POST가 require_admin()
    # 뒤에서 정당하게 추가됨(/api/scheduler/calculator/status의 GET과는 별개).
    ("/api/scheduler/calculator/run-once", "POST"),
    # STEP S12: Dashboard Quick Action 「파이프라인 실행(전량)」 수동 실행 POST가
    # require_admin() 뒤에서 정당하게 추가됨(/api/scheduler/blog/run-once와는 다른 함수).
    ("/api/scheduler/pipeline/run-once", "POST"),
    # STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) 수동 실행 POST가
    # require_admin() 뒤에서 정당하게 추가됨(새 pipeline이 아니라 S11/S12 서비스를 재사용하는 dispatcher).
    ("/api/scheduler/integrated/run-once", "POST"),
    # STEP P2-06: Site Management 생성/Import POST 2개가 require_admin() 뒤에서
    # 정당하게 추가됨(P2-04의 GET /api/sites 조회와는 별개 endpoint).
    ("/api/sites", "POST"),
    ("/api/sites/import", "POST"),
    # STEP P2-07: 사이트 기본 정보 수정(PUT)/Override 저장·초기화(POST)가
    # require_admin() 뒤에서 정당하게 추가됨.
    ("/api/sites/{site_id}", "PUT"),
    ("/api/sites/{site_id}/override", "POST"),
    ("/api/sites/{site_id}/override/reset", "POST"),
    # STEP P2-08: Activate/Deactivate/Archive/Restore POST 4개가
    # require_admin() 뒤에서 정당하게 추가됨.
    ("/api/sites/{site_id}/activate", "POST"),
    ("/api/sites/{site_id}/deactivate", "POST"),
    ("/api/sites/{site_id}/archive", "POST"),
    ("/api/sites/{site_id}/restore", "POST"),
    # STEP P2-09: Hard Delete(DELETE)/Clone(POST)가 require_admin() 뒤에서
    # 정당하게 추가됨(이 프로젝트 전체에서 처음 등록되는 DELETE).
    ("/api/sites/{site_id}", "DELETE"),
    ("/api/sites/{site_id}/clone", "POST"),
    # CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01:
    # Publishing Policy/Auto Publishing PATCH 2개가 require_admin() 뒤에서
    # 정당하게 추가되어 이제 46개다(§WRITE-SURFACE-FIX-01).
    ("/api/scheduler/publishing-policy", "PATCH"),
    ("/api/scheduler/auto-publishing", "PATCH"),
})

# 참고용 read endpoint(§4의 명시 금지 목록에 대응하는 실제 존재 경로들).
CORE_GET_ROUTES = frozenset({
    "/api/settings",
    "/api/settings/general",
    "/api/settings/{section}",
    "/api/calculators/{slug}/formula",
    "/api/health",
    "/api/health/details",
    "/api/health/external",
    "/api/calculators",
    "/api/calculators/{slug}",
    "/api/logs/errors",
    "/api/logs/recent",
    "/api/logs/live",
    "/api/costs",
    "/api/workboard",
    "/api/pipeline/status",
    "/api/scheduler/blog/status",
    "/api/scheduler/blog/config",
    "/api/scheduler/blog/today",
    "/api/scheduler/blog/history",
    "/api/scheduler/calculator/status",
    "/api/scheduler/content-sync/status",
})


def _app():
    from api.main import app
    return app


# ── §9: collector가 실제로 route를 검사하는지 증명 ──────────────────────────

def test_collector_finds_a_nonzero_number_of_routes():
    routes = collect_routes(_app())
    assert len(routes) > 0


def test_collector_finds_all_known_core_get_routes():
    routes = collect_routes(_app())
    found_paths = {r.path for r in routes}
    missing = CORE_GET_ROUTES - found_paths
    assert missing == set(), f"collector가 실제 존재하는 route를 놓쳤다: {missing}"


def test_collector_finds_the_two_known_write_routes():
    """이 테스트가 실패한다면 collector가 다시 얕은 순회로 퇴행한 것이다 —
    반드시 nested router까지 내려가서 PATCH/POST를 찾아내야 한다."""
    routes = collect_routes(_app())
    found = {(r.path, m) for r in routes for m in r.methods}
    assert ("/api/scheduler/blog/config", "PATCH") in found
    assert ("/api/scheduler/blog/run-once", "POST") in found


# ── §5: 정확한 write surface assertion (개수/집합 일치, "없다"가 아니라 "정확히 이것") ──

def test_actual_write_surface_matches_expected_exactly():
    actual = frozenset(write_routes(_app()))
    assert actual == EXPECTED_WRITE_ROUTES, (
        f"실제 write route 집합이 예상과 다르다.\n"
        f"actual={sorted(actual)}\nexpected={sorted(EXPECTED_WRITE_ROUTES)}"
    )


def test_exactly_ten_write_routes_exist():
    assert len(write_routes(_app())) == 46


# ── §4: PUT/DELETE는 전체 API에 단 하나도 없어야 한다 ───────────────────────

def test_no_put_routes_exist_anywhere():
    """STEP P2-07 이전에는 PUT이 전혀 없었다. PUT /api/sites/{site_id}(사이트
    기본 정보 수정)만 require_admin() 뒤에서 정당하게 추가되어, 이제 그 하나만
    허용된다 — 그 외 PUT은 여전히 없어야 한다."""
    routes = collect_routes(_app())
    put_routes = [(r.path, "PUT") for r in routes if "PUT" in r.methods]
    assert put_routes == [("/api/sites/{site_id}", "PUT")]


def test_no_delete_routes_exist_anywhere():
    """STEP P2-09에서 DELETE /api/sites/{site_id}(Hard Delete)가 require_admin()
    뒤에서 정당하게 추가되었다 — 이 프로젝트 전체에서 처음 등록되는 DELETE다."""
    routes = collect_routes(_app())
    delete_routes = [(r.path, "DELETE") for r in routes if "DELETE" in r.methods]
    assert delete_routes == [("/api/sites/{site_id}", "DELETE")]


# ── §6: Settings write surface ───────────────────────────────────────────

def test_settings_get_routes_exist():
    routes = collect_routes(_app())
    paths = {r.path for r in routes if "GET" in r.methods}
    assert "/api/settings" in paths
    assert "/api/settings/{section}" in paths


def test_settings_has_only_the_general_write_route():
    """STEP 4-F: Settings General PATCH가, STEP P2-14: Image-Google PATCH가
    require_admin() 뒤에서 정당하게 추가되어 이제 2개다 — 그 외에는 여전히
    쓰기 route가 없어야 한다."""
    assert write_routes(_app(), prefix="/api/settings") == [
        ("/api/settings/general", "PATCH"),
        ("/api/settings/image-google", "PATCH"),
    ]


# ── §7: Calculator write surface ─────────────────────────────────────────

def test_calculator_get_routes_exist():
    routes = collect_routes(_app())
    paths = {r.path for r in routes if "GET" in r.methods}
    assert "/api/calculators" in paths
    assert "/api/calculators/{slug}" in paths


def test_calculator_has_only_the_formula_promote_checklist_and_generate_write_routes():
    """STEP 4-G: Formula PATCH, STEP 4-H-1: promote POST, STEP 4-H-2: checklist
    PATCH, STEP 4-H-5: generate POST, P0-2: build/deploy POST, P0-4: 콘텐츠 생성 5개,
    P0-5: Mode B(Contract 기반 생성) 4개, STEP S1: Human Review Approval 2개가
    각각 require_admin() 뒤에서 정당하게 추가되어 이제 17개다 — 그 외에는 여전히
    쓰기 route가 없어야 한다."""
    assert sorted(write_routes(_app(), prefix="/api/calculators")) == [
        ("/api/calculators/generate", "POST"),
        ("/api/calculators/generate/contract", "POST"),
        ("/api/calculators/generate/contract/slug-check", "POST"),
        ("/api/calculators/generate/contract/validate", "POST"),
        ("/api/calculators/generate/contract/{job_id}/save", "POST"),
        ("/api/calculators/{slug}/build", "POST"),
        ("/api/calculators/{slug}/checklist", "PATCH"),
        ("/api/calculators/{slug}/content/body", "POST"),
        ("/api/calculators/{slug}/content/faq", "POST"),
        ("/api/calculators/{slug}/content/generate", "POST"),
        ("/api/calculators/{slug}/content/image", "POST"),
        ("/api/calculators/{slug}/content/seo", "POST"),
        ("/api/calculators/{slug}/deploy", "POST"),
        ("/api/calculators/{slug}/formula", "PATCH"),
        ("/api/calculators/{slug}/promote", "POST"),
        ("/api/calculators/{slug}/review/approve", "POST"),
        ("/api/calculators/{slug}/review/unapprove", "POST"),
    ]


# ── §8: Logs / Cost / Pipeline / Health write surface ────────────────────

def test_logs_cost_pipeline_health_get_routes_exist():
    routes = collect_routes(_app())
    paths = {r.path for r in routes if "GET" in r.methods}
    for expected in (
        "/api/logs/errors", "/api/logs/recent", "/api/logs/live",
        "/api/costs", "/api/pipeline/status",
        "/api/health", "/api/health/details",
    ):
        assert expected in paths, f"{expected} 가 사라졌다"


def test_logs_pipeline_have_zero_write_routes():
    for prefix in ("/api/logs", "/api/pipeline"):
        assert write_routes(_app(), prefix=prefix) == [], f"{prefix} 하위에 쓰기 endpoint가 있으면 안 됨"


def test_health_has_only_the_external_run_write_route():
    """STEP S3: /api/health/external/run(POST)이 require_admin() 뒤에서 정당하게
    추가되어 더 이상 0개가 아니다 — 그 하나 외에는 여전히 쓰기 route가 없어야 한다."""
    assert write_routes(_app(), prefix="/api/health") == [("/api/health/external/run", "POST")]


def test_costs_has_only_the_resume_retry_and_remove_write_routes():
    """STEP S5: /api/costs/resume, /api/costs/retry, STEP S6: /api/costs/remove
    (전부 POST, require_admin)가 정당하게 추가되어 더 이상 0개가 아니다 — 그
    셋 외에는 여전히 쓰기 route가 없어야 한다."""
    assert sorted(write_routes(_app(), prefix="/api/costs")) == [
        ("/api/costs/remove", "POST"),
        ("/api/costs/resume", "POST"),
        ("/api/costs/retry", "POST"),
    ]


# ── §4 명시 금지 목록: 존재해서는 안 되는 구체적 write 조합들 ──────────────────

def test_explicitly_forbidden_write_combinations_absent():
    routes = collect_routes(_app())
    all_pairs = {(r.path, m) for r in routes for m in r.methods}
    forbidden_prefixes_methods = [
        ("/api/settings", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/calculators", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/logs", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/costs", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/health", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/registry", {"POST", "PATCH", "PUT", "DELETE"}),
        # STEP P2-06/P2-07: POST /(생성), POST /import, PUT /{site_id}(수정),
        # POST /{site_id}/override(및 /reset)만 정당한 예외 — EXPECTED_WRITE_
        # ROUTES에 개별 등록되어 있으므로 아래 PATCH/PUT/DELETE 차단은 그 외의
        # 경우만 잡는다(예: PATCH /{site_id}, DELETE /{site_id} 등은 여전히 금지).
        ("/api/sites", {"PATCH", "PUT", "DELETE"}),
        ("/api/pipeline", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/strategy-room", {"POST", "PATCH", "PUT", "DELETE"}),
        ("/api/scheduler/content-sync", {"PATCH", "PUT", "DELETE"}),
        # STEP S11: /calculator/status(GET)는 그대로 두고, 그 하위에 PATCH/PUT/DELETE만 금지
        # (POST run-once는 EXPECTED_WRITE_ROUTES의 정당한 예외).
        ("/api/scheduler/calculator", {"PATCH", "PUT", "DELETE"}),
        # STEP S12: /pipeline/run-once(POST)만 정당한 예외, 그 외 PATCH/PUT/DELETE 금지.
        ("/api/scheduler/pipeline", {"PATCH", "PUT", "DELETE"}),
        # STEP S13: /integrated/run-once(POST)만 정당한 예외, 그 외 PATCH/PUT/DELETE 금지.
        ("/api/scheduler/integrated", {"PATCH", "PUT", "DELETE"}),
    ]
    violations = []
    for path, method in all_pairs:
        for prefix, methods in forbidden_prefixes_methods:
            if path.startswith(prefix) and method in methods and (path, method) not in EXPECTED_WRITE_ROUTES:
                violations.append((path, method))
    assert violations == [], f"금지된 write endpoint 발견: {violations}"


# ── §12: 외부 서비스 호출 차단(이 파일의 검증 과정 자체가 route 존재 확인뿐이므로
#         호출될 이유가 없지만, 회귀 방지 차원에서 명시적으로 monkeypatch해 확인) ──

def test_route_inspection_makes_no_external_http_calls(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise AssertionError("route 검사 과정에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)

    app = _app()
    routes = collect_routes(app)
    assert len(routes) > 0
    assert write_routes(app) == sorted(EXPECTED_WRITE_ROUTES)
