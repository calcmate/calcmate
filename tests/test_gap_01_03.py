# -*- coding: utf-8 -*-
"""tests/test_gap_01_03.py — CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01.

GAP-01 POST /api/calculators/{slug}/status            (dashboard.py "⏸ 상태토글")
GAP-03 POST /api/sites/rebuild                         (dashboard.py "⚙️ Build" 전체 재빌드)
GAP-02 POST /api/calculators/{slug}/delete/{prepare,confirm} (dashboard.py "🗑 삭제")

계산기 저장소/Registry는 메모리 fake, 삭제는 fake delete_app, 재빌드 subprocess는 fake runner,
_site/lock은 tmp_path다 — 운영 DB/Registry/_site, WP/GitHub/Telegram에 닿지 않는다.
"""
import copy
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "gap-01-03-viewer-token"
ADMIN_TOKEN = "gap-01-03-admin-token"
_ROOT = Path(__file__).resolve().parent.parent
_REAL_SITE = _ROOT / "data" / "workspace" / "_site"


class FakeRepo:
    def __init__(self, rows):
        self.rows = {r["slug"]: dict(r) for r in rows}
        self.updates = []

    def get_by_slug(self, slug):
        r = self.rows.get(slug)
        return dict(r) if r else None

    def get_all(self):
        return [dict(r) for r in self.rows.values()]

    def update(self, calc_id, data):
        self.updates.append((calc_id, dict(data)))
        for r in self.rows.values():
            if r["id"] == calc_id:
                r.update(data)
                r["updated_at"] = "2026-10-03T00:00:00"

    def delete(self, calc_id):
        self.rows = {s: r for s, r in self.rows.items() if r["id"] != calc_id}


ROWS = [
    {"id": "c1", "slug": "af-ready", "name": "AF 준비", "status": "active", "formula": "a*b",
     "article_content": "본문", "published_url": "", "template_id": "t1", "updated_at": "old"},
    {"id": "c2", "slug": "af-other", "name": "AF 다른", "status": "inactive", "formula": "a+b",
     "article_content": "", "published_url": "", "template_id": "t2", "updated_at": "old"},
    {"id": "c3", "slug": "golden-one", "name": "기본", "status": "active", "formula": "x",
     "article_content": "", "published_url": "https://calcmate.kr/golden-one/", "updated_at": "old"},
    {"id": "c4", "slug": "af-hold", "name": "보류", "status": "active", "formula": "y",
     "article_content": "", "published_url": "", "updated_at": "old"},
]
REG = {
    "af-ready": {"source": "app_factory", "status": "READY", "category": "x"},
    "af-other": {"source": "app_factory", "status": "READY", "category": "x"},
    "golden-one": {"source": "manual", "status": "active"},
    "af-hold": {"source": "app_factory", "status": "HOLD"},
}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    from api.services import calculator_service as CS
    from api.services import site_rebuild_service as RB
    from modules import app_factory as AF

    repo = FakeRepo(ROWS)
    reg = copy.deepcopy(REG)
    cfg = {"SITE_URL": "https://calcmate.kr"}
    monkeypatch.setattr(CS, "_repo_and_cfg", lambda: (repo, dict(cfg)))
    monkeypatch.setattr(CS, "_registry", lambda: dict(reg))
    calls = {"delete_app": [], "runner": [], "external": []}

    def fake_delete_app(c, slug):
        calls["delete_app"].append(slug)
        row = repo.get_by_slug(slug)
        if not row:
            return False, "없음"
        repo.delete(row["id"])
        reg.pop(slug, None)
        return True, "삭제"
    monkeypatch.setattr(AF, "delete_app", fake_delete_app)

    # 외부 호출 감시 — 하나라도 불리면 테스트 실패
    def _ext(name):
        def f(*a, **k):
            calls["external"].append(name)
            raise AssertionError(f"external call: {name}")
        return f
    import requests
    from modules import telegram_ops, github_deployer
    monkeypatch.setattr(requests.Session, "request", _ext("requests"))
    monkeypatch.setattr(telegram_ops, "notify_level", _ext("telegram"))
    monkeypatch.setattr(github_deployer, "deploy_app", _ext("github.deploy_app"))
    monkeypatch.setattr(github_deployer, "deploy_site_pages", _ext("github.deploy_site_pages"))

    monkeypatch.setattr(RB, "_ROOT", tmp_path)
    monkeypatch.setattr(RB, "_runner", _ext("runner-not-configured"))
    import modules.review_center as RC
    monkeypatch.setattr(RC, "pre_build_qa", lambda calc, cfg, prev_files=None: [
        {"step": 1, "label": "수식", "passed": True, "skipped": False, "detail": "ok"}])

    with CS._delete_lock:
        CS._delete_tokens.clear()
    clear_audit_events()
    yield {"repo": repo, "reg": reg, "calls": calls, "tmp": tmp_path, "CS": CS, "RB": RB}
    clear_audit_events()


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(token=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _audit():
    from api.auth.service import get_audit_events
    return get_audit_events()


# ══════════════════════════════════════════════════════════════════════════
# GAP-01 상태토글
# ══════════════════════════════════════════════════════════════════════════

def test_status_active_to_inactive(env):
    r = _client().post("/api/calculators/af-ready/status", json={"status": "inactive"}, headers=_h())
    assert r.status_code == 200 and r.json()["success"] is True
    assert r.json()["data"] == {"ok": True, "slug": "af-ready", "status": "inactive", "previous": "active"}
    assert env["repo"].rows["af-ready"]["status"] == "inactive"


def test_status_inactive_to_active(env):
    r = _client().post("/api/calculators/af-other/status", json={"status": "active"}, headers=_h())
    assert r.json()["data"]["status"] == "active"
    assert env["repo"].rows["af-other"]["status"] == "active"


def test_status_only_status_field_changes(env):
    before = dict(env["repo"].rows["af-ready"])
    _client().post("/api/calculators/af-ready/status", json={"status": "inactive"}, headers=_h())
    after = env["repo"].rows["af-ready"]
    assert env["repo"].updates == [("c1", {"status": "inactive"})]
    changed = {k for k in after if after.get(k) != before.get(k)}
    assert changed == {"status", "updated_at"}
    # 다른 계산기 무변경
    assert env["repo"].rows["af-other"] == {**ROWS[1]}


@pytest.mark.parametrize("bad", ["ACTIVE", "deleted", "hold", " active"])
def test_status_invalid_value(env, bad):
    r = _client().post("/api/calculators/af-ready/status", json={"status": bad}, headers=_h())
    assert r.status_code == 200 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert env["repo"].updates == []


def test_status_invalid_slug(env):
    r = _client().post("/api/calculators/Bad_Slug!/status", json={"status": "active"}, headers=_h())
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = _client().post("/api/calculators/no-such-calc/status", json={"status": "active"}, headers=_h())
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert env["repo"].updates == []


def test_status_field_injection_rejected(env):
    r = _client().post("/api/calculators/af-ready/status",
                       json={"status": "inactive", "published_url": "https://evil", "formula": "1"}, headers=_h())
    assert r.status_code == 422
    assert env["repo"].updates == []
    assert env["repo"].rows["af-ready"]["published_url"] == ""


def test_status_auth(env):
    c = _client()
    assert c.post("/api/calculators/af-ready/status", json={"status": "inactive"}).status_code == 401
    assert c.post("/api/calculators/af-ready/status", json={"status": "inactive"},
                  headers=_h(VIEWER_TOKEN)).status_code == 403
    assert env["repo"].updates == []


def test_status_audit(env):
    _client().post("/api/calculators/af-ready/status", json={"status": "inactive"}, headers=_h())
    ev = [e for e in _audit() if e.action == "calculator_status_set"]
    assert len(ev) == 1 and ev[0].resource_id == "af-ready" and ev[0].result == "success"


def test_status_unexpected_error_is_500_without_leak(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("SECRET-DB-DETAIL")
    monkeypatch.setattr(env["repo"], "update", boom)
    r = _client().post("/api/calculators/af-ready/status", json={"status": "inactive"}, headers=_h())
    assert r.status_code == 500 and "SECRET-DB-DETAIL" not in r.text


# ══════════════════════════════════════════════════════════════════════════
# GAP-03 전체 정적 사이트 재빌드
# ══════════════════════════════════════════════════════════════════════════

def _site(env):
    return env["tmp"] / "data" / "workspace" / "_site"


def _good_runner(env, skip=(), error=(), rc=0, write_pages=True):
    from api.services.site_rebuild_service import REQUIRED_OUTPUTS

    def run(root, timeout):
        env["calls"]["runner"].append((root, timeout))
        site = _site(env)
        lines = []
        if write_pages:
            for rel in REQUIRED_OUTPUTS:
                p = site / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                body = "<urlset>https://calcmate.kr/af-ready/</urlset>" if rel == "sitemap.xml" else "x"
                p.write_text(body, encoding="utf-8")
                lines.append(f"  [OK] {rel}")
        for slug in ("af-ready", "af-other", "golden-one"):
            if slug in skip:
                lines.append(f"  [SKIP] {slug} — 사유")
                continue
            if slug in error:
                lines.append(f"  [ERROR] {slug}: SECRET-TRACE token=abc")
                continue
            d = site / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text("<html></html>", encoding="utf-8")
            lines.append(f"  [OK] {slug}")
        lines.append("  [SKIP] af-hold — HOLD 상태")
        return subprocess.CompletedProcess(["x"], rc, stdout="\n".join(lines), stderr="SECRET-STDERR")
    return run


def test_rebuild_admin_success(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    assert r.status_code == 200 and r.json()["success"] is True
    d = r.json()["data"]
    assert d["ok"] is True and d["stage"] == "done" and d["deployed"] is False
    assert d["validation"]["required_missing"] == [] and d["validation"]["calculators_missing"] == []
    assert d["validation"]["calculators_expected"] == 3          # HOLD 제외
    assert d["validation"]["target_index"] and d["validation"]["target_in_sitemap"]
    assert d["summary"]["error_count"] == 0 and d["summary"]["skipped"] == ["af-hold"]
    assert any("git push" in s for s in d["manual_deploy_steps"])
    assert env["calls"]["runner"] == [(env["tmp"], 180)]
    assert "SECRET-STDERR" not in r.text
    assert not (env["tmp"] / "data" / "schedule" / "wp_blog_deploy.lock").exists()   # lock 해제
    ev = [e for e in _audit() if e.action == "site_rebuild"]
    assert ev and ev[0].result == "success"


def test_rebuild_auth(env):
    c = _client()
    assert c.post("/api/sites/rebuild", json={"slug": "af-ready"}).status_code == 401
    assert c.post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h(VIEWER_TOKEN)).status_code == 403
    assert env["calls"]["runner"] == []


def test_rebuild_requires_ready_app_factory(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    for slug in ("af-hold", "golden-one"):
        r = _client().post("/api/sites/rebuild", json={"slug": slug}, headers=_h())
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _client().post("/api/sites/rebuild", json={"slug": "nope-x"}, headers=_h()).json()["error"]["code"] == "NOT_FOUND"
    assert env["calls"]["runner"] == []


def test_rebuild_qa_failure_blocks(env, monkeypatch):
    import modules.review_center as RC
    monkeypatch.setattr(RC, "pre_build_qa", lambda calc, cfg, prev_files=None: [
        {"step": 3, "label": "스모크", "passed": False, "skipped": False, "detail": "실패"}])
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    d = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h()).json()["data"]
    assert d["ok"] is False and d["stage"] == "qa"
    assert env["calls"]["runner"] == []


def test_rebuild_lock_conflict_file_lock(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    lock = env["tmp"] / "data" / "schedule" / "wp_blog_deploy.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held", encoding="utf-8")
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    assert r.json()["error"]["code"] == "LOCK_CONFLICT"
    assert env["calls"]["runner"] == [] and lock.exists()


def test_rebuild_lock_conflict_in_process(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    assert env["RB"]._proc_lock.acquire(blocking=False)
    try:
        r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    finally:
        env["RB"]._proc_lock.release()
    assert r.json()["error"]["code"] == "LOCK_CONFLICT"
    assert env["calls"]["runner"] == []


def test_rebuild_timeout(env, monkeypatch):
    def slow(root, timeout):
        raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
    monkeypatch.setattr(env["RB"], "_runner", slow)
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    assert r.status_code == 200 and r.json()["error"]["code"] == "TIMEOUT"
    assert not (env["tmp"] / "data" / "schedule" / "wp_blog_deploy.lock").exists()
    assert env["RB"]._proc_lock.acquire(blocking=False)
    env["RB"]._proc_lock.release()


def test_rebuild_script_failure(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env, rc=1))
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    d = r.json()["data"]
    assert d["ok"] is False and d["stage"] == "build" and d["returncode"] == 1
    assert "SECRET-STDERR" not in r.text


def test_rebuild_output_validation_failure(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env, write_pages=False))
    d = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h()).json()["data"]
    assert d["ok"] is False and d["stage"] == "validation"
    assert "sitemap.xml" in d["validation"]["required_missing"]


def test_rebuild_missing_calculator_and_error_lines(env, monkeypatch):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env, error=("af-other",)))
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    d = r.json()["data"]
    assert d["ok"] is False and d["stage"] == "validation"
    assert d["validation"]["calculators_missing"] == ["af-other"]
    assert d["summary"]["errors"] == ["af-other"]
    assert "SECRET-TRACE" not in r.text and "token=abc" not in r.text


def test_rebuild_stale_required_page_fails(env, monkeypatch):
    import os
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    run = env["RB"]._runner

    def run_then_age(root, timeout):
        res = run(root, timeout)
        p = _site(env) / "robots.txt"
        os.utime(p, (1_000_000, 1_000_000))
        return res
    monkeypatch.setattr(env["RB"], "_runner", run_then_age)
    d = _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h()).json()["data"]
    assert d["ok"] is False and d["validation"]["required_stale"] == ["robots.txt"]


@pytest.mark.parametrize("slug", ["af-ready; rm -rf /", "../af-ready", "af-ready && calc", "$(whoami)", "AF-READY"])
def test_rebuild_slug_injection_rejected(env, monkeypatch, slug):
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    r = _client().post("/api/sites/rebuild", json={"slug": slug}, headers=_h())
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert env["calls"]["runner"] == []


def test_rebuild_default_runner_is_fixed_command(env, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    monkeypatch.setattr(env["RB"].subprocess, "run", fake_run)
    env["RB"]._default_runner(env["tmp"], 180)
    assert seen["argv"] == [sys.executable, str(env["tmp"] / "scripts" / "_rebuild_site.py")]
    assert seen["kw"]["shell"] is False and seen["kw"]["timeout"] == 180
    assert seen["kw"]["cwd"] == str(env["tmp"])


def test_rebuild_extra_field_rejected(env):
    r = _client().post("/api/sites/rebuild", json={"slug": "af-ready", "cmd": "dir"}, headers=_h())
    assert r.status_code == 422


def test_rebuild_separate_from_individual_build(env, monkeypatch):
    CS = env["CS"]
    built = []
    monkeypatch.setattr(CS, "build_calculator", lambda slug: built.append(slug) or {"ok": True, "slug": slug})
    monkeypatch.setattr(env["RB"], "_runner", _good_runner(env))
    r = _client().post("/api/calculators/af-ready/build", headers=_h())
    assert r.json()["data"] == {"ok": True, "slug": "af-ready"}
    assert env["calls"]["runner"] == []                      # 개별 build는 전체 재빌드를 부르지 않음
    _client().post("/api/sites/rebuild", json={"slug": "af-ready"}, headers=_h())
    assert built == ["af-ready"]                             # 전체 재빌드는 개별 build를 부르지 않음


# ══════════════════════════════════════════════════════════════════════════
# GAP-02 계산기 삭제
# ══════════════════════════════════════════════════════════════════════════

def _prepare(slug="af-ready", token=ADMIN_TOKEN):
    return _client().post(f"/api/calculators/{slug}/delete/prepare", headers=_h(token))


def _confirm(slug, tok, confirm_slug=None, token=ADMIN_TOKEN):
    return _client().post(f"/api/calculators/{slug}/delete/confirm",
                          json={"token": tok, "confirm_slug": confirm_slug or slug}, headers=_h(token))


def _site_fingerprint():
    if not _REAL_SITE.exists():
        return None
    return sorted((str(p.relative_to(_REAL_SITE)), p.stat().st_mtime) for p in _REAL_SITE.iterdir())


def test_delete_two_step_success(env):
    before_site = _site_fingerprint()
    p = _prepare()
    d = p.json()["data"]
    assert d["slug"] == "af-ready" and d["name"] == "AF 준비" and d["token"]
    assert "data/workspace/_site" in d["not_touched"]
    assert env["calls"]["delete_app"] == []                  # prepare만으로는 삭제 안 됨
    r = _confirm("af-ready", d["token"])
    assert r.json()["success"] is True
    assert r.json()["data"] == {"ok": True, "slug": "af-ready", "calc_id": "c1", "deleted": True,
                                "db_removed": True, "registry_removed": True}
    assert env["calls"]["delete_app"] == ["af-ready"]
    assert "af-ready" not in env["repo"].rows and "af-ready" not in env["reg"]
    # 다른 계산기 영향 없음
    assert set(env["repo"].rows) == {"af-other", "golden-one", "af-hold"}
    assert env["repo"].rows["af-other"] == ROWS[1]
    assert _site_fingerprint() == before_site
    assert env["calls"]["external"] == []
    acts = [(e.action, e.resource_id, e.result) for e in _audit()]
    assert ("calculator_delete", "af-ready", "success") in acts
    assert all(e.timestamp and e.actor_id for e in _audit())


def test_delete_auth(env):
    c = _client()
    assert c.post("/api/calculators/af-ready/delete/prepare").status_code == 401
    assert c.post("/api/calculators/af-ready/delete/prepare", headers=_h(VIEWER_TOKEN)).status_code == 403
    tok = _prepare().json()["data"]["token"]
    assert c.post("/api/calculators/af-ready/delete/confirm",
                  json={"token": tok, "confirm_slug": "af-ready"}).status_code == 401
    assert _confirm("af-ready", tok, token=VIEWER_TOKEN).status_code == 403
    assert env["calls"]["delete_app"] == []


def test_delete_invalid_slug(env):
    assert _prepare("Bad_Slug").json()["error"]["code"] == "VALIDATION_ERROR"
    assert _prepare("no-such-x").json()["error"]["code"] == "NOT_FOUND"
    assert _confirm("Bad_Slug", "t").json()["error"]["code"] == "VALIDATION_ERROR"


def test_delete_non_app_factory_forbidden(env):
    r = _prepare("golden-one")
    assert r.json()["error"]["code"] == "DELETE_FORBIDDEN"
    assert env["calls"]["delete_app"] == [] and "golden-one" in env["repo"].rows


def test_delete_without_confirmation(env):
    r = _client().post("/api/calculators/af-ready/delete/confirm", json={}, headers=_h())
    assert r.status_code == 422
    r = _client().post("/api/calculators/af-ready/delete/confirm", json={"confirm": True}, headers=_h())
    assert r.status_code == 422
    assert env["calls"]["delete_app"] == []


def test_delete_wrong_confirmation(env):
    tok = _prepare().json()["data"]["token"]
    assert _confirm("af-ready", "forged-token").json()["error"]["code"] == "CONFIRMATION_INVALID"
    # slug 재입력 불일치 → 거부 + 토큰 폐기(1회용)
    assert _confirm("af-ready", tok, confirm_slug="af-other").json()["error"]["code"] == "CONFIRMATION_INVALID"
    assert _confirm("af-ready", tok).json()["error"]["code"] == "CONFIRMATION_INVALID"
    # 다른 계산기 토큰으로 삭제 불가
    tok2 = _prepare("af-other").json()["data"]["token"]
    assert _confirm("af-ready", tok2).json()["error"]["code"] == "CONFIRMATION_INVALID"
    assert env["calls"]["delete_app"] == [] and "af-ready" in env["repo"].rows
    assert ("calculator_delete", "af-ready", "blocked") in [(e.action, e.resource_id, e.result) for e in _audit()]


def test_delete_expired_token(env, monkeypatch):
    monkeypatch.setattr(env["CS"], "DELETE_TOKEN_TTL_SECONDS", 0)
    tok = _prepare().json()["data"]["token"]
    assert _confirm("af-ready", tok).json()["error"]["code"] == "CONFIRMATION_INVALID"
    assert env["calls"]["delete_app"] == []


def test_delete_target_changed_after_prepare(env):
    tok = _prepare().json()["data"]["token"]
    env["repo"].rows["af-ready"]["id"] = "c1-replaced"
    assert _confirm("af-ready", tok).json()["error"]["code"] == "CONFIRMATION_INVALID"
    assert env["calls"]["delete_app"] == []


def test_delete_duplicate_is_safe(env):
    tok = _prepare().json()["data"]["token"]
    assert _confirm("af-ready", tok).json()["success"] is True
    assert _confirm("af-ready", tok).json()["error"]["code"] == "CONFIRMATION_INVALID"
    assert _prepare().json()["error"]["code"] == "NOT_FOUND"
    assert env["calls"]["delete_app"] == ["af-ready"]


def test_delete_failure_keeps_data_and_hides_detail(env, monkeypatch):
    from modules import app_factory as AF
    monkeypatch.setattr(AF, "delete_app", lambda c, s: (False, "calculators 삭제 실패: SECRET-SQL"))
    tok = _prepare().json()["data"]["token"]
    r = _confirm("af-ready", tok)
    assert r.json()["error"]["code"] == "DELETE_FAILED" and "SECRET-SQL" not in r.text
    assert "af-ready" in env["repo"].rows


def test_delete_verify_failure(env, monkeypatch):
    from modules import app_factory as AF
    repo = env["repo"]

    def db_only(c, slug):             # Registry 정리 실패를 흉내(원본은 경고만 남기고 True 반환)
        repo.delete(repo.get_by_slug(slug)["id"])
        return True, "ok"
    monkeypatch.setattr(AF, "delete_app", db_only)
    tok = _prepare().json()["data"]["token"]
    r = _confirm("af-ready", tok)
    assert r.json()["error"]["code"] == "DELETE_VERIFY_FAILED"
    assert ("calculator_delete", "af-ready", "failed") in [(e.action, e.resource_id, e.result) for e in _audit()]


def test_delete_audit_has_no_token(env):
    tok = _prepare().json()["data"]["token"]
    _confirm("af-ready", tok)
    for e in _audit():
        assert tok not in repr(e)
