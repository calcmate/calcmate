# -*- coding: utf-8 -*-
"""tests/test_strategy_room.py — STEP S8: Strategy Room React/FastAPI 이관 검증.

dashboard.py "🧠 전략회의실" 탭(elif tab == "🧠 전략회의실":, "▶ 전략회의실 실행"
버튼)과 동일한 실행 의미를 검증한다. modules.strategy_room.run_strategy_room()의
실제 구현(진짜 AI 호출)은 이 파일의 어떤 테스트에서도 실행하지 않는다 — 항상
monkeypatch로 대체한다. Calculator/Registry/DB 관련 함수가 호출되지 않는지도
구조적으로 확인한다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "strategy-room-test-viewer-token"
ADMIN_TOKEN = "strategy-room-test-admin-token"

FAKE_RESULT = {
    "new_category_candidates": ["재테크"],
    "rss_recommendations": ["https://example.test/feed"],
    "rewrite_candidates": [],
    "best_publish_time": ["09:00"],
    "monetization_suggestions": "테스트 제안",
    "auto_topic_expansion_eligible": {
        "condition_1_adsense_post": True, "condition_2_post_count": False,
        "condition_3_ctr": False, "condition_4_positive_recommendation": True,
        "all_met": False,
    },
    "summary": "테스트 요약",
    "_tokens": 1234,
}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _reset_lock():
    from api.services import strategy_room_service
    if strategy_room_service._run_lock.locked():
        strategy_room_service._run_lock.release()
    yield
    if strategy_room_service._run_lock.locked():
        strategy_room_service._run_lock.release()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════
# §6/§12: 인증
# ══════════════════════════════════════════════════════════════════════════

def test_run_without_auth_returns_401():
    r = _client().post("/api/strategy-room/run")
    assert r.status_code == 401


def test_run_as_viewer_returns_403():
    r = _client().post("/api/strategy-room/run", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_as_admin_returns_200(monkeypatch):
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: dict(FAKE_RESULT))

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# §7/§8: 정상 실행 + 반환값 + 예외 처리
# ══════════════════════════════════════════════════════════════════════════

def test_calls_real_run_strategy_room_with_collected_analytics(monkeypatch):
    """실제 함수가 정확히 호출되는지, analytics가 dashboard.py와 동일한 방식으로
    수집되는지 spy로 확인한다."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    fake_posts = [
        {"상태값": "발행완료", "최종추천제목": "글1", "발행 URL": "http://x/1", "발행일시": "2026-09-01"},
        {"상태값": "발행완료", "최종추천제목": "글2", "발행 URL": "http://x/2", "발행일시": "2026-09-03"},
        {"상태값": "초안", "최종추천제목": "글3", "발행 URL": "", "발행일시": "2026-09-05"},  # 필터링되어야 함
    ]
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: fake_posts)

    called = {}
    def _fake_run(analytics, cfg):
        called["analytics"] = analytics
        called["cfg"] = cfg
        return dict(FAKE_RESULT)
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", _fake_run)

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["enabled"] is True
    assert body["error"] is None
    assert body["result"] == FAKE_RESULT

    # analytics는 dashboard.py:3032-3044와 동일한 필드만 채워야 한다.
    assert called["analytics"]["total_published"] == 2  # "초안" 상태는 제외
    assert len(called["analytics"]["recent_posts"]) == 2
    # 최신순 정렬(발행일시 내림차순) 확인 — 09-03이 먼저 와야 함
    assert called["analytics"]["recent_posts"][0]["date"] == "2026-09-03"
    assert called["cfg"]["ENABLE_STRATEGY_ROOM"] is True


def test_return_structure_passed_through_unmodified(monkeypatch):
    """run_strategy_room()의 반환 구조(_tokens 포함)를 임의로 재가공하지 않고
    그대로 전달하는지 확인 — 새로운 포맷을 설계하지 않는다는 원칙 검증."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: dict(FAKE_RESULT))

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["result"]["_tokens"] == 1234
    assert data["result"]["auto_topic_expansion_eligible"]["all_met"] is False
    assert set(data["result"].keys()) == set(FAKE_RESULT.keys())


def test_empty_result_from_disabled_or_no_json_is_not_an_error(monkeypatch):
    """run_strategy_room()이 {}를 반환하는 정상 케이스(비활성 상태 또는 LLM이
    JSON을 못 만든 경우)는 HTTP 오류가 아니라 성공 응답 안의 빈 result여야 한다
    (dashboard.py의 "빈 결과" 안내와 동일한 의미)."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: {})

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["result"] == {}
    assert data["error"] is None


def test_disabled_flag_reflects_real_config(monkeypatch):
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": False})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: {})

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["enabled"] is False


def test_unexpected_exception_returns_clean_failure_not_500(monkeypatch):
    """run_strategy_room() 자체는 내부에서 예외를 흡수하지만(원본 설계), 그
    바깥(예: import 실패 등 진짜 예상 밖의 오류)에서 예외가 나면 dashboard.py의
    바깥쪽 try/except와 동일한 의미로 명확한 실패를 반환해야 한다."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    def _boom(analytics, cfg):
        raise RuntimeError("예상치 못한 오류(시뮬레이션)")
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", _boom)

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["result"] == {}
    assert "전략회의실 실행 중 오류" in data["error"]
    assert "예상치 못한 오류" in data["error"]


def test_analytics_collection_failure_does_not_block_execution(monkeypatch):
    """dashboard.py:3043-3044와 동일 — 운영 데이터 수집 자체가 실패해도 빈
    analytics로 계속 진행해야 한다(전체 실행을 막지 않음)."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    def _boom(cfg, table):
        raise RuntimeError("캐시 읽기 실패(시뮬레이션)")
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", _boom)

    called = {}
    def _fake_run(analytics, cfg):
        called["analytics"] = analytics
        return dict(FAKE_RESULT)
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", _fake_run)

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["result"] == FAKE_RESULT
    assert called["analytics"] == {}  # 수집 실패 → 빈 analytics로 계속


# ══════════════════════════════════════════════════════════════════════════
# §12: 중복 실행 방지
# ══════════════════════════════════════════════════════════════════════════

def test_concurrent_duplicate_requests_only_run_once(monkeypatch):
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_run(analytics, cfg):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return dict(FAKE_RESULT)

    monkeypatch.setattr("modules.strategy_room.run_strategy_room", _slow_run)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r2.json()["data"]["result"] == {}
    assert "이미 진행 중" in r2.json()["data"]["error"]

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Side Effect 없음 + 구조 확인
# ══════════════════════════════════════════════════════════════════════════

def test_never_calls_calculator_or_registry_or_deploy(monkeypatch):
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": True})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: dict(FAKE_RESULT))

    import sys as _sys
    originally_absent = [m for m in ("modules.app_factory",) if m not in _sys.modules]

    r = _client().post("/api/strategy-room/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 Strategy Room 처리 중 새로 import됨(계산기 파이프라인 접근 의심)"


def test_service_source_never_references_protected_pipeline():
    import inspect
    from api.services import strategy_room_service
    source = inspect.getsource(strategy_room_service)
    for forbidden in (
        "generate_app", "generate_app_with_contract", "build_contract",
        "check_hold_rules", "validate_formula", "save_app",
        "CalculatorRepository", "registry_loader", "cost_manager", "retry_queue",
    ):
        assert forbidden not in source


def test_only_one_new_write_route_added_under_strategy_room():
    from _route_utils import write_routes
    from api.main import app
    assert write_routes(app, prefix="/api/strategy-room") == [("/api/strategy-room/run", "POST")]


def test_client_cannot_forge_enabled_or_result_via_request_body(monkeypatch):
    """POST에 임의 body(예: {"enabled": true, "result": {...}})를 실어도 서버는
    무시하고 실제 cfg/run_strategy_room() 결과만 신뢰해야 한다(endpoint가 body를
    파싱하지 않으므로 애초에 반영될 수 없음)."""
    monkeypatch.setattr("api.services.strategy_room_service.load_config", lambda *a, **k: {"ENABLE_STRATEGY_ROOM": False})
    monkeypatch.setattr("api.services.strategy_room_service.cache_read", lambda cfg, table: [])
    monkeypatch.setattr("modules.strategy_room.run_strategy_room", lambda analytics, cfg: {})

    r = _client().post(
        "/api/strategy-room/run", headers=_auth(ADMIN_TOKEN),
        json={"enabled": True, "result": {"summary": "forged"}},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["enabled"] is False
    assert data["result"] == {}
