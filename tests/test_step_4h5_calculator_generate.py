# -*- coding: utf-8 -*-
"""tests/test_step_4h5_calculator_generate.py — STEP 4-H-5: POST /api/calculators/
generate(Mode A) + GET /api/calculators/generate/{job_id} 검증.

이 파일은 STEP 4-H-3/4-H-4에서 이미 exhaustive하게 검증된 save_app() 자체의
내부 동작(고아 자동정리, Legal Hold 폴백, 동시성 락)을 재검증하지 않는다.
대신 이번 STEP에서 새로 연결한 glue 코드(Job 제출/조회, 동시 실행 제한,
에러 매핑, 인증, 민감정보 비유출)만 검증한다.

안전 설계(STEP 4-H-4에서 겪은 Registry 오염 사고의 재발 방지):
modules.app_factory.generate_app()/save_app()의 실제 구현을 이 파일의 어떤
테스트에서도 실행하지 않는다 — 둘 다 항상 monkeypatch로 완전히 대체한다.
따라서 tmp_path/_REG_DIR/_AUTO_PATH 격리가 실패하더라도 애초에 실제 파일
시스템에 접근하는 코드 경로 자체가 실행되지 않는다(이중 안전장치로, 파일 끝의
test_real_registry_unchanged_by_this_test_file()이 실측으로 다시 확인한다).
실제 AI API 호출 없음. Job store는 매 테스트마다 새로 생성해 이전 테스트의
동시성 상태가 새지 않게 한다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

VIEWER_TOKEN = "step4h5-test-viewer-token"
ADMIN_TOKEN = "step4h5-test-admin-token"

_ROOT = Path(__file__).resolve().parent.parent


def _registry_snapshot():
    """docs/registry_auto.yaml, docs/registry/*.yaml의 git 상태 스냅샷."""
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


def _file_mtime(rel_path):
    p = _ROOT / rel_path
    return p.stat().st_mtime if p.exists() else None


# 이 테스트 파일이 import되는 시점(=수집 시점, 어떤 테스트도 실행되기 전)의
# 스냅샷 — "깨끗해야 한다"가 아니라 "이 파일 실행 전후로 동일해야 한다"를
# 검증하기 위함(기존에 이미 존재하는 프로덕션 drift와 무관하게 검증).
_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()
_BEFORE_CONFIG_MTIME = _file_mtime("config/config.yaml")
_BEFORE_DB_MTIME = _file_mtime("data/blog_auto.db")


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _fresh_job_store():
    """매 테스트마다 GenerationJobStore 싱글턴을 새로 만든다(동시성 상태가
    테스트 간에 새지 않도록). 테스트가 끝나면 executor를 정리해 스레드가
    다음 테스트/세션 종료 이후까지 남지 않게 한다."""
    import api.services.generation_job_store as job_store_module
    job_store_module._store = None
    yield
    if job_store_module._store is not None:
        job_store_module._store.shutdown(wait=True)
        job_store_module._store = None


@pytest.fixture(autouse=True)
def _never_touch_real_config_loader(monkeypatch):
    """load_config()가 혹시라도 실제로 호출되더라도(모든 테스트가 generate_app/
    save_app 자체를 mock하므로 정상 경로에서는 호출 결과가 쓰이지 않는다)
    운영 config.yaml을 파싱하지 않도록 기본값으로 막아 둔다. 민감정보 유출
    테스트에서는 이 fixture를 다시 override한다."""
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise AssertionError("Calculator generate 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


def _mock_generate_success(monkeypatch, extra=None):
    def _fake_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        base = {
            "name": name, "category": category, "description": desc, "tier": tier,
            "formula": "a", "input_schema": {"a": "number"}, "output_schema": {"b": "number"},
            # P0-1 HTML/JS 완결성 게이트를 통과하는 최소-완결 HTML(input+button+script,
            # </html> 존재) — 이 테스트 파일의 목적(Job 제출/조회/동시성/에러매핑)과
            # 무관하므로 완결성 검증 자체를 테스트하지 않고 그냥 통과시키기 위함.
            "html": ('<html><body><input id="a">'
                     '<button onclick="c()">계산</button>'
                     '<script>function c(){}</script></body></html>'),
            "seo_title": "", "seo_desc": "", "faq": [],
        }
        if extra:
            base.update(extra)
        return base

    monkeypatch.setattr("modules.app_factory.generate_app", _fake_generate)


def _mock_generate_failure(monkeypatch, message="AI 생성 실패(mock)"):
    def _boom(cfg, name, category="", desc="", tier=2, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr("modules.app_factory.generate_app", _boom)


def _mock_save_success(monkeypatch):
    def _fake_save(cfg, app, site_id="", slug=None):
        return True, f"✅ '{app.get('name')}' 계산기 + 템플릿 저장 완료 (mock)"

    monkeypatch.setattr("modules.app_factory.save_app", _fake_save)


def _mock_save_failure(monkeypatch, message="중복 계산기명: 이미 등록됨"):
    def _fake_save(cfg, app, site_id="", slug=None):
        return False, message

    monkeypatch.setattr("modules.app_factory.save_app", _fake_save)


def _wait_for_terminal(client, job_id, timeout=5):
    """GET endpoint를 실제로 폴링해 Job이 succeeded/failed에 도달할 때까지 기다린다
    (설계된 실제 흐름 그대로 — POST 이후 폴링). 이 함수가 반환한 뒤에는 백그라운드
    스레드가 이미 끝난 상태이므로, 이후 monkeypatch가 되돌려져도 안전하다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/calculators/generate/{job_id}", headers=_auth(ADMIN_TOKEN))
        data = r.json()["data"]
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id}이 {timeout}초 내에 종료 상태에 도달하지 못함")


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_generate_without_auth_returns_401(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post("/api/calculators/generate", json={"name": "테스트"})
    assert r.status_code == 401


def test_generate_as_viewer_returns_403(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate", json={"name": "테스트"}, headers=_auth(VIEWER_TOKEN)
    )
    assert r.status_code == 403


def test_generate_job_get_without_auth_returns_401(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().get("/api/calculators/generate/does-not-exist")
    assert r.status_code == 401


def test_generate_job_get_as_viewer_returns_403(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().get(
        "/api/calculators/generate/does-not-exist", headers=_auth(VIEWER_TOKEN)
    )
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# Request 검증
# ══════════════════════════════════════════════════════════════════════════

def test_generate_missing_name_returns_422(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate", json={"category": "세금"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r.status_code == 422


def test_generate_unknown_field_rejected(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate",
        json={"name": "테스트", "mode": "B"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_generate_invalid_slug_pattern_returns_422(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate",
        json={"name": "테스트", "slug": "한글Slug!!"},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_generate_invalid_tier_returns_422(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate",
        json={"name": "테스트", "tier": 3},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 422


def test_generate_never_starts_job_on_validation_failure(monkeypatch):
    """Request validation 실패 시 Job 자체가 생성되지 않아야 한다."""
    _block_external_http(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "modules.app_factory.generate_app",
        lambda *a, **k: calls.append(1) or {"name": "x"},
    )
    _client().post("/api/calculators/generate", json={}, headers=_auth(ADMIN_TOKEN))
    assert calls == []


# ══════════════════════════════════════════════════════════════════════════
# Test 1 — 정상 Mode A 요청
# ══════════════════════════════════════════════════════════════════════════

def test_normal_generate_request_succeeds(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate_success(monkeypatch)
    _mock_save_success(monkeypatch)

    c = _client()
    r = c.post(
        "/api/calculators/generate",
        json={"name": "정상생성계산기", "category": "세금/세법", "description": "설명", "tier": 2},
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    job_id = body["data"]["job_id"]
    assert body["data"]["status"] in ("queued", "running", "succeeded")

    final = _wait_for_terminal(c, job_id)
    assert final["status"] == "succeeded"
    assert final["result"]["name"] == "정상생성계산기"
    assert final["result"]["slug"]
    assert final["error"] is None


def test_generate_audit_event_recorded_on_submit(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate_success(monkeypatch)
    _mock_save_success(monkeypatch)
    from api.auth.service import get_audit_events

    c = _client()
    r = c.post(
        "/api/calculators/generate", json={"name": "감사로그계산기"}, headers=_auth(ADMIN_TOKEN)
    )
    job_id = r.json()["data"]["job_id"]
    _wait_for_terminal(c, job_id)

    events = get_audit_events()
    assert len(events) == 1
    assert events[0].action == "calculator_generate_submit"
    assert events[0].actor_role == "admin"
    assert events[0].result == "success"


def test_no_audit_event_on_401_or_403(monkeypatch):
    _block_external_http(monkeypatch)
    from api.auth.service import get_audit_events

    c = _client()
    c.post("/api/calculators/generate", json={"name": "x"})  # 401
    c.post("/api/calculators/generate", json={"name": "x"}, headers=_auth(VIEWER_TOKEN))  # 403
    assert get_audit_events() == []


# ══════════════════════════════════════════════════════════════════════════
# Test 2 — 동시 요청(1개 실행, 1개 즉시 거부)
# ══════════════════════════════════════════════════════════════════════════

def test_concurrent_requests_one_runs_one_rejected_immediately(monkeypatch):
    _block_external_http(monkeypatch)
    import threading

    release = threading.Event()
    started = threading.Event()

    def _slow_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        started.set()
        release.wait(timeout=5)
        return {"name": name, "category": category, "formula": "a", "input_schema": {}, "output_schema": {},
                "html": ('<html><body><input id="a">'
                         '<button onclick="c()">계산</button>'
                         '<script>function c(){}</script></body></html>')}

    monkeypatch.setattr("modules.app_factory.generate_app", _slow_generate)
    _mock_save_success(monkeypatch)

    c = _client()
    r1 = c.post(
        "/api/calculators/generate", json={"name": "느린생성A"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r1.status_code == 200
    job1 = r1.json()["data"]["job_id"]
    assert started.wait(timeout=5)  # job1이 실제로 실행 중임을 확인

    # job1이 아직 실행 중인 동안 두 번째 요청 — 즉시 거부되어야 한다(큐잉 없음).
    r2 = c.post(
        "/api/calculators/generate", json={"name": "느린생성B"}, headers=_auth(ADMIN_TOKEN)
    )
    assert r2.status_code == 409
    assert "실행 중" in r2.json()["detail"]

    release.set()
    final1 = _wait_for_terminal(c, job1)
    assert final1["status"] == "succeeded"


def test_concurrent_requests_do_not_both_reach_save_app(monkeypatch):
    """동시에 두 개가 실제 저장(save_app)까지 진행되지 않아야 한다 — save_app이
    2번 호출되면 안 된다."""
    _block_external_http(monkeypatch)
    import threading

    release = threading.Event()
    started = threading.Event()
    save_calls = []

    def _slow_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        started.set()
        release.wait(timeout=5)
        return {"name": name, "category": category, "formula": "a", "input_schema": {}, "output_schema": {},
                "html": ('<html><body><input id="a">'
                         '<button onclick="c()">계산</button>'
                         '<script>function c(){}</script></body></html>')}

    def _tracked_save(cfg, app, site_id="", slug=None):
        save_calls.append(app.get("name"))
        return True, "ok"

    monkeypatch.setattr("modules.app_factory.generate_app", _slow_generate)
    monkeypatch.setattr("modules.app_factory.save_app", _tracked_save)

    c = _client()
    r1 = c.post("/api/calculators/generate", json={"name": "동시저장A"}, headers=_auth(ADMIN_TOKEN))
    job1 = r1.json()["data"]["job_id"]
    assert started.wait(timeout=5)

    r2 = c.post("/api/calculators/generate", json={"name": "동시저장B"}, headers=_auth(ADMIN_TOKEN))
    assert r2.status_code == 409

    release.set()
    _wait_for_terminal(c, job1)
    assert save_calls == ["동시저장A"], f"save_app이 정확히 1번만 호출되어야 한다: {save_calls}"


# ══════════════════════════════════════════════════════════════════════════
# Test 3 — Mode A 생성 실패
# ══════════════════════════════════════════════════════════════════════════

def test_mode_a_generation_failure_marks_job_failed(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate_failure(monkeypatch, message="AI 호출 실패(mock)")
    saved = []

    def _tracked_save(*a, **k):
        saved.append(1)
        return True, "ok"

    monkeypatch.setattr("modules.app_factory.save_app", _tracked_save)

    c = _client()
    r = c.post("/api/calculators/generate", json={"name": "생성실패계산기"}, headers=_auth(ADMIN_TOKEN))
    job_id = r.json()["data"]["job_id"]
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "AI 호출 실패" in final["error"]
    assert final["result"] is None
    assert saved == [], "생성이 실패하면 save_app()이 호출되면 안 된다"


# ══════════════════════════════════════════════════════════════════════════
# Test 4 — save_app 실패
# ══════════════════════════════════════════════════════════════════════════

def test_save_app_failure_marks_job_failed(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate_success(monkeypatch)
    _mock_save_failure(monkeypatch, message="중복 계산기명: '중복계산기' 이미 등록됨")

    c = _client()
    r = c.post("/api/calculators/generate", json={"name": "중복계산기"}, headers=_auth(ADMIN_TOKEN))
    job_id = r.json()["data"]["job_id"]
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "중복 계산기명" in final["error"]
    assert final["result"] is None


# ══════════════════════════════════════════════════════════════════════════
# Test 5 — 실패 후 재시도
# ══════════════════════════════════════════════════════════════════════════

def test_retry_after_failure_runs_normally(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate_failure(monkeypatch, message="일시적 오류(mock)")

    c = _client()
    r1 = c.post("/api/calculators/generate", json={"name": "재시도계산기"}, headers=_auth(ADMIN_TOKEN))
    job1 = r1.json()["data"]["job_id"]
    final1 = _wait_for_terminal(c, job1)
    assert final1["status"] == "failed"

    # 첫 번째가 종료 상태에 도달했으므로 슬롯이 비어 즉시 재시도 가능해야 한다.
    _mock_generate_success(monkeypatch)
    _mock_save_success(monkeypatch)
    r2 = c.post("/api/calculators/generate", json={"name": "재시도계산기"}, headers=_auth(ADMIN_TOKEN))
    assert r2.status_code == 200
    job2 = r2.json()["data"]["job_id"]
    assert job2 != job1
    final2 = _wait_for_terminal(c, job2)
    assert final2["status"] == "succeeded"


# ══════════════════════════════════════════════════════════════════════════
# Test 6 — 민감정보 유출 검증
# ══════════════════════════════════════════════════════════════════════════

def test_no_secrets_leak_into_job_or_response(monkeypatch):
    _block_external_http(monkeypatch)
    secret_marker = "sk-should-never-leak-step4h5"
    monkeypatch.setattr(
        "modules.config_loader.load_config",
        lambda *a, **k: {"OPENAI_API_KEY": secret_marker, "SECRET": "top-secret-4h5"},
    )

    def _generate_uses_cfg(cfg, name, category="", desc="", tier=2, **kwargs):
        assert cfg.get("OPENAI_API_KEY") == secret_marker  # cfg는 실제로 전달됨(사용은 하되)
        return {"name": name, "category": category, "formula": "a", "input_schema": {}, "output_schema": {},
                "html": ('<html><body><input id="a">'
                         '<button onclick="c()">계산</button>'
                         '<script>function c(){}</script></body></html>')}

    monkeypatch.setattr("modules.app_factory.generate_app", _generate_uses_cfg)
    _mock_save_success(monkeypatch)

    c = _client()
    r = c.post("/api/calculators/generate", json={"name": "보안테스트계산기"}, headers=_auth(ADMIN_TOKEN))
    job_id = r.json()["data"]["job_id"]
    final = _wait_for_terminal(c, job_id)

    dumped = str(r.json()) + str(final)
    assert secret_marker not in dumped
    assert "top-secret-4h5" not in dumped


def test_generate_job_not_found_returns_404(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().get(
        "/api/calculators/generate/00000000000000000000000000000000",
        headers=_auth(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# save_app()을 실제로 우회하지 않는지 확인 (§5)
# ══════════════════════════════════════════════════════════════════════════

def test_service_calls_real_save_app_function_object():
    """calculator_service.submit_calculator_generation()이 modules.app_factory의
    실제 save_app 함수 객체를 참조하는지(새 저장 경로를 만들지 않았는지) 확인한다
    — monkeypatch 없이 모듈 속성만 비교."""
    import inspect
    import modules.app_factory as af
    from api.services import calculator_service

    src = inspect.getsource(calculator_service.submit_calculator_generation)
    assert "app_factory.save_app(" in src
    assert "app_factory.generate_app(" in src
    # save_app이 STEP 4-H-4의 락 wrapper인지(내부에 _save_app_locked를 감싸는 구조인지)도 확인.
    assert af.save_app.__name__ == "save_app"
    assert hasattr(af, "_save_app_locked")
    assert hasattr(af, "_SAVE_APP_LOCK")


# ══════════════════════════════════════════════════════════════════════════
# Route surface / 회귀
# ══════════════════════════════════════════════════════════════════════════

def test_calculators_write_routes_include_generate():
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert ("/api/calculators/generate", "POST") in write_paths



# ══════════════════════════════════════════════════════════════════════════
# Test 7 — 운영 Registry/DB/Config 불변 (실측)
# ══════════════════════════════════════════════════════════════════════════

def test_real_registry_unchanged_by_this_test_file():
    """이 테스트 파일의 어떤 테스트도 실제 운영 Registry/config/DB를 건드리지
    않았어야 한다. '항상 깨끗해야 한다'가 아니라 '이 파일 실행 전후로 완전히
    동일해야 한다'를 확인한다 — 기존에 이미 존재하는(이 세션과 무관한) 프로덕션
    drift와 무관하게 검증하기 위함이다(STEP 4-H-4에서 겪은 사고의 재발 방지 확인).
    pytest는 파일 내 테스트를 정의 순서대로 실행하므로 이 테스트를 파일 맨 끝에
    두어 앞선 모든 테스트의 누적 효과를 검증한다."""
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
    assert _file_mtime("config/config.yaml") == _BEFORE_CONFIG_MTIME, "운영 config.yaml mtime 변경됨"
    assert _file_mtime("data/blog_auto.db") == _BEFORE_DB_MTIME, "운영 DB mtime 변경됨"
