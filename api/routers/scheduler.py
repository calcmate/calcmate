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
from api.services import calculator_quick_action_service
from api.services import pipeline_run_service
from api.services import integrated_run_service
from api.services import content_sync_service
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


# ── Calculator Quick Action: 계산기 생성 ───────────────────────────────────
# dashboard.py "🧮 계산기 생성" 버튼과 동일. calculator_quick_action_service.run_once() 재사용.
@router.post("/calculator/run-once")
def post_calculator_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_quick_action_service.run_once()
        return ok(result)
    except calculator_quick_action_service.CalculatorQuickActionBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── Pipeline Quick Action: 파이프라인 실행 ─────────────────────────────────
# dashboard.py "▶ 파이프라인 실행(전량)" 버튼과 동일. pipeline_run_service.run_once() 재사용.
@router.post("/pipeline/run-once")
def post_pipeline_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = pipeline_run_service.run_once()
        return ok(result)
    except pipeline_run_service.PipelineRunBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── Pipeline Quick Action: 글 생성(1건) ─────────────────────────────────────
# dashboard.py "📝 글 생성(1건)" 버튼과 동일(main.run_once(cfg, max_count=1)).
# /pipeline/run-once(전량)·/blog/run-once(Blog Scheduler)와 다른 기능이다.
@router.post("/pipeline/run-one")
def post_pipeline_run_one(user: CurrentUser = Depends(require_admin)):
    try:
        result = pipeline_run_service.run_one()
        return ok(result)
    except pipeline_run_service.PipelineRunBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── Integrated Quick Action: 통합 실행 ──────────────────────────────────────
# dashboard.py "▶ 실행" 버튼과 동일. integrated_run_service.run_once() 재사용.
class IntegratedRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: Literal["Calculator만", "WordPress만", "순차(Calculator→WordPress)"] = "순차(Calculator→WordPress)"
    # CURRENT-SITE-02: React 현재 Site 선택(dashboard.py current_site_id). 생략하면
    # dashboard.py 기본값(전체 site 목록의 첫 번째)을 쓴다 — 기존 호출 호환.
    site_id: str | None = Field(default=None, min_length=1)


@router.post("/integrated/run-once")
def post_integrated_run_once(
    body: IntegratedRunRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = integrated_run_service.run_once(order=body.order, site_id=body.site_id)
        return ok(result)
    except integrated_run_service.IntegratedRunSiteNotFound as e:
        return fail("VALIDATION_ERROR", str(e))
    except calculator_quick_action_service.CalculatorQuickActionBusy as e:
        return fail("LOCK_CONFLICT", str(e))
    except pipeline_run_service.PipelineRunBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── Content Sync Status ─────────────────────────────────────────────────────
# pending/processing/failed 개수만 반환 (상세 리스트는 /content-sync/pending 등 조회)
# CONTENT_SYNC.enabled는 ConfigService에서 조회. ContentSyncWorker 상태는 WorkerManager에서 조회.
@router.get("/content-sync/status")
def get_content_sync_status():
    from api.services.config_service import ConfigService
    from api.services.worker_manager import get_worker_manager
    pending = dual_adapter.list_pending_sync()
    processing = dual_adapter.list_all_sync("processing")
    failed = dual_adapter.list_all_sync("failed_permanent")
    enabled = bool(ConfigService().get_section("CONTENT_SYNC").get("enabled", True))
    worker_status = get_worker_manager().get_status("content_sync")
    return ok({
        "enabled": enabled,
        "running": worker_status.get("running", False),
        "thread_alive": worker_status.get("thread_alive", False),
        "pending_count": len(pending),
        "processing_count": len(processing),
        "failed_count": len(failed),
        "total_queued": len(pending) + len(processing) + len(failed),
    })


# ── Content Sync Manual Run ─────────────────────────────────────────────────
# dashboard.py "🔄 Sync Now" 버튼과 동일. content_sync_service.run_once() 재사용.
class ContentSyncRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["recent", "full"] = "recent"


@router.post("/content-sync/run-once")
def post_content_sync_run_once(
    body: ContentSyncRunRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = content_sync_service.run_once(mode=body.mode)
        return ok(result)
    except content_sync_service.ContentSyncBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── Calculator WebApp Scheduler ──────────────────────────────────────────────
# Calculator WebApp Scheduler (CALC_WEBAPP_SCHEDULE) — 정적 계산기 웹앱 자동 생성
# SEO Calculator Quick Action(/calculator/run-once)과는 완전히 별개다.

class CalcWebAppSlot(BaseModel):
    start: str
    end: str


class CalcWebAppConfigPatch(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    targets: list[str] | None = None
    poll_seconds: int | None = None


@router.get("/calculator/status")
def get_calculator_scheduler_status():
    """Calculator WebApp Scheduler 상태 조회 (enabled, running, thread_alive)."""
    try:
        return ok(get_worker_manager().get_status("calc_webapp"))
    except KeyError as e:
        return fail("WORKER_NOT_FOUND", str(e))


@router.get("/calculator/config")
def get_calculator_config():
    """Calculator WebApp Scheduler 설정 조회 (enabled, mode, targets, poll_seconds)."""
    try:
        return ok(ConfigService().get_section("CALC_WEBAPP_SCHEDULE"))
    except ConfigSectionNotAllowed as e:
        return fail("SECTION_NOT_ALLOWED", str(e))


@router.patch("/calculator/config")
def patch_calculator_config(
    body: CalcWebAppConfigPatch,
    user: CurrentUser = Depends(require_admin)
):
    """Calculator WebApp Scheduler 설정 변경 (enabled, mode, targets, poll_seconds)."""
    try:
        result = ConfigService().patch_calc_webapp_schedule(
            enabled=body.enabled,
            mode=body.mode,
            targets=body.targets,
            poll_seconds=body.poll_seconds,
        )
        return ok(result)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.post("/calculator-webapp/run-once")
def post_calculator_webapp_run_once(user: CurrentUser = Depends(require_admin)):
    """Calculator WebApp Scheduler 수동 1회 실행 (Build → QA → _site).

    주의: 이 endpoint는 SEO Calculator Quick Action(/calculator/run-once)과
    완전히 별개다. 이 endpoint는 정적 계산기 웹앱 생성을 담당한다.
    GitHub Deploy/Registry Publish는 자동 실행하지 않는다(qa_deploy 모드라도).
    """
    from api.services import calculator_webapp_scheduler_service
    try:
        result = calculator_webapp_scheduler_service.run_once()
    except calculator_webapp_scheduler_service.CalculatorWebAppSchedulerBusy as e:
        return fail("LOCK_CONFLICT", str(e))
    return ok(result)


# ── Publishing Planner Manual Run ────────────────────────────────────────────
# dashboard.py "▶ 수동 Planner 실행" 버튼과 동일. publishing_planner_service.run_once() 재사용.
# 기존 planner loop(WorkerManager) 또는 Streamlit 수동 실행과 중복되지 않음:
# - WorkerManager는 AUTO_PUBLISHING.enabled + FASTAPI_WORKER_MODE=1일 때만 자동 실행
# - 이 endpoint는 AUTO_PUBLISHING/BLOG_SCHEDULE 상태와 무관하게 1회 실행만 요청
# - modules.publishing_planner.run_planner_once()는 자체 중복검사/lock 내장(fail-closed 반환)
@router.post("/planner/run-once")
def post_planner_run_once(user: CurrentUser = Depends(require_admin)):
    result = publishing_planner_service.run_once()
    return ok(result)
