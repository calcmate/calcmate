# -*- coding: utf-8 -*-
"""tests/test_site_pages_deploy_02.py — SITE-PAGE-DEPLOYMENT-02 검증.

dashboard.py "🌐 사이트 페이지 배포"의 React/FastAPI 이관(미리보기/로컬 저장/배포)과
배포 transport 변경(GitHub Contents API → 로컬 Git 1회 commit + in-sync push)을 검증한다.

안전 설계:
- 운영 저장소/운영 _site/DB/Sheets는 건드리지 않는다. 배포 테스트는 tmp_path의 bare
  "origin" + clone 작업 repo에서만 실행한다.
- `git push`는 github_deployer._git 래퍼에서 가로채 실행하지 않는다(호출만 기록).
- GitHub API(requests, create_repo/_put_file/_enable_pages)는 호출 시 즉시 실패하도록 막는다.
- site_generator.generate_all은 고정 산출물로 대체한다(파리티 테스트만 실제 generator를
  DB/blog 어댑터를 빈 가짜로 바꿔 실행).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER = "spd02-viewer-token"
ADMIN = "spd02-admin-token"
SECRET = "ghp_SECRETTOKEN0123456789"
SITE_FILES = ("index.html", "site.css", "about/index.html", "privacy/index.html", "terms/index.html",
              "contact/index.html", "404.html", "sitemap.xml", "robots.txt")
SITE = "data/workspace/_site"


def pages(tag="new"):
    return {p: f"<!-- {tag} {p} -->" for p in SITE_FILES}


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _no_github_api(monkeypatch):
    """GitHub HTTP 호출/Contents API 경로가 실행되면 즉시 실패."""
    import requests
    from modules import github_deployer as GH

    def _boom(*a, **k):
        raise AssertionError("GitHub API must not be called")
    for name in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, name, _boom)
    for name in ("create_repo", "_put_file", "_enable_pages"):
        monkeypatch.setattr(GH, name, _boom)


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(t=ADMIN):
    return {"Authorization": f"Bearer {t}"}


def _post(path, token=ADMIN):
    return _client().post(path, headers=_h(token))


@pytest.fixture
def svc_env(monkeypatch, tmp_path):
    """서비스 cfg를 tmp 루트로, generator를 고정 산출물로 대체."""
    from api.services import site_pages_service as S
    from modules import site_generator
    state = {"pages": pages(), "raise": None, "cfg": {"_root": str(tmp_path), "SITE_URL": "https://calcmate.kr",
                                                      "SITE_NAME": "CalcMate", "GITHUB_TOKEN": SECRET}}

    def _gen(cfg):
        if state["raise"]:
            raise state["raise"]
        return dict(state["pages"])
    monkeypatch.setattr(site_generator, "generate_all", _gen)
    monkeypatch.setattr(S, "load_config", lambda *a, **k: dict(state["cfg"]))
    return state


ROUTES = ["/api/sites/pages/preview", "/api/sites/pages/save", "/api/sites/pages/deploy"]


@pytest.mark.parametrize("path", ROUTES)
def test_unauthenticated_401(path):
    assert _client().post(path).status_code == 401


@pytest.mark.parametrize("path", ROUTES)
def test_viewer_403(path, svc_env):
    assert _post(path, VIEWER).status_code == 403


# ── Generator 파리티 ────────────────────────────────────────────────────────

def test_preview_matches_generate_all_exactly(monkeypatch, tmp_path):
    """실제 generate_all(cfg)과 미리보기 결과가 같다(파일 수/이름/내용). DB·blog 어댑터는 빈 가짜."""
    import adapters.db.factory as F
    from api.services import site_pages_service as S
    from modules import site_generator

    class _EmptyDb:
        def get_all(self, *a, **k):
            return []

        def get_where(self, *a, **k):
            return []

    class _EmptyBlog:
        def list_all(self, *a, **k):
            return []
    monkeypatch.setattr(F, "get_db_adapter", lambda cfg: _EmptyDb())
    monkeypatch.setattr(F, "get_blog_article_storage_adapter", lambda cfg: _EmptyDb())
    import repositories.blog_article_repository as B
    monkeypatch.setattr(B, "BlogArticleRepository", lambda adapter: _EmptyBlog())
    cfg = {"_root": str(tmp_path), "SITE_URL": "https://example-site.kr", "SITE_NAME": "테스트사이트"}
    monkeypatch.setattr(S, "load_config", lambda *a, **k: dict(cfg))

    expected = site_generator.generate_all(dict(cfg))
    d = _post("/api/sites/pages/preview").json()["data"]
    assert d["count"] == 9 and [p["path"] for p in d["pages"]] == list(SITE_FILES)
    assert {p["path"]: p["content"] for p in d["pages"]} == expected
    by = {p["path"]: p["content"] for p in d["pages"]}
    assert "https://example-site.kr" in by["sitemap.xml"] and "https://example-site.kr" in by["robots.txt"]
    assert "테스트사이트 소개" in by["about/index.html"]          # SITE_NAME 반영(소개 페이지 제목)
    assert d["site_url"] == "https://example-site.kr/"


# ── Preview ────────────────────────────────────────────────────────────────

def test_preview_returns_9_pages_without_writes(svc_env, tmp_path):
    d = _post("/api/sites/pages/preview").json()["data"]
    assert d["count"] == 9 and {p["path"] for p in d["pages"]} == set(SITE_FILES)
    assert not (tmp_path / SITE).exists()


def test_preview_generator_failure(svc_env):
    svc_env["raise"] = RuntimeError(f"boom {SECRET}")
    r = _post("/api/sites/pages/preview")
    assert r.json()["error"]["code"] == "SITE_PAGES_BUILD_FAILED"
    assert SECRET not in r.text


def test_preview_incomplete_output_rejected(svc_env):
    svc_env["pages"] = {k: v for k, v in pages().items() if k != "robots.txt"}
    r = _post("/api/sites/pages/preview")
    assert r.json()["error"]["code"] == "SITE_PAGES_BUILD_FAILED" and "robots.txt" in r.text


def test_preview_does_not_leak_credentials(svc_env):
    r = _post("/api/sites/pages/preview")
    assert SECRET not in r.text and "GITHUB_TOKEN" not in r.text


# ── Local Save ─────────────────────────────────────────────────────────────

def test_save_writes_only_9_files_under_site(svc_env, tmp_path, monkeypatch):
    from modules import github_deployer as GH
    monkeypatch.setattr(GH, "_git", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no git on save")))
    site = tmp_path / SITE
    site.mkdir(parents=True)
    (site / "CNAME").write_text("calcmate.kr\n", encoding="utf-8")
    d = _post("/api/sites/pages/save").json()["data"]
    assert d["ok"] is True and d["count"] == 9 and d["failed"] == []
    for p in SITE_FILES:
        assert (site / p).read_text(encoding="utf-8") == pages()[p]
    assert (site / "CNAME").read_text(encoding="utf-8") == "calcmate.kr\n"
    all_files = sorted(str(f.relative_to(tmp_path)).replace("\\", "/") for f in tmp_path.rglob("*") if f.is_file())
    assert all_files == sorted([f"{SITE}/{p}" for p in SITE_FILES] + [f"{SITE}/CNAME"])


def test_save_generator_failure_writes_nothing(svc_env, tmp_path):
    svc_env["raise"] = RuntimeError("boom")
    assert _post("/api/sites/pages/save").json()["error"]["code"] == "SITE_PAGES_BUILD_FAILED"
    assert not (tmp_path / SITE).exists()


# ── Deploy (격리 git repo) ──────────────────────────────────────────────────

def _git(args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def _make_repo(tmp_path):
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "-b", "master", str(origin)], tmp_path)
    work = tmp_path / "work"
    _git(["clone", str(origin), str(work)], tmp_path)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(["config", k, v], work)
    site = work / SITE
    for p, c in pages("old").items():
        (site / p).parent.mkdir(parents=True, exist_ok=True)
        (site / p).write_text(c, encoding="utf-8")
    (site / "CNAME").write_text("calcmate.kr\n", encoding="utf-8")
    (site / "bmi-calculator").mkdir()
    (site / "bmi-calculator" / "index.html").write_text("calc", encoding="utf-8")
    (work / "modules").mkdir()
    (work / "modules" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (work / "data" / "schedule").mkdir(parents=True)
    (work / ".gitignore").write_text("data/schedule/\n", encoding="utf-8")
    _git(["add", "-A"], work)
    _git(["commit", "-q", "-m", "initial"], work)
    _git(["push", "-q", "origin", "master"], work)
    return origin, work


@pytest.fixture
def repo_env(monkeypatch, tmp_path, svc_env):
    from api.services import site_pages_service as S
    from modules import github_deployer as GH
    origin, work = _make_repo(tmp_path)
    svc_env["cfg"]["_root"] = str(work)
    pushes = []
    real = GH._git

    def _git_no_push(root, args):
        if args and args[0] == "push":
            pushes.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")
        return real(root, args)
    monkeypatch.setattr(GH, "_git", _git_no_push)
    monkeypatch.setattr(GH, "_origin_full_name", lambda root: "owner/repo")
    monkeypatch.setattr(S, "_validate_against_current", lambda cfg, p: None)
    return {"origin": origin, "work": work, "pushes": pushes}


def _log(cwd, ref="HEAD"):
    return _git(["log", "--format=%H %s", ref], cwd).stdout.split("\n")[0]


def _origin_head(origin):
    return _git(["rev-parse", "master"], origin).stdout.strip()


def test_deploy_in_sync_commits_9_files_once_and_pushes(repo_env):
    origin_before = _origin_head(repo_env["origin"])
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is True and d["committed"] is True and d["pushed"] is True and d["deployed"] is True
    assert sorted(d["files"]) == sorted(f"{SITE}/{p}" for p in SITE_FILES)
    assert d["pages_url"] == "https://calcmate.kr/"
    assert repo_env["pushes"] == [["push", "origin", "master"]]
    work = repo_env["work"]
    assert _log(work).endswith("deploy: update site pages")
    committed = set(_git(["show", "--name-only", "--format=", "HEAD"], work).stdout.split())
    assert committed == {f"{SITE}/{p}" for p in SITE_FILES}                 # Test 10
    assert f"{SITE}/CNAME" not in committed
    assert _git(["rev-list", "--count", "origin/master..HEAD"], work).stdout.strip() == "1"
    assert _origin_head(repo_env["origin"]) == origin_before                  # 실제 push 없음


def test_deploy_unrelated_dirty_files_not_staged(repo_env):
    """Test 8: modules/x.py 수정·untracked 파일이 있어도 9개 파일만 commit되고 dirty는 그대로."""
    work = repo_env["work"]
    (work / "modules" / "x.py").write_text("x = 2\n", encoding="utf-8")
    (work / "notes.txt").write_text("untracked", encoding="utf-8")
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is True
    committed = set(_git(["show", "--name-only", "--format=", "HEAD"], work).stdout.split())
    assert committed == {f"{SITE}/{p}" for p in SITE_FILES}
    st = _git(["status", "--porcelain"], work).stdout
    assert " M modules/x.py" in st and "?? notes.txt" in st


def test_deploy_local_ahead_blocked(repo_env):
    """Test 2: 로컬 commit이 push되지 않은 상태(ahead) → push/commit 없음."""
    work = repo_env["work"]
    (work / "modules" / "x.py").write_text("x = 3\n", encoding="utf-8")
    _git(["commit", "-qam", "local only"], work)
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "remote_diverged" in d["message"] and "ahead" in d["message"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head and repo_env["pushes"] == []


def _push_from_other_clone(tmp_path, origin, fname="other.txt"):
    other = tmp_path / f"other_{fname}"
    _git(["clone", str(origin), str(other)], tmp_path)
    _git(["config", "user.email", "o@example.com"], other)
    _git(["config", "user.name", "o"], other)
    (other / fname).write_text("other", encoding="utf-8")
    _git(["add", fname], other)
    _git(["commit", "-qm", "other change"], other)
    _git(["push", "-q", "origin", "master"], other)


def test_deploy_origin_ahead_blocked(repo_env, tmp_path):
    """Test 3: 원격이 앞섬(behind) → 차단. 자동 pull/rebase 없음."""
    _push_from_other_clone(tmp_path, repo_env["origin"])
    work = repo_env["work"]
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "behind" in d["message"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head and repo_env["pushes"] == []


def test_deploy_diverged_blocked(repo_env, tmp_path):
    """Test 4: 양쪽 모두 새 commit(diverged) → 차단."""
    _push_from_other_clone(tmp_path, repo_env["origin"], "theirs.txt")
    work = repo_env["work"]
    (work / "modules" / "x.py").write_text("x = 4\n", encoding="utf-8")
    _git(["commit", "-qam", "ours"], work)
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "diverged" in d["message"] and repo_env["pushes"] == []


def test_deploy_generator_failure_writes_and_commits_nothing(repo_env, svc_env):
    """Test 5."""
    svc_env["raise"] = RuntimeError("boom")
    work = repo_env["work"]
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    assert _post("/api/sites/pages/deploy").json()["error"]["code"] == "SITE_PAGES_BUILD_FAILED"
    assert (work / SITE / "index.html").read_text(encoding="utf-8") == pages("old")["index.html"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head and repo_env["pushes"] == []


def test_deploy_missing_file_blocked(repo_env, svc_env):
    """Test 6: 산출물에 파일이 빠지면 배포 금지(부분 배포 없음)."""
    svc_env["pages"] = {k: v for k, v in pages().items() if k != "about/index.html"}
    work = repo_env["work"]
    assert _post("/api/sites/pages/deploy").json()["error"]["code"] == "SITE_PAGES_BUILD_FAILED"
    assert (work / SITE / "index.html").read_text(encoding="utf-8") == pages("old")["index.html"]
    assert repo_env["pushes"] == []


@pytest.mark.parametrize("dirty", ["about/extra.html", "CNAME"])
def test_deploy_change_outside_9_files_blocked(repo_env, dirty):
    """Test 7: 사이트 공통 영역의 9개 외 변경(about/extra.html, CNAME) → 차단, CNAME 미stage."""
    work = repo_env["work"]
    (work / SITE / dirty).write_text("changed", encoding="utf-8")
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "pre_existing_dirty" in d["message"] and dirty in d["message"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head
    assert _git(["diff", "--cached", "--name-only"], work).stdout.strip() == ""
    assert repo_env["pushes"] == []


def test_deploy_calculator_dir_changes_do_not_block_and_are_not_staged(repo_env):
    work = repo_env["work"]
    (work / SITE / "bmi-calculator" / "index.html").write_text("calc changed", encoding="utf-8")
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is True
    committed = set(_git(["show", "--name-only", "--format=", "HEAD"], work).stdout.split())
    assert f"{SITE}/bmi-calculator/index.html" not in committed


def test_deploy_index_not_clean_blocked(repo_env):
    """Test 9: 이미 staged된 변경이 있으면 차단(staged 대상 검증)."""
    work = repo_env["work"]
    (work / "modules" / "x.py").write_text("x = 5\n", encoding="utf-8")
    _git(["add", "modules/x.py"], work)
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "index_not_clean" in d["message"]
    assert _git(["diff", "--cached", "--name-only"], work).stdout.strip() == "modules/x.py"
    assert repo_env["pushes"] == []


def test_deploy_no_change_is_ok_without_commit(repo_env, svc_env):
    svc_env["pages"] = pages("old")
    work = repo_env["work"]
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is True and d["committed"] is False and "변경 없음" in d["message"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head and repo_env["pushes"] == []


def test_deploy_validation_failure_writes_nothing(repo_env, monkeypatch):
    from api.services import site_pages_service as S
    monkeypatch.setattr(S, "_validate_against_current", lambda cfg, p: "golden10_missing:x")
    work = repo_env["work"]
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and d["stage"] == "validation" and "golden10_missing" in d["message"]
    assert (work / SITE / "index.html").read_text(encoding="utf-8") == pages("old")["index.html"]


def test_deploy_uses_existing_blog_deploy_validators(monkeypatch, tmp_path):
    """index/sitemap 검증은 wp_blog_deploy의 기존 validator를 현재 _site 파일 대비로 호출한다."""
    from api.services import site_pages_service as S
    from modules import wp_blog_deploy as W
    site = tmp_path / SITE
    site.mkdir(parents=True)
    (site / "index.html").write_text(pages("old")["index.html"], encoding="utf-8")
    (site / "sitemap.xml").write_text(pages("old")["sitemap.xml"], encoding="utf-8")
    calls = []
    monkeypatch.setattr(W, "validate_index_html", lambda o, n, g: calls.append(("i", o, n, g)) or (False, "grid_changed"))
    monkeypatch.setattr(W, "validate_sitemap_xml", lambda o, n, g: calls.append(("s", o, n, g)) or (True, None))
    assert S._validate_against_current({"_root": str(tmp_path)}, pages()) == "grid_changed"
    assert calls[0][1] == pages("old")["index.html"] and calls[0][2] == pages()["index.html"]
    assert calls[1][1] == pages("old")["sitemap.xml"] and len(calls[0][3]) > 0   # Golden10 slug 집합 전달


def test_deploy_lock_busy_returns_lock_conflict(repo_env, svc_env):
    from modules import wp_blog_deploy as W
    cfg = dict(svc_env["cfg"])
    assert W._acquire_lock(cfg) is True
    try:
        r = _post("/api/sites/pages/deploy")
        assert r.json()["error"]["code"] == "LOCK_CONFLICT"
    finally:
        W._release_lock(cfg)
    assert repo_env["pushes"] == []


def test_deploy_without_token_skips(repo_env, svc_env):
    svc_env["cfg"].pop("GITHUB_TOKEN")
    work = repo_env["work"]
    head = _git(["rev-parse", "HEAD"], work).stdout.strip()
    import os
    os.environ.pop("GITHUB_TOKEN", None)
    d = _post("/api/sites/pages/deploy").json()["data"]
    assert d["ok"] is False and "GITHUB_TOKEN" in d["message"]
    assert _git(["rev-parse", "HEAD"], work).stdout.strip() == head and repo_env["pushes"] == []


def test_dry_run_plan_lists_changes_without_writing(repo_env):
    from api.services import site_pages_service as S
    work = repo_env["work"]
    d = S.deploy_site_pages(dry_run=True)
    assert d["dry_run"] is True and d["ok"] is False
    # dry-run은 파일을 쓰지 않으므로 현재 _site(old)와 생성물(new)이 달라 스냅샷 불일치로 보고된다.
    assert any("스냅샷 불일치" in b for b in d["plan"]["blockers"])
    assert (work / SITE / "index.html").read_text(encoding="utf-8") == pages("old")["index.html"]
    assert repo_env["pushes"] == []


def test_deploy_response_has_no_credentials(repo_env):
    r = _post("/api/sites/pages/deploy")
    assert SECRET not in r.text


def test_existing_calculator_reserved_policy_unchanged():
    from modules import github_deployer as GH
    for e in ("index.html", "sitemap.xml", "CNAME", "about", "contact", "privacy", "terms", "404",
              "404.html", "robots.txt", "site.css"):
        assert GH._validate_slug(e) == f"reserved_site_entry:{e!r}"
