# -*- coding: utf-8 -*-
"""tests/test_health_external.py — STEP S3: 실질 헬스체크(외부 서비스) React/FastAPI 이관.

dashboard.py "🏥 헬스체크 센터" 탭과 동일한 의미를 검증한다: OpenAI/Claude/Gemini/
Google Sheets/Drive/WordPress/Service Account 7종 체크, CRITICAL/WARNING 레벨,
critical_passed() 전체 판정, 마지막 캐시 파일(health_monitor.RESULT_PATH).

안전 설계: modules.utils.health_monitor.run()의 실제 구현(진짜 외부 API 호출)은
이 파일의 어떤 테스트에서도 실행하지 않는다 — 항상 monkeypatch로 대체한다
(실제 비용 발생 금지, 신규 계산기/Registry/DB 변경 없음).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "health-ext-test-viewer-token"
ADMIN_TOKEN = "health-ext-test-admin-token"

FAKE_RESULTS = {
    "openai": {"status": "OK", "level": "CRITICAL"},
    "claude": {"status": "OK", "level": "CRITICAL"},
    "gemini": {"status": "OK", "level": "CRITICAL"},
    "google_sheet": {"status": "OK", "level": "CRITICAL"},
    "google_drive": {"status": "OK", "level": "CRITICAL"},
    "service_account": {"status": "OK", "level": "CRITICAL", "info": "project_id=x"},
    "wordpress": {"status": "FAIL", "level": "WARNING", "error": "연결 거부"},
    "timestamp": "2026-09-05T12:00:00",
}


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


def _mock_run_success(monkeypatch, tmp_path):
    """health_monitor.run()을 실제 외부 호출 없이 대체 — 실제 함수는 절대 호출하지 않는다."""
    result_path = tmp_path / "health_last.json"

    def _fake_run(cfg):
        result_path.write_text(json.dumps(FAKE_RESULTS), encoding="utf-8")
        return dict(FAKE_RESULTS)

    monkeypatch.setattr("modules.utils.health_monitor.run", _fake_run)
    monkeypatch.setattr("modules.utils.health_monitor.RESULT_PATH", result_path)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})
    return result_path


# ── 인증/권한 ──────────────────────────────────────────────────────────────

def test_get_external_without_auth_returns_401():
    r = _client().get("/api/health/external")
    assert r.status_code == 401


def test_get_external_as_viewer_returns_403():
    r = _client().get("/api/health/external", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_external_without_auth_returns_401():
    r = _client().post("/api/health/external/run")
    assert r.status_code == 401


def test_run_external_as_viewer_returns_403():
    r = _client().post("/api/health/external/run", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


# ── 캐시 조회(GET) ─────────────────────────────────────────────────────────

def test_get_external_with_no_cache_file_reports_unavailable(monkeypatch, tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr("modules.utils.health_monitor.RESULT_PATH", missing_path)
    r = _client().get("/api/health/external", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["available"] is False
    assert body["data"]["checks"] == {}


def test_get_external_reads_the_actual_cache_file(monkeypatch, tmp_path):
    result_path = _mock_run_success(monkeypatch, tmp_path)
    # run()은 호출하지 않고, 파일이 이미 있다고 가정한 상태만 검증한다.
    result_path.write_text(json.dumps(FAKE_RESULTS), encoding="utf-8")
    r = _client().get("/api/health/external", headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["data"]["available"] is True
    assert body["data"]["timestamp"] == "2026-09-05T12:00:00"
    assert body["data"]["checks"]["openai"]["status"] == "OK"
    assert body["data"]["checks"]["wordpress"]["status"] == "FAIL"
    assert "timestamp" not in body["data"]["checks"]  # timestamp는 별도 필드로 분리됨


def test_get_external_critical_passed_true_when_only_wordpress_fails(monkeypatch, tmp_path):
    """WordPress는 WARNING이므로, CRITICAL 6개가 전부 OK면 wordpress FAIL이어도
    전체 판정은 PASS여야 한다(critical_passed() 재사용 — main.py의 파이프라인
    게이트와 동일한 의미)."""
    result_path = tmp_path / "health_last.json"
    result_path.write_text(json.dumps(FAKE_RESULTS), encoding="utf-8")
    monkeypatch.setattr("modules.utils.health_monitor.RESULT_PATH", result_path)
    r = _client().get("/api/health/external", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["critical_passed"] is True


def test_get_external_critical_passed_false_when_a_critical_check_fails(monkeypatch, tmp_path):
    bad = dict(FAKE_RESULTS)
    bad["openai"] = {"status": "FAIL", "level": "CRITICAL", "error": "invalid api key"}
    result_path = tmp_path / "health_last.json"
    result_path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr("modules.utils.health_monitor.RESULT_PATH", result_path)
    r = _client().get("/api/health/external", headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["critical_passed"] is False


def test_get_external_corrupted_cache_file_reports_unavailable_not_500(monkeypatch, tmp_path):
    result_path = tmp_path / "health_last.json"
    result_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("modules.utils.health_monitor.RESULT_PATH", result_path)
    r = _client().get("/api/health/external", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["available"] is False


# ── 실시간 실행(POST) ──────────────────────────────────────────────────────

def test_run_external_calls_health_monitor_run_and_returns_shaped_result(monkeypatch, tmp_path):
    called = {}

    def _fake_run(cfg):
        called["cfg"] = cfg
        return dict(FAKE_RESULTS)

    monkeypatch.setattr("modules.utils.health_monitor.run", _fake_run)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {"FAKE": True})
    r = _client().post("/api/health/external/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["available"] is True
    assert body["data"]["checks"]["claude"]["status"] == "OK"
    assert called["cfg"] == {"FAKE": True}  # 실제 config_loader.load_config()를 그대로 재사용했는지 확인


def test_run_external_exception_returns_clean_failure_not_500(monkeypatch):
    """timeout/exception 처리: load_config()나 run() 자체가 예외를 던져도
    500이 아니라 명확한 실패 상태(success=True, data.available=False)로 반환해야
    한다(§3 원칙: "timeout/exception을 명확한 실패 상태로 반환")."""
    def _boom(*a, **k):
        raise RuntimeError("config.yaml 파싱 실패(시뮬레이션)")

    monkeypatch.setattr("modules.config_loader.load_config", _boom)
    r = _client().post("/api/health/external/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["available"] is False
    assert "config.yaml" in body["data"]["error"]


def test_run_external_individual_check_failure_still_returns_200_with_fail_status(monkeypatch):
    """개별 체크 실패(예: OpenAI 인증 실패)는 health_monitor.run() 내부에서 이미
    try/except로 처리되어 있으므로(원본 함수 그대로 재사용), 여기서는 그 FAIL이
    그대로 통과되는지만 확인한다."""
    partial_fail = dict(FAKE_RESULTS)
    partial_fail["openai"] = {"status": "FAIL", "level": "CRITICAL", "error": "invalid_api_key"}

    monkeypatch.setattr("modules.utils.health_monitor.run", lambda cfg: partial_fail)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})
    r = _client().post("/api/health/external/run", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["checks"]["openai"]["status"] == "FAIL"
    assert body["data"]["critical_passed"] is False


def test_run_external_never_touches_db_or_registry(monkeypatch, tmp_path):
    """실질 헬스체크 실행이 DB/Registry에 아무 부작용도 남기지 않는지 구조적으로
    확인 — health_service 모듈이 DB/Registry 관련 모듈을 import/호출하지 않는다."""
    import inspect
    from api.services import health_service
    source = inspect.getsource(health_service)
    for forbidden in ("CalculatorRepository", "app_factory", "registry_loader", "save_app"):
        assert forbidden not in source


# ── 클라이언트가 PASS를 임의 조작할 수 없음 ──────────────────────────────────

def test_client_cannot_forge_critical_passed_via_request_body(monkeypatch, tmp_path):
    """POST 요청에 임의의 body를 실어도(예: {"critical_passed": true}) 서버는
    무시하고 실제 health_monitor.run() 결과만 신뢰해야 한다."""
    bad = dict(FAKE_RESULTS)
    bad["openai"] = {"status": "FAIL", "level": "CRITICAL", "error": "invalid"}
    monkeypatch.setattr("modules.utils.health_monitor.run", lambda cfg: bad)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})
    r = _client().post(
        "/api/health/external/run",
        headers=_auth(ADMIN_TOKEN),
        json={"critical_passed": True, "checks": {"openai": {"status": "OK"}}},
    )
    assert r.status_code == 200
    assert r.json()["data"]["critical_passed"] is False
    assert r.json()["data"]["checks"]["openai"]["status"] == "FAIL"
