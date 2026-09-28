"""api/routers/workboard.py — 작업 현황 보드(Kanban) 조회 라우터.

STEP S9: dashboard.py "📋 작업 보드" 탭과 동일한 6개 컬럼 조회를 재현한다.
GET 전용(읽기 전용 기능 — 상태 변경/드래그앤드롭 endpoint를 만들지 않는다).
require_admin 적용 — 최근 STEP(S3/S4/S5/S6/S8)에서 신규 추가된 endpoint에
일관되게 적용해 온 정책을 따른다.
"""
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok
from api.services import workboard_service

router = APIRouter(prefix="/api", tags=["workboard"])


@router.get("/workboard")
def get_workboard(user: CurrentUser = Depends(require_admin)):
    return ok(workboard_service.get_workboard())
