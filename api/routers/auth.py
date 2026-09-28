"""api/routers/auth.py — 인증 진단용 GET endpoint 2개 (STEP 18-Q).

둘 다 GET이며 어떤 비즈니스 로직(Publish/Trash/Scheduler/Calculator)도 건드리지
않는다 — 순수하게 인증 dependency 체인이 실제 HTTP 요청 경로에서 올바르게
401/403/통과를 반환하는지 확인하기 위한 진단 endpoint다. Write route가 아니므로
STEP 18-N의 write surface(정확히 2개) 검사에 영향을 주지 않는다.
"""
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_admin, require_authenticated
from api.auth.models import CurrentUser
from api.dependencies import ok

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def get_me(user: CurrentUser = Depends(require_authenticated)):
    return ok({"id": user.id, "role": user.role.value if user.role else None})


@router.get("/admin-check")
def admin_check(user: CurrentUser = Depends(require_admin)):
    return ok({"id": user.id, "role": user.role.value if user.role else None, "admin": True})
