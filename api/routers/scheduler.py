"""api/routers/scheduler.py — Blog Scheduler 라우터 (최소 구조).

STEP 18-C: Blog Scheduler status 조회 (WorkerManager 상태 조회만, 실제 실행 없음).
STEP 18-E: Blog Scheduler 관리 기능(config 조회/저장, today, history, run-once) 추가.
run-once는 modules.scheduler.run_scheduler_loop()를 기동하지 않고, main.resolve_blog_publish_fn()이
반환하는 기존 엔진 함수를 정확히 1회만 호출한다(api/services/blog_scheduler_service.py 경유).
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
