"""CALCMATE-CALCULATOR-DEPLOY-FIX-03 — 계산기 published_url canonical 계약.

deploy_app()이 반환해 repo.publish()가 저장하는 published_url은 항상
SITE_URL(= https://calcmate.kr) + "/<slug>/" 이어야 한다. GitHub Pages(github.io)·
salarymate·블로그(/blog/) URL은 만들지 않는다. git/네트워크/DB 접근 없음 —
_deploy_slug_local/_origin_full_name/_plan_slug_deploy는 전부 monkeypatch한다.
"""
import pytest

import modules.github_deployer as GH

CFG = {"GITHUB_TOKEN": "x", "_root": ".", "SITE_URL": "https://calcmate.kr"}
FILES = {"index.html": "<h1>x</h1>"}


# TEST-01 / TEST-02 / TEST-03
@pytest.mark.parametrize("slug", [
    "bmi-calculator", "severance-pay", "freelancer-tax-3p3", "four-insurances",
    "연말정산_환급액_계산기", "자동차_취등록세_계산기",
])
def test_canonical_url_for_existing_slug_formats(slug):
    url = GH.calculator_public_url(CFG, slug)
    assert url == f"https://calcmate.kr/{slug}/"
    assert url.endswith("/") and not url.endswith("//")


def test_bmi_example():
    assert GH.calculator_public_url(CFG, "bmi-calculator") == "https://calcmate.kr/bmi-calculator/"


@pytest.mark.parametrize("site_url", ["https://calcmate.kr", "https://calcmate.kr/", " https://calcmate.kr// "])
def test_trailing_slash_normalized(site_url):
    assert GH.calculator_public_url({"SITE_URL": site_url}, "bmi-calculator") == \
        "https://calcmate.kr/bmi-calculator/"


def test_default_when_site_url_missing():
    assert GH.calculator_public_url({}, "bmi-calculator") == "https://calcmate.kr/bmi-calculator/"


# TEST-04 / TEST-05 / TEST-06 — 잘못된 base는 fail-closed
@pytest.mark.parametrize("site_url", [
    "https://calcmate.github.io",           # GitHub Pages
    "https://calcmate.github.io/calcmate",  # GitHub Pages + repo 경로
    "http://salarymate.test",               # SalaryMate 로컬 WP
    "https://salarymate.github.io",         # app_generator 구 기본값
    "https://calcmate.kr/blog",             # 블로그 경로
    "https://calcmate.kr/blog/",
    "http://calcmate.kr",                   # https 아님
    "calcmate.kr",                          # scheme 없음
])
def test_rejects_non_canonical_site_base(site_url):
    with pytest.raises(ValueError):
        GH.calculator_public_url({"SITE_URL": site_url}, "bmi-calculator")


@pytest.mark.parametrize("slug", ["", "..", "../x", "a/b", "blog/x", "index.html", "about"])
def test_rejects_unsafe_slug(slug):
    with pytest.raises(ValueError):
        GH.calculator_public_url(CFG, slug)


def test_blog_slug_is_not_blog_url():
    url = GH.calculator_public_url(CFG, "blog-like-calc")
    assert "/blog/" not in url and url == "https://calcmate.kr/blog-like-calc/"


def test_github_io_url_builder_removed():
    assert not hasattr(GH, "get_deploy_url")


# TEST-07 — deploy_app() 반환값(= repo.publish()에 저장되는 값) 계약
@pytest.fixture
def fake_git(monkeypatch):
    calls = []
    monkeypatch.setattr(GH, "_origin_full_name", lambda root: "calcmate/calcmate")
    monkeypatch.setattr(GH, "_deploy_slug_local",
                        lambda root, slug, files: calls.append(slug) or (True, "deadbeef"))
    return calls


def test_deploy_app_returns_canonical_url(fake_git):
    ok, url = GH.deploy_app(CFG, FILES, repo="calcmate", subdir="bmi-calculator")
    assert ok is True and url == "https://calcmate.kr/bmi-calculator/"
    assert "github.io" not in url and fake_git == ["bmi-calculator"]


def test_deploy_app_ignores_repo_name_for_url(fake_git):
    ok, url = GH.deploy_app(CFG, FILES, repo="salarymate-calculators", subdir="severance-pay")
    assert ok and url == "https://calcmate.kr/severance-pay/"


def test_deploy_app_invalid_site_url_blocks_before_git(fake_git):
    cfg = dict(CFG, SITE_URL="https://calcmate.github.io")
    ok, msg = GH.deploy_app(cfg, FILES, subdir="bmi-calculator")
    assert ok is False and "SITE_URL" in msg
    assert fake_git == [], "URL 검증 실패 시 git 경로에 진입하면 안 된다"


def test_deploy_app_failure_returns_message_not_url(monkeypatch):
    monkeypatch.setattr(GH, "_origin_full_name", lambda root: "calcmate/calcmate")
    monkeypatch.setattr(GH, "_deploy_slug_local", lambda root, slug, files: (False, "배포 중단 — x"))
    ok, msg = GH.deploy_app(CFG, FILES, subdir="bmi-calculator")
    assert ok is False and msg == "배포 중단 — x"


def test_dry_run_deploy_url_is_canonical(monkeypatch):
    monkeypatch.setattr(GH, "_origin_full_name", lambda root: "calcmate/calcmate")
    monkeypatch.setattr(GH, "_plan_slug_deploy", lambda root, slug, files, dry_run: {
        "status": "dry_run", "dry_run": True, "slug": slug, "blockers": [],
        "deploy_allowed": True, "blocked_reason": None})
    ok, plan = GH.deploy_app(CFG, FILES, subdir="bmi-calculator", dry_run=True)
    assert ok is False and plan["deploy_url"] == "https://calcmate.kr/bmi-calculator/"
    assert plan["deploy_allowed"] is True


def test_dry_run_invalid_site_url_is_reported_as_blocker(monkeypatch):
    monkeypatch.setattr(GH, "_origin_full_name", lambda root: "calcmate/calcmate")
    monkeypatch.setattr(GH, "_plan_slug_deploy", lambda root, slug, files, dry_run: {
        "status": "dry_run", "dry_run": True, "slug": slug, "blockers": [],
        "deploy_allowed": True, "blocked_reason": None})
    ok, plan = GH.deploy_app(dict(CFG, SITE_URL="http://salarymate.test"), FILES,
                             subdir="bmi-calculator", dry_run=True)
    assert plan["deploy_url"] is None and plan["deploy_allowed"] is False
    assert "SITE_URL" in plan["blocked_reason"]
