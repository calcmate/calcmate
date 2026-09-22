"""api/routers/scheduler.py — Scheduler 라우터.

STEP 18-C: status 3종(WorkerManager 상태 조회만, 실제 실행 없음).
STEP 18-E: Blog Scheduler 관리 기능(config 조회/저장, today, history, run-once) 추가.
run-once는 modules.scheduler.run_scheduler_loop()를 기동하지 않고, main.resolve_blog_publish_fn()이
반환하는 기존 엔진 함수를 정확히 1회만 호출한다(api/services/blog_scheduler_service.py 경유).
STEP S10: Content Sync 수동 실행(run-once) 추가 — modules.content_sync.run_sync_once()를
그대로 호출한다(api/services/content_sync_service.py 경유). Calculator Scheduler는
이번 STEP에서도 조회 전용을 유지한다.
STEP S11: Dashboard Quick Action 「🧮 계산기 생성」 수동 실행(POST
/calculator/run-once) 추가 — modules.calculator_pipeline.run_calculator_once()를
그대로 호출한다(api/services/calculator_quick_action_service.py 경유). 이 endpoint는
GET /calculator/status가 조회하는 CALC_WEBAPP_SCHEDULE 라인과는 무관한 별도
파이프라인이다.
STEP S12: Dashboard Quick Action 「▶ 파이프라인 실행(전량)」 수동 실행(POST
/pipeline/run-once) 추가 — main.py의 run_once(cfg)를 그대로 호출한다
(api/services/pipeline_run_service.py 경유). /blog/run-once(blog_scheduler_service,
modules.blog_scheduler_adapter 경유)와는 다른 함수를 호출하는 별도 endpoint다.
STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) 수동 실행(POST
/integrated/run-once) 추가 — 새 pipeline이 아니라 site의 활성 platforms에 따라
/calculator/run-once(S11)와 /pipeline/run-once(S12)를 재사용하는 얇은 dispatcher
(api/services/integrated_run_service.py 경유).
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok, fail
from api.services.worker_manager import get_worker_manager
from api.services.config_service import ConfigService, ConfigSectionNotAllowed
from api.services import blog_scheduler_service
from api.services import content_sync_service
from api.services import calculator_quick_action_service
from api.services import pipeline_run_service
from api.services import integrated_run_service

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/blog/status")
def get_blog_scheduler_status():
    return ok(get_worker_manager().get_status("blog"))


@router.get("/calculator/status")
def get_calculator_scheduler_status():
    return ok(get_worker_manager().get_status("calculator"))


@router.get("/content-sync/status")
def get_content_sync_status():
    return ok(get_worker_manager().get_status("content_sync"))


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


@router.post("/blog/run-once")
def post_blog_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = blog_scheduler_service.run_once()
        return ok(result)
    except blog_scheduler_service.BlogSchedulerDisabled as e:
        return fail("SCHEDULER_DISABLED", str(e))
    except blog_scheduler_service.BlogSchedulerBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── STEP S10: Content Sync 수동 실행 ─────────────────────────────────────


class ContentSyncRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["recent", "full"] = "recent"


@router.post("/content-sync/run-once")
def post_content_sync_run_once(
    body: ContentSyncRunRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = content_sync_service.run_once(body.mode)
        return ok(result)
    except content_sync_service.ContentSyncBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── STEP S11: Dashboard Quick Action 「🧮 계산기 생성」 수동 실행 ──────────
# /api/scheduler/calculator/status(WorkerManager, CALC_WEBAPP_SCHEDULE)와는
# 별개의 파이프라인(modules.calculator_pipeline.run_calculator_once, SEO 글
# 생산)이다 — 혼동 방지를 위해 calculator_quick_action_service.py를 참고.


@router.post("/calculator/run-once")
def post_calculator_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_quick_action_service.run_once()
        return ok(result)
    except calculator_quick_action_service.CalculatorQuickActionBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── STEP S12: Dashboard Quick Action 「▶ 파이프라인 실행(전량)」 수동 실행 ──
# main.py의 run_once(cfg)를 그대로 호출한다 — /api/scheduler/blog/run-once
# (blog_scheduler_service, modules.blog_scheduler_adapter 경유)와는 다른 함수다.
# 자세한 구분은 pipeline_run_service.py 참고.


@router.post("/pipeline/run-once")
def post_pipeline_run_once(user: CurrentUser = Depends(require_admin)):
    try:
        result = pipeline_run_service.run_once()
        return ok(result)
    except pipeline_run_service.PipelineRunBusy as e:
        return fail("LOCK_CONFLICT", str(e))


# ── STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) 수동 실행 ────────
# 새 pipeline이 아니라 /calculator/run-once(S11)·/pipeline/run-once(S12)를
# site의 활성 platforms에 따라 골라 호출하는 dispatcher. 자세한 분기는
# integrated_run_service.py 참고.


class IntegratedRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: Literal["순차(Calculator→WordPress)", "Calculator만", "WordPress만"] = "순차(Calculator→WordPress)"


@router.post("/integrated/run-once")
def post_integrated_run_once(
    body: IntegratedRunRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = integrated_run_service.run_once(body.order)
        return ok(result)
    except (calculator_quick_action_service.CalculatorQuickActionBusy,
            pipeline_run_service.PipelineRunBusy) as e:
        return fail("LOCK_CONFLICT", str(e))
