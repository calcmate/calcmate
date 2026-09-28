"""CALCMATE-CALCULATOR-AUTO-BUILD-E2E-01 — Mode A 자동 Build 격리 E2E.

실제 서비스 경로(POST /api/calculators/generate → GenerationJobStore → _target →
Formula/HTML·JS Gate → 실제 save_app → 실제 build_calculator)를 그대로 실행한다.
AI 생성(generate_app)만 고정 결과로 대체한다.

격리: DB(SQLite)·registry_auto·docs/registry·calculator_index·contract schema·
pending_sync·_site를 전부 tmp_path로 돌린다. 네트워크는 socket 수준에서 차단하고
(AI/Sheets/WP/GitHub 호출 불가), Approval/Deploy 함수는 호출 카운터로 감시한다.
운영 파일은 읽기(legal_master 등 SSOT)만 하며 쓰지 않는다.
"""
import socket
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.services.calculator_service as svc
import modules.app_factory as af
import modules.registry_loader as rl
import adapters.db.dual_adapter as dual

SLUG = "auto-build-e2e-test"
NAME = "자동빌드 E2E 테스트 계산기"
HTML = ('<!DOCTYPE html><html><body><input id="a" type="number">'
        '<button onclick="calc()">계산</button><div id="result"></div>'
        '<script>function calc(){document.getElementById("result").textContent='
        'Number(document.getElementById("a").value)*2;}</script></body></html>')


def _fake_app(name):
    return {
        "name": name, "category": "노무/급여", "calculator_type": "general",
        "description": "E2E 격리 테스트용", "tier": 2,
        "formula": "a * 2",
        "input_schema": {"a": "number"}, "output_schema": {"result": "number"},
        "labels": {"a": "입력값", "result": "결과"},
        "html": HTML, "css": "", "js": "",
        "seo_title": "자동빌드 E2E", "seo_desc": "E2E", "faq": [],
        "_formula_valid": True, "_formula_msg": "OK",
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """모든 쓰기 대상을 tmp_path로 격리하고, 호출 순서/외부 접근을 기록한다."""
    root = tmp_path / "ws"
    reg_dir = root / "docs" / "registry"
    reg_dir.mkdir(parents=True)
    cfg = {"DB_ADAPTER": "sqlite", "SQLITE_PATH": "e2e.db", "_root": str(root),
           "SITE_URL": "https://calcmate.kr"}

    # config: _target(함수 내부 import)와 build 경로(svc 모듈 전역) 모두 격리 cfg
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: dict(cfg))
    monkeypatch.setattr(svc, "load_config", lambda *a, **k: dict(cfg))

    # registry / index / contract / pending_sync 경로 격리
    monkeypatch.setattr(af, "_REG_DIR", reg_dir)
    monkeypatch.setattr(af, "_SCHEMA_DIR", root / "docs" / "contract_schema")
    monkeypatch.setattr(af, "_CALC_INDEX_PATH", root / "docs" / "calculator_index.json")
    monkeypatch.setattr(rl, "_REG_DIR", reg_dir)
    monkeypatch.setattr(rl, "_AUTO_PATH", root / "docs" / "registry_auto.yaml")
    monkeypatch.setattr(dual, "_SYNC_QUEUE_PATH", root / "data" / "sync" / "pending_sync.json")
    rl.invalidate()

    # 네트워크 차단(AI/Sheets/WP/GitHub/Pages 모두 socket 경유). Windows asyncio(TestClient)가
    # 내부적으로 쓰는 loopback socketpair만 허용하고, loopback이라도 서비스 포트(로컬 WP·API
    # 서버 등)로의 연결은 차단한다.
    net = []
    real_connect = socket.socket.connect
    service_ports = {80, 443, 8000, 5173, 8080, 8501}

    def _guard(self, address, *a, **k):
        host, port = (address[0], address[1]) if isinstance(address, tuple) else (str(address), None)
        if host in ("127.0.0.1", "::1", "localhost") and port not in service_ports:
            return real_connect(self, address, *a, **k)
        net.append(address)
        raise AssertionError(f"외부 네트워크 접근 금지: {address}")
    monkeypatch.setattr(socket.socket, "connect", _guard)

    # AI 생성만 고정 결과로 대체
    ai_calls = []

    def _fake_generate(cfg_, name, category="", desc="", tier=2, **k):
        ai_calls.append(name)
        return _fake_app(name)
    monkeypatch.setattr(af, "generate_app", _fake_generate)

    # 실제 save_app/build_calculator를 감싸 호출 순서만 기록
    order = []
    real_save, real_build = af.save_app, svc.build_calculator

    def _save(*a, **k):
        order.append("save")
        return real_save(*a, **k)

    def _build(slug):
        order.append("build")
        return real_build(slug)
    monkeypatch.setattr(af, "save_app", _save)
    monkeypatch.setattr(svc, "build_calculator", _build)

    # Approval/Deploy 감시(호출되면 카운트)
    forbidden = {}
    import modules.github_deployer as gh
    targets = [(svc, "approve_calculator_review"), (svc, "deploy_calculator"),
               (gh, "deploy_app"), (gh, "_put_file")]
    try:  # review_approval_store가 있는 환경이면 함께 감시(없으면 호출 자체가 불가능)
        import api.services.review_approval_store as ras
        targets.append((ras, "get_review_approval_store"))
    except ImportError:
        pass
    for mod, attr in targets:
        key = f"{mod.__name__}.{attr}"
        forbidden[key] = 0

        def _spy(*a, _k=key, **k):
            forbidden[_k] += 1
            raise AssertionError(f"{_k} must not be called")
        monkeypatch.setattr(mod, attr, _spy)

    import api.services.generation_job_store as js
    js._store = None
    yield {"root": root, "cfg": cfg, "order": order, "ai": ai_calls, "net": net,
           "forbidden": forbidden}
    if js._store is not None:
        js._store.shutdown(wait=True)
        js._store = None
    rl.invalidate()


def _submit_via_http_and_wait(name=NAME, slug=SLUG):
    from api.main import app
    client = TestClient(app)
    r = client.post("/api/calculators/generate",
                    json={"name": name, "category": "노무/급여", "description": "E2E", "tier": 2, "slug": slug})
    assert r.status_code == 200, r.text
    job_id = r.json()["data"]["job_id"]
    for _ in range(600):
        j = client.get(f"/api/calculators/generate/{job_id}").json()["data"]
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture(autouse=True)
def _local_admin(monkeypatch):
    # 인증은 기존 LOCAL_MODE 경계를 그대로 사용(로컬 admin) — 서버 기동 없이 TestClient만.
    monkeypatch.setenv("CALCMATE_DASHBOARD_LOCAL_MODE", "1")


def _assert_clean_side(env):
    assert env["ai"] == [NAME], "AI 생성은 mock 1회만"
    assert env["net"] == [], "외부 네트워크 접근 0"
    assert all(v == 0 for v in env["forbidden"].values()), env["forbidden"]


def test_e2e_01_generate_save_autobuild_succeeds(env):
    job = _submit_via_http_and_wait()
    assert job["status"] == "succeeded", job
    assert env["order"] == ["save", "build"], "save 성공 후 build 정확히 1회"
    r = job["result"]
    assert r["slug"] == SLUG and r["name"] == NAME
    assert r["message"].startswith("✅") and "Build" in r["message"]   # 기존 저장 메시지 + Build 요약
    b = r["build"]
    assert b["ok"] is True, b
    assert b["stage"] == "build"
    site = env["root"] / "data" / "workspace" / "_site" / SLUG
    assert b["snapshot_dir"] and Path(b["snapshot_dir"]).resolve() == site.resolve()
    for fn in ("index.html", "style.css", "script.js"):
        assert (site / fn).is_file() and (site / fn).stat().st_size > 0, fn
    # 격리 저장 결과 확인
    assert (env["root"] / "e2e.db").is_file()
    assert "auto-build-e2e-test" in (env["root"] / "docs" / "registry_auto.yaml").read_text(encoding="utf-8")
    assert (env["root"] / "docs" / "registry" / "labor_af.yaml").is_file()
    _assert_clean_side(env)


def test_e2e_02_save_failure_skips_build(env, monkeypatch):
    order = env["order"]
    monkeypatch.setattr(af, "save_app", lambda *a, **k: (order.append("save"), (False, "🔒 저장 차단(E2E)"))[1])
    job = _submit_via_http_and_wait()
    assert job["status"] == "failed" and "저장 차단" in job["error"]
    assert order == ["save"], "save 실패 시 build 0회"
    assert not (env["root"] / "data" / "workspace" / "_site" / SLUG).exists()
    _assert_clean_side(env)


def test_e2e_03_build_blocked_keeps_job_succeeded(env, monkeypatch):
    # 실제 build_calculator를 그대로 쓰되, 실제 게이트(HTML/JS 완결성)가 막도록 생성 결과를 잘라낸다.
    import modules.app_generator as AG
    real_gen = AG.generate_calculator

    def _truncated(calc, cfg):
        files = real_gen(calc, cfg)
        files["index.html"] = files["index.html"][: len(files["index.html"]) // 3]
        return files
    monkeypatch.setattr(AG, "generate_calculator", _truncated)
    job = _submit_via_http_and_wait()
    assert job["status"] == "succeeded", job
    assert env["order"] == ["save", "build"]
    b = job["result"]["build"]
    assert b["ok"] is False and b["stage"] == "build" and b["snapshot_dir"] is None
    assert "Build 미완료(build)" in job["result"]["message"]
    assert not (env["root"] / "data" / "workspace" / "_site" / SLUG).exists(), "차단 시 스냅샷 미작성"
    _assert_clean_side(env)


def test_e2e_04_registry_missing_recorded_as_registry_stage(env, monkeypatch):
    # save_app이 v3 Registry(_af.yaml) 기록에 실패하는 실제 상황을 재현 — save는 성공(경고)으로 반환된다.
    def _v3_fail(*a, **k):
        raise OSError("E2E: v3 registry write failed")
    monkeypatch.setattr(af, "_write_registry_v3", _v3_fail)
    job = _submit_via_http_and_wait()
    assert job["status"] == "succeeded", job
    assert env["order"] == ["save", "build"]
    assert "v3 Registry 기록 실패" in job["result"]["message"]
    b = job["result"]["build"]
    assert b["ok"] is False and b["stage"] == "registry" and SLUG in b["message"]
    assert not (env["root"] / "data" / "workspace" / "_site" / SLUG).exists()
    _assert_clean_side(env)
