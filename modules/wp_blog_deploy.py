# -*- coding: utf-8 -*-
"""
modules/wp_blog_deploy.py — WP Publish → blog_articles → index/sitemap → 배포 오케스트레이션(STEP194)

목적
----
STEP186(wp_blog_sync)과 STEP191(site_generator SQLite-primary 복구)에서 각각
검증된 기존 함수를 그대로 재사용해, "신규 WP 글 감지 → index/sitemap 재생성 →
안전 검증 → 허용 파일만 staging → (dry_run이 아니면) commit/push"까지의
오케스트레이션만 담당한다. WP sync 로직/site 생성 로직/Adapter 정책 등
기존 코드는 이 파일에서 전혀 재구현하지 않는다.

절대 원칙
--------
- calculators/*, GOLDEN_10 원본, dashboard.py, scheduler, deploy.yml은
  이 모듈이 절대 건드리지 않는다.
- git add는 오직 ALLOWED_DEPLOY_FILES에 명시된 2개 파일만 대상으로 하며,
  "git add ." / "git add -A"에 준하는 방식은 절대 사용하지 않는다.
- staging 직후 `git diff --cached --name-only`가 ALLOWED_DEPLOY_FILES와
  정확히 일치하지 않으면 commit하지 않는다(기존 dirty 파일 유입 방지).
- push 직전/직후 origin의 대상 브랜치가 예상과 다르면(원격이 그 사이 바뀌면)
  자동으로 pull/merge/rebase하지 않고 push 자체를 하지 않는다.
- dry_run=True(기본값)에서는 WP sync → generation → validation → staging까지만
  수행하고 commit/push는 절대 실행하지 않는다.

독립 polling worker(STEP197)
----------------------------
run_wp_blog_deploy_loop()는 위 run_wp_blog_deploy_once()를 저빈도로 반복 호출만
할 뿐, sync/generation/validation/staging/commit/push 로직을 절대 복제하지
않는다. 기존 scheduler.lock/content_sync.lock/wp_blog_sync.lock과는 별개로
run_wp_blog_deploy_once() 내부의 wp_blog_deploy.lock을 그대로 사용한다(이 파일이
새 lock을 만들지 않는다). CLI(`python -m modules.wp_blog_deploy`)는 명시적으로
`--live`를 주지 않는 한 항상 dry-run이다.
"""
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from modules.logger import get_logger

LOG = get_logger()

DEFAULT_POLL_SECONDS = 300  # 5분 — webhook처럼 실시간 감지가 목적이 아니라
                             # 저빈도로 안전하게 새 Publish 유무만 확인하는 것이 목적

COMMIT_MESSAGE = "chore(blog): sync published WordPress articles"

ALLOWED_DEPLOY_FILES = (
    "data/workspace/_site/index.html",
    "data/workspace/_site/sitemap.xml",
)


# ── lock (wp_blog_sync.lock과 이름이 겹치지 않는 별도 lock) ────────────────
def _schedule_dir(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    d = root / "data" / "schedule"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "wp_blog_deploy.lock"


def _acquire_lock(cfg: dict, stale_seconds: int = 1800) -> bool:
    p = _lock_path(cfg)
    if p.exists():
        try:
            if time.time() - p.stat().st_mtime > stale_seconds:
                p.unlink(missing_ok=True)
            else:
                return False
        except Exception:
            return False
    try:
        p.write_text(datetime.now().isoformat(), encoding="utf-8")
        return True
    except Exception:
        return False


def _release_lock(cfg: dict) -> None:
    _lock_path(cfg).unlink(missing_ok=True)


def _log_path(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    d = root / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "wp_blog_deploy.log"


def _append_log(cfg: dict, record: dict) -> None:
    """loop cycle 1회 요약을 로그 파일에 append. 인증정보는 이 record에 절대 담기지
    않는다(run_wp_blog_deploy_once()의 반환값 자체가 이미 인증정보를 포함하지 않음)."""
    record = dict(record)
    record.setdefault("at", datetime.now().isoformat())
    try:
        with open(_log_path(cfg), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        LOG.warning("[wp_blog_deploy] 로그 기록 실패(무시): %s", e)


# ── 순수 검증 함수(파일 I/O 없음, 단위 테스트 용이) ─────────────────────────
def _extract_calc_grid(html: str) -> str | None:
    try:
        s = html.index('<section class="cm-section" id="calculators"')
        e = html.index("<!-- 서비스 소개 -->", s)
        return html[s:e]
    except ValueError:
        return None


def validate_index_html(old_html: str, new_html: str, golden10_slugs: set) -> tuple[bool, str | None]:
    """계산기 그리드 불변 + GOLDEN_10 링크 전부 유지 + 내용이 줄어들지 않았는지만 확인한다.
    (신규 카드 "추가"만 허용, 기존 내용 손실/치환은 전부 실패로 판정)"""
    if not new_html:
        return False, "empty_new_index"
    for slug in golden10_slugs:
        if f"/blog/{slug}/" not in new_html:
            return False, f"golden10_missing:{slug}"
    if old_html:
        old_grid = _extract_calc_grid(old_html)
        new_grid = _extract_calc_grid(new_html)
        if old_grid is not None and new_grid != old_grid:
            return False, "calculator_grid_changed"
        if len(new_html) < len(old_html):
            return False, "index_shrunk"
    return True, None


def validate_sitemap_xml(old_xml: str, new_xml: str, golden10_slugs: set) -> tuple[bool, str | None]:
    """중복 URL 없음 + 기존 URL이 하나도 사라지지 않음 + GOLDEN_10 URL 전부 유지."""
    if not new_xml:
        return False, "empty_new_sitemap"
    new_urls = re.findall(r"<loc>(.*?)</loc>", new_xml)
    if len(new_urls) != len(set(new_urls)):
        return False, "duplicate_urls"
    if old_xml:
        old_urls = set(re.findall(r"<loc>(.*?)</loc>", old_xml))
        missing = old_urls - set(new_urls)
        if missing:
            return False, f"urls_removed:{sorted(missing)}"
    for slug in golden10_slugs:
        if not any(u.endswith(f"/blog/{slug}/") for u in new_urls):
            return False, f"golden10_url_missing:{slug}"
    return True, None


# ── git 헬퍼(전부 명시적 파일/브랜치 인자, "." 나 "-A"는 어디에도 쓰지 않음) ──
def _run_git(args: list, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")


def stage_allowed_files(repo_dir: str, allowed: tuple = ALLOWED_DEPLOY_FILES) -> tuple[bool, list, str | None]:
    """allowed에 명시된 파일만 정확히 하나씩 git add하고, 그 직후 staged 목록이
    allowed와 정확히 일치하는지 검증한다. 기존 dirty 파일이 섞여 들어오면 실패."""
    for f in allowed:
        r = _run_git(["add", "--", f], repo_dir)
        if r.returncode != 0:
            return False, [], f"git_add_failed:{f}:{r.stderr.strip()}"

    r = _run_git(["diff", "--cached", "--name-only"], repo_dir)
    if r.returncode != 0:
        return False, [], f"git_diff_cached_failed:{r.stderr.strip()}"

    staged = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    staged_norm = sorted(p.replace("\\", "/") for p in staged)
    allowed_norm = sorted(p.replace("\\", "/") for p in allowed)
    if staged_norm != allowed_norm:
        return False, staged, f"staged_allowlist_mismatch: expected={allowed_norm} actual={staged_norm}"
    return True, staged, None


def _rev_parse(repo_dir: str, ref: str) -> str | None:
    r = _run_git(["rev-parse", ref], repo_dir)
    return r.stdout.strip() if r.returncode == 0 else None


def check_remote_unchanged(repo_dir: str, branch: str = "master") -> tuple[bool, str | None, str | None]:
    """git fetch 후 origin/<branch>가 로컬 HEAD와 일치하는지 확인한다(커밋 전 사전 점검).
    pull/merge/rebase는 절대 수행하지 않는다 — 불일치 시 그대로 실패 반환."""
    r = _run_git(["fetch", "origin", branch], repo_dir)
    if r.returncode != 0:
        return False, f"git_fetch_failed:{r.stderr.strip()}", None
    origin_sha = _rev_parse(repo_dir, f"origin/{branch}")
    head_sha = _rev_parse(repo_dir, "HEAD")
    if origin_sha is None or head_sha is None:
        return False, "rev_parse_failed", None
    if origin_sha != head_sha:
        return False, f"remote_diverged_before_commit:origin={origin_sha}:head={head_sha}", origin_sha
    return True, None, origin_sha


def commit_staged(repo_dir: str, message: str = COMMIT_MESSAGE) -> tuple[bool, str | None, str | None]:
    r = _run_git(["commit", "-m", message], repo_dir)
    if r.returncode != 0:
        return False, None, f"git_commit_failed:{r.stderr.strip()}"
    return True, _rev_parse(repo_dir, "HEAD"), None


def push_if_remote_unchanged(repo_dir: str, base_sha: str, branch: str = "master") -> tuple[bool, str | None]:
    """push 직전 재확인 — base_sha(커밋 전 origin 기준)와 지금의 origin이 다르면
    (그 사이 다른 프로세스가 push했다는 뜻) push를 하지 않는다. pull/rebase 없음."""
    r = _run_git(["fetch", "origin", branch], repo_dir)
    if r.returncode != 0:
        return False, f"git_fetch_failed:{r.stderr.strip()}"
    origin_sha = _rev_parse(repo_dir, f"origin/{branch}")
    if origin_sha != base_sha:
        return False, f"remote_changed_during_process:expected={base_sha}:now={origin_sha}"
    r2 = _run_git(["push", "origin", branch], repo_dir)
    if r2.returncode != 0:
        return False, f"git_push_failed:{r2.stderr.strip()}"
    return True, None


# ── 오케스트레이션 ──────────────────────────────────────────────────────
def run_wp_blog_deploy_once(cfg: dict, dry_run: bool = True, repo_dir: str | None = None,
                             sync_fn=None, generate_index_fn=None, generate_sitemap_fn=None,
                             branch: str = "master") -> dict:
    """WP 신규 Publish 감지 → blog_articles 반영(기존 run_wp_blog_sync_once 재사용) →
    index/sitemap 재생성 → 안전 검증 → 허용 파일만 staging → (dry_run이 아니면) commit/push.

    sync_fn/generate_index_fn/generate_sitemap_fn을 주입하면 실제 WP/DB/site_generator를
    호출하지 않고 격리 테스트할 수 있다(기본값은 각각 run_wp_blog_sync_once/generate_index/
    generate_sitemap — 기존 함수 그대로 재사용, 새로 구현하지 않음).
    """
    if repo_dir is None:
        repo_dir = cfg.get("_root", ".")
    repo_path = Path(repo_dir)

    result = {"stage": "start", "success": False, "hold_reason": None,
              "dry_run": dry_run, "new_count": 0, "staged_files": []}

    if not _acquire_lock(cfg):
        result.update(stage="lock", hold_reason="lock_busy")
        return result

    try:
        if sync_fn is None:
            from modules.wp_blog_sync import run_wp_blog_sync_once as sync_fn
        sync_result = sync_fn(cfg)
        result["wp_sync"] = sync_result

        if not sync_result.get("success"):
            result.update(stage="wp_sync", hold_reason="wp_sync_failed")
            return result

        new_count = int(sync_result.get("new_count", 0))
        result["new_count"] = new_count
        if new_count == 0:
            result.update(stage="wp_sync", success=True, hold_reason=None,
                           message="no_new_articles")
            return result

        # ── generation ──
        index_path = repo_path / "data/workspace/_site/index.html"
        sitemap_path = repo_path / "data/workspace/_site/sitemap.xml"
        old_index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        old_sitemap = sitemap_path.read_text(encoding="utf-8") if sitemap_path.exists() else ""

        if generate_index_fn is None:
            from modules.site_generator import generate_index as generate_index_fn
        if generate_sitemap_fn is None:
            from modules.site_generator import generate_sitemap as generate_sitemap_fn
        new_index = generate_index_fn(cfg)
        new_sitemap = generate_sitemap_fn(cfg)
        result["stage"] = "generation"

        from content.blog import GOLDEN_10
        golden10_slugs = {gc.slug for gc in GOLDEN_10}

        ok_i, reason_i = validate_index_html(old_index, new_index, golden10_slugs)
        ok_s, reason_s = validate_sitemap_xml(old_sitemap, new_sitemap, golden10_slugs)
        if not (ok_i and ok_s):
            result.update(stage="validation", hold_reason=reason_i or reason_s)
            return result
        result["stage"] = "validation"

        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(new_index, encoding="utf-8")
        sitemap_path.write_text(new_sitemap, encoding="utf-8")
        result["stage"] = "write"

        # ── staging(허용 파일만) ──
        stage_ok, staged, stage_reason = stage_allowed_files(repo_dir)
        result["staged_files"] = staged
        if not stage_ok:
            result.update(stage="staging", hold_reason=stage_reason)
            return result
        result["stage"] = "staging"

        if dry_run:
            result.update(success=True, stage="dry_run_complete",
                           message="dry_run: staged only, no commit/push")
            return result

        # ── remote 보호(커밋 전) ──
        remote_ok, remote_reason, base_sha = check_remote_unchanged(repo_dir, branch)
        if not remote_ok:
            result.update(stage="remote_check", hold_reason=remote_reason)
            return result

        commit_ok, commit_sha, commit_reason = commit_staged(repo_dir)
        if not commit_ok:
            result.update(stage="commit", hold_reason=commit_reason)
            return result
        result["commit_sha"] = commit_sha

        push_ok, push_reason = push_if_remote_unchanged(repo_dir, base_sha, branch)
        if not push_ok:
            result.update(stage="push", hold_reason=push_reason)
            return result

        result.update(success=True, stage="push_complete")
        return result
    finally:
        _release_lock(cfg)


# ── 독립 polling worker(STEP197) ────────────────────────────────────────
def run_wp_blog_deploy_loop(cfg: dict, interval_seconds: int = DEFAULT_POLL_SECONDS, *,
                             dry_run: bool = True, stop_event=None, deploy_fn=None,
                             **once_kwargs) -> None:
    """저빈도 독립 polling 루프 — 매 cycle마다 run_wp_blog_deploy_once()를 그대로
    호출할 뿐, sync/generation/validation/staging/commit/push 로직을 이 함수
    안에서 절대 다시 구현하지 않는다(deploy_fn 주입 시에도 마찬가지 — 테스트에서만
    fake로 교체).

    dry_run 기본값은 True다 — 이 함수를 실수로 직접 호출해도 production commit/push는
    발생하지 않는다. 실제 운영에서 push까지 하려면 호출부가 dry_run=False를 명시해야
    한다. lock은 이 함수가 아니라 run_wp_blog_deploy_once() 내부(wp_blog_deploy.lock)가
    담당한다 — 이 루프는 새 lock을 만들지 않는다.

    stop_event(threading.Event 등, .is_set()/.wait(timeout) 지원)가 주어지면 각
    cycle 사이 대기 중에도 즉시 반응해 다음 cycle 없이 정상 종료한다.
    """
    if deploy_fn is None:
        deploy_fn = run_wp_blog_deploy_once

    LOG.info("[wp_blog_deploy] 독립 polling 루프 시작(interval=%ds, dry_run=%s)",
             interval_seconds, dry_run)

    while True:
        if stop_event is not None and stop_event.is_set():
            LOG.info("[wp_blog_deploy] stop_event 감지 — 다음 cycle을 시작하지 않고 종료")
            return

        try:
            result = deploy_fn(cfg, dry_run=dry_run, **once_kwargs)
            _append_log(cfg, {
                "event": "loop_cycle",
                **{k: v for k, v in result.items() if k != "wp_sync"},
            })
            if result.get("success"):
                LOG.info("[wp_blog_deploy] cycle 완료: stage=%s new_count=%s",
                         result.get("stage"), result.get("new_count"))
            else:
                LOG.warning("[wp_blog_deploy] cycle 결과: stage=%s hold_reason=%s",
                            result.get("stage"), result.get("hold_reason"))
        except Exception as e:
            # 이 cycle의 예외를 조용히 삼키지 않는다 — 로그에 남기고 루프 자체는 계속한다.
            LOG.error("[wp_blog_deploy] cycle 예외(다음 cycle에서 재시도): %s", e, exc_info=True)
            _append_log(cfg, {"event": "loop_cycle_exception", "error": str(e)})

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                LOG.info("[wp_blog_deploy] stop_event 감지(대기 중) — 종료")
                return
        else:
            time.sleep(interval_seconds)


def _main_cli() -> int:
    """python -m modules.wp_blog_deploy [--loop] [--interval N] [--live]

    기본 실행은 항상 dry-run이다(--live를 명시해야만 실제 commit/push 허용)."""
    import argparse

    parser = argparse.ArgumentParser(description="WP Blog Deploy - 독립 배포 worker")
    parser.add_argument("--loop", action="store_true",
                         help="독립 polling 루프로 상시 실행(기본은 1회만 실행)")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_SECONDS,
                         help=f"polling 간격(초), 기본 {DEFAULT_POLL_SECONDS}")
    parser.add_argument("--live", action="store_true",
                         help="명시해야만 실제 commit/push를 허용한다(기본은 dry-run)")
    args = parser.parse_args()

    from modules.config_loader import load_config
    cfg = load_config()
    dry_run = not args.live

    if args.loop:
        run_wp_blog_deploy_loop(cfg, interval_seconds=args.interval, dry_run=dry_run)
        return 0

    result = run_wp_blog_deploy_once(cfg, dry_run=dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    import sys
    sys.exit(_main_cli())
