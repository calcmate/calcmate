"""api/routers/scheduler.py — Blog Scheduler 라우터 (최소 구조).

STEP 18-C: Blog Scheduler status 조회 (WorkerManager 상태 조회만, 실제 실행 없음).
STEP 18-E: Blog Scheduler 관리 기능(config 조회/저장, today, history, run-once) 추가.
run-once는 modules.scheduler.run_scheduler_loop()를 기동하지 않고, main.resolve_blog_publish_fn()이
반환하는 기존 엔진 함수를 정확히 1회만 호출한다(api/services/blog_scheduler_service.py 경유).
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok, fail
from api.services.worker_manager import get_worker_manager
from api.services.config_service import ConfigService, ConfigSectionNotAllowed
from api.services import blog_scheduler_service
from api.services import topic_pool_service
from api.services import publishing_planner_service
from modules.config_loader import load_config
from adapters.db import dual_adapter

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/blog/status")
def get_blog_scheduler_status():
    return ok(get_worker_manager().get_status("blog"))


# ── STEP 18-E: Blog Scheduler 관리 ──────────────────────────────────────


class BlogSlot(BaseModel):
    start: str
    end: str


class BlogScheduleConfigPatch(BaseModel):
    enabled: bool
    mode: str
    publish_slots: list[BlogSlot]
    weekday_only: bool = False


@router.get("/blog/config")
def get_blog_config():
    try:
        return ok(ConfigService().get_section("BLOG_SCHEDULE"))
    except ConfigSectionNotAllowed as e:
        return fail("SECTION_NOT_ALLOWED", str(e))


@router.patch("/blog/config")
def patch_blog_config(body: BlogScheduleConfigPatch, user: CurrentUser = Depends(require_admin)):
    try:
        result = ConfigService().patch_blog_schedule(
            enabled=body.enabled,
            mode=body.mode,
            publish_slots=[slot.model_dump() for slot in body.publish_slots],
            weekday_only=body.weekday_only,
        )
        return ok(result)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.get("/blog/today")
def get_blog_today():
    return ok(blog_scheduler_service.get_today_schedule())


@router.get("/blog/history")
def get_blog_history():
    return ok({"records": blog_scheduler_service.get_history()})


@router.get("/blog/oneoff")
def get_blog_oneoff():
    return ok({"reservations": blog_scheduler_service.get_oneoff_reservations()})


# CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01: 수동 1회성 예약 생성.
# blog_scheduler_service.create_oneoff_reservation()가 modules.scheduler.
# add_oneoff_reservation()에 그대로 위임한다(timezone/mode 검증, lock, 중복
# 방지, reservation schema는 그 함수 책임 — 여기서 재구현하지 않음).
class OneoffReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: str
    mode: Literal["draft", "publish"] = "draft"
    topic_id: str | None = None


@router.post("/blog/oneoff")
def post_blog_oneoff(
    body: OneoffReservationCreate,
    user: CurrentUser = Depends(require_admin)
):
    try:
        entry = blog_scheduler_service.create_oneoff_reservation(
            body.scheduled_at, body.mode, topic_id=body.topic_id,
        )
        return ok(entry)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))
    except RuntimeError as e:
        return fail("LOCK_CONFLICT", str(e))


# CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01: Topic Pool 조회(React가
# approved Topic을 확인할 수 있는 최소 GET). topic_pool_service.list_topics()가
# modules.topic_pool.list_topics()에 그대로 위임한다.
@router.get("/topics")
def get_topics(status: str | None = None):
    return ok({"topics": topic_pool_service.list_topics(status=status)})


# CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01: Publishing Planner 수동 1회
# 실행. publishing_planner_service.run_once()가 modules.publishing_planner.
# run_planner_once()에 그대로 위임한다(approved Topic 검색/capacity/slot 계산/
# WP 중복검사/reservation 생성/Topic 상태 변경은 전부 그 함수 책임).
@router.post("/planner/run-once")
def post_planner_run_once(user: CurrentUser = Depends(require_admin)):
    return ok(publishing_planner_service.run_once())


@router.post("/blog/run-once")
def post_blog_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = blog_scheduler_service.run_once()
        return ok(result)
    except blog_scheduler_service.BlogSchedulerDisabled as e:
        return fail("SCHEDULER_DISABLED", str(e))
    except blog_scheduler_service.BlogSchedulerBusy as e:
        return fail("LOCK_CONFLICT", str(e))


class BlogRunOnceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["draft", "publish"] = "draft"


@router.post("/blog/run-once/oneoff")
def post_blog_run_once_oneoff(
    body: BlogRunOnceRequest,
    user: CurrentUser = Depends(require_admin)
):
    """1회 실행 전용 endpoint. BLOG_SCHEDULE.enabled와 무관하게 실행되며,
    사용자가 선택한 mode(draft/publish)를 전달한다."""
    try:
        result = blog_scheduler_service.run_once(mode=body.mode)
        return ok(result)
    except blog_scheduler_service.BlogSchedulerDisabled as e:
        return fail("SCHEDULER_DISABLED", str(e))
    except blog_scheduler_service.BlogSchedulerBusy as e:
        return fail("LOCK_CONFLICT", str(e))
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))


# ── STEP 65: Content Sync Pending 큐 조회 / 수동 Retry / Resume ───────────────
# Streamlit dashboard.py "🔁 동기화 복구" 탭(dashboard.py:3887-3989) 이관.
# adapters.db.dual_adapter의 기존 함수(list_pending_sync, list_all_sync,
# retry_pending_sync, resume_failed_sync)를 그대로 재사용한다.
# 새로운 retry 로직/큐 스키마/lock 메커니즘은 전혀 만들지 않는다.


class SyncQueueItem(BaseModel):
    """dual_adapter.enqueue_sync()가 생성하는 큐 레코드 스키마와 호환."""
    model_config = ConfigDict(extra="forbid")

    id: str
    op: Literal["insert", "update", "delete"]
    table: str
    row: dict
    row_id: str
    direction: Literal["sheets_to_sqlite", "sqlite_to_sheets"] | None = None
    source_adapter: Literal["DualAdapter", "SQLiteFirstAdapter"] | None = None
    delete_targets: dict | None = None
    retry_count: int = 0
    status: Literal["pending", "processing", "failed_permanent"]
    error: str = ""
    created_at: str
    last_attempt_at: str | None = None


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qid: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qid: str = Field(min_length=1)


# ── GET /content-sync/pending ─────────────────────────────────────────────────
@router.get("/content-sync/pending")
def get_pending_sync():
    """pending_sync 큐에서 status='pending'인 항목만 조회."""
    return ok(dual_adapter.list_pending_sync())


# ── GET /content-sync/processing ──────────────────────────────────────────────
@router.get("/content-sync/processing")
def get_processing_sync():
    """pending_sync 큐에서 status='processing'인 항목만 조회."""
    return ok(dual_adapter.list_all_sync("processing"))


# ── GET /content-sync/failed ──────────────────────────────────────────────────
@router.get("/content-sync/failed")
def get_failed_sync():
    """pending_sync 큐에서 status='failed_permanent'인 항목만 조회."""
    return ok(dual_adapter.list_all_sync("failed_permanent"))


# ── POST /content-sync/retry ──────────────────────────────────────────────────
@router.post("/content-sync/retry")
def post_retry_sync(
    body: RetryRequest,
    user: CurrentUser = Depends(require_admin),
):
    """pending_sync 큐 항목 1개를 정확히 1회 재시도한다.

    cfg는 서버에서 load_config()로 조달하며, client에서 받지 않는다.
    dual_adapter.retry_pending_sync()의 반환값을 그대로 전달한다.
    """
    cfg = load_config()
    result = dual_adapter.retry_pending_sync(body.qid, cfg)
    if result.get("result") == "success":
        return ok(result)
    if result.get("result") in ("not_found", "unsupported", "duplicate"):
        return fail(result["result"].upper(), result.get("detail", ""))
    # failed
    return fail("RETRY_FAILED", result.get("detail", ""))


# ── POST /content-sync/resume ─────────────────────────────────────────────────
@router.post("/content-sync/resume")
def post_resume_sync(
    body: ResumeRequest,
    user: CurrentUser = Depends(require_admin),
):
    """failed_permanent 상태의 큐 항목을 pending으로 되돌린다.

    실제 재시도는 하지 않고 상태만 복구한다(다음 재시도는 retry endpoint가 담당).
    """
    result = dual_adapter.resume_failed_sync(body.qid)
    if result.get("result") == "success":
        return ok(result)
    if result.get("result") in ("not_found", "unsupported"):
        return fail(result["result"].upper(), result.get("detail", ""))
    return fail("RESUME_FAILED", result.get("detail", ""))
