"""api/main.py — FastAPI 엔트리포인트 (Worker Owner).

React Dashboard
  ↓
FastAPI
  ├─ API
  ├─ Blog Scheduler Worker
  └─ One-off Scheduler Worker
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers.scheduler import router as scheduler_router
from api.routers.publishing_policy import router as publishing_policy_router
from api.routers.settings import router as settings_router
from api.routers.health import router as health_router
from api.routers.dashboard import router as dashboard_router
from api.routers.calculators import router as calculators_router
from api.routers.logs import router as logs_router
from api.routers.costs import router as costs_router
from api.routers.publish import router as publish_router
from api.routers.auth import router as auth_router
from api.routers.blog import router as blog_router
from api.routers.strategy_room import router as strategy_room_router
from api.routers.workboard import router as workboard_router
from api.routers.sites import router as sites_router
from api.services.worker_manager import get_worker_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. WorkerManager 초기화
    wm = get_worker_manager()

    # 2. Blog Scheduler worker 시작 (BLOG_SCHEDULE.enabled인 경우)
    from api.services.worker_manager import _worker_enabled
    if _worker_enabled("blog"):
        get_worker_manager().start_worker("blog")

    # 3. One-off Scheduler worker 시작 (BLOG_SCHEDULE.enabled OR AUTO_PUBLISHING.enabled)
    from api.services.worker_manager import _worker_enabled as _oneoff_enabled
    if _oneoff_enabled("oneoff"):
        get_worker_manager().start_worker("oneoff")

    try:
        yield
    finally:
        # Shutdown: 모든 worker 정지
        get_worker_manager().stop_all_workers()


app = FastAPI(
    title="CalcMate API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(scheduler_router)
app.include_router(publishing_policy_router)
app.include_router(settings_router)
app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(calculators_router)
app.include_router(logs_router)
app.include_router(costs_router)
app.include_router(publish_router)
app.include_router(auth_router)
app.include_router(blog_router)
app.include_router(strategy_room_router)
app.include_router(workboard_router)
app.include_router(sites_router)
