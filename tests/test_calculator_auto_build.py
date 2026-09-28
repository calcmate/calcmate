"""CALCMATE-CALCULATOR-AUTO-BUILD-IMPLEMENT-01 — Mode A 생성 Job의 자동 Build.

submit_calculator_generation()의 _target()은 save_app() 성공 직후 기존
build_calculator()를 1회 호출해 결과를 result["build"]에 기록한다. 계산기는 이미
저장됐으므로 Build 차단/대상 조회 실패여도 Job은 succeeded로 남는다.

generate_app/save_app/build_calculator/load_config를 전부 대체한다 — 실제 AI 호출,
운영 DB/Registry/_site 접근, 외부 HTTP가 일어나지 않는다.
"""
import time

import pytest

import api.services.calculator_service as svc

HTML = ('<html><body><input id="a">'
        '<button onclick="c()">계산</button>'
        '<script>function c(){}</script></body></html>')


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    import api.services.generation_job_store as job_store_module
    job_store_module._store = None

    import requests

    def _boom(*a, **k):
        raise AssertionError("외부 HTTP 호출 금지")
    for m in ("get", "post", "put", "patch", "delete", "request"):
        monkeypatch.setattr(requests, m, _boom)

    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})
    monkeypatch.setattr("modules.app_factory.generate_app",
                        lambda cfg, name, category="", desc="", tier=2, **k: {
                            "name": name, "formula": "a", "html": HTML,
                            "input_schema": {"a": "number"}, "output_schema": {"b": "number"},
                            "_formula_valid": True})
    saves = []
    monkeypatch.setattr("modules.app_factory.save_app",
                        lambda cfg, app, slug=None, **k: saves.append(slug) or (True, "✅ 저장 완료"))
    yield saves
    if job_store_module._store is not None:
        job_store_module._store.shutdown(wait=True)
        job_store_module._store = None


def _run_job(slug="auto-build-test"):
    job = svc.submit_calculator_generation(
        name="자동빌드테스트", category="", description="", tier=2, slug=slug)
    from api.services.generation_job_store import get_job_store
    for _ in range(200):
        j = get_job_store().get(job["job_id"]).to_public_dict()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_build_success_is_recorded_and_called_once(monkeypatch, _isolated):
    calls = []

    def _fake_build(slug):
        calls.append(slug)
        return {"ok": True, "slug": slug, "stage": "build", "message": "✅ Build 완료",
                "snapshot_dir": f"/tmp/_site/{slug}"}
    monkeypatch.setattr(svc, "build_calculator", _fake_build)

    job = _run_job()
    assert job["status"] == "succeeded"
    assert calls == ["auto-build-test"], "save 성공 후 build_calculator는 정확히 1회"
    assert _isolated == ["auto-build-test"]
    r = job["result"]
    assert r["slug"] == "auto-build-test" and r["name"] == "자동빌드테스트"
    assert r["message"].startswith("✅ 저장 완료")          # 기존 message 유지 + Build 요약
    assert r["build"] == {"ok": True, "stage": "build", "message": "✅ Build 완료",
                          "snapshot_dir": "/tmp/_site/auto-build-test"}


def test_build_blocked_keeps_job_succeeded(monkeypatch, _isolated):
    monkeypatch.setattr(svc, "build_calculator", lambda slug: {
        "ok": False, "slug": slug, "stage": "build",
        "message": "❌ Build 차단 — 아래 검사 결과를 확인하세요", "snapshot_dir": None,
        "qa_steps": [{"step": 1, "passed": False}]})

    job = _run_job()
    assert job["status"] == "succeeded", "계산기는 저장됐으므로 Build 차단이 Job 실패가 되면 안 된다"
    b = job["result"]["build"]
    assert b["ok"] is False
    assert b["stage"] == "build"
    assert b["message"] == "❌ Build 차단 — 아래 검사 결과를 확인하세요"
    assert b["snapshot_dir"] is None
    assert "Build 미완료(build)" in job["result"]["message"]


def test_registry_missing_is_recorded_as_registry_stage(monkeypatch, _isolated):
    def _not_found(slug):
        raise svc.CalculatorNotFound(slug)
    monkeypatch.setattr(svc, "build_calculator", _not_found)

    job = _run_job()
    assert job["status"] == "succeeded"
    b = job["result"]["build"]
    assert b["ok"] is False and b["stage"] == "registry" and b["snapshot_dir"] is None
    assert "auto-build-test" in b["message"]


def test_unexpected_build_exception_is_not_swallowed(monkeypatch, _isolated):
    def _boom(slug):
        raise ValueError("unexpected")
    monkeypatch.setattr(svc, "build_calculator", _boom)

    job = _run_job()
    assert job["status"] == "failed" and "unexpected" in job["error"]


def test_save_failure_does_not_build(monkeypatch, _isolated):
    calls = []
    monkeypatch.setattr("modules.app_factory.save_app", lambda cfg, app, slug=None, **k: (False, "중복 슬러그"))
    monkeypatch.setattr(svc, "build_calculator", lambda slug: calls.append(slug))

    job = _run_job()
    assert job["status"] == "failed" and calls == []


def test_auto_build_path_does_not_touch_approval_or_deploy():
    import inspect
    src = inspect.getsource(svc.submit_calculator_generation)
    for forbidden in ("approve_calculator_review", "review_approval_store",
                      "deploy_calculator", "github_deployer", "deploy_app"):
        assert forbidden not in src
