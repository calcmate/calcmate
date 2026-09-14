# -*- coding: utf-8 -*-
"""
modules/wp_blog_sync.py — WP Publish → blog_articles 신규 등록 동기화(v12, STEP186)

목적
----
WordPress에 새로 Publish된 글을 자동 감지해 "blog_articles"에 신규 INSERT하고,
메인 「자주 찾는 계산 가이드」/sitemap이 이를 병합해 노출할 수 있도록 데이터를
준비한다(실제 병합은 modules/site_generator.py 쪽 책임).

기존 Publish Scheduler(modules/scheduler.py)와 Content Sync(modules/content_sync.py)
와는 완전히 분리된 독립 서비스다:
  - 별도 진입점(run_wp_blog_sync.bat, 이번 STEP에서는 파일만 준비)
  - 별도 lock 파일(data/schedule/wp_blog_sync.lock) — scheduler.lock/content_sync.lock과
    이름이 겹치지 않는다.
  - content_sync.py의 lock/poll 루프 "패턴"만 참고했을 뿐 그 코드를 그대로 가져오지
    않는다(Sheets/텔레그램/ArticleRepository 등 이 모듈과 무관한 의존성은 포함하지 않음).

핵심 경계(절대 원칙)
--------------------
- calculators.article_content는 이 모듈 어디에서도 읽거나 쓰지 않는다.
- GOLDEN_10 원본 10개(및 대응하는 기존 blog_articles row)는 이 모듈이 자동으로
  새로 만들거나 덮어쓰지 않는다 — WP publish 목록에 GOLDEN_10 slug가 있으면
  "신규"로도 "갱신 대상"으로도 취급하지 않고 그대로 건너뛴다(별도 안전 STEP 몫).
- 이번 STEP의 실제 write 대상은 "GOLDEN_10에 없는, blog_articles에도 아직 없는
  신규 Publish 글"로 제한한다. 기존 10개의 콘텐츠 갱신(UPDATE)은 이 모듈이
  수행하지 않는다(감지 정보는 참고용으로만 반환).
- 여러 신규 글을 한 번에 반영할 때는 단일 connection + 명시적 BEGIN/COMMIT/ROLLBACK
  으로 "전체 성공/전체 롤백"을 보장한다. SQLiteAdapter.insert()/update()를 반복
  호출하는 방식(각자 자체 커밋)은 사용하지 않는다.
"""
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.wp_readonly_client import get_wp_post_readonly, list_wp_posts_readonly, WP_PRODUCTION_URL
from modules.logger import get_logger

LOG = get_logger()

KST = timezone(timedelta(hours=9))

NEW_ARTICLE_INTENT = "howto"          # 신규 글 임시 기본 분류값(정확한 분류를 뜻하지 않음, STEP185 확정)
NEW_ARTICLE_CONTENT_SOURCE = "wordpress_auto"


# ── lock (scheduler.py/content_sync.py와 동일 "파일 mtime 기반 stale-lock" 패턴,
#    코드는 재사용하지 않고 이 모듈 전용 파일 경로로 새로 정의) ──────────────
def _schedule_dir(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    d = root / "data" / "schedule"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path(cfg: dict) -> Path:
    # scheduler.lock(Publish 슬롯) / content_sync.lock(WP↔Sheets)과 절대 겹치지 않는 별도 lock
    return _schedule_dir(cfg) / "wp_blog_sync.lock"


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
    return d / "wp_blog_sync.log"


def _append_log(cfg: dict, record: dict) -> None:
    """실행 1회 요약을 로그 파일에 append. 인증정보(username/app_password/토큰)는
    호출부에서 record에 절대 담지 않는다 — 이 함수는 record를 그대로 직렬화만 한다."""
    record = dict(record)
    record.setdefault("at", datetime.now().isoformat())
    try:
        with open(_log_path(cfg), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        LOG.warning("[wp_blog_sync] 로그 기록 실패(무시): %s", e)


# ── timezone 유틸(STEP185 확정: 기존 last_synced_at은 naive KST) ───────────
def _naive_kst_to_utc(naive_iso: str):
    """blog_articles의 naive-local(KST) ISO 문자열 → UTC-aware datetime.
    기존 저장 형식/값 자체는 절대 변환하지 않고, 비교 시점에만 메모리 상에서 해석한다."""
    dt = datetime.fromisoformat(naive_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(timezone.utc)


def _wp_gmt_to_utc(gmt_iso: str):
    """WP REST의 *_gmt 필드(이미 UTC) → UTC-aware datetime."""
    dt = datetime.fromisoformat(gmt_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── 신규/수정 감지(순수 함수 — I/O 없음, 단위 테스트 용이) ─────────────────
def detect_new_and_modified(wp_posts: list[dict], existing_rows: list[dict],
                             golden10_slugs: set) -> dict:
    """WP publish 목록 vs blog_articles 기존 row를 비교해 분류한다.

    Args:
        wp_posts: list_wp_posts_readonly()["posts"] 형태(status=publish로 이미 필터된 것을 권장)
        existing_rows: BlogArticleRepository.list_all() 결과
        golden10_slugs: content.blog.GOLDEN_10의 slug 집합(원본 리스트 자체는 인자로 받지 않음 —
            이 함수는 GOLDEN_10을 import하지 않고 호출부가 넘긴 집합만 사용한다)

    Returns:
        {
          "new": [wp_post, ...],            # blog_articles에 없고 GOLDEN_10도 아닌 진짜 신규
          "skipped_golden10": [wp_post,...],# GOLDEN_10 slug와 겹쳐 신규 취급하지 않은 것(방어용)
          "modified": [{"post":..., "row":...}, ...],  # 기존 row 중 WP가 더 최근인 것(참고용, 미반영)
        }
    """
    existing_by_id = {str(r.get("wp_post_id", "")): r for r in existing_rows if r.get("wp_post_id")}

    new_posts = []
    skipped_golden10 = []
    modified = []

    for post in wp_posts:
        if str(post.get("status", "")) != "publish":
            continue
        wp_id = str(post.get("id", ""))
        row = existing_by_id.get(wp_id)

        if row is None:
            # blog_articles에 아직 없음 — GOLDEN_10 slug와 겹치면 절대 신규로 취급하지 않는다.
            if post.get("slug", "") in golden10_slugs:
                skipped_golden10.append(post)
            else:
                new_posts.append(post)
            continue

        # 이미 존재하는 row — 수정 여부만 참고용으로 판정(이 함수는 write하지 않음).
        last_synced_at = row.get("last_synced_at") or row.get("updated_at")
        modified_gmt = post.get("modified_gmt")
        if not last_synced_at or not modified_gmt:
            continue
        try:
            wp_dt = _wp_gmt_to_utc(modified_gmt)
            db_dt = _naive_kst_to_utc(last_synced_at)
        except Exception:
            continue
        if wp_dt > db_dt:
            modified.append({"post": post, "row": row})

    return {"new": new_posts, "skipped_golden10": skipped_golden10, "modified": modified}


# ── 신규 row 조립(단건 GET으로 본문 확보) ──────────────────────────────────
def _strip_html_tags(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", "", html or "")
    return text.strip()


def build_new_article_row(post: dict, wp_full: dict) -> dict:
    """WP 목록 항목(post) + 단건 GET 결과(wp_full)로 blog_articles INSERT용 row를 조립한다.

    calculators 테이블은 참조하지 않는다(calculator_id=None 고정).
    intent/content_source는 STEP185에서 확정한 임시 기본값을 사용한다(정확한 분류를
    뜻하지 않으며, 향후 별도 자동 분류 기능이 이 필드를 나중에 UPDATE할 수 있다).
    """
    import urllib.parse
    slug = urllib.parse.unquote(post.get("slug", ""))
    now_iso = datetime.now().isoformat()
    excerpt_text = _strip_html_tags(wp_full.get("excerpt", "")) or None

    return {
        "article_id": "blog_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4],
        "slug": slug,
        "title": wp_full.get("title", ""),
        "content": wp_full.get("content", ""),
        "calculator_id": None,
        "intent": NEW_ARTICLE_INTENT,
        "content_source": NEW_ARTICLE_CONTENT_SOURCE,
        "status": "publish",
        "wp_post_id": str(post.get("id", "")),
        "wp_status": "publish",
        "wp_permalink": wp_full.get("link", ""),
        "canonical_url": f"https://calcmate.kr/blog/{slug}/",
        "seo_title": None,
        "meta_description": excerpt_text,
        "published_at": wp_full.get("date", "") or post.get("date", ""),
        "created_at": now_iso,
        "updated_at": now_iso,
        "last_synced_at": now_iso,
        "sync_status": "synced",
        "sync_error": None,
    }


_REQUIRED_ROW_FIELDS = (
    "article_id", "slug", "title", "content", "intent", "content_source",
    "status", "wp_post_id", "wp_status", "wp_permalink", "published_at",
    "created_at", "updated_at", "last_synced_at", "sync_status",
)


def _validate_row(row: dict) -> str | None:
    """NOT NULL 컬럼이 비어있지 않은지 확인. 문제 없으면 None, 있으면 사유 문자열."""
    for field in _REQUIRED_ROW_FIELDS:
        if not row.get(field):
            return f"required_field_empty:{field}"
    return None


# ── DB 반영: 단일 connection + 명시적 트랜잭션(전체 성공/전체 롤백) ────────
def insert_new_articles_transactional(db_path: str, rows: list[dict],
                                       busy_timeout_seconds: float = 5.0,
                                       max_attempts: int = 3) -> dict:
    """여러 신규 row를 하나의 트랜잭션으로 INSERT한다. 하나라도 실패하면 전부 rollback.

    SQLiteAdapter.insert()(호출마다 자체 commit)는 사용하지 않는다 — 이 함수만
    별도로 단일 connection을 열고 BEGIN/COMMIT/ROLLBACK을 명시적으로 관리한다.
    다른 코드 경로(SQLiteAdapter 자체)는 전혀 수정하지 않는다.

    동시 접근으로 인한 'database is locked'에 대비해 sqlite3.connect(timeout=...)의
    내장 busy-wait(=busy_timeout과 동등)를 사용하고, 그래도 실패하면 최대
    max_attempts회까지만 짧게 재시도한다(무한 재시도 금지).
    """
    if not rows:
        return {"success": True, "inserted": 0}

    for field in rows[0].keys():
        pass  # 컬럼 목록은 rows[0] 기준(모든 row가 동일 키 집합이어야 함 — build_new_article_row 보장)

    cols = list(rows[0].keys())
    col_sql = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)

    last_error = None
    for attempt in range(1, max_attempts + 1):
        conn = sqlite3.connect(db_path, timeout=busy_timeout_seconds)
        try:
            conn.execute("BEGIN")
            for row in rows:
                missing = _validate_row(row)
                if missing:
                    raise ValueError(f"invalid_row({row.get('wp_post_id')}): {missing}")
                values = [row.get(c) for c in cols]
                conn.execute(
                    f'INSERT INTO "blog_articles" ({col_sql}) VALUES ({placeholders})',
                    values,
                )
            conn.commit()
            return {"success": True, "inserted": len(rows)}
        except sqlite3.OperationalError as e:
            conn.rollback()
            last_error = str(e)
            if "locked" in last_error.lower() and attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            return {"success": False, "inserted": 0, "error": last_error}
        except Exception as e:
            conn.rollback()
            return {"success": False, "inserted": 0, "error": str(e)}
        finally:
            conn.close()

    return {"success": False, "inserted": 0, "error": last_error or "unknown_error"}


# ── 1회 실행(오케스트레이션) ────────────────────────────────────────────
def run_wp_blog_sync_once(cfg: dict, db_path: str | None = None,
                           repo=None, golden10_slugs: set | None = None) -> dict:
    """WP publish 목록 조회 → 신규 감지 → 본문 확보 → transaction INSERT.

    실패 시 즉시 HOLD(부분 반영 없음). calculators.article_content는 어디에서도
    접근하지 않는다. GOLDEN_10과 겹치는 slug, 기존 blog_articles row는 절대
    자동으로 새로 쓰거나 덮어쓰지 않는다(신규 오직 GOLDEN_10에 없는 순수 신규 글만).
    """
    from adapters.db.factory import get_db_adapter
    from repositories.blog_article_repository import BlogArticleRepository

    wp_cfg = (cfg.get("wordpress") or {})
    wp_url = wp_cfg.get("url", WP_PRODUCTION_URL)
    username = wp_cfg.get("username", "")
    app_password = wp_cfg.get("app_password", "")

    if db_path is None:
        db_path = str(Path(cfg.get("_root", ".")) / cfg.get("SQLITE_PATH", "data/blog_auto.db"))
    if repo is None:
        repo = BlogArticleRepository(get_db_adapter(cfg))
    if golden10_slugs is None:
        from content.blog import GOLDEN_10
        golden10_slugs = {gc.slug for gc in GOLDEN_10}

    listing = list_wp_posts_readonly(wp_url=wp_url, username=username, app_password=app_password)
    if not listing.get("success"):
        result = {"success": False, "hold_reason": "wp_list_failed", "detail": listing.get("error", "")}
        _append_log(cfg, {"event": "sync_once", **result})
        return result

    existing_rows = repo.list_all()
    detection = detect_new_and_modified(listing["posts"], existing_rows, golden10_slugs)

    new_rows = []
    for post in detection["new"]:
        wp_full = get_wp_post_readonly(post["id"], wp_url=wp_url, username=username, app_password=app_password)
        if not wp_full.get("success"):
            result = {
                "success": False, "hold_reason": "wp_get_individual_failed",
                "wp_post_id": post.get("id"), "detail": wp_full.get("error", ""),
            }
            _append_log(cfg, {"event": "sync_once", **result})
            return result
        row = build_new_article_row(post, wp_full)
        invalid = _validate_row(row)
        if invalid:
            result = {"success": False, "hold_reason": invalid, "wp_post_id": post.get("id")}
            _append_log(cfg, {"event": "sync_once", **result})
            return result
        new_rows.append(row)

    write_result = insert_new_articles_transactional(db_path, new_rows) if new_rows else {"success": True, "inserted": 0}

    summary = {
        "success": bool(write_result.get("success")),
        "wp_total": len(listing["posts"]),
        "new_count": len(new_rows),
        "inserted": write_result.get("inserted", 0),
        "modified_detected": len(detection["modified"]),
        "skipped_golden10": len(detection["skipped_golden10"]),
        "hold_reason": None if write_result.get("success") else "db_transaction_failed",
        "detail": write_result.get("error", ""),
    }
    _append_log(cfg, {"event": "sync_once", **summary})
    if not write_result.get("success"):
        LOG.error("[wp_blog_sync] transaction 실패 — 전체 rollback됨: %s", write_result.get("error"))
    else:
        LOG.info("[wp_blog_sync] 완료 신규=%d 반영=%d 수정감지(미반영)=%d",
                  summary["new_count"], summary["inserted"], summary["modified_detected"])
    return summary


# ── 독립 polling 루프 ───────────────────────────────────────────────────
def run_wp_blog_sync_loop(cfg: dict, poll_seconds: int = 1800) -> None:
    """기존 scheduler(발행 슬롯)/content_sync(WP↔Sheets)와 독립적인 저빈도 polling 루프.

    별도 lock 파일 사용(wp_blog_sync.lock), 중복 실행 방지. 한 tick의 예외가 다음
    tick 실행을 막지 않도록 매 tick을 개별적으로 try/except하고, 실패해도
    poll_seconds만큼 쉬고 나서만 재시도한다(무한 오류 폭주 방지).
    """
    LOG.info("[wp_blog_sync] 독립 polling 루프 시작(poll=%ds)", poll_seconds)
    while True:
        try:
            if _acquire_lock(cfg):
                try:
                    run_wp_blog_sync_once(cfg)
                finally:
                    _release_lock(cfg)
            else:
                LOG.info("[wp_blog_sync] 다른 실행 진행 중(lock) — 이번 주기 건너뜀")
        except Exception as e:
            LOG.error("[wp_blog_sync] 루프 오류(다음 주기에 재시도): %s", e, exc_info=True)
            _append_log(cfg, {"event": "loop_error", "error": str(e)})
        time.sleep(poll_seconds)
