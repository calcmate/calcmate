# -*- coding: utf-8 -*-
"""tests/test_step_v1ops03_local_mode.py — STEP V1-OPS-03: 로컬 전용 무인증
관리자 모드(CALCMATE_DASHBOARD_LOCAL_MODE) 검증.

변경 지점은 api/auth/dependencies.py::get_current_user() 단 한 곳이다.
CALCMATE_DASHBOARD_LOCAL_MODE 환경변수가 truthy일 때만 토큰 검사를 건너뛰고
고정 admin CurrentUser를 반환한다 — require_authenticated()/require_admin()/
authenticate_token()/CurrentUser/Role 등 기존 구조는 전혀 건드리지 않았다.

이 파일은 두 가지를 증명한다.
1. 환경변수가 없으면(기본값) 기존 401/403 동작이 100% 그대로 유지된다
   (외부/운영 배포 환경 보호 확인).
2. 환경변수가 설정되면 토큰 없이도 Calculator/Blog Scheduler 등 관리자
   endpoint에 도달할 수 있다 — 단, 실제 저장/실행은 STEP 4-H-5~7 및
   STEP 18-E의 기존 격리 패턴을 그대로 재사용해 mock/tmp_path로 막는다.

실제 AI 호출 없음. 실제 Registry/DB/config.yaml에는 쓰지 않는다(전부 mock
또는 tmp_path 격리 — STEP 4-H-4 사고 재발 방지 설계를 그대로 계승).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

_LOCAL_MODE_ENV = "CALCMATE_DASHBOARD_LOCAL_MODE"
REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


def _client():
    from api.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """모든 테스트가 명시적으로 own 상태에서 시작하도록 관련 env var를 전부
    제거한다 — 다른 테스트 파일이 남긴 값이 섞이지 않게 한다."""
    monkeypatch.delenv(_LOCAL_MODE_ENV, raising=False)
    monkeypatch.delenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", raising=False)
    monkeypatch.delenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _fresh_job_store():
    import api.services.generation_job_store as job_store_module
    job_store_module._store = None
    yield
    if job_store_module._store is not None:
        job_store_module._store.shutdown(wait=True)
        job_store_module._store = None


def _wait_for_terminal(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/calculators/generate/{job_id}")
        data = r.json()["data"]
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id}이 {timeout}초 내에 종료 상태에 도달하지 못함")


# ══════════════════════════════════════════════════════════════════════════
# 1) 기본값(환경변수 없음) — 기존 401/403 동작 100% 유지
# ══════════════════════════════════════════════════════════════════════════

def test_local_mode_off_by_default_auth_me_401():
    r = _client().get("/api/auth/me")
    assert r.status_code == 401


def test_local_mode_off_by_default_calculator_generate_401():
    r = _client().post("/api/calculators/generate", json={"name": "x"})
    assert r.status_code == 401


def test_local_mode_off_by_default_blog_scheduler_patch_401():
    r = _client().patch("/api/scheduler/blog/config", json={
        "enabled": True, "mode": "draft",
        "publish_slots": [{"start": "08:00", "end": "08:30"}],
        "weekday_only": False,
    })
    assert r.status_code == 401


@pytest.mark.parametrize("falsy_value", ["0", "false", "no", "", "off"])
def test_local_mode_falsy_values_do_not_activate(monkeypatch, falsy_value):
    """오탐 방지: "0"/"false"/빈 문자열 등은 활성화로 취급하지 않아야 한다."""
    monkeypatch.setenv(_LOCAL_MODE_ENV, falsy_value)
    r = _client().get("/api/auth/me")
    assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# 2) 로컬 모드 ON — 토큰 없이 admin 도달
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("truthy_value", ["1", "true", "TRUE", "yes"])
def test_local_mode_on_auth_me_returns_admin_without_token(monkeypatch, truthy_value):
    monkeypatch.setenv(_LOCAL_MODE_ENV, truthy_value)
    r = _client().get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["role"] == "admin"
    assert body["data"]["id"] == "local-admin"


def test_local_mode_on_admin_check_passes_without_token(monkeypatch):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    r = _client().get("/api/auth/admin-check")
    assert r.status_code == 200
    assert r.json()["data"]["admin"] is True


def test_local_mode_on_identity_is_fixed_regardless_of_headers(monkeypatch):
    """임의의(무효한) Authorization 헤더를 보내도 결과가 동일해야 한다 —
    토큰 값 자체를 아예 들여다보지 않는다는 것을 증명."""
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    r = _client().get("/api/auth/me", headers={"Authorization": "Bearer totally-invalid-garbage"})
    assert r.status_code == 200
    assert r.json()["data"]["id"] == "local-admin"


# ══════════════════════════════════════════════════════════════════════════
# 3) Calculator 생성 권한 — 로컬 모드에서 토큰 없이 통과
#    (STEP 4-H-5와 동일하게 generate_app/save_app을 완전히 mock — 실제 저장 없음)
# ══════════════════════════════════════════════════════════════════════════

def _mock_generate_and_save(monkeypatch):
    def _fake_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        return {
            "name": name, "category": category, "formula": "a",
            "input_schema": {"a": "number"}, "output_schema": {"b": "number"},
            "_formula_valid": True, "_formula_msg": "OK",
            # P0-1 HTML/JS 완결성 게이트를 통과하는 최소-완결 HTML(input+button+script,
            # </html> 존재) — 이 파일은 LOCAL_MODE 인증 우회를 테스트하는 것이라
            # HTML 완결성 검증에서 걸리면 안 된다.
            "html": ('<html><body><input id="a">'
                     '<button onclick="c()">계산</button>'
                     '<script>function c(){}</script></body></html>'),
        }

    def _fake_save(cfg, app, site_id="", slug=None):
        return True, "✅ 저장 완료(mock)"

    monkeypatch.setattr("modules.app_factory.generate_app", _fake_generate)
    monkeypatch.setattr("modules.app_factory.save_app", _fake_save)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})


def test_local_mode_on_calculator_generate_without_token_succeeds(monkeypatch):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    _mock_generate_and_save(monkeypatch)

    c = _client()
    r = c.post("/api/calculators/generate", json={"name": "로컬모드계산기"})
    assert r.status_code == 200
    job_id = r.json()["data"]["job_id"]

    final = _wait_for_terminal(c, job_id)
    assert final["status"] == "succeeded"


def test_local_mode_on_calculator_generate_job_poll_without_token(monkeypatch):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    _mock_generate_and_save(monkeypatch)

    c = _client()
    job_id = c.post("/api/calculators/generate", json={"name": "폴링확인계산기"}).json()["data"]["job_id"]
    r = c.get(f"/api/calculators/generate/{job_id}")
    assert r.status_code == 200  # require_admin 뒤에 있지만 로컬 모드라 토큰 없이 통과


# ══════════════════════════════════════════════════════════════════════════
# 4) Blog Scheduler 관리 권한 — 로컬 모드에서 토큰 없이 통과
#    (STEP 18-E와 동일하게 tmp_path 격리 config만 사용, 실제 config.yaml 무변경)
# ══════════════════════════════════════════════════════════════════════════

def test_local_mode_on_blog_scheduler_patch_without_token_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")

    tmp_config = tmp_path / "config.yaml"
    tmp_config.write_text(REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    import api.routers.scheduler as scheduler_router
    from api.services.config_service import ConfigService

    monkeypatch.setattr(
        scheduler_router, "ConfigService",
        lambda: ConfigService(config_path=tmp_config),
    )

    import hashlib
    real_hash_before = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()

    r = _client().patch("/api/scheduler/blog/config", json={
        "enabled": True, "mode": "draft",
        "publish_slots": [{"start": "07:00", "end": "07:30"}],
        "weekday_only": False,
    })  # Authorization 헤더 없음

    assert r.status_code == 200
    assert r.json()["success"] is True

    real_hash_after = hashlib.sha256(REAL_CONFIG.read_bytes()).hexdigest()
    assert real_hash_before == real_hash_after, "실제 config.yaml이 변경됨"
    assert '"07:00"' in tmp_config.read_text(encoding="utf-8")


def test_local_mode_on_blog_run_once_without_token_isolated(monkeypatch):
    """실제 블로그 생성 엔진은 호출하지 않는다(mock) — 토큰 없이 endpoint에
    도달하는지만 확인한다(STEP 18-E 기존 격리 패턴 재사용)."""
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")

    import api.services.blog_scheduler_service as svc
    called = []

    def _fake_run_once():
        called.append(1)
        return {"ran": True, "mock": True}

    monkeypatch.setattr(svc, "run_once", _fake_run_once)

    r = _client().post("/api/scheduler/blog/run-once")  # Authorization 헤더 없음
    assert r.status_code == 200
    assert called == [1]


# ══════════════════════════════════════════════════════════════════════════
# 5) 그 외 관리자 endpoint(Promote/Checklist/Formula/Settings)도 동일하게 통과
# ══════════════════════════════════════════════════════════════════════════

def test_local_mode_on_calculator_promote_without_token_reaches_service(monkeypatch):
    """실제 Registry 조작 없이, require_admin() 관문을 토큰 없이 통과하는지만
    확인한다 — 서비스 함수 자체는 mock으로 대체."""
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    import api.services.calculator_service as svc
    monkeypatch.setattr(
        svc, "promote_calculator_to_ready",
        lambda slug: {"slug": slug, "status": "READY", "message": "mock"},
    )
    r = _client().post("/api/calculators/does-not-matter/promote")
    assert r.status_code == 200


def test_local_mode_on_settings_patch_without_token_reaches_service(monkeypatch):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    import api.routers.settings as settings_router
    monkeypatch.setattr(
        settings_router.ConfigService, "patch_general_settings",
        lambda self, updates: {"updated": list(updates.keys())},
    )
    r = _client().patch("/api/settings/general", json={"daily_ai_budget": 5})
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 6) Secret 비노출
# ══════════════════════════════════════════════════════════════════════════

def test_local_mode_response_never_contains_env_var_name_or_value(monkeypatch):
    monkeypatch.setenv(_LOCAL_MODE_ENV, "1")
    r = _client().get("/api/auth/me")
    dumped = r.text
    assert _LOCAL_MODE_ENV not in dumped
    assert "os.environ" not in dumped


# ══════════════════════════════════════════════════════════════════════════
# 7) 운영 파일 무손상 (실측)
# ══════════════════════════════════════════════════════════════════════════

_ROOT = Path(__file__).resolve().parent.parent


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry", "config/config.yaml"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_SNAPSHOT = _registry_snapshot()


def test_real_registry_and_config_unchanged_by_this_test_file():
    after = _registry_snapshot()
    assert after == _BEFORE_SNAPSHOT, (
        f"운영 Registry/config가 변경됨:\nbefore={_BEFORE_SNAPSHOT!r}\nafter={after!r}"
    )
