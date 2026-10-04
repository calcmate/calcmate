# -*- coding: utf-8 -*-
"""
modules/content_sync.py — Content Sync Engine (v12 신규)

목적
----
WordPress(발행 채널)의 실제 상태를 "기준(source of truth)"으로 삼아,
CalcMate blog_articles에 기록된 발행 글과 WP 상태가 어긋났는지 주기적으로 점검하는
**독립 서비스**.

CALCMATE-CONTENT-SYNC-BLOG-ARTICLES-MIGRATION-IMPLEMENT-01:
  - 대상 WP: 평면 WORDPRESS_URL(obsolete 로컬 salarymate.test) 대신
    config_loader._apply_wp_target(cfg, "production")으로 secrets.yaml의 nested
    wordpress.{url,username,app_password} 세트를 사용한다(get_adapter()).
  - 데이터 source: 레거시 articles(Sheets 마스터_DB) 대신 blog_articles
    (BlogArticleRepository + get_blog_article_storage_adapter, READ-ONLY).
  - 쓰기 소유권: blog_articles의 유일한 writer는 modules/wp_blog_sync.py(INSERT)다.
    content_sync는 blog_articles/Sheets에 절대 쓰지 않고, 판정 결과는 자기 소유
    파일(data/schedule/content_sync_state.json, sync_history.jsonl)에만 남긴다.

Publish Scheduler(scheduler.py)와 완전히 분리되어 있다:
  - 별도 진입점(run_sync.py)에서 기동
  - 별도 lock 파일(data/schedule/content_sync.lock)
  - 별도 이력 파일(data/schedule/sync_history.jsonl)
scheduler.py 의 run_scheduler_loop 패턴(poll 루프 + 파일 lock)만 재사용하고,
발행 로직은 일절 건드리지 않는다.

매칭 키
-------
post_id(= wp_post_id) 단일 기준. URL은 URL_CHANGED 판정에만 쓰고 매칭 키로 쓰지 않는다.

동기화 플래그(sync_flag) — blog_articles 기준 의미
-------------------------------------------------
  OK               : blog_articles row ↔ WP(publish) 일치
  WP_DELETED       : row에 wp_post_id가 있으나 WP에서 404(영구삭제)
  WP_TRASH         : WP에서 휴지통(trash) 상태
  WP_NOT_PUBLISHED : WP에 존재하지만 publish가 아님(draft/pending/private/future) — 이상
                     기록만, 알림 대상 아님
  URL_CHANGED      : WP 링크가 row의 wp_permalink와 다름(퍼센트 인코딩/끝 슬래시 정규화 후 비교)
  ORPHAN_WP        : WP에 publish 상태로 있는데 blog_articles에 대응 wp_post_id가 없음
                     (목록 조회는 status=publish만 — draft 등은 ORPHAN 판정 대상 아님)
  ORPHAN_SHEET     : (플래그 문자열은 UI 호환을 위해 유지) blog_articles row가 status=publish
                     인데 wp_post_id가 없어 WP와 대조 불가

확장 포인트(지금은 미구현, 시그니처/구조만)
  - Restore: WP_TRASH 글 운영자 복원 트리거 → restore_from_trash() 스텁
  - Output Adapter: WordPress 외 PDF/스토어/토스미니앱 등도 같은 sync 구조로
    관리할 수 있도록 WP 호출을 OutputAdapter로 분리(현재 WordPressAdapter만 구현).
"""
import json
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from urllib.parse import unquote

import requests

from . import publisher
from . import telegram_ops
from .config_loader import is_wordpress_ready
from .logger import get_logger
from .scheduler import _create_lock_file, _recover_stale_lock, _release_owned_lock

LOG = get_logger()

# Lock ownership token storage for content_sync.lock
_CONTENT_SYNC_LOCK_TOKENS: dict[str, dict] = {}

# sync_flag 값
FLAG_OK = "OK"
FLAG_WP_DELETED = "WP_DELETED"
FLAG_WP_TRASH = "WP_TRASH"
FLAG_WP_NOT_PUBLISHED = "WP_NOT_PUBLISHED"
FLAG_URL_CHANGED = "URL_CHANGED"
FLAG_ORPHAN_WP = "ORPHAN_WP"
FLAG_ORPHAN_SHEET = "ORPHAN_SHEET"

SYNC_FLAGS = (FLAG_OK, FLAG_WP_DELETED, FLAG_WP_TRASH, FLAG_WP_NOT_PUBLISHED,
              FLAG_URL_CHANGED, FLAG_ORPHAN_WP, FLAG_ORPHAN_SHEET)

# 텔레그램 알림 대상 이상 상태(WP_TRASH는 운영자 의도 삭제, WP_NOT_PUBLISHED는 운영자
# 의도 비공개일 수 있어 알림 제외 — 이력엔 남김)
ALERT_FLAGS = (FLAG_WP_DELETED, FLAG_URL_CHANGED, FLAG_ORPHAN_WP, FLAG_ORPHAN_SHEET)

# 판정 상태 기록 필드(content_sync 소유 state 파일 안의 키)
COL_WP_STATUS = "wp_status"
COL_LAST_SYNCED = "last_synced_at"
COL_SYNC_FLAG = "sync_flag"

_PRODUCTION_WP_TARGET = "production"
_WP_FLAT_KEYS = ("WORDPRESS_URL", "WORDPRESS_USERNAME", "WORDPRESS_APP_PASSWORD", "WORDPRESS_PASSWORD")


# ── 경로 / lock / 이력 (scheduler.py 패턴 재사용, 파일만 분리) ──────
def _schedule_dir(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    d = root / "data" / "schedule"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _lock_path(cfg: dict) -> Path:
    # Publish Scheduler(scheduler.lock)와 절대 겹치지 않는 별도 lock
    return _schedule_dir(cfg) / "content_sync.lock"

def _history_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "sync_history.jsonl"

def _state_path(cfg: dict) -> Path:
    # 직전 판정(post별 sync_flag/wp_status) 보관 — 상태가 바뀐 경우만 이력/알림 대상으로
    # 삼기 위한 content_sync 전용 파일. blog_articles/Sheets에는 쓰지 않는다.
    return _schedule_dir(cfg) / "content_sync_state.json"

def _load_state(cfg: dict) -> dict:
    p = _state_path(cfg)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        LOG.warning("[sync] state 읽기 실패(%s) — 빈 상태로 시작", e)
        return {}

def _save_state(cfg: dict, state: dict):
    p = _state_path(cfg)
    try:
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        LOG.warning("[sync] state 기록 실패: %s", e)

def _acquire_lock(cfg: dict, stale_seconds: int = 3600) -> bool:
    """Acquire content_sync.lock with owner-aware atomic acquisition.

    Uses O_CREAT|O_EXCL for atomic creation, stores owner token (PID, process_start_time, UUID, timestamp),
    verifies process liveness before stale recovery, and protects against PID reuse.
    """
    p = _lock_path(cfg)
    try:
        if not _recover_stale_lock(p, stale_seconds):
            return False
        return _create_lock_file(p, _CONTENT_SYNC_LOCK_TOKENS) is not None
    except Exception:
        return False

def _release_lock(cfg: dict) -> bool:
    """Release content_sync.lock only if current owner matches local token.

    Verifies the lock file's current token matches the token this process acquired,
    preventing accidental deletion of another owner's lock. No local token → no delete.
    """
    return _release_owned_lock(_lock_path(cfg), _CONTENT_SYNC_LOCK_TOKENS)

def _append_history(cfg: dict, record: dict):
    """sync 실행/이상 1건 기록. scheduler.py 의 _append_history 패턴."""
    try:
        with open(_history_path(cfg), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        LOG.warning("sync 이력 기록 실패: %s", e)


# 루프 예외 알림 스팸 방지용 스로틀(scheduler._alert_throttled와 동일 패턴).
_last_alert_ts: dict = {}

def _alert_throttled(cfg: dict, tag: str, level: str, title: str, detail="",
                     event: str = "error", min_interval: int = 1800) -> None:
    """telegram_ops.notify_level을 스로틀링해서 호출(알림 폭주 방지). 실패해도 무시."""
    now = time.time()
    if now - _last_alert_ts.get(tag, 0) < min_interval:
        return
    _last_alert_ts[tag] = now
    try:
        telegram_ops.notify_level(cfg, level, title, detail, event=event)
    except Exception:
        pass


# ── Output Adapter 구조 ───────────────────────────────────────────
# 지금은 WordPress만 대상이지만, 나중에 PDF/스토어/토스미니앱 등 다른 채널을
# 같은 sync 로직으로 관리할 수 있도록 채널 호출부를 이 어댑터 인터페이스로 격리한다.
# content_sync 의 비교/판정 로직은 어댑터가 돌려주는 표준 dict만 알면 된다.
class OutputAdapter:
    """발행 채널 어댑터 추상 인터페이스. 채널마다 구현체를 갈아끼운다."""
    name = "base"

    def is_ready(self) -> bool:
        raise NotImplementedError

    def fetch_one(self, post_id: str) -> dict:
        """단일 글 상태 조회. 표준 반환:
            {"exists": True|False|None, "status": str, "link": str, "error": str}
          - exists True  : 채널에 존재(status/link 유효)
          - exists False : 확실히 없음(404 등) → WP_DELETED 판정 근거
          - exists None  : 일시적/미확정 오류(인증/네트워크) → 판정 보류(덮어쓰지 않음)
        """
        raise NotImplementedError

    def fetch_all(self, since: str | None = None) -> list[dict]:
        """채널의 발행 글 목록. 표준 반환: [{"post_id", "status", "link"}...]
        since(ISO8601) 지정 시 그 이후 발행분만(recent 모드)."""
        raise NotImplementedError

    def restore(self, post_id: str) -> dict:
        """휴지통 → 발행 복원(확장 포인트에서 사용). 표준 반환: publisher.restore_post 형식."""
        raise NotImplementedError


class WordPressAdapter(OutputAdapter):
    """WordPress REST 어댑터. 기존 publisher.py의 WP CRUD 클라이언트를 재사용."""
    name = "wordpress"

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def is_ready(self) -> bool:
        return is_wordpress_ready(self._cfg)

    def fetch_one(self, post_id: str) -> dict:
        res = publisher.get_post(self._cfg, post_id)  # GET /posts/{id} (기존 클라이언트)
        if res.get("success"):
            return {"exists": True, "status": res.get("status", ""),
                    "link": res.get("link", ""), "error": ""}
        err = str(res.get("error", ""))
        if err == "not_found":                       # 404 → 확실히 삭제됨
            return {"exists": False, "status": "", "link": "", "error": "not_found"}
        # 인증/권한/네트워크 등 미확정 오류 → 판정 보류
        return {"exists": None, "status": "", "link": "", "error": err}

    def fetch_all(self, since: str | None = None) -> list[dict]:
        """GET /wp-json/wp/v2/posts 페이지네이션. ORPHAN_WP 판정용(발행 상태만)."""
        if not self.is_ready():
            return []
        base = self._cfg.get("WORDPRESS_URL", "").rstrip("/") + "/wp-json/wp/v2/posts"
        params = {"per_page": 100, "page": 1, "status": "publish",
                  "_fields": "id,link,status,date"}
        if since:
            params["after"] = since
        out: list[dict] = []
        auth = publisher._wp_auth(self._cfg)          # 인증 헬퍼 재사용
        while True:
            try:
                resp = requests.get(base, params=params, auth=auth, timeout=30)
            except Exception as e:
                LOG.warning("[sync] WP 목록 조회 실패(page=%s): %s", params["page"], e)
                break
            # 마지막 페이지를 넘어서면 WP는 400(rest_post_invalid_page_number) 반환
            if resp.status_code == 400:
                break
            if resp.status_code != 200:
                LOG.warning("[sync] WP 목록 조회 HTTP %s (page=%s)", resp.status_code, params["page"])
                break
            batch = resp.json() or []
            if not batch:
                break
            for p in batch:
                out.append({"post_id": str(p.get("id", "")),
                            "status": p.get("status", ""),
                            "link": p.get("link", "")})
            try:
                total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
            except Exception:
                total_pages = 1
            if params["page"] >= total_pages:
                break
            params["page"] += 1
        return out

    def restore(self, post_id: str) -> dict:
        return publisher.restore_post(self._cfg, post_id)  # 기존 복원 클라이언트 재사용


def _production_wp_cfg(cfg: dict) -> dict:
    """cfg 사본에 production WordPress credential set을 적용한다.

    endpoint/인증을 수동 조합하지 않고 config_loader._apply_wp_target(..., "production")을
    그대로 재사용한다(secrets.yaml nested wordpress.* → flat WORDPRESS_* 3개 원자 교체).
    production 세트가 없으면 로컬 flat 값으로 되돌아가지 않도록 flat WP 키를 모두 제거해
    채널을 '미구성'으로 만든다(fail-closed — salarymate.test fallback 없음)."""
    from .config_loader import _apply_wp_target, ConfigError
    wp_cfg = dict(cfg or {})
    try:
        return _apply_wp_target(wp_cfg, _PRODUCTION_WP_TARGET)
    except ConfigError as e:
        LOG.warning("[sync] production WordPress 설정 없음 — 채널 미구성으로 처리: %s", e)
        for k in _WP_FLAT_KEYS:
            wp_cfg.pop(k, None)
        return wp_cfg


def get_adapter(cfg: dict) -> OutputAdapter:
    """현재는 WordPress 하나(CalcMate production). 나중에 채널별 분기(config)만 추가하면 됨."""
    return WordPressAdapter(_production_wp_cfg(cfg))


def _blog_article_repo(cfg: dict):
    """blog_articles 읽기 전용 접근 — wp_blog_sync와 같은 기존 Repository/adapter 재사용."""
    from adapters.db.factory import get_blog_article_storage_adapter
    from repositories.blog_article_repository import BlogArticleRepository
    return BlogArticleRepository(get_blog_article_storage_adapter(cfg))


# ── blog_articles 행 헬퍼 ──────────────────────────────────────────
def _row_post_id(row: dict) -> str:
    return str(row.get("wp_post_id", "") or "").strip()

def _row_url(row: dict) -> str:
    return str(row.get("wp_permalink", "") or "").strip()

def _norm_url(url: str) -> str:
    # 한글 slug는 WP 응답/저장값 사이에 퍼센트 인코딩 여부가 다를 수 있다.
    return unquote(str(url or "").strip()).rstrip("/")

def _row_published_date(row: dict) -> date | None:
    raw = str(row.get("published_at", "") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date()
    except Exception:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except Exception:
            return None

def _is_recent(row: dict, days: int) -> bool:
    d = _row_published_date(row)
    if d is None:
        return True   # 날짜 불명은 안전하게 포함(누락보다 과검사)
    return d >= (date.today() - timedelta(days=days))


# ── 판정 로직 ──────────────────────────────────────────────────────
def _classify(row: dict, wp: dict) -> tuple[str, str]:
    """(sync_flag, wp_status) 반환. wp 는 adapter.fetch_one 표준 dict."""
    exists = wp.get("exists")
    if exists is None:
        return "", ""                        # 미확정 — 호출부에서 skip
    if exists is False:
        return FLAG_WP_DELETED, ""           # 404
    status = str(wp.get("status", "") or "")
    if status == "trash":
        return FLAG_WP_TRASH, status
    if status == "publish":
        wp_link = _norm_url(wp.get("link", ""))
        row_url = _norm_url(_row_url(row))
        if wp_link and row_url and wp_link != row_url:
            return FLAG_URL_CHANGED, status
        return FLAG_OK, status
    # draft/pending/private/future 등: 삭제/고아가 아니라 "비공개 전환"으로만 기록(알림 제외).
    return FLAG_WP_NOT_PUBLISHED, status


# ── 동기화 1회 실행 ────────────────────────────────────────────────
def run_sync_once(cfg: dict, mode: str = "recent", adapter: OutputAdapter | None = None,
                  *, dry_run: bool = False, repo=None) -> dict:
    """WP(CalcMate production) 기준으로 blog_articles 발행 글 상태를 1회 점검.

    mode="recent": 최근 N일(CONTENT_SYNC.recent_days, 기본 30) 발행분만 대조.
    mode="full"  : 전체 스캔.
    dry_run=True : 판정만 하고 state/이력/텔레그램에 아무것도 쓰지 않는다.
    repo         : 테스트 주입용(기본 blog_articles Repository, READ-ONLY로만 사용).
    반환: 요약 dict(검사/변경/이상 카운트 + 이상 목록 + 판정별 후보 목록).
    """
    mode = "full" if str(mode).lower() == "full" else "recent"
    cs = cfg.get("CONTENT_SYNC", {}) or {}
    recent_days = int(cs.get("recent_days", 30))
    adapter = adapter or get_adapter(cfg)
    started = datetime.now()

    if not adapter.is_ready():
        LOG.info("[sync] 채널(%s) 미구성 — 동기화 건너뜀", adapter.name)
        return {"ok": False, "reason": "adapter_not_ready", "mode": mode,
                "checked": 0, "changed": 0, "anomalies": [], "dry_run": dry_run}

    repo = repo or _blog_article_repo(cfg)
    all_rows = repo.list_all()
    state = _load_state(cfg)

    # 대조 대상 행: recent면 최근분만
    if mode == "recent":
        target_rows = [r for r in all_rows if _is_recent(r, recent_days)]
    else:
        target_rows = list(all_rows)

    now_iso = datetime.now().isoformat(timespec="seconds")
    checked = 0
    changed = 0
    skipped = 0
    anomalies: list[dict] = []
    candidates: dict[str, list[str]] = {f: [] for f in SYNC_FLAGS}
    errors: list[dict] = []

    # 1~3·5) blog_articles 각 row의 wp_post_id를 WP와 대조
    for row in target_rows:
        post_id = _row_post_id(row)
        if not post_id:
            # ORPHAN_SHEET: blog_articles가 publish라는데 wp_post_id가 없어 WP와 대조 불가
            if str(row.get("status", "")).strip() == "publish":
                candidates[FLAG_ORPHAN_SHEET].append(str(row.get("article_id", "")))
                if _state_changed(state, row, FLAG_ORPHAN_SHEET, ""):
                    _record(cfg, state, row, FLAG_ORPHAN_SHEET, "", now_iso, anomalies, dry_run)
                    changed += 1
            continue

        checked += 1
        wp = adapter.fetch_one(post_id)
        flag, wp_status = _classify(row, wp)
        if not flag:                          # 미확정 오류 → 이번 회차 판정 보류
            skipped += 1
            errors.append({"post_id": post_id, "error": str(wp.get("error", ""))})
            LOG.warning("[sync] post_id=%s 판정 보류(%s)", post_id, wp.get("error"))
            continue
        candidates[flag].append(post_id)

        # 상태가 달라졌을 때만 state/이력 기록(불필요한 알림 방지)
        if _state_changed(state, row, flag, wp_status):
            _record(cfg, state, row, flag, wp_status, now_iso, anomalies, dry_run)
            changed += 1

    # 4) ORPHAN_WP: WP에 publish로 있는데 blog_articles에 대응 wp_post_id가 없음
    since_iso = None
    if mode == "recent":
        since_iso = (started - timedelta(days=recent_days)).isoformat()
    db_ids = {_row_post_id(r) for r in all_rows if _row_post_id(r)}
    for wp_post in adapter.fetch_all(since=since_iso):
        pid = str(wp_post.get("post_id", "") or "").strip()
        if pid and pid not in db_ids:
            rec = {"flag": FLAG_ORPHAN_WP, "post_id": pid,
                   "url": wp_post.get("link", ""), "wp_status": wp_post.get("status", ""),
                   "article_id": ""}
            candidates[FLAG_ORPHAN_WP].append(pid)
            anomalies.append(rec)
            if not dry_run:
                _append_history(cfg, {"at": now_iso, "mode": mode, **rec})

    summary = {
        "ok": True,
        "mode": mode,
        "adapter": adapter.name,
        "dry_run": dry_run,
        "candidate_count": len(target_rows),
        "matched_count": len(candidates[FLAG_OK]),
        "checked": checked,
        "changed": changed,
        "skipped": skipped,
        "errors": errors,
        "candidates": {f: ids for f, ids in candidates.items() if f != FLAG_OK},
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    if dry_run:
        LOG.info("[sync] dry-run 완료 mode=%s 대상=%d 일치=%d 보류=%d 이상후보=%d (기록/알림 없음)",
                 mode, len(target_rows), summary["matched_count"], skipped, len(anomalies))
        return summary

    _save_state(cfg, state)
    _append_history(cfg, {"at": now_iso, "event": "sync_run", **{
        k: summary[k] for k in ("mode", "adapter", "checked", "changed", "skipped", "anomaly_count")}})
    LOG.info("[sync] 완료 mode=%s 검사=%d 변경=%d 보류=%d 이상=%d",
             mode, checked, changed, skipped, len(anomalies))

    _notify_anomalies(cfg, summary)
    return summary


def _state_key(row: dict) -> str:
    return _row_post_id(row) or "article:" + str(row.get("article_id", "") or "")


def _state_changed(state: dict, row: dict, flag: str, wp_status: str) -> bool:
    prev = state.get(_state_key(row)) or {}
    return (str(prev.get(COL_SYNC_FLAG, "") or "") != flag
            or str(prev.get(COL_WP_STATUS, "") or "") != wp_status)


def _record(cfg: dict, state: dict, row: dict, flag: str, wp_status: str,
            now_iso: str, anomalies: list, dry_run: bool = False):
    """판정 결과를 content_sync 전용 state에 반영하고, 이상 상태면 anomalies/이력에 적재.
    blog_articles(및 Sheets 백업)에는 쓰지 않는다 — 그 테이블의 writer는 wp_blog_sync뿐."""
    article_id = str(row.get("article_id", "") or "").strip()
    if not dry_run:
        state[_state_key(row)] = {COL_SYNC_FLAG: flag, COL_WP_STATUS: wp_status,
                                  COL_LAST_SYNCED: now_iso, "article_id": article_id}
    rec = {"flag": flag, "post_id": _row_post_id(row), "url": _row_url(row),
           "wp_status": wp_status, "article_id": article_id,
           "title": row.get("title", "")}
    if flag in SYNC_FLAGS and flag != FLAG_OK:
        anomalies.append(rec)
        if not dry_run:
            _append_history(cfg, {"at": now_iso, **rec})


def _notify_anomalies(cfg: dict, summary: dict):
    """이상 상태(WP_DELETED/URL_CHANGED/ORPHAN_WP/ORPHAN_SHEET) 요약 텔레그램 전송.
    기존 telegram_ops(=telegram_notifier) 파이프라인 재사용."""
    alerts = [a for a in summary.get("anomalies", []) if a.get("flag") in ALERT_FLAGS]
    if not alerts:
        return
    from collections import Counter
    counts = Counter(a["flag"] for a in alerts)
    head = " · ".join(f"{k} {v}" for k, v in counts.items())
    lines = [f"🔄 [콘텐츠 동기화] 이상 {len(alerts)}건 ({summary.get('mode')})", head, ""]
    for a in alerts[:15]:   # 과다 방지
        title = (a.get("title") or "").strip()
        label = f" — {title[:30]}" if title else ""
        pid = a.get("post_id") or "-"
        lines.append(f"• {a['flag']} · id={pid}{label}")
    if len(alerts) > 15:
        lines.append(f"…외 {len(alerts) - 15}건")
    try:
        telegram_ops.notify(cfg, "\n".join(lines))
    except Exception as e:
        LOG.warning("[sync] 텔레그램 알림 실패: %s", e)


# ── 확장 포인트: Restore (지금은 스텁) ─────────────────────────────
def restore_from_trash(cfg: dict, post_id: str, adapter: OutputAdapter | None = None) -> dict:
    """[확장 포인트 — 미구현]
    WP_TRASH 상태 글을 운영자가 '복원' 트리거하면:
        1) 채널(WP)에서 휴지통 → 발행 복원  (adapter.restore(post_id))
        2) 해당 Sheet 행 sync_flag = OK 로 되돌리고 wp_status/last_synced_at 갱신
    복원 채널 자체는 publisher.restore_post / WordPressAdapter.restore 로 이미 준비돼 있으나,
    운영자 트리거 UI/정책과 함께 붙일 예정이라 지금은 시그니처만 남긴다.
    """
    raise NotImplementedError("restore_from_trash 는 아직 구현되지 않았습니다(확장 포인트).")


# ── 독립 스케줄 루프 (scheduler.run_scheduler_loop 패턴, Publish와 분리) ──
def _due_now(now: datetime, run_at: str, window_min: int = 60) -> bool:
    """now 가 run_at(HH:MM) ~ run_at+window 안에 있으면 True."""
    try:
        h, m = run_at.strip().split(":")
        target = int(h) * 60 + int(m)
    except Exception:
        target = 3 * 60   # 파싱 실패 시 03:00
    now_min = now.hour * 60 + now.minute
    return target <= now_min < target + window_min

def _resolve_mode(cfg: dict, now: datetime) -> str:
    """full_scan_weekday(기본 월요일=0)면 full, 아니면 recent."""
    cs = cfg.get("CONTENT_SYNC", {}) or {}
    try:
        full_wd = int(cs.get("full_scan_weekday", 0))
    except Exception:
        full_wd = 0
    return "full" if now.weekday() == full_wd else "recent"

# ── Catch-up (재부팅/새벽 미가동 대비: 시작 시 오늘분 밀렸으면 즉시 1회) ──
def _last_sync_run_date(cfg: dict) -> date | None:
    """sync_history.jsonl 의 마지막 'sync_run' 이벤트 날짜(= last_synced_at 기록 시점).
    없으면 None. 로컬 파일만 읽어 startup 비용이 거의 없다."""
    p = _history_path(cfg)
    if not p.exists():
        return None
    last = None
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("event") == "sync_run" and rec.get("at"):
                    last = rec["at"]
    except Exception:
        return None
    if not last:
        return None
    try:
        return datetime.fromisoformat(str(last)).date()
    except Exception:
        try:
            return datetime.strptime(str(last)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

def synced_today(cfg: dict) -> bool:
    """오늘 이미 동기화(sync_run)가 1회라도 완료됐는지."""
    return _last_sync_run_date(cfg) == date.today()

def catch_up_if_needed(cfg: dict, adapter: OutputAdapter | None = None) -> dict | None:
    """대시보드/서비스 시작 시 호출. 오늘 아직 동기화가 안 됐으면 즉시 1회 실행.
    mode는 요일 규칙 그대로(full_scan_weekday면 full, 아니면 recent).
    반환: 실행했으면 run_sync_once 요약, 건너뛰면 None."""
    cs = cfg.get("CONTENT_SYNC", {}) or {}
    if not cs.get("enabled", True):
        return None
    if synced_today(cfg):
        LOG.info("[sync] 오늘 이미 동기화됨 — catch-up 생략")
        return None
    if not _acquire_lock(cfg):
        LOG.info("[sync] catch-up: 다른 동기화 진행 중(lock) — 생략")
        return None
    try:
        mode = _resolve_mode(cfg, datetime.now())
        LOG.info("[sync] catch-up 실행 (오늘 미동기화, mode=%s)", mode)
        return run_sync_once(cfg, mode=mode, adapter=adapter)
    finally:
        _release_lock(cfg)


def _content_sync_config_path(cfg: dict) -> Path:
    """cfg가 로드된 config.yaml 경로를 재구성한다(run_sync.py --instance 지원과 동일 규칙).
    cfg에 _root/_instance_id가 없으면(dashboard.py 등 기본 실행) 기본 경로를 쓴다."""
    root = Path(cfg.get("_root") or Path(__file__).resolve().parent.parent)
    instance_id = cfg.get("_instance_id")
    if instance_id and instance_id != "default":
        return root / "config" / "instances" / instance_id / "config.yaml"
    return root / "config" / "config.yaml"


def _content_sync_enabled_now(cfg: dict, fallback: bool) -> bool:
    """루프 tick마다 config.yaml의 CONTENT_SYNC.enabled만 다시 읽는다(안전한 최소 재로딩).
    OPS-SCHED-01/02에서 확정된 원인 보완: run_sync_loop()는 시작 시점의 cs를 그대로
    들고 있어 실행 중 enabled=false로 바뀌어도 반영하지 못했다 — 이 함수를 매 tick
    실행 직전에 호출해 최신 값을 확인한다.
    secrets 병합/스키마 검증 등 load_config()의 나머지 처리는 건드리지 않는다(민감정보가
    아니고 매 tick 확인해야 하므로 가벼운 재읽기로 충분). 파일을 못 읽거나 파싱에
    실패하면 기존에 알던 값(fallback)을 그대로 유지한다 — 재로딩 실패로 자동 Sync가
    오동작(무한 실행 또는 무한 중단)하지 않도록."""
    import yaml
    path = _content_sync_config_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        cs = raw.get("CONTENT_SYNC", {}) or {}
        return bool(cs.get("enabled", fallback))
    except Exception as e:
        LOG.warning("[sync] enabled 재확인 실패(%s: %s) — 이전 값(%s) 유지", path, e, fallback)
        return fallback


def run_sync_loop(cfg: dict, poll_seconds: int | None = None):
    """콘텐츠 동기화 독립 루프. Publish Scheduler와 분리된 lock/이력/스케줄.

    매일 CONTENT_SYNC.run_at(기본 03:00, Publish 슬롯과 겹치지 않는 새벽)에 1회 실행.
    실행 mode: full_scan_weekday면 full, 그 외 recent.
    시작 시 catch-up: 재부팅 등으로 새벽 실행을 놓쳤어도 오늘분이 밀렸으면 즉시 1회 실행.
    실행 직전(각 tick의 due 판정 통과 시)마다 enabled를 다시 확인해, 루프 시작 이후
    config.yaml에서 OFF로 바뀌면 그 시점부터 자동 실행을 건너뛴다.
    """
    cs = cfg.get("CONTENT_SYNC", {}) or {}
    poll = int(poll_seconds if poll_seconds is not None else cs.get("poll_seconds", 60))
    run_at = str(cs.get("run_at", "03:00"))
    LOG.info("[sync] Content Sync 스케줄러 시작 (run_at=%s, poll=%ds)", run_at, poll)
    # 시작 시점 밀린 오늘분 즉시 처리(놓친 새벽 스케줄 복구)
    try:
        catch_up_if_needed(cfg)
    except Exception as e:
        LOG.error("[sync] catch-up 오류: %s", e, exc_info=True)
        _alert_throttled(cfg, "sync_catchup", "ERROR", "Content Sync catch-up 예외", e)
    # 재시작 후 같은 날 중복 실행 방지: 마지막 sync 날짜를 영속 마커에서 복원
    last_run_date = _last_sync_run_date(cfg)
    while True:
        try:
            now = datetime.now()
            if last_run_date != now.date() and _due_now(now, run_at):
                if not _content_sync_enabled_now(cfg, cs.get("enabled", True)):
                    LOG.info("[sync] CONTENT_SYNC.enabled=false(재확인됨) — 이번 주기 자동 실행 건너뜀")
                else:
                    mode = _resolve_mode(cfg, now)
                    if _acquire_lock(cfg):
                        try:
                            run_sync_once(cfg, mode=mode)
                            last_run_date = now.date()
                        finally:
                            _release_lock(cfg)
                    else:
                        LOG.info("[sync] 다른 동기화 진행 중(lock) — 이번 주기 건너뜀")
        except Exception as e:
            LOG.error("[sync] 루프 오류: %s", e, exc_info=True)
            # 루프 예외 — 운영자 즉시 인지(Sprint 1 §1-4). 스팸 방지 스로틀.
            _alert_throttled(cfg, "sync_loop", "ERROR", "Content Sync 루프 예외", e)
        time.sleep(poll)
