"""api/routers/publishing_policy.py — Publishing Policy 라우터.

PUBLISHING_POLICY 섹션의 조회/저장/미리보기 전용 엔드포인트.
기존 publishing_policy_service를 thin wrapper로 호출한다.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok, fail
from api.services import publishing_policy_service as pps

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class TimeRange(BaseModel):
    start: str
    end: str


class WeekdayEntry(BaseModel):
    count: int
    time_ranges: List[TimeRange]


class PublishingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Seoul"
    weekdays: dict
    max_pending_reservations: int = 10


class AutoPublishing(BaseModel):
    enabled: bool


@router.get("/publishing-policy")
def get_publishing_policy():
    """PUBLISHING_POLICY 조회 (인증 불필요 — 기존 GET 조회 endpoint 정책과 동일).

    기존 필드에 source("config" | "default")만 추가한다 — 저장된 정책이 없어
    DEFAULT_POLICY를 보여주는 상태를 Dashboard가 구분하도록. preview/PATCH 응답에는
    넣지 않는다(validate_policy의 최상위 키 계약 보호)."""
    policy, source = pps.get_policy_with_source()
    return ok({**policy, "source": source})


@router.patch("/publishing-policy")
def patch_publishing_policy(
    body: PublishingPolicy,
    user: CurrentUser = Depends(require_admin),
):
    """PUBLISHING_POLICY 저장 (require_admin 필요)."""
    try:
        result = pps.patch_policy(body.model_dump())
        return ok(result)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.get("/publishing-policy/preview")
def get_publishing_policy_preview(
    days: int = 7,
):
    """PUBLISHING_POLICY 기반 향후 days일간 발행 시각 미리보기 (인증 불필요 — read-only 조회)."""
    policy = pps.get_policy()
    try:
        result = pps.preview(policy, days)
        return ok(result)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.get("/auto-publishing")
def get_auto_publishing():
    """AUTO_PUBLISHING 조회 (인증 불필요 — 기존 GET 조회 endpoint 정책과 동일)."""
    auto = pps.get_auto_publishing()
    return ok(auto)


@router.patch("/auto-publishing")
def patch_auto_publishing(
    body: AutoPublishing,
    user: CurrentUser = Depends(require_admin),
):
    """AUTO_PUBLISHING 저장 (require_admin 필요)."""
    try:
        result = pps.patch_auto_publishing(body.enabled)
        return ok(result)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))