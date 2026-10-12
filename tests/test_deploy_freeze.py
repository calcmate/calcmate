# -*- coding: utf-8 -*-
"""tests/test_deploy_freeze.py — 계산기 배포 동결(CALCMATE-PUBLIC-SAFETY-DEPLOY-FREEZE).

B2: modules.deploy_freeze 표식 파일이 있으면 P1(deploy_calculator)·P2(rebuild_site)·
    P7(run_calc_webapp_once)가 어떤 조회·생성·쓰기보다 먼저 차단된다.
B3: scripts/deploy_freeze_guard.py가 커밋된 _site 계산기 파일을 기준선과 비교해
    추가·삭제·변경을 실패로 처리하고, 기준선 누락·손상도 실패로 처리한다.

표식 파일은 CALCMATE_DEPLOY_FREEZE_MARKER로 tmp_path에만 만든다 — 실제 저장소의
data/workspace/DEPLOY_FREEZE는 건드리지 않는다. 가드 테스트는 git 객체를 읽기만 한다.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from modules import deploy_freeze

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "deploy_freeze_guard.py"
BASELINE = ROOT / ".github" / "deploy_freeze_baseline.json"


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    marker = tmp_path / "DEPLOY_FREEZE"
    marker.write_text("frozen\n", encoding="utf-8")
    monkeypatch.setenv(deploy_freeze.MARKER_ENV, str(marker))
    return marker


@pytest.fixture
def unfrozen(tmp_path, monkeypatch):
    monkeypatch.setenv(deploy_freeze.MARKER_ENV, str(tmp_path / "absent"))


def _boom(*_a, **_k):
    raise AssertionError("동결 중에는 호출되면 안 된다")


# ── B2: 플래그 ─────────────────────────────────────────────────────────────
def test_is_frozen_follows_marker(frozen, monkeypatch, tmp_path):
    assert deploy_freeze.is_frozen() is True
    monkeypatch.setenv(deploy_freeze.MARKER_ENV, str(tmp_path / "absent"))
    assert deploy_freeze.is_frozen() is False


def test_is_frozen_fail_closed_on_error(monkeypatch):
    def _raise():
        raise PermissionError("denied")
    monkeypatch.setattr(deploy_freeze, "marker_path", _raise)
    assert deploy_freeze.is_frozen() is True


def test_default_marker_is_gitignored_local_state():
    assert deploy_freeze.DEFAULT_MARKER == ROOT / "data" / "workspace" / "DEPLOY_FREEZE"
    r = subprocess.run(["git", "check-ignore", "-q", "data/workspace/DEPLOY_FREEZE"], cwd=ROOT)
    assert r.returncode == 0


# ── B2: 차단 지점 ──────────────────────────────────────────────────────────
def test_deploy_calculator_blocked_before_any_lookup(frozen, monkeypatch):
    from api.services import calculator_service as svc
    monkeypatch.setattr(svc, "_get_calc_or_raise", _boom)
    monkeypatch.setattr(svc, "build_calculator", _boom)
    r = svc.deploy_calculator("bmi-calculator")
    assert r["ok"] is False and r["stage"] == "freeze"
    assert r["published_url"] is None and r["build_result"] is None
    assert "동결" in r["blocked_reason"]


def test_rebuild_site_blocked_before_any_lookup(frozen, monkeypatch):
    from api.services import calculator_service as CS
    from api.services import site_rebuild_service as svc
    monkeypatch.setattr(CS, "_get_calc_or_raise", _boom)
    monkeypatch.setattr(svc, "_runner", _boom)
    with pytest.raises(svc.SiteRebuildError) as e:
        svc.rebuild_site("bmi-calculator")
    assert e.value.code == "DEPLOY_FROZEN"


def test_calc_webapp_once_does_nothing_when_frozen(frozen, monkeypatch):
    from modules import calc_webapp_pipeline as pipeline
    import modules.app_generator as AG
    import modules.site_snapshot as SS
    monkeypatch.setattr(AG, "generate_calculator", _boom)
    monkeypatch.setattr(SS, "write_site_snapshot", _boom)
    cfg = {"CALC_WEBAPP_SCHEDULE": {"mode": "qa_deploy", "targets": ["calc_1"]}}
    assert pipeline.run_calc_webapp_once(cfg) == {"produced": 0, "reason": "deploy_freeze"}


def test_deploy_calculator_not_frozen_reaches_existing_gates(unfrozen, monkeypatch):
    from api.services import calculator_service as svc

    class _NotFound(Exception):
        pass
    def _lookup(_slug):
        raise _NotFound()
    monkeypatch.setattr(svc, "_get_calc_or_raise", _lookup)
    with pytest.raises(_NotFound):
        svc.deploy_calculator("bmi-calculator")


# ── B3: CI 가드 ────────────────────────────────────────────────────────────
def _guard(*args):
    # -X utf8: Windows 파이프의 기본 인코딩(cp949) 대신 UTF-8로 출력(CI의 Linux와 동일 조건).
    return subprocess.run([sys.executable, "-X", "utf8", "-B", str(GUARD), *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def _baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_repository_baseline_matches_head():
    r = _guard("check", "--baseline", str(BASELINE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FREEZE_GUARD_OK" in r.stdout


def test_baseline_shape():
    b = _baseline()
    assert b["schema"] == 1 and len(b["commit"]) == 40
    blobs = b["calculator_blobs"]
    assert blobs and all(len(v) == 40 for v in blobs.values())
    # 공용 사이트 파일은 기준선에 들어가지 않는다(블로그 index/sitemap 갱신은 계속 배포 가능).
    assert not any(p.split("/", 1)[0] in {"index.html", "sitemap.xml", "about", "CNAME"} for p in blobs)


@pytest.mark.parametrize("mutate, label", [
    (lambda b: b.__setitem__(sorted(b)[0], "0" * 40), "changed"),
    (lambda b: b.__setitem__("ghost-calculator/index.html", "1" * 40), "removed"),
    (lambda b: b.pop(sorted(b)[0]), "added"),
])
def test_guard_detects_calculator_drift(tmp_path, mutate, label):
    b = _baseline()
    mutate(b["calculator_blobs"])
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    r = _guard("check", "--baseline", str(p))
    assert r.returncode == 1, r.stdout
    assert "FREEZE_GUARD_FAIL" in r.stdout and f"{label}:" in r.stdout


@pytest.mark.parametrize("content", [None, "not json", json.dumps({"calculator_blobs": {}})])
def test_guard_fails_closed_on_bad_baseline(tmp_path, content):
    p = tmp_path / "baseline.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    r = _guard("check", "--baseline", str(p))
    assert r.returncode == 2
    assert "FREEZE_GUARD_FAIL" in r.stdout


def test_workflow_runs_guard_before_upload_and_drops_modules_trigger():
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "'modules/**'" not in wf
    guard_at = wf.index("scripts/deploy_freeze_guard.py check --baseline .github/deploy_freeze_baseline.json")
    assert guard_at < wf.index("actions/upload-pages-artifact")
    assert guard_at < wf.index("actions/deploy-pages")
