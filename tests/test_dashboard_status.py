# -*- coding: utf-8 -*-
"""tests/test_dashboard_status.py — STEP P2-02: Dashboard 순수 상태/진행 표시
React/FastAPI 이관 검증.

dashboard.py render_pipeline_status()(dashboard.py:380-413, "⛓️ Workflow" 블로그+
계산기 파이프라인 다이어그램)와 render_progress()(dashboard.py:489-511, "📈 진행
현황")와 동일한 계산을 검증한다. 전부 READ-ONLY이며, 실제 파일/DB를 이 파일의
테스트에서 직접 건드리지 않는다 — 항상 monkeypatch로 대체한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "dashboard-status-test-viewer-token"
ADMIN_TOKEN = "dashboard-status-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _mock_load_config(monkeypatch):
    monkeypatch.setattr("api.services.dashboard_status_service.load_config", lambda: {"FAKE": True})


# ══════════════════════════════════════════════════════════════════════════
# 인증 — 두 endpoint 모두
# ══════════════════════════════════════════════════════════════════════════

def test_pipeline_status_without_auth_returns_401():
    r = _client().get("/api/dashboard/pipeline-status")
    assert r.status_code == 401


def test_pipeline_status_as_viewer_returns_403():
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_progress_without_auth_returns_401():
    r = _client().get("/api/dashboard/progress")
    assert r.status_code == 401


def test_progress_as_viewer_returns_403():
    r = _client().get("/api/dashboard/progress", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# Workflow(파이프라인 다이어그램) — 데이터 source + 계산식
# ══════════════════════════════════════════════════════════════════════════

def test_pipeline_status_as_admin_returns_10_blog_and_7_calculator_steps(monkeypatch):
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.pipeline_status.get_pipeline_state", lambda cfg: {"stages": []})
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["blog"]) == 10
    assert len(data["calculator"]) == 7


def test_blog_step_status_matches_first_stage_whose_name_contains_a_keyword(monkeypatch):
    """'전략' 단계는 keys=["전략","리서치"]다 — stage 이름에 '전략'이 포함되면
    그 status를 그대로 가져온다(추측 없이 dashboard.py의 키워드 목록 그대로)."""
    _mock_load_config(monkeypatch)
    monkeypatch.setattr(
        "modules.pipeline_status.get_pipeline_state",
        lambda cfg: {"stages": [{"name": "M0 전략", "model": "-", "status": "running"}]},
    )
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(ADMIN_TOKEN))
    blog = {s["label"]: s["status"] for s in r.json()["data"]["blog"]}
    assert blog["전략"] == "running"
    # 매칭되는 stage가 없는 다른 단계는 전부 기본값 "pending"
    assert blog["수집"] == "pending"
    assert blog["발행"] == "pending"


def test_blog_step_status_defaults_to_pending_when_no_stage_matches(monkeypatch):
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.pipeline_status.get_pipeline_state", lambda cfg: {"stages": []})
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(ADMIN_TOKEN))
    blog = r.json()["data"]["blog"]
    assert all(s["status"] == "pending" for s in blog)


def test_calculator_steps_never_carry_a_status_field(monkeypatch):
    """dashboard.py는 계산기 행을 항상 live=False로 렌더링해 실제 상태를 절대
    반영하지 않는다 — 원본 stages에 계산기 키워드와 매칭될 이름이 있어도
    무시되어야 한다(status 필드 자체가 없어야 함)."""
    _mock_load_config(monkeypatch)
    monkeypatch.setattr(
        "modules.pipeline_status.get_pipeline_state",
        lambda cfg: {"stages": [{"name": "SEO", "model": "-", "status": "running"}]},
    )
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(ADMIN_TOKEN))
    calculator = r.json()["data"]["calculator"]
    assert len(calculator) == 7
    for step in calculator:
        assert "status" not in step


def test_pipeline_status_source_error_falls_back_to_all_pending(monkeypatch):
    _mock_load_config(monkeypatch)
    def _boom(cfg):
        raise RuntimeError("pipeline.log unreadable")
    monkeypatch.setattr("modules.pipeline_status.get_pipeline_state", _boom)
    r = _client().get("/api/dashboard/pipeline-status", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    blog = r.json()["data"]["blog"]
    assert all(s["status"] == "pending" for s in blog)


# ══════════════════════════════════════════════════════════════════════════
# 진행 현황 — 데이터 source + 계산식
# ══════════════════════════════════════════════════════════════════════════

def test_progress_as_admin_returns_expected_shape(monkeypatch):
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {
        "total": 4, "completed": 2, "pending": 1, "failed": 1, "running": 0, "next": "2026-09-06T10:00:00",
    })
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [1, 2, 3])
    r = _client().get("/api/dashboard/progress", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data == {
        "total": 4, "completed": 2, "pct": 50, "failed": 1, "running": 0,
        "next": "2026-09-06T10:00:00", "retry_pending": 3,
    }


def test_progress_percentage_rounds_down_via_int_truncation(monkeypatch):
    """dashboard.py는 int(comp/total*100)를 쓴다(반올림이 아니라 절삭) — 1/3=33.33%
    → 33이어야 하며 34가 아니다."""
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {"total": 3, "completed": 1, "failed": 0, "running": 0, "next": None})
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    r = _client().get("/api/dashboard/progress", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["pct"] == 33


def test_progress_with_zero_total_shows_zero_percent_not_division_error(monkeypatch):
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {"total": 0, "completed": 0, "failed": 0, "running": 0, "next": None})
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: None)
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    r = _client().get("/api/dashboard/progress", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["pct"] == 0
    assert data["total"] == 0


def test_progress_schedule_source_error_falls_back_to_empty_summary(monkeypatch):
    _mock_load_config(monkeypatch)
    def _boom(cfg):
        raise RuntimeError("schedule file corrupt")
    monkeypatch.setattr("modules.scheduler.load_schedule", _boom)
    monkeypatch.setattr("modules.retry_queue.list_pending", lambda: [])
    r = _client().get("/api/dashboard/progress", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 0
    assert data["pct"] == 0
    assert data["failed"] == 0
    assert data["next"] is None


def test_progress_retry_queue_source_error_falls_back_to_dash_string(monkeypatch):
    """dashboard.py는 retry_queue 조회 실패 시 retry_n = "—"(문자열)로 표시한다 —
    다른 KPI(total/failed 등)에는 영향이 없어야 한다."""
    _mock_load_config(monkeypatch)
    monkeypatch.setattr("modules.scheduler.summarize", lambda sched: {"total": 2, "completed": 1, "failed": 0, "running": 1, "next": None})
    monkeypatch.setattr("modules.scheduler.load_schedule", lambda cfg: {"schedule": []})
    def _boom():
        raise RuntimeError("retry queue file corrupt")
    monkeypatch.setattr("modules.retry_queue.list_pending", _boom)
    r = _client().get("/api/dashboard/progress", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["retry_pending"] == "—"
    assert data["total"] == 2  # 다른 필드는 영향 없음


# ══════════════════════════════════════════════════════════════════════════
# read-only 보장 + write route 없음
# ══════════════════════════════════════════════════════════════════════════

def _module_function_bodies_without_docstrings(module):
    """모듈의 모든 top-level 함수 소스에서 docstring만 제거하고 이어붙인다.
    STEP P2-11에서 모듈 docstring 설명 문장 안에 "_save()"/"BudgetTracker"
    같은 단어가 우연히 등장해(P2-06/P2-07에서 이미 겪은 것과 동일한 자체
    테스트 취약점) 원래의 순수 raw-string 스캔이 모듈 전체(함수 밖 docstring
    포함)를 보는 바람에 오탐하던 문제를 고친다 — 실제 "코드가 호출하는지"만
    본다."""
    import ast
    import inspect
    source = inspect.getsource(module)
    tree = ast.parse(source)
    bodies = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
            bodies.append(ast.unparse(node))
    return "\n".join(bodies)


def test_service_source_never_writes_anything():
    from api.services import dashboard_status_service
    source = _module_function_bodies_without_docstrings(dashboard_status_service)
    for forbidden in (
        "_save", ".record(", "save_schedule", "retry_queue.remove", "retry_queue.retry",
        "retry_queue.enqueue", "open(", "write_text", "run_calculator_once", "main.run_once",
        "BudgetTracker(",
    ):
        assert forbidden not in source


def test_no_new_write_routes_added_under_dashboard():
    from _route_utils import write_routes
    from api.main import app
    assert write_routes(app, prefix="/api/dashboard") == []


def test_total_post_route_count_unchanged():
    """P2-02는 GET만 추가한다 — 작성 당시(S13 시점) 전체 write route 수는 32개였다.
    이후 STEP P2-06에서 Site Management 생성/Import POST 2개가 정당하게 추가되어
    34개가, STEP P2-07에서 PUT 1개(개별 사이트 수정)와 POST 2개(Override 저장/
    초기화)가 정당하게 추가되어 37개가, STEP P2-08에서 Activate/Deactivate/
    Archive/Restore POST 4개가 정당하게 추가되어 41개가, STEP P2-09에서 Hard
    Delete(DELETE) 1개와 Clone(POST) 1개가 정당하게 추가되어 43개가, STEP
    P2-14에서 Settings Image-gen/Google 연동 PATCH 1개가 정당하게 추가되어
    이제 44개가 되었다(test_fastapi_route_security.py의 카운트와 동일하게 유지)."""
    from _route_utils import write_routes
    from api.main import app
    # C-TEST-CONTRACT-FIX-02: Streamlit→FastAPI 이관(A 커밋)으로 46개 추가 → 92개(route_security와 동일).
    assert len(write_routes(app)) == 92
