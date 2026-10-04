"""api/main.py — FastAPI 엔트리포인트 (Worker Owner).

React Dashboard
  ↓
FastAPI
  ├─ API
  ├─ Blog Scheduler Worker
  ├─ One-off Scheduler Worker
  ├─ Content Sync Worker
  ├─ Publishing Planner Worker
  ├─ WP Blog Sync Worker
  └─ Calculator WebApp Scheduler Worker
"""
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import JSONResponse

from api.dependencies import fail

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
from api.routers.topic_reconciliation import router as topic_reconciliation_router
from api.routers.assistant import router as assistant_router
from api.routers.workspace import router as workspace_router
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
    if _worker_enabled("oneoff"):
        get_worker_manager().start_worker("oneoff")

    # 4. Content Sync Worker 시작 (CONTENT_SYNC.enabled AND FASTAPI_WORKER_MODE=1)
    if _worker_enabled("content_sync"):
        get_worker_manager().start_worker("content_sync")

    # 5. Publishing Planner Worker 시작 (AUTO_PUBLISHING.enabled AND FASTAPI_WORKER_MODE=1)
    if _worker_enabled("publishing_planner"):
        get_worker_manager().start_worker("publishing_planner")

    # 6. WP Blog Sync Worker 시작 (WP_BLOG_SYNC.enabled AND FASTAPI_WORKER_MODE=1)
    if _worker_enabled("wp_blog_sync"):
        get_worker_manager().start_worker("wp_blog_sync")

    # 7. Calculator WebApp Scheduler Worker 시작 (CALC_WEBAPP_SCHEDULE.enabled AND FASTAPI_WORKER_MODE=1)
    if _worker_enabled("calc_webapp"):
        get_worker_manager().start_worker("calc_webapp")

    try:
        yield
    finally:
        # Shutdown: 모든 worker 정지
        get_worker_manager().stop_all_workers()


# ── HARDEN-01: localhost Host/Origin guard ───────────────────────────────────
# LOCAL_MODE(로그인 없이 local-admin)는 그대로 둔다. 이 guard는 인증보다 먼저
# 실행되어 (1) localhost가 아닌 Host(DNS rebinding 등)를 모든 method에서 차단하고
# (2) 상태 변경 요청(POST/PUT/PATCH/DELETE)에 외부 Origin이 붙어 있으면 차단한다.
# Origin 헤더가 없는 요청(curl/Python/내부 스크립트)과 GET은 Origin으로 막지 않는다.
# Vite proxy(changeOrigin: true)는 Host를 127.0.0.1:8000으로 바꾸고 Origin은 유지한다.
# 서버가 IPv4 127.0.0.1에만 bind되어 있으므로 [::1]은 허용하지 않는다.
_ALLOWED_HOSTS = frozenset({("127.0.0.1", 8000), ("localhost", 8000)})
_ALLOWED_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})
_ORIGIN_CHECKED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_HOST_RE = re.compile(r"^([a-z0-9.-]+)(?::([1-9][0-9]{0,4}))?$")


def _parse_host(value: str):
    """Host 헤더 → (hostname, port|None). 형식이 맞지 않으면 None."""
    m = _HOST_RE.match(value.strip().lower())
    if not m:
        return None
    return m.group(1), (int(m.group(2)) if m.group(2) else None)


class LocalhostGuardMiddleware:
    """Host allowlist(모든 HTTP 요청) + Origin allowlist(상태 변경 요청) ASGI middleware."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers") or []
        hosts = [v for k, v in headers if k == b"host"]
        if len(hosts) != 1 or _parse_host(hosts[0].decode("latin-1")) not in _ALLOWED_HOSTS:
            await JSONResponse(fail("INVALID_HOST", "허용되지 않은 Host입니다."),
                               status_code=400)(scope, receive, send)
            return
        if scope["method"].upper() in _ORIGIN_CHECKED_METHODS:
            origins = [v for k, v in headers if k == b"origin"]
            if len(origins) > 1 or (origins and origins[0].decode("latin-1") not in _ALLOWED_ORIGINS):
                await JSONResponse(fail("FORBIDDEN_ORIGIN", "허용되지 않은 Origin입니다."),
                                   status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = FastAPI(
    title="CalcMate API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(LocalhostGuardMiddleware)

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
app.include_router(topic_reconciliation_router)
app.include_router(assistant_router)
app.include_router(workspace_router)
