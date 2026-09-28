"""api/routers/logs.py — 로그/파이프라인 조회 라우터 (STEP 18-G).

전부 GET, 조회 전용. 로그 삭제/정리/rotate endpoint는 만들지 않는다.
"""
from fastapi import APIRouter, Query

from api.dependencies import ok
from api.services import log_service

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs/errors")
def get_logs_errors():
    return ok(log_service.get_error_logs())


@router.get("/logs/recent")
def get_logs_recent():
    return ok(log_service.get_recent_logs())


@router.get("/logs/live")
def get_logs_live(level: str = Query("all", pattern="^(all|error|warn_error|info)$")):
    return ok(log_service.get_live_logs(level=level))


@router.get("/pipeline/status")
def get_pipeline_status():
    return ok(log_service.get_pipeline_status())
