"""api/routers/costs.py — 비용 모니터 조회 + 실행 라우터.

STEP 18-G: GET 전용으로 시작. STEP S4: require_admin 적용(비용/Retry Queue
데이터는 운영 정보이므로 기존엔 인증 없이 공개였던 것을 admin 전용으로 전환).

STEP S5: "제거(remove)"를 제외한 Manual Resume(POST /costs/resume)과 Retry Queue
수동 재시도(POST /costs/retry) 2개만 추가한다(이번 STEP의 명시적 범위) — 둘 다
require_admin, 새 실행 로직 없이 modules.cost_manager/modules.retry_queue를
그대로 재사용한다(api/services/cost_service.py 경유).

STEP S6: Retry Queue 수동 제거(POST /costs/remove) 1개만 추가한다 — 마찬가지로
require_admin, modules.retry_queue.remove()를 그대로 재사용한다.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok
from api.services import cost_service

router = APIRouter(prefix="/api", tags=["costs"])


@router.get("/costs")
def get_costs(user: CurrentUser = Depends(require_admin)):
    return ok(cost_service.get_cost_status())


@router.post("/costs/resume")
def post_costs_resume(user: CurrentUser = Depends(require_admin)):
    return ok(cost_service.resume_cost_manager())


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)


@router.post("/costs/retry")
def post_costs_retry(body: RetryRequest, user: CurrentUser = Depends(require_admin)):
    return ok(cost_service.retry_pending_item(body.id))


class RemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)


@router.post("/costs/remove")
def post_costs_remove(body: RemoveRequest, user: CurrentUser = Depends(require_admin)):
    return ok(cost_service.remove_pending_item(body.id))
