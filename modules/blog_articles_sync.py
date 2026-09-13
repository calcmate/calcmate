"""
modules/blog_articles_sync.py — blog_articles ↔ WordPress Production 변경 감지(READ-ONLY)

run_blog_articles_sync_once()는 다음만 수행한다:
  1. blog_articles 전체 조회
  2. 각 wp_post_id로 WP GET(주입된 wp_get_fn, 기본은 get_wp_post_readonly)
  3. WP 값과 SQLite 값을 비교
  4. 변경 사항을 INFO/WARN/FAIL/CRITICAL로 분류
  5. 결과 리스트를 반환

이 함수는 SQLite/Sheets/WordPress 어디에도 쓰지 않는다. 자동 수정은 다음 STEP의
사람 승인 이후에만 별도 함수로 수행한다(이 파일에는 그런 함수가 없다).
"""
from urllib.parse import unquote

from repositories.blog_article_repository import BlogArticleRepository
from modules.wp_readonly_client import get_wp_post_readonly

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_FAIL = "FAIL"
SEVERITY_CRITICAL = "CRITICAL"


def _classify_one(row: dict, wp: dict) -> dict:
    """row(SQLite blog_articles 1건) vs wp(get_wp_post_readonly 결과 1건) → 판정 dict."""
    article_id = row["article_id"]
    wp_post_id = row["wp_post_id"]

    if not wp.get("success"):
        if wp.get("http_status") == 404:
            return {"article_id": article_id, "wp_post_id": wp_post_id,
                    "severity": SEVERITY_CRITICAL, "reasons": ["wp_post_not_found_404"],
                    "wp": wp}
        return {"article_id": article_id, "wp_post_id": wp_post_id,
                "severity": SEVERITY_CRITICAL, "reasons": [f"wp_get_failed: {wp.get('error')}"],
                "wp": wp}

    reasons = []
    severity = SEVERITY_INFO

    if str(wp.get("id")) != str(wp_post_id):
        reasons.append(f"wp_post_id_mismatch(expected={wp_post_id}, actual={wp.get('id')})")
        severity = SEVERITY_CRITICAL

    # WP REST는 한글 slug를 URL-encoded로 반환하므로(SQLite엔 디코딩된 값 저장),
    # 정규화 후 비교해야 정상 데이터를 slug_changed로 오판하지 않는다.
    if unquote(wp.get("slug", "")) != row.get("slug", ""):
        reasons.append("slug_changed")
        if severity != SEVERITY_CRITICAL:
            severity = SEVERITY_FAIL

    if wp.get("status", "") != row.get("wp_status", ""):
        reasons.append(f"status_changed({row.get('wp_status')}->{wp.get('status')})")
        if severity != SEVERITY_CRITICAL:
            severity = SEVERITY_FAIL

    if wp.get("link", "") != row.get("wp_permalink", ""):
        reasons.append("permalink_changed")
        if severity not in (SEVERITY_CRITICAL, SEVERITY_FAIL):
            severity = SEVERITY_FAIL

    if severity == SEVERITY_INFO:
        if wp.get("modified", "") != row.get("last_synced_at", "") and \
           wp.get("modified", "") != row.get("updated_at", ""):
            reasons.append("modified_changed")
            severity = SEVERITY_WARN
        if wp.get("title", "") != row.get("title", ""):
            reasons.append("title_changed")
            severity = SEVERITY_WARN
        if wp.get("content", "") != row.get("content", ""):
            reasons.append("content_changed")
            severity = SEVERITY_WARN
        # STEP18: excerpt ↔ meta_description 비교는 동기화 판정에서 제외한다(정책 B).
        # meta_description은 현재 10건 모두 NULL(STEP12에서 정책 미확정으로 의도적 보류)이며
        # 실제 SEO 렌더링에도 쓰이지 않아, 이 비교는 "값이 없어서" 매번 오탐(WARN)만 발생시켰다.

    if not reasons:
        reasons = ["no_change"]

    return {"article_id": article_id, "wp_post_id": wp_post_id,
            "severity": severity, "reasons": reasons, "wp": wp}


def run_blog_articles_sync_once(cfg: dict, repo: BlogArticleRepository = None,
                                 wp_get_fn=None, wp_url: str = None) -> list[dict]:
    """blog_articles 전체를 WP Production과 대조하고 판정 결과 리스트를 반환한다.

    SQLite/Sheets/WordPress 어느 곳에도 쓰지 않는다(READ-ONLY). 반환값을 보고
    실제 조치를 할지는 호출자(사람 승인 이후의 별도 STEP)의 책임이다.
    """
    if repo is None:
        from adapters.db.factory import get_blog_article_storage_adapter
        repo = BlogArticleRepository(get_blog_article_storage_adapter(cfg))
    if wp_get_fn is None:
        wp_get_fn = get_wp_post_readonly

    kwargs = {}
    if wp_url is not None:
        kwargs["wp_url"] = wp_url
    wp_cfg = cfg.get("wordpress", {}) or {}
    username = wp_cfg.get("username", "")
    app_password = wp_cfg.get("app_password", "")

    results = []
    for row in repo.list_all():
        wp = wp_get_fn(row["wp_post_id"], username=username, app_password=app_password, **kwargs)
        results.append(_classify_one(row, wp))
    return results


# ── STEP20: sync_logs 저장(판정 로직과 분리) ──────────────────────────
_RESULT_PRIORITY = [SEVERITY_CRITICAL, SEVERITY_FAIL, SEVERITY_WARN]  # 없으면 PASS
RUN_RESULT_PASS = "PASS"


def _aggregate(results: list[dict]) -> dict:
    counts = {SEVERITY_INFO: 0, SEVERITY_WARN: 0, SEVERITY_FAIL: 0, SEVERITY_CRITICAL: 0}
    for r in results:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1
    result = RUN_RESULT_PASS
    for sev in _RESULT_PRIORITY:
        if counts.get(sev, 0) > 0:
            result = sev
            break
    return {"counts": counts, "result": result}


def _log_error_fields(entry: dict) -> tuple[str | None, str | None]:
    """CRITICAL 판정에서만 error_type/error_message를 채운다(그 외엔 None, None)."""
    if entry["severity"] != SEVERITY_CRITICAL:
        return None, None
    reasons = entry["reasons"]
    if any(r == "wp_post_not_found_404" for r in reasons):
        return "wp_post_not_found_404", reasons[0]
    if any(r.startswith("wp_get_failed") for r in reasons):
        msg = next(r for r in reasons if r.startswith("wp_get_failed"))
        return "wp_get_failed", msg
    if any(r.startswith("wp_post_id_mismatch") for r in reasons):
        msg = next(r for r in reasons if r.startswith("wp_post_id_mismatch"))
        return "wp_post_id_mismatch", msg
    return "unknown_critical", ",".join(reasons)


def run_blog_articles_sync_and_log(cfg: dict, repo: BlogArticleRepository = None,
                                    log_repo=None, wp_get_fn=None, wp_url: str = None,
                                    logger=None) -> list[dict]:
    """run_blog_articles_sync_once()를 그대로 호출하고(판정 로직 무변경), 그 결과를
    sync_runs/sync_log_entries에 저장한다. 로그 저장이 실패해도 판정 결과(results)는
    그대로 반환한다(sync 판정 성공 + 로그 저장 실패를 분리, STEP19 §11 원칙).

    본문(content)/발췌(excerpt)/before-after 전체값은 저장하지 않는다(STEP20 §5).
    """
    import time
    import uuid
    from datetime import datetime

    if repo is None:
        from adapters.db.factory import get_blog_article_storage_adapter
        repo = BlogArticleRepository(get_blog_article_storage_adapter(cfg))

    started_at = datetime.now().isoformat()
    t0 = time.monotonic()

    results = run_blog_articles_sync_once(cfg, repo=repo, wp_get_fn=wp_get_fn, wp_url=wp_url)

    finished_at = datetime.now().isoformat()
    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        if log_repo is None:
            from adapters.db.sqlite_adapter import SQLiteAdapter
            from repositories.sync_log_repository import SyncLogRepository
            log_repo = SyncLogRepository(SQLiteAdapter(cfg))

        agg = _aggregate(results)
        run_id = "sync_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]

        log_repo.insert_run({
            "run_id": run_id, "target": "blog_articles",
            "started_at": started_at, "finished_at": finished_at, "duration_ms": duration_ms,
            "result": agg["result"], "total_count": len(results),
            "info_count": agg["counts"][SEVERITY_INFO], "warn_count": agg["counts"][SEVERITY_WARN],
            "fail_count": agg["counts"][SEVERITY_FAIL], "critical_count": agg["counts"][SEVERITY_CRITICAL],
        })

        for r in results:
            error_type, error_message = _log_error_fields(r)
            entry_id = "log_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]
            # slug는 SQLite 원본(디코딩된 값)을 사용 — WP GET 실패 시에도 조회 가능하고,
            # 한글 slug가 URL-encoded로 로그에 남는 것을 방지한다.
            sqlite_row = repo.get_by_article_id(r["article_id"])
            slug = sqlite_row["slug"] if sqlite_row else ""
            log_repo.insert_entry({
                "entry_id": entry_id, "run_id": run_id,
                "article_id": r["article_id"], "wp_post_id": r["wp_post_id"],
                "slug": slug,
                "severity": r["severity"], "reasons": ",".join(r["reasons"]),
                "error_type": error_type, "error_message": error_message,
                "checked_at": finished_at,
            })
    except Exception as e:
        if logger is not None:
            logger.warning("sync_logs 저장 실패(판정 결과는 정상 반환): %s", e)
        # 로그 저장 실패는 여기서 소진한다 — run_blog_articles_sync_once()의 결과를
        # 절대 깨뜨리지 않는다(STEP20 §7 핵심 원칙).

    return results
