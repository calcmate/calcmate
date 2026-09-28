"""api/services/publish_service.py — Article Publish/Trash 조회+쓰기 서비스
(STEP 18-P: 조회, STEP 18-R: Edit/Trash/Restore 쓰기 추가).

조회는 dashboard.py의 "📋 발행 목록"(dashboard.py:585-687)/"🗑️ 휴지통"
(dashboard.py:689-743)과 동일한 데이터 소스(cached_posts() → modules.dashboard_cache
의 "articles" 테이블 미러)를 그대로 재사용한다.

쓰기(Edit/Trash/Restore)는 dashboard.py가 실제로 쓰는 것과 정확히 동일한 두 계층만
재사용한다 — 새 WordPress client나 새 DB access layer를 만들지 않는다:
  - modules.publisher.update_post() / delete_post(force=False) / restore_post()
  - repositories.article_repository.ArticleRepository.update_status() / append_history()
쓰기 경로의 "리소스 조회"만은 dashboard_cache(빠른 SQLite 미러, Google Sheets 실시간
호출 없음)를 사용한다 — ArticleRepository.get_by_id()는 DualAdapter를 통해 매 호출마다
Sheets를 먼저 시도하므로(STEP 18-L에서 확인된 특성), 단순 조회에는 쓰지 않는다.
이 판단으로 "Google Sheets 호출 = 0" 요구사항을 자연스럽게 만족한다.
"""
from modules.config_loader import load_config
from modules.dashboard_cache import read as cache_read

from api.services.log_service import mask_secrets

# dashboard.py:595의 "발행 목록" 탭이 실제로 표시하는 상태값 집합과 정확히 동일하게 유지한다.
PUBLISH_STATUSES = ("발행완료", "검수대기", "수정됨")
TRASH_STATUS = "휴지통"


def _summarize(row: dict) -> dict:
    return {
        "id": row.get("ID", ""),
        "title": mask_secrets(row.get("최종추천제목", "")),
        "status": row.get("상태값", ""),
        "published_at": row.get("발행일시", ""),
        "url": mask_secrets(row.get("발행 URL", "")),
        "wp_post_id": row.get("wp_post_id", ""),
    }


def _articles() -> list:
    cfg = load_config()
    return cache_read(cfg, "articles")


def get_all_articles() -> dict:
    """§5 GET /api/publish — 전체 article 수, 상태별 count, 전체 목록."""
    rows = _articles()
    by_status: dict = {}
    for r in rows:
        status = str(r.get("상태값", "")).strip() or "(미상)"
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "articles": [_summarize(r) for r in rows],
    }


def get_publish_articles() -> dict:
    """§5 GET /api/publish/articles — dashboard.py 발행 목록 탭과 동일한 필터
    (상태값 in 발행완료/검수대기/수정됨), 최신 발행일시 우선 정렬(dashboard.py:596과 동일)."""
    rows = [r for r in _articles() if r.get("상태값") in PUBLISH_STATUSES]
    rows.sort(key=lambda r: r.get("발행일시", ""), reverse=True)
    return {"total": len(rows), "articles": [_summarize(r) for r in rows]}


def get_trash_articles() -> dict:
    """§5 GET /api/trash — dashboard.py 휴지통 탭과 동일한 필터(상태값 == 휴지통),
    동일 정렬(dashboard.py:699)."""
    rows = [r for r in _articles() if r.get("상태값") == TRASH_STATUS]
    rows.sort(key=lambda r: r.get("발행일시", ""), reverse=True)
    return {"total": len(rows), "articles": [_summarize(r) for r in rows]}


# ══════════════════════════════════════════════════════════════════════════
# STEP 18-R — Write 경로(Edit / Trash / Restore). require_admin() 뒤에서만 호출된다.
# ══════════════════════════════════════════════════════════════════════════


class ArticleNotFound(Exception):
    """§12 step 4: 리소스 조회 실패 → 라우터에서 404로 변환."""


class ArticleValidationError(Exception):
    """§12 step 3/5: 입력값/확인문구 오류 → 라우터에서 400으로 변환."""


def find_article_row(article_id: str) -> dict:
    """dashboard_cache 미러에서 article 1건을 찾는다(Google Sheets 실시간 호출 없음).
    §12 step 4 '리소스 조회'에 해당 — 이 단계에서는 어떤 write도 수행하지 않는다."""
    for row in _articles():
        if str(row.get("ID", "")) == str(article_id):
            return row
    raise ArticleNotFound(article_id)


def _require_wp_post_id(row: dict) -> str:
    wp_id = str(row.get("wp_post_id", "") or "").strip()
    if not wp_id:
        # dashboard.py:604/709와 동일한 사유 — wp_post_id 없는 글은 편집/복원 대상이 아니다.
        raise ArticleValidationError("wp_post_id가 없어 이 작업을 수행할 수 없습니다.")
    return wp_id


def _repo():
    """dashboard.py의 발행목록/휴지통 탭이 실제로 만드는 것과 동일한 조합
    (repositories.article_repository.ArticleRepository(get_db_adapter(cfg)))."""
    from adapters.db.factory import get_db_adapter
    from repositories.article_repository import ArticleRepository

    cfg = load_config()
    return ArticleRepository(get_db_adapter(cfg)), cfg


def edit_article(article_id: str, title: str | None, content: str | None,
                  excerpt: str | None, actor_id: str, actor_role: str) -> dict:
    """dashboard.py:606-632 "✏️ 수정"과 동일한 순서: publisher.update_post() 성공 시에만
    로컬 반영(update_status + append_history). 실패 시 로컬 완전 미변경."""
    import modules.publisher as publisher
    from api.auth.models import AuditEvent
    from api.auth.service import record_audit_event

    row = find_article_row(article_id)
    wp_id = _require_wp_post_id(row)
    if title is None and content is None and excerpt is None:
        raise ArticleValidationError("수정할 필드가 없습니다(title/content/excerpt 모두 비어있음).")

    repo, cfg = _repo()
    res = publisher.update_post(cfg, wp_id, title=title, content=content, excerpt=excerpt)

    if res.get("success"):
        repo.update_status(article_id, "수정됨")
        repo.append_history(article_id, "update", {
            "wp_post_id": res.get("wp_post_id", wp_id),
            "modified": res.get("modified", ""),
            "operator": "api",
        })
    record_audit_event(AuditEvent(
        actor_id=actor_id, actor_role=actor_role, action="publish_edit",
        resource="article", resource_id=str(article_id),
        result="success" if res.get("success") else "failed",
    ))
    return res


def trash_article(article_id: str, confirmation: str, actor_id: str, actor_role: str) -> dict:
    """dashboard.py:634-685 "🗑️ 삭제(휴지통 이동)"과 동일한 순서:
    get_post() 재확인 → delete_post(force=False) → 성공 시에만 로컬 반영.
    force=True(영구삭제)는 절대 사용하지 않는다."""
    import modules.publisher as publisher
    from api.auth.models import AuditEvent
    from api.auth.service import record_audit_event

    row = find_article_row(article_id)
    wp_id = _require_wp_post_id(row)
    if confirmation != "TRASH":
        raise ArticleValidationError('confirmation 값이 "TRASH"와 일치해야 합니다.')

    cfg = load_config()
    check = publisher.get_post(cfg, wp_id)
    if not check.get("success"):
        record_audit_event(AuditEvent(
            actor_id=actor_id, actor_role=actor_role, action="trash",
            resource="article", resource_id=str(article_id), result="failed",
        ))
        return check

    repo, _ = _repo()
    res = publisher.delete_post(cfg, wp_id, force=False)

    if res.get("success"):
        repo.update_status(article_id, "휴지통")
        repo.append_history(article_id, "trash", {
            "wp_post_id": wp_id,
            "title": check.get("title", ""),
            "operator": "api",
            "wp_status": res.get("wp_status", ""),
            "force": False,
        })
    record_audit_event(AuditEvent(
        actor_id=actor_id, actor_role=actor_role, action="trash",
        resource="article", resource_id=str(article_id),
        result="success" if res.get("success") else "failed",
    ))
    return res


def restore_article(article_id: str, confirmation: str, actor_id: str, actor_role: str) -> dict:
    """dashboard.py:689-741 "♻️ 복원"과 동일한 순서: 로컬 상태가 휴지통일 때만 시도,
    publisher.restore_post() 성공 시에만 로컬 반영."""
    import modules.publisher as publisher
    from api.auth.models import AuditEvent
    from api.auth.service import record_audit_event

    row = find_article_row(article_id)
    if row.get("상태값") != TRASH_STATUS:
        raise ArticleValidationError("휴지통 상태가 아닌 Article은 복원할 수 없습니다.")
    wp_id = _require_wp_post_id(row)
    if confirmation != "RESTORE":
        raise ArticleValidationError('confirmation 값이 "RESTORE"와 일치해야 합니다.')

    repo, cfg = _repo()
    res = publisher.restore_post(cfg, wp_id)

    if res.get("success"):
        # 이 시점에서 로컬 상태는 이미 "휴지통"으로 확인됐다(위에서 gate) — WP가
        # already_restored=True를 반환해도(WP-로컬 불일치) 로컬은 항상 동기화한다.
        repo.update_status(article_id, "발행완료")
        repo.append_history(article_id, "restore", {
            "wp_post_id": wp_id,
            "title": res.get("title", ""),
            "operator": "api",
            "wp_status": res.get("wp_status", ""),
            "restored_from": TRASH_STATUS,
            "already_restored": bool(res.get("already_restored")),
        })
    record_audit_event(AuditEvent(
        actor_id=actor_id, actor_role=actor_role, action="restore",
        resource="article", resource_id=str(article_id),
        result="success" if res.get("success") else "failed",
    ))
    return res
