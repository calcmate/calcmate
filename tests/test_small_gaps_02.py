# -*- coding: utf-8 -*-
"""tests/test_small_gaps_02.py — CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02 검증.

A. POST /api/scheduler/calculator-webapp/run-once: Busy → 200 + LOCK_CONFLICT
B. POST /api/scheduler/pipeline/run-one: main.run_once(cfg, max_count=1)
C. POST /api/settings/wordpress/test: dashboard.py "🔌 WordPress 연결 테스트"
D. POST /api/calculators/generate/preview(+/save, /discard): Mode A 검토 후 저장

모든 외부 경로(AI 생성, save_app, build, WP HTTP, 파이프라인, lock)는 monkeypatch로
대체한다 — 실제 WP/Sheets/GitHub/Telegram/DB/Registry에 닿는 코드는 실행되지 않는다.
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "small-gaps-02-viewer-token"
ADMIN_TOKEN = "small-gaps-02-admin-token"
_ROOT = Path(__file__).resolve().parent.parent
SECRET_PW = "abcd EFGH ijkl MNOP"


def _registry_snapshot():
    r = subprocess.run(["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
                       cwd=_ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.stdout


def _mtime(rel):
    p = _ROOT / rel
    return p.stat().st_mtime if p.exists() else None


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _fresh_job_store():
    import api.services.generation_job_store as m
    m._store = None
    yield
    if m._store is not None:
        m._store.shutdown(wait=True)
        m._store = None


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(token=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
# A. Calculator Webapp manual run
# ══════════════════════════════════════════════════════════════════════════

def test_webapp_success_contract_unchanged(monkeypatch):
    from api.services import calculator_webapp_scheduler_service as svc
    monkeypatch.setattr(svc, "run_once", lambda: {"produced": 1, "reason": "ok"})
    r = _client().post("/api/scheduler/calculator-webapp/run-once", headers=_h())
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["data"] == {"produced": 1, "reason": "ok"}


def test_webapp_busy_returns_lock_conflict(monkeypatch):
    from api.services import calculator_webapp_scheduler_service as svc

    def _busy():
        raise svc.CalculatorWebAppSchedulerBusy("Calculator WebApp Scheduler가 이미 실행 중입니다.")
    monkeypatch.setattr(svc, "run_once", _busy)
    r = _client().post("/api/scheduler/calculator-webapp/run-once", headers=_h())
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "LOCK_CONFLICT"


def test_webapp_unexpected_exception_is_500_without_leak(monkeypatch):
    from api.services import calculator_webapp_scheduler_service as svc

    def _boom():
        raise RuntimeError("SECRET-WEBAPP-DETAIL")
    monkeypatch.setattr(svc, "run_once", _boom)
    r = _client().post("/api/scheduler/calculator-webapp/run-once", headers=_h())
    assert r.status_code == 500
    assert "SECRET-WEBAPP-DETAIL" not in r.text
    assert "LOCK_CONFLICT" not in r.text


def test_webapp_viewer_forbidden():
    r = _client().post("/api/scheduler/calculator-webapp/run-once", headers=_h(VIEWER_TOKEN))
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# B. Blog 글 생성(1건) — main.run_once(cfg, max_count=1)
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def pipeline_spy(monkeypatch):
    from api.services import pipeline_run_service as svc
    calls = {"run_once": [], "load_config": [], "acquire": 0, "release": 0}

    def _load_config(*a, **k):
        calls["load_config"].append((a, k))
        return {"BLOG_SCHEDULE": {"enabled": False}, "DAILY_POST_COUNT": 5}

    def _run_once(cfg, dry_run=False, max_count=None):
        calls["run_once"].append({"cfg": cfg, "max_count": max_count, "dry_run": dry_run})
        return {"produced": 1, "processed": 1, "dup": 0, "failed": 0, "no_wp": 0, "reason": "ok"}

    def _acquire(cfg, **kw):
        calls["acquire"] += 1
        return True

    def _release(cfg):
        calls["release"] += 1

    monkeypatch.setattr(svc, "load_config", _load_config)
    monkeypatch.setattr(svc.PIPE, "run_once", _run_once)
    monkeypatch.setattr(svc.scheduler_engine, "_acquire_lock", _acquire)
    monkeypatch.setattr(svc.scheduler_engine, "_release_lock", _release)
    return calls


def test_run_one_passes_max_count_1_not_daily_post_count(pipeline_spy):
    r = _client().post("/api/scheduler/pipeline/run-one", headers=_h())
    assert r.status_code == 200 and r.json()["success"] is True
    assert len(pipeline_spy["run_once"]) == 1
    assert pipeline_spy["run_once"][0]["max_count"] == 1
    assert pipeline_spy["run_once"][0]["dry_run"] is False
    assert r.json()["data"]["produced"] == 1


def test_run_one_independent_of_blog_scheduler_switch(pipeline_spy):
    """BLOG_SCHEDULE.enabled=false여도 실행된다(dashboard.py 원본과 동일)."""
    r = _client().post("/api/scheduler/pipeline/run-one", headers=_h())
    assert r.json()["success"] is True
    assert pipeline_spy["run_once"][0]["cfg"]["BLOG_SCHEDULE"]["enabled"] is False


def test_run_one_uses_same_cfg_and_lock_as_pipeline_run_once(pipeline_spy):
    """WP 대상 미지정 load_config()(= 기존 /pipeline/run-once, dashboard.py load_cfg와
    동일 대상) + blog scheduler_line lock 획득/해제."""
    _client().post("/api/scheduler/pipeline/run-one", headers=_h())
    args, kwargs = pipeline_spy["load_config"][0]
    assert args == () and kwargs.get("wp_target") is None
    assert pipeline_spy["run_once"][0]["cfg"]["scheduler_line"] == "blog"
    assert pipeline_spy["acquire"] == 1 and pipeline_spy["release"] == 1


def test_run_one_busy_returns_lock_conflict_and_does_not_run(pipeline_spy, monkeypatch):
    from api.services import pipeline_run_service as svc
    monkeypatch.setattr(svc.scheduler_engine, "_acquire_lock", lambda cfg, **kw: False)
    r = _client().post("/api/scheduler/pipeline/run-one", headers=_h())
    assert r.status_code == 200
    assert r.json()["error"]["code"] == "LOCK_CONFLICT"
    assert pipeline_spy["run_once"] == []


def test_run_one_budget_result_passed_through(pipeline_spy, monkeypatch):
    """예산 초과 시 main.run_once가 반환하는 {"produced": 0, "reason": "budget_daily"}를
    가공하지 않고 그대로 전달한다(예산 가드는 main.run_once 내부 — 변경 없음)."""
    from api.services import pipeline_run_service as svc
    monkeypatch.setattr(svc.PIPE, "run_once",
                        lambda cfg, dry_run=False, max_count=None: {"produced": 0, "reason": "budget_daily"})
    r = _client().post("/api/scheduler/pipeline/run-one", headers=_h())
    assert r.json()["data"] == {"produced": 0, "reason": "budget_daily"}


def test_existing_pipeline_run_once_still_uses_daily_count(pipeline_spy):
    _client().post("/api/scheduler/pipeline/run-once", headers=_h())
    assert pipeline_spy["run_once"][0]["max_count"] is None


def test_run_one_viewer_forbidden(pipeline_spy):
    r = _client().post("/api/scheduler/pipeline/run-one", headers=_h(VIEWER_TOKEN))
    assert r.status_code == 403
    assert pipeline_spy["run_once"] == []


# ══════════════════════════════════════════════════════════════════════════
# C. WordPress 연결 테스트
# ══════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, code, payload=None, bad_json=False):
        self.status_code = code
        self._payload = payload or {}
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def wp_env(monkeypatch, tmp_path):
    """저장값은 tmp config(secrets.yaml 없음)로 격리, requests.get은 기록 후 지정 응답."""
    import requests
    from api.services import operations_settings_service as ops
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("WORDPRESS_URL: ''\n", encoding="utf-8")

    class _FakeSvc:
        _config_path = cfg_path

        def _load_raw(self):
            return {"WORDPRESS_URL": "https://saved.example", "WORDPRESS_USERNAME": "saveduser",
                    "WORDPRESS_APP_PASSWORD": "saved pw 1234"}

    monkeypatch.setattr(ops, "ConfigService", _FakeSvc)
    state = {"calls": [], "resp": _Resp(200, {"name": "운영자"})}

    def _get(url, auth=None, timeout=None, **kw):
        state["calls"].append({"url": url, "auth": auth, "timeout": timeout})
        if isinstance(state["resp"], Exception):
            raise state["resp"]
        return state["resp"]
    monkeypatch.setattr(requests, "get", _get)
    return state


def _wp(body=None):
    if body is None:
        body = {"wordpress_url": "https://wp.example/", "wordpress_username": "admin",
                "wordpress_app_password": SECRET_PW}
    return _client().post("/api/settings/wordpress/test", headers=_h(), json=body)


def test_wp_200_success_with_user_name(wp_env):
    r = _wp()
    d = r.json()["data"]
    assert r.status_code == 200 and d["ok"] is True and d["result"] == "success"
    assert d["user_name"] == "운영자"
    c = wp_env["calls"][0]
    assert c["url"] == "https://wp.example/wp-json/wp/v2/users/me"
    assert c["auth"] == ("admin", SECRET_PW.replace(" ", ""))
    assert c["timeout"] == 10


@pytest.mark.parametrize("code", [401, 403])
def test_wp_auth_failed(wp_env, code):
    wp_env["resp"] = _Resp(code)
    d = _wp().json()["data"]
    assert d["ok"] is False and d["result"] == "auth_failed" and d["status_code"] == code


def test_wp_500_reports_status_code(wp_env):
    wp_env["resp"] = _Resp(500)
    d = _wp().json()["data"]
    assert d["ok"] is False and d["result"] == "http_error" and d["status_code"] == 500


def test_wp_timeout(wp_env):
    import requests
    wp_env["resp"] = requests.exceptions.Timeout(f"timed out with auth {SECRET_PW}")
    r = _wp()
    assert r.json()["data"]["result"] == "timeout"
    assert SECRET_PW not in r.text


def test_wp_connection_error_does_not_leak_raw_exception(wp_env):
    import requests
    wp_env["resp"] = requests.exceptions.ConnectionError(f"boom https://admin:{SECRET_PW}@wp.example")
    r = _wp()
    assert r.json()["data"]["result"] == "connection_error"
    assert SECRET_PW not in r.text and "boom" not in r.text


@pytest.mark.parametrize("url", ["ftp://wp.example", "wp.example", "https://", "javascript:alert(1)"])
def test_wp_invalid_url_rejected_without_request(wp_env, url):
    r = _wp({"wordpress_url": url, "wordpress_username": "admin", "wordpress_app_password": SECRET_PW})
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert wp_env["calls"] == []


def test_wp_missing_credentials(wp_env, monkeypatch):
    from api.services import operations_settings_service as ops

    class _Empty(ops.ConfigService):
        def _load_raw(self):
            return {}
    monkeypatch.setattr(ops, "ConfigService", _Empty)
    r = _wp({"wordpress_url": "https://wp.example", "wordpress_username": "", "wordpress_app_password": ""})
    assert r.json()["error"]["code"] == "WORDPRESS_NOT_CONFIGURED"
    assert wp_env["calls"] == []


def test_wp_falls_back_to_saved_values_and_never_returns_password(wp_env):
    r = _wp({})
    c = wp_env["calls"][0]
    assert c["url"] == "https://saved.example/wp-json/wp/v2/users/me"
    assert c["auth"] == ("saveduser", "savedpw1234")
    assert "saved pw 1234" not in r.text and "savedpw1234" not in r.text
    assert "Authorization" not in r.text


def test_wp_response_never_contains_password(wp_env):
    for resp in (_Resp(200, {"name": "x"}), _Resp(401), _Resp(500), _Resp(200, bad_json=True)):
        wp_env["resp"] = resp
        r = _wp()
        assert SECRET_PW not in r.text and SECRET_PW.replace(" ", "") not in r.text


def test_wp_viewer_forbidden(wp_env):
    r = _client().post("/api/settings/wordpress/test", headers=_h(VIEWER_TOKEN), json={})
    assert r.status_code == 403
    assert wp_env["calls"] == []


# ══════════════════════════════════════════════════════════════════════════
# D. Mode A preview → save / discard
# ══════════════════════════════════════════════════════════════════════════

FAKE_APP = {
    "name": "퇴직금 계산기", "tier": 2, "_tokens": 1234, "_steps": [("spec", "ok")],
    "_formula_valid": True, "_formula_msg": "", "calculator_type": "simple",
    "formula": "a*b", "seo_title": "퇴직금 계산기 2026", "input_schema": {"a": {}, "b": {}},
    "output_schema": {"r": {}}, "faq": [{"q": "Q", "a": "A"}], "blog_draft": "draft",
    "html": "<html><script>function calc(){}</script></html>",
}


@pytest.fixture
def af(monkeypatch):
    """generate_app/save_app/build/slug/html 검증을 모두 대체하고 호출을 기록한다."""
    from modules import app_factory, review_center
    from api.services import calculator_service as cs
    st = {"generate": 0, "save": [], "build": [], "conflict": False,
          "app": dict(FAKE_APP), "html_ok": True}

    def _gen(cfg, name, category="", desc="", tier=2):
        st["generate"] += 1
        return dict(st["app"])

    def _save(cfg, app, slug=None):
        st["save"].append(slug)
        return True, f"저장 완료: {slug}"

    def _build(slug):
        st["build"].append(slug)
        return {"ok": True, "stage": "done", "message": "built", "snapshot_dir": f"_site/{slug}"}

    monkeypatch.setattr(cs, "load_config", lambda *a, **k: {})
    monkeypatch.setattr(app_factory, "generate_app", _gen)
    monkeypatch.setattr(app_factory, "save_app", _save)
    monkeypatch.setattr(cs, "build_calculator", _build)
    monkeypatch.setattr(review_center, "validate_html_js_completeness",
                        lambda html: (st["html_ok"], "" if st["html_ok"] else "HTML 잘림", []))
    monkeypatch.setattr(review_center, "check_slug_conflict",
                        lambda slug, cfg: (slug, st["conflict"], "이미 존재" if st["conflict"] else "OK"))
    return st


def _wait_job(c, job_id, tries=100):
    for _ in range(tries):
        d = c.get(f"/api/calculators/generate/{job_id}", headers=_h()).json()["data"]
        if d["status"] in ("succeeded", "failed"):
            return d
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _preview(c):
    r = c.post("/api/calculators/generate/preview", headers=_h(),
               json={"name": "퇴직금 계산기", "category": "노무", "description": "d", "tier": 2})
    assert r.status_code == 200, r.text
    return r.json()["data"]["job_id"]


def test_preview_generates_without_save_build_or_registry_change(af):
    before = (_registry_snapshot(), _mtime("data/blog_auto.db"), _mtime("config/config.yaml"))
    c = _client()
    d = _wait_job(c, _preview(c))
    assert d["status"] == "succeeded"
    res = d["result"]
    assert res["mode"] == "A_preview" and res["saved"] is False
    for k in ("suggested_slug", "tier", "formula", "html", "faq", "seo_title",
              "formula_valid", "html_complete", "input_schema", "output_schema"):
        assert k in res
    assert res["seo_title"] == "퇴직금 계산기 2026" and res["html"] == FAKE_APP["html"]
    assert af["generate"] == 1 and af["save"] == [] and af["build"] == []
    assert (_registry_snapshot(), _mtime("data/blog_auto.db"), _mtime("config/config.yaml")) == before


def test_preview_save_runs_gates_then_save_app_and_build(af):
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    r = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(), json={"slug": "severance-pay"})
    d = r.json()["data"]
    assert d["ok"] is True and d["slug"] == "severance-pay"
    assert af["save"] == ["severance-pay"] and af["build"] == ["severance-pay"]
    job = _wait_job(c, job_id)
    assert job["result"]["saved"] is True and "app" not in job["result"] and "html" not in job["result"]


def test_preview_save_twice_rejected(af):
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(), json={"slug": "severance-pay"})
    r = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(), json={"slug": "severance-pay"})
    assert r.json()["error"]["code"] == "PREVIEW_STATE_INVALID"
    assert af["save"] == ["severance-pay"]


def test_preview_save_blocked_by_slug_conflict(af):
    af["conflict"] = True
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    d = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(),
               json={"slug": "severance-pay"}).json()["data"]
    assert d["ok"] is False and "중복" in d["blocked_reason"]
    assert af["save"] == [] and af["build"] == []


def test_preview_save_blocked_by_formula_hard_gate(af):
    af["app"] = {**FAKE_APP, "_formula_valid": False, "_formula_msg": "변수 불일치"}
    c = _client()
    job_id = _preview(c)
    res = _wait_job(c, job_id)["result"]
    assert res["formula_valid"] is False          # 검토 화면에는 경고로 노출
    d = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(),
               json={"slug": "severance-pay"}).json()["data"]
    assert d["ok"] is False and "formula" in d["blocked_reason"]
    assert af["save"] == []


def test_preview_save_blocked_by_html_completeness(af):
    af["html_ok"] = False
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    d = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(),
               json={"slug": "severance-pay"}).json()["data"]
    assert d["ok"] is False and af["save"] == []


def test_preview_save_rejects_bad_slug(af):
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    r = c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(), json={"slug": "한글 슬러그"})
    assert r.status_code == 422
    assert af["save"] == []


def test_preview_discard_removes_job_only(af):
    before = (_registry_snapshot(), _mtime("data/blog_auto.db"))
    c = _client()
    job_id = _preview(c)
    _wait_job(c, job_id)
    r = c.post(f"/api/calculators/generate/preview/{job_id}/discard", headers=_h())
    assert r.json()["data"] == {"discarded": True, "job_id": job_id}
    assert c.get(f"/api/calculators/generate/{job_id}", headers=_h()).json()["error"]["code"] == "NOT_FOUND"
    assert af["save"] == [] and af["build"] == []
    assert (_registry_snapshot(), _mtime("data/blog_auto.db")) == before


def test_discard_rejects_unknown_saved_running_and_non_preview(af, monkeypatch):
    c = _client()
    assert c.post("/api/calculators/generate/preview/nope/discard", headers=_h()).json()["error"]["code"] == "NOT_FOUND"

    job_id = _preview(c)
    _wait_job(c, job_id)
    c.post(f"/api/calculators/generate/preview/{job_id}/save", headers=_h(), json={"slug": "severance-pay"})
    assert c.post(f"/api/calculators/generate/preview/{job_id}/discard",
                  headers=_h()).json()["error"]["code"] == "PREVIEW_STATE_INVALID"

    from api.services.generation_job_store import get_job_store
    store = get_job_store()
    _, _, other = store.submit("legacy-mode-a", lambda: {"slug": "x"})
    for _ in range(100):
        if store.get(other).status == "succeeded":
            break
        time.sleep(0.02)
    assert c.post(f"/api/calculators/generate/preview/{other}/discard",
                  headers=_h()).json()["error"]["code"] == "PREVIEW_STATE_INVALID"
    assert c.post(f"/api/calculators/generate/preview/{other}/save", headers=_h(),
                  json={"slug": "x"}).json()["error"]["code"] == "PREVIEW_STATE_INVALID"

    import threading
    gate = threading.Event()
    _, _, running = store.submit("preview:slow", lambda: (gate.wait(5), {"app": {}})[1])
    try:
        assert c.post(f"/api/calculators/generate/preview/{running}/discard",
                      headers=_h()).json()["error"]["code"] == "PREVIEW_STATE_INVALID"
    finally:
        gate.set()


def test_preview_viewer_forbidden(af):
    c = _client()
    assert c.post("/api/calculators/generate/preview", headers=_h(VIEWER_TOKEN),
                  json={"name": "x"}).status_code == 403
    assert c.post("/api/calculators/generate/preview/x/save", headers=_h(VIEWER_TOKEN),
                  json={"slug": "x"}).status_code == 403
    assert c.post("/api/calculators/generate/preview/x/discard", headers=_h(VIEWER_TOKEN)).status_code == 403
    assert af["generate"] == 0


def test_legacy_generate_endpoint_still_saves_in_one_job(af):
    """기존 POST /generate(생성+저장 일괄) 계약 유지."""
    c = _client()
    r = c.post("/api/calculators/generate", headers=_h(), json={"name": "퇴직금 계산기", "slug": "severance-pay"})
    d = _wait_job(c, r.json()["data"]["job_id"])
    assert d["status"] == "succeeded" and af["save"] == ["severance-pay"]
