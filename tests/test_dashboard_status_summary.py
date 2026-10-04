# -*- coding: utf-8 -*-
"""tests/test_dashboard_status_summary.py — STEP P2-10: Dashboard "📊 현황"
React/FastAPI 이관 검증.

dashboard.py "📊 현황" 탭(dashboard.py:562-584)과 동일한 계산을 검증한다.
전부 READ-ONLY이며, 실제 운영 DB/파일을 이 파일의 어떤 테스트에서도 직접
건드리지 않는다 — 항상 monkeypatch로 대체한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "dashboard-status-summary-test-viewer-token"
ADMIN_TOKEN = "dashboard-status-summary-test-admin-token"


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


def _mock(monkeypatch, posts, daily_goal=3):
    monkeypatch.setattr("api.services.dashboard_status_service.load_config",
                         lambda: {"DAILY_POST_COUNT": daily_goal})
    monkeypatch.setattr("modules.dashboard_cache.read", lambda cfg, table, ttl=120: posts)


def _post(status, published_at=""):
    return {"상태값": status, "발행일시": published_at}


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_status_summary_without_auth_returns_401():
    r = _client().get("/api/dashboard/status-summary")
    assert r.status_code == 401


def test_status_summary_as_viewer_returns_403():
    r = _client().get("/api/dashboard/status-summary", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_status_summary_as_admin_returns_200(monkeypatch):
    _mock(monkeypatch, [])
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 정상 데이터 계산
# ══════════════════════════════════════════════════════════════════════════

def test_status_counts_computed_correctly(monkeypatch):
    posts = [
        _post("대기"), _post("대기"),
        _post("작성중"),
        _post("검수대기"),
        _post("발행완료"), _post("발행완료"), _post("발행완료"),
        _post("이미지오류"),
        _post("재처리대기"),
    ]
    _mock(monkeypatch, posts)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    by_status = {s["status"]: s["count"] for s in data["statuses"]}
    assert by_status == {
        "대기": 2, "작성중": 1, "검수대기": 1, "발행완료": 3, "이미지오류": 1, "재처리대기": 1,
    }


def test_status_list_order_and_icons_match_original(monkeypatch):
    """dashboard.py:572 STATE_MAP 순서/아이콘 그대로 재현되어야 한다."""
    _mock(monkeypatch, [])
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    statuses = r.json()["data"]["statuses"]
    assert [(s["status"], s["icon"]) for s in statuses] == [
        ("대기", "🟡"), ("작성중", "🔵"), ("검수대기", "🟠"),
        ("발행완료", "🟢"), ("이미지오류", "🔴"), ("재처리대기", "⚫"),
    ]


def test_unknown_status_values_excluded_from_display(monkeypatch):
    """원본은 6개 상태 외에는 화면에 표시하지 않는다(품질보류/발행실패 등)."""
    posts = [_post("품질보류"), _post("발행실패"), _post("발행완료")]
    _mock(monkeypatch, posts)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    by_status = {s["status"]: s["count"] for s in r.json()["data"]["statuses"]}
    assert set(by_status.keys()) == {"대기", "작성중", "검수대기", "발행완료", "이미지오류", "재처리대기"}
    assert by_status["발행완료"] == 1


def test_today_published_counts_only_today_and_matching_statuses(monkeypatch):
    from datetime import date, timedelta
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    posts = [
        _post("발행완료", f"{today}T09:00:00"),
        _post("검수대기", f"{today}T10:00:00"),
        _post("발행완료", f"{yesterday}T09:00:00"),  # 어제 — 제외
        _post("대기", f"{today}T11:00:00"),  # 상태 불일치 — 제외
    ]
    _mock(monkeypatch, posts)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["today_published"] == 2


def test_daily_goal_read_from_config(monkeypatch):
    _mock(monkeypatch, [], daily_goal=5)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["daily_goal"] == 5


def test_daily_goal_defaults_to_three_when_missing(monkeypatch):
    monkeypatch.setattr("api.services.dashboard_status_service.load_config", lambda: {})
    monkeypatch.setattr("modules.dashboard_cache.read", lambda cfg, table, ttl=120: [])
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["daily_goal"] == 3


def test_progress_percent_computed_correctly(monkeypatch):
    from datetime import date
    today = date.today().isoformat()
    posts = [_post("발행완료", f"{today}T09:00:00") for _ in range(2)]
    _mock(monkeypatch, posts, daily_goal=4)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["today_published"] == 2
    assert data["daily_goal"] == 4
    assert data["progress_percent"] == 50  # 2/4 = 0.5 → 50%


def test_progress_percent_clamped_to_100_when_over_goal(monkeypatch):
    from datetime import date
    today = date.today().isoformat()
    posts = [_post("발행완료", f"{today}T09:00:00") for _ in range(9)]
    _mock(monkeypatch, posts, daily_goal=3)
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["progress_percent"] == 100  # min(9/3, 1.0) = 1.0 → 100%, 초과분 클램프


# ══════════════════════════════════════════════════════════════════════════
# 빈 데이터 / source read 오류
# ══════════════════════════════════════════════════════════════════════════

def test_empty_articles_returns_all_zero_counts(monkeypatch):
    _mock(monkeypatch, [])
    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert all(s["count"] == 0 for s in data["statuses"])
    assert data["today_published"] == 0
    assert data["progress_percent"] == 0


def test_source_read_error_does_not_crash_and_returns_empty_summary(monkeypatch):
    """dashboard.py 원본은 try/except로 감싸 "데이터 로드 오류"만 표시한다 —
    이 서비스도 예외 상황에서 크래시하지 않고 빈 집계를 반환해야 한다."""
    monkeypatch.setattr("api.services.dashboard_status_service.load_config",
                         lambda: {"DAILY_POST_COUNT": 3})

    def _boom(cfg, table, ttl=120):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr("modules.dashboard_cache.read", _boom)

    r = _client().get("/api/dashboard/status-summary", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert all(s["count"] == 0 for s in data["statuses"])
    assert data["today_published"] == 0


# ══════════════════════════════════════════════════════════════════════════
# write 없음 검증 + 다른 완료 기능에 대한 직접 호출/수정 없음(AST 검사)
# ══════════════════════════════════════════════════════════════════════════

def _source_body_without_docstring(fn):
    import ast
    import inspect
    source = inspect.getsource(fn)
    tree = ast.parse(source)
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant) and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]
    return ast.unparse(func)


def test_service_source_has_no_write_calls():
    from api.services import dashboard_status_service
    source = _source_body_without_docstring(dashboard_status_service.get_status_summary)
    for forbidden in ("insert(", "update(", "delete(", ".save(", ".append(", "yaml.dump(",
                      "write(", "save_wp_profile", "site_repo", "calc_repo"):
        assert forbidden not in source, f"get_status_summary가 쓰기 호출({forbidden})을 포함함"


def test_service_source_never_touches_other_completed_features():
    """P2-04~P2-09(Site Management)/Registry/HOLD/Scheduler/Calculator 파이프라인/
    Blog 파이프라인/Settings/AI Workspace를 직접 호출하지 않는지 소스 레벨로
    확인한다 — 이 STEP은 articles 상태 집계만 읽는다."""
    from api.services import dashboard_status_service
    source = _source_body_without_docstring(dashboard_status_service.get_status_summary)
    for forbidden in (
        "site_service", "SiteRepository", "calculator_service", "CalculatorRepository",
        "registry_auto", "app_factory", "site_wizard", "publisher", "scheduler",
    ):
        assert forbidden not in source, f"get_status_summary가 범위 밖 기능({forbidden})을 참조함"


def test_status_summary_route_is_get_only():
    from _route_utils import collect_routes
    from api.main import app
    routes = [r for r in collect_routes(app) if r.path == "/api/dashboard/status-summary"]
    assert len(routes) == 1
    assert routes[0].methods == frozenset({"GET"})
