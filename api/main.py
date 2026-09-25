"""api/main.py — FastAPI 엔트리포인트 (최소 구조).

이번 Feature(Blog Scheduler / Publishing Policy / Settings)에 필요한
router만 등록한다. unrelated router(health, dashboard, calculators, logs,
costs, publish, auth, blog, strategy_room, workboard, sites)는 제외한다.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers.scheduler import router as scheduler_router
from api.routers.publishing_policy import router as publishing_policy_router
from api.routers.settings import router as settings_router
from api.services.worker_manager import get_worker_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WorkerManager singleton을 여기서 1회만 생성한다(§7). 이 생성은 워커를 기동하지
    # 않는다 — WorkerManager는 상태를 "조회"만 하는 stateless 컴포넌트이기 때문이다.
    get_worker_manager()
    yield


app = FastAPI(
    title="CalcMate API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(scheduler_router)
app.include_router(publishing_policy_router)
app.include_router(settings_router)
