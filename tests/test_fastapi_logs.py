# -*- coding: utf-8 -*-
"""tests/test_fastapi_logs.py — STEP 18-G 로그/비용/파이프라인 조회 API 검증.

전부 READ-ONLY. 쓰기 endpoint가 없는지, 로그 파일에 쓰기가 발생하지 않는지 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

# STEP S4: /api/costs가 require_admin으로 전환되어, 이 파일에서 그 endpoint를
# 호출하는 기존 테스트들은 admin 토큰이 필요해졌다(다른 endpoint는 여전히 공개).
_ADMIN_TOKEN = "logs-test-admin-token"


@pytest.fixture(autouse=True)
def _admin_token_for_costs(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", _ADMIN_TOKEN)


# log_service는 `from modules.dashboard_cache import read as cache_read`로 가져오므로
# consumer namespace를 patch한다 — 운영 dashboard_cache.db/Sheets에 접근하지 않는다.
@pytest.fixture(autouse=True)
def _isolate_log_cache(monkeypatch):
    monkeypatch.setattr(
        "api.services.log_service.cache_read",
        lambda cfg, table, ttl=120, auto_refresh=True: [],
    )


# 실제 data/logs/pipeline.log는 실행 중인 FastAPI/wp_blog_deploy도 기록하므로 비교 대상에서
# 제외하고, log_service가 읽는 경로를 tmp_path의 테스트 로그로 바꾼다.
@pytest.fixture
def _tmp_pipeline_log(tmp_path, monkeypatch):
    log_path = tmp_path / "pipeline.log"
    log_path.write_text("2026-01-01 00:00:00 [INFO] test line\n"
                        "2026-01-01 00:00:01 [ERROR] test error\n", encoding="utf-8")
    monkeypatch.setattr("api.services.log_service._PIPELINE_LOG", log_path)
    return log_path


def _admin_auth():
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _client():
    from api.main import app
    return TestClient(app)


def test_get_logs_errors():
    r = _client().get("/api/logs/errors")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "operation_errors" in body["data"]
    assert "calculator_quality_holds" in body["data"]
    assert "total" in body["data"]


def test_get_logs_recent():
    r = _client().get("/api/logs/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert isinstance(body["data"]["lines"], list)


def test_get_logs_live_default():
    r = _client().get("/api/logs/live")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "entries" in body["data"]
    assert "counts" in body["data"]


def test_get_logs_live_level_filter():
    r = _client().get("/api/logs/live?level=error")
    assert r.status_code == 200
    body = r.json()
    for entry in body["data"]["entries"]:
        assert entry["level"] == "error"


def test_get_logs_live_rejects_invalid_level():
    r = _client().get("/api/logs/live?level=not-a-level")
    assert r.status_code == 422  # pydantic/FastAPI Query pattern validation


def test_get_pipeline_status():
    r = _client().get("/api/pipeline/status")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    for key in ("stages", "finished", "has_error", "cost_today", "tokens_today"):
        assert key in body["data"]


def test_get_costs():
    r = _client().get("/api/costs", headers=_admin_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("today", "month", "total_cost", "by_provider_month", "by_model_month",
                "cost_manager", "retry_queue"):
        assert key in data


# ── 로그 파일 write 금지 확인(§7) ──────────────────────────────────────

def test_log_file_untouched_by_api_calls(_tmp_pipeline_log):
    import hashlib
    _PIPELINE_LOG = _tmp_pipeline_log
    before_exists = _PIPELINE_LOG.exists()
    before_hash = hashlib.sha256(_PIPELINE_LOG.read_bytes()).hexdigest() if before_exists else None
    before_mtime = _PIPELINE_LOG.stat().st_mtime if before_exists else None

    c = _client()
    c.get("/api/logs/errors")
    c.get("/api/logs/recent")
    c.get("/api/logs/live")
    c.get("/api/pipeline/status")
    c.get("/api/costs", headers=_admin_auth())

    after_exists = _PIPELINE_LOG.exists()
    assert before_exists == after_exists
    if before_exists:
        after_hash = hashlib.sha256(_PIPELINE_LOG.read_bytes()).hexdigest()
        after_mtime = _PIPELINE_LOG.stat().st_mtime
        assert before_hash == after_hash
        assert before_mtime == after_mtime


def test_no_write_endpoints_registered_for_logs_and_pipeline():
    """STEP 18-N: tests/_route_utils.write_routes()로 nested router까지 재귀
    수집해 검사한다(app.routes 얕은 순회는 vacuously PASS했음 — STEP 18-M 발견).
    STEP S5: /api/costs 하위엔 이제 resume/retry 2개의 정당한 write route가
    있으므로 이 검사에서 제외하고 tests/test_cost_resume_retry.py가 전담한다."""
    from api.main import app
    write_paths = (
        write_routes(app, prefix="/api/logs")
        + write_routes(app, prefix="/api/pipeline")
    )
    assert write_paths == [], f"로그/파이프라인 쓰기 endpoint가 존재하면 안 됨: {write_paths}"


def test_no_cost_or_retry_write_functions_called(monkeypatch):
    """조회 API 호출 과정에서 BudgetTracker.record / cost_manager.resume,pause /
    retry_queue.retry,remove,enqueue가 절대 호출되지 않는지 확인."""
    from modules.logger import BudgetTracker
    from modules import cost_manager, retry_queue

    def _boom(*a, **kw):
        raise AssertionError("쓰기 함수가 호출되면 안 된다")

    monkeypatch.setattr(BudgetTracker, "record", _boom)
    monkeypatch.setattr(cost_manager, "resume", _boom)
    monkeypatch.setattr(cost_manager, "pause", _boom)
    monkeypatch.setattr(retry_queue, "retry", _boom)
    monkeypatch.setattr(retry_queue, "remove", _boom)
    monkeypatch.setattr(retry_queue, "enqueue", _boom)

    r = _client().get("/api/costs", headers=_admin_auth())
    assert r.status_code == 200
    assert r.json()["success"] is True


# ── 민감정보 마스킹(§17) ────────────────────────────────────────────────

def test_mask_secrets_redacts_known_patterns():
    from api.services.log_service import mask_secrets

    assert "sk-****" in mask_secrets("key=sk-abcdefghijklmnop used")
    assert "abcdefghijklmnop" not in mask_secrets("key=sk-abcdefghijklmnop used")

    masked = mask_secrets("Authorization: Bearer abcdef123456")
    assert "abcdef123456" not in masked

    masked2 = mask_secrets("password=hunter2plus more text")
    assert "hunter2plus" not in masked2

    # 마스킹 대상이 없는 일반 텍스트는 그대로 유지
    assert mask_secrets("일반 로그 메시지입니다") == "일반 로그 메시지입니다"
