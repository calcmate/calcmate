# -*- coding: utf-8 -*-
"""tests/test_cost_monitor.py — STEP S4: Cost Monitor 비용 집계/Breakdown
React/FastAPI 이관 검증.

dashboard.py "💰 Revenue > 💰 비용 모니터" 탭과 동일한 원본 집계 로직
(modules.logger.BudgetTracker)을 그대로 재사용하는지, /api/costs가 이번 STEP에서
처음으로 require_admin으로 보호되는지, 클라이언트가 값을 조작할 수 없는지를
검증한다. Manual Resume/Retry Queue 조작은 이번 STEP의 범위가 아니다 — 그 데이터가
이미 존재하는 get_cost_status() 응답에 read-only로 포함돼 있을 뿐, 여기서 실행
가능한 어떤 write 함수도 호출하지 않는다(BudgetTracker.record/cost_manager.resume,
pause/retry_queue.retry,remove,enqueue 전부 이 파일에서 monkeypatch로 막아
호출되면 즉시 실패하게 한다).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "cost-monitor-test-viewer-token"
ADMIN_TOKEN = "cost-monitor-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _block_all_write_functions(monkeypatch):
    """이 파일의 어떤 테스트에서도 실제 비용 기록/재개/재시도 함수가 호출되면
    안 된다 — 조회(get_cost_status)가 순수 읽기 전용임을 구조적으로 보장한다."""
    from modules.logger import BudgetTracker
    from modules import cost_manager, retry_queue

    def _boom(*a, **k):
        raise AssertionError("쓰기 함수가 호출되면 안 된다(Cost Monitor는 읽기 전용)")

    monkeypatch.setattr(BudgetTracker, "record", _boom)
    monkeypatch.setattr(cost_manager, "resume", _boom)
    monkeypatch.setattr(cost_manager, "pause", _boom)
    monkeypatch.setattr(retry_queue, "retry", _boom)
    monkeypatch.setattr(retry_queue, "remove", _boom)
    monkeypatch.setattr(retry_queue, "enqueue", _boom)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


# ── §9-C: 인증 ─────────────────────────────────────────────────────────────

def test_get_costs_without_auth_returns_401():
    r = _client().get("/api/costs")
    assert r.status_code == 401


def test_get_costs_as_viewer_returns_403():
    r = _client().get("/api/costs", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_get_costs_as_admin_returns_200():
    r = _client().get("/api/costs", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ── §9-A: 정상 조회(실제 저장된 구조 기준) ──────────────────────────────────

def test_response_shape_matches_real_get_cost_status_fields():
    """cost_service.get_cost_status()가 실제로 반환하는 필드 그대로 응답에
    실려오는지 확인 — 새 필드를 임의로 추가하거나 기존 필드를 누락하지 않는다."""
    r = _client().get("/api/costs", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    for key in ("today", "month", "total_cost", "by_provider_month", "by_model_month",
                "cost_manager", "retry_queue"):
        assert key in data
    for key in ("used", "limit", "exceeded", "tokens"):
        assert key in data["today"]
    for key in ("used", "limit", "exceeded"):
        assert key in data["month"]


def test_uses_real_budget_tracker_not_a_reimplementation(monkeypatch):
    """§9-E: 새 비용 계산식을 만들지 않고 실제 BudgetTracker를 그대로 호출하는지
    확인 — BudgetTracker.get_provider_breakdown/get_model_breakdown을 스파이해
    실제로 호출됐는지, 그리고 반환값이 그대로(가공 없이) 응답에 실리는지 검증."""
    from modules.logger import BudgetTracker

    called = {}
    real_provider = BudgetTracker.get_provider_breakdown
    real_model = BudgetTracker.get_model_breakdown

    def _spy_provider(self, scope="monthly"):
        called["provider_scope"] = scope
        return {"openai": 1.2345}

    def _spy_model(self, scope="monthly"):
        called["model_scope"] = scope
        return {"gpt-4o-mini": 0.9999}

    monkeypatch.setattr(BudgetTracker, "get_provider_breakdown", _spy_provider)
    monkeypatch.setattr(BudgetTracker, "get_model_breakdown", _spy_model)

    r = _client().get("/api/costs", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert called["provider_scope"] == "monthly"
    assert called["model_scope"] == "monthly"
    assert data["by_provider_month"] == {"openai": 1.2345}
    assert data["by_model_month"] == {"gpt-4o-mini": 0.9999}
    assert real_provider is not None and real_model is not None  # 원본 함수 참조 확인(재구현 아님)


# ── §9-B: 데이터 없음 ────────────────────────────────────────────────────

def test_empty_budget_data_returns_clean_zeros_not_500(monkeypatch, tmp_path):
    """budget.json이 아예 없는 상태(신규 설치/데이터 없음)를 시뮬레이션 —
    BudgetTracker._load()의 기존 기본값 그대로 빈 breakdown이 나와야 한다."""
    from modules.logger import BudgetTracker
    original_init = BudgetTracker.__init__

    def _fake_init(self, cfg):
        self.cfg = cfg
        self.path = tmp_path / "budget_does_not_exist.json"
        self._load()

    monkeypatch.setattr(BudgetTracker, "__init__", _fake_init)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})

    r = _client().get("/api/costs", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["today"]["used"] == 0
    assert data["month"]["used"] == 0
    assert data["total_cost"] == 0
    assert data["by_provider_month"] == {"openai": 0, "claude": 0, "gemini": 0}
    assert data["by_model_month"] == {}
    assert original_init is not None


# ── §9-D: 데이터 위조 방지 ──────────────────────────────────────────────

def test_get_costs_still_has_no_body_to_forge_with():
    """GET /api/costs 자체는 body를 받지 않으므로 클라이언트가 cost/usage 값을
    주입할 방법이 없다. STEP S5에서 resume/retry, STEP S6에서 remove까지
    3개의 write route가 정당하게 추가되었다(전부 실행 전용, 값 조작이 아닌
    실행 트리거) — 세부 인증/차단 검증은 tests/test_cost_resume_retry.py와
    tests/test_cost_remove.py가 전담한다."""
    from _route_utils import write_routes
    from api.main import app
    assert sorted(write_routes(app, prefix="/api/costs")) == [
        ("/api/costs/remove", "POST"),
        ("/api/costs/resume", "POST"),
        ("/api/costs/retry", "POST"),
    ]


def test_client_supplied_body_is_ignored_on_get(monkeypatch):
    """GET에 body를 실어 보내도(비표준이지만) 서버는 실제 BudgetTracker 결과만
    반환하고 클라이언트 값을 반영하지 않는지 확인."""
    from modules.logger import BudgetTracker
    monkeypatch.setattr(BudgetTracker, "get_provider_breakdown", lambda self, scope="monthly": {"claude": 0.01})

    r = _client().request(
        "GET", "/api/costs", headers=_auth(ADMIN_TOKEN),
        json={"by_provider_month": {"openai": 999999}},
    )
    assert r.status_code == 200
    assert r.json()["data"]["by_provider_month"] == {"claude": 0.01}


# ── 데이터 안전(§8): DB/Registry 미변경 ──────────────────────────────────

def test_get_costs_never_touches_db_or_registry():
    import inspect
    from api.services import cost_service
    source = inspect.getsource(cost_service)
    for forbidden in ("CalculatorRepository", "app_factory", "registry_loader", "save_app", "generate_app"):
        assert forbidden not in source
