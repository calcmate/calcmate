# -*- coding: utf-8 -*-
"""
modules/github_deployer.py — 계산기 GitHub Pages 자동 배포 (SalaryMate 확장, 신규)

생성된 계산기 정적 파일(index.html/style.css/script.js)을 GitHub 저장소에
업로드하고 GitHub Pages를 활성화하여 공개 URL을 반환한다.

환경설정(우선순위: cfg → 환경변수):
  GITHUB_TOKEN  : PAT (repo 권한)
  GITHUB_REPO   : 대상 저장소명(없으면 create_repo로 생성)

토큰 미설정 시 모든 함수는 (False, 안내메시지)로 graceful 처리(크래시 없음).
"""
import base64
import os

import requests

from .logger import get_logger

LOG = get_logger()
_API = "https://api.github.com"


def _token(cfg: dict) -> str:
    return (cfg.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def is_configured(cfg: dict) -> bool:
    return bool(_token(cfg))


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {_token(cfg)}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _owner(cfg: dict) -> str:
    r = requests.get(f"{_API}/user", headers=_headers(cfg), timeout=15)
    r.raise_for_status()
    return r.json()["login"]


def create_repo(cfg: dict, name: str, private: bool = False) -> tuple:
    """저장소 생성(이미 있으면 재사용). 반환: (ok, repo_full_name 또는 메시지)."""
    if not is_configured(cfg):
        return False, "GITHUB_TOKEN 미설정 — 배포 건너뜀"
    try:
        owner = _owner(cfg)
        # 존재 확인
        chk = requests.get(f"{_API}/repos/{owner}/{name}", headers=_headers(cfg), timeout=15)
        if chk.status_code == 200:
            return True, f"{owner}/{name}"
        r = requests.post(f"{_API}/user/repos", headers=_headers(cfg),
                          json={"name": name, "private": private, "auto_init": True}, timeout=20)
        r.raise_for_status()
        LOG.info("GitHub repo 생성: %s", r.json().get("full_name"))
        return True, r.json()["full_name"]
    except Exception as e:
        LOG.error("create_repo 실패: %s", e)
        return False, f"repo 생성 실패: {e}"


def _put_file(cfg: dict, full_name: str, path: str, content: str, branch: str = "master") -> bool:
    url = f"{_API}/repos/{full_name}/contents/{path}"
    headers = _headers(cfg)
    # 기존 파일 sha 확인(업데이트용)
    sha = None
    g = requests.get(url, headers=headers, params={"ref": branch}, timeout=15)
    if g.status_code == 200:
        sha = g.json().get("sha")
    body = {"message": f"deploy {path}",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch}
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=headers, json=body, timeout=20)
    r.raise_for_status()
    return True


def _enable_pages(cfg: dict, full_name: str, branch: str = "main", path: str = "/") -> None:
    url = f"{_API}/repos/{full_name}/pages"
    headers = _headers(cfg)
    try:
        requests.post(url, headers=headers,
                      json={"source": {"branch": branch, "path": path}}, timeout=20)
    except Exception as e:
        LOG.warning("Pages 활성화 경고(이미 켜졌을 수 있음): %s", e)


# ── 계산기 Deploy: 로컬 Git 경로 ─────────────────────────────────────────
# Contents API로 원격 master에 파일마다 직접 커밋하던 방식은 로컬/원격을 분기시키고
# 파일 수만큼 Pages 배포를 일으켰다. 계산기 Deploy는 이제 로컬 저장소의
# data/workspace/_site/<slug>/** 만 stage → 1회 commit → 원격 불변 확인 후 push 한다.
_SITE_REL = "data/workspace/_site"
_BRANCH = "master"
# _site 루트의 공용 사이트 파일/페이지 — 계산기 slug로 쓸 수 없다(자동 stage 금지 대상).
_RESERVED_SITE_ENTRIES = frozenset({
    "index.html", "sitemap.xml", "CNAME", "about", "contact", "privacy", "terms",
    "404", "404.html", "robots.txt", "site.css",
})


def _git(root: str, args: list):
    import subprocess
    # GIT_OPTIONAL_LOCKS=0: status 등 조회 명령이 index stat 캐시를 갱신(쓰기)하지 않도록.
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, env=env)


def _rev(root: str, ref: str):
    r = _git(root, ["rev-parse", "--verify", "--quiet", ref])
    return r.stdout.strip() if r.returncode == 0 else None


def _validate_slug(slug: str) -> str | None:
    """slug가 _site 바로 아래의 단일 계산기 디렉터리 이름인지 확인. 문제 시 사유 반환."""
    s = str(slug or "")
    if not s.strip():
        return "empty_slug"
    if s != s.strip() or s in (".", "..") or s.startswith("."):
        return f"invalid_slug:{s!r}"
    if any(ch in s for ch in ("/", "\\", ":", "\0")) or os.path.isabs(s):
        return f"invalid_slug:{s!r}"
    if s in _RESERVED_SITE_ENTRIES:
        return f"reserved_site_entry:{s!r}"
    return None


def _changed_paths(root: str, pathspec: str) -> list | None:
    """pathspec 아래의 modified/untracked/deleted/staged 경로(저장소 기준, '/' 구분)."""
    r = _git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", pathspec])
    if r.returncode != 0:
        return None
    out, entries, i = [], r.stdout.split("\0"), 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        out.append(e[3:])
        if e[0] in ("R", "C"):  # rename/copy는 원래 경로가 다음 항목으로 온다
            out.append(entries[i])
            i += 1
    return out


class _Blocked(Exception):
    """실배포 모드에서 첫 차단 사유로 즉시 중단(fail-fast)."""


def _remote_state(root: str, head: str, remote: str) -> str:
    """local HEAD와 원격 branch head의 관계: in_sync/ahead/behind/diverged/unknown."""
    if head == remote:
        return "in_sync"
    if _git(root, ["cat-file", "-e", f"{remote}^{{commit}}"]).returncode != 0:
        return "unknown"  # 원격 커밋이 로컬에 없음(미fetch) — 최소 behind
    if _git(root, ["merge-base", "--is-ancestor", remote, head]).returncode == 0:
        return "ahead"
    if _git(root, ["merge-base", "--is-ancestor", head, remote]).returncode == 0:
        return "behind"
    return "diverged"


def _plan_slug_deploy(root: str, slug: str, files: dict, branch: str = _BRANCH,
                      dry_run: bool = False) -> dict:
    """배포 전 검증 + 예상 결과 계산. 저장소/원격에 어떤 쓰기도 하지 않는다
    (실배포 모드의 fetch는 remote-tracking ref 갱신만 한다).

    dry_run=False: 첫 차단 사유에서 _Blocked를 던진다(FIX-01 fail-fast 순서 유지).
    dry_run=True : 가능한 모든 차단 사유를 blockers에 모아 반환한다. 원격은 fetch
                   대신 ls-remote로 읽어 remote-tracking ref도 바꾸지 않는다."""
    from pathlib import Path
    from .site_snapshot import _SNAPSHOT_FILES

    plan = {
        "status": "dry_run" if dry_run else "checked", "dry_run": dry_run,
        "slug": slug, "branch": branch, "target_path": None,
        "files": [], "file_count": 0, "changed_files": [],
        "commit_message": f"deploy calculator {slug}",
        "commit_would_be_required": False, "push_would_be_required": False,
        "local_head": None, "remote_head": None, "remote_state": None,
        "deploy_allowed": False, "blocked_reason": None, "blockers": [],
    }

    def block(msg: str):
        plan["blockers"].append(msg)
        if not dry_run:
            raise _Blocked(msg)

    def done() -> dict:
        plan["deploy_allowed"] = not plan["blockers"]
        plan["blocked_reason"] = plan["blockers"][0] if plan["blockers"] else None
        return plan

    bad = _validate_slug(slug)
    if bad:
        block(bad)
        return done()

    top = _git(root, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        block("git 저장소가 아님")
        return done()
    repo_root = Path(top.stdout.strip()).resolve()
    root = str(repo_root)
    plan["_root"] = root
    site_root = (repo_root / _SITE_REL).resolve()
    target = (site_root / slug).resolve()
    if target.parent != site_root or target.name != slug or not target.is_dir():
        block(f"_site 하위 계산기 디렉터리가 아님: {slug!r}")
        return done()
    slug_rel = f"{_SITE_REL}/{slug}"
    plan["target_path"] = slug_rel + "/"

    # 배포 파일은 이미 Build가 _site/<slug>/에 쓴 확정 스냅샷과 정확히 같아야 한다.
    deploy_rel = []
    for fname, content in files.items():
        if fname.startswith("_"):
            continue
        if fname not in _SNAPSHOT_FILES:
            block(f"허용되지 않는 파일명: {fname!r}")
            continue
        p = target / fname
        if not p.is_file() or p.read_text(encoding="utf-8") != content:
            block(f"스냅샷 불일치: {slug_rel}/{fname}")
            continue
        deploy_rel.append(f"{slug_rel}/{fname}")
    plan["files"], plan["file_count"] = deploy_rel, len(deploy_rel)
    if not deploy_rel and not plan["blockers"]:
        block("배포할 파일 없음")

    if _git(root, ["symbolic-ref", "--short", "HEAD"]).stdout.strip() != branch:
        block(f"현재 브랜치가 {branch}가 아님")
    staged = _git(root, ["diff", "--cached", "--name-only"])
    if staged.returncode != 0 or staged.stdout.strip():
        block("index에 이미 staged 변경이 있음(index_not_clean)")

    # Remote divergence guard: local HEAD == 원격 branch head 일 때만 진행(ahead도 거부).
    head = _rev(root, "HEAD")
    if dry_run:
        r = _git(root, ["ls-remote", "origin", f"refs/heads/{branch}"])
        remote = r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None
        if remote is None:
            block(f"git ls-remote 실패: {r.stderr.strip()}")
    else:
        f = _git(root, ["fetch", "origin", branch])
        if f.returncode != 0:
            block(f"git fetch 실패: {f.stderr.strip()}")
        remote = _rev(root, f"origin/{branch}")
    plan["local_head"], plan["remote_head"] = head, remote
    if head and remote:
        plan["remote_state"] = _remote_state(root, head, remote)
    if not head or head != remote:
        block(f"remote_diverged: state={plan['remote_state']} "
              f"HEAD={head} origin/{branch}={remote}")

    # 기존 dirty 보호: slug 아래 변경은 전부 이번 스냅샷 파일이어야 한다.
    changed = _changed_paths(root, slug_rel)
    if changed is None:
        block("git status 실패")
        return done()
    unexpected = sorted(set(changed) - set(deploy_rel))
    if unexpected:
        block(f"스냅샷 외 기존 변경(pre_existing_dirty): {unexpected}")
    to_commit = sorted(set(changed) & set(deploy_rel))
    plan["changed_files"] = to_commit
    plan["commit_would_be_required"] = plan["push_would_be_required"] = bool(to_commit)
    return done()


def _deploy_slug_local(root: str, slug: str, files: dict, branch: str = _BRANCH) -> tuple:
    """_site/<slug>/ 의 확정 스냅샷을 로컬 commit 1회 + 원격 불변 시에만 push.
    반환: (ok, 메시지). 어떤 불확실한 상태도 fail-closed(commit/push 없이 중단)."""
    try:
        plan = _plan_slug_deploy(root, slug, files, branch)
    except _Blocked as e:
        return False, f"배포 중단 — {e}"
    root, head, to_commit = plan["_root"], plan["local_head"], plan["changed_files"]
    if not to_commit:
        return True, "변경 없음 — 이미 배포된 스냅샷"

    a = _git(root, ["add", "--", *to_commit])
    if a.returncode != 0:
        return False, f"배포 중단 — git add 실패: {a.stderr.strip()}"
    staged = _git(root, ["diff", "--cached", "--name-only", "-z"])
    staged_set = {p for p in staged.stdout.split("\0") if p}
    if staged.returncode != 0 or staged_set != set(to_commit):
        # 방금 이 함수가 stage한 경로만 index에서 내린다(작업트리는 그대로).
        _git(root, ["reset", "-q", "--", *to_commit])
        return False, f"배포 중단 — staged 목록 불일치: {sorted(staged_set)}"
    c = _git(root, ["commit", "-q", "-m", plan["commit_message"]])
    if c.returncode != 0:
        _git(root, ["reset", "-q", "--", *to_commit])
        return False, f"배포 중단 — git commit 실패: {c.stderr.strip()}"
    new_head = _rev(root, "HEAD")

    # push 직전 재확인 — 그 사이 원격이 바뀌었으면 push하지 않는다(pull/rebase/force 없음).
    f = _git(root, ["fetch", "origin", branch])
    now = _rev(root, f"origin/{branch}") if f.returncode == 0 else None
    if now != head:
        return False, (f"push 중단 — 원격 변경 감지(expected={head} now={now}). "
                       f"로컬 commit {new_head}만 생성됨")
    p = _git(root, ["push", "origin", branch])
    if p.returncode != 0:
        return False, f"push 실패: {p.stderr.strip()} — 로컬 commit {new_head}만 생성됨"
    LOG.info("계산기 배포 push 완료: %s (%s)", slug, new_head)
    return True, new_head


def _origin_full_name(root: str) -> str | None:
    """origin URL(https/ssh)에서 owner/repo 추출."""
    import re
    url = _git(root, ["config", "--get", "remote.origin.url"]).stdout.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def deploy_app(cfg: dict, files: dict, repo: str = None, subdir: str = "",
               *, dry_run: bool = False) -> tuple:
    """files={'index.html':..,'style.css':..,'script.js':..} = _site/<subdir>/ 확정 스냅샷.
    반환: (ok, published_url 또는 메시지). published_url은 calculator_public_url()의
    canonical 공개 URL(SITE_URL/<slug>/)이며 GitHub Pages(github.io) URL이 아니다.

    실제 운영 Pages 구성(build_type=workflow, .github/workflows/deploy.yml)은
    master 브랜치의 data/workspace/_site/** 변경을 감지해 Actions가 빌드/배포한다.
    이 함수는 GitHub Contents API로 원격에 직접 쓰지 않는다 — 로컬 저장소
    (cfg["_root"])에서 data/workspace/_site/<subdir>/** 만 stage해 1회 commit하고,
    local HEAD == origin/master(분기/ahead 모두 거부)였고 그 사이 원격이 바뀌지
    않았을 때만 push한다. repo 인자는 호출부 호환용이며 배포 대상은 로컬 저장소의
    origin이다(저장소 생성/Pages 설정 변경 없음).

    dry_run=True: 같은 검증만 수행하고 (False, plan dict)를 반환한다 — git add/
    commit/push/fetch, HTTP 호출 없음. 배포가 일어나지 않았으므로 ok는 항상 False
    ("if ok: publish" 호출부가 실수로 기록하지 않도록). 판정은 plan["deploy_allowed"],
    사유는 plan["blocked_reason"]/plan["blockers"]를 본다.
    """
    root = cfg.get("_root") or "."
    if dry_run:
        try:
            plan = _plan_slug_deploy(root, subdir, files, dry_run=True)
            plan.pop("_root", None)
            full = _origin_full_name(root)
            try:
                plan["deploy_url"], url_err = calculator_public_url(cfg, subdir), None
            except ValueError as e:
                plan["deploy_url"], url_err = None, str(e)
            extra = ([] if is_configured(cfg) else ["GITHUB_TOKEN 미설정"]) + \
                    ([] if full else ["origin이 GitHub 저장소가 아님"]) + \
                    ([url_err] if url_err else [])
            if extra:
                plan["blockers"] += extra
                plan["deploy_allowed"] = False
                plan["blocked_reason"] = plan["blocked_reason"] or extra[0]
        except Exception as e:
            plan = {"status": "dry_run", "dry_run": True, "slug": subdir,
                    "deploy_allowed": False, "blocked_reason": f"dry-run 실패: {e}",
                    "blockers": [f"dry-run 실패: {e}"]}
        return False, plan

    if not is_configured(cfg):
        return False, "GITHUB_TOKEN 미설정 — 배포 건너뜀(로컬 미리보기만 가능)"
    try:
        # URL은 쓰기 전에 계산 — push 성공 후 URL 실패로 "실패" 보고되는 일이 없도록.
        try:
            url = calculator_public_url(cfg, subdir)
        except ValueError as e:
            return False, f"배포 중단 — {e}"
        if not _origin_full_name(root):
            return False, "배포 중단 — origin이 GitHub 저장소가 아님"
        ok, msg = _deploy_slug_local(root, subdir, files)
        if not ok:
            LOG.warning("deploy_app 중단(slug=%s): %s", subdir, msg)
            return False, msg
        return True, url
    except Exception as e:
        LOG.error("deploy_app 실패: %s", e)
        return False, f"배포 실패: {e}"


# 계산기 공개 URL의 SSOT는 config SITE_URL(= https://calcmate.kr)이다 — site_generator,
# scripts/_rebuild_site.py, cta_builder와 같은 규칙(SITE_URL 기본값, "{base}/{slug}/",
# slug는 인코딩 없이 그대로)을 따른다. 블로그(/blog/)·WP origin·GitHub Pages는 대상이 아니다.
_DEFAULT_SITE_URL = "https://calcmate.kr"


def calculator_public_url(cfg: dict, slug: str) -> str:
    """slug → 계산기 canonical 공개 URL(https://calcmate.kr/<slug>/).
    SITE_URL이 https 루트 도메인이 아니거나(경로 포함 — 예: /blog/) github.io/salarymate
    호스트면, 또는 slug가 단일 계산기 디렉터리 이름이 아니면 ValueError(fail-closed)."""
    from urllib.parse import urlparse

    bad = _validate_slug(slug)
    if bad:
        raise ValueError(f"published_url 계산 불가 — {bad}")
    base = str(cfg.get("SITE_URL") or _DEFAULT_SITE_URL).strip().rstrip("/")
    u = urlparse(base)
    host = (u.hostname or "").lower()
    if (u.scheme != "https" or not host or u.path or u.query or u.fragment
            or host.endswith("github.io") or "salarymate" in host):
        raise ValueError(f"published_url 계산 불가 — SITE_URL이 공개 사이트 루트가 아님: {base!r}")
    return f"{base}/{slug}/"
