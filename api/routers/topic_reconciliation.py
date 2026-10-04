"""api/routers/topic_reconciliation.py — published Topic ↔ WP 상태 대조 / 수동
candidate 복귀 (CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01).

dashboard.py "🔍 published Topic ↔ WP 상태 대조"(1219-1289) 이관. 대상 Topic 목록은
기존 GET /api/scheduler/topics?status=published를 그대로 쓴다(새 조회 API 없음).
두 endpoint 모두 운영 WP 자격증명으로 WP GET을 하고, 복귀는 topic_pool DB를
변경하므로 admin 전용이다. 복귀는 원본의 동의 체크박스와 같은 confirm=true가 필요하다.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok, fail
from api.services import topic_reconciliation_service

router = APIRouter(prefix="/api/scheduler/topics", tags=["scheduler"])


@router.post("/{topic_id}/wp-check")
def post_topic_wp_check(topic_id: str, user: CurrentUser = Depends(require_admin)):
    return ok(topic_reconciliation_service.check_topic(topic_id))


class TopicRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


@router.post("/{topic_id}/revert-candidate")
def post_topic_revert_candidate(
    topic_id: str,
    body: TopicRevertRequest,
    user: CurrentUser = Depends(require_admin),
):
    if not body.confirm:
        return fail("CONFIRM_REQUIRED", "candidate 복귀에 동의(confirm=true)가 필요합니다.")
    try:
        return ok(topic_reconciliation_service.revert_to_candidate(topic_id))
    except topic_reconciliation_service.TopicNotRevertable as e:
        return fail("NOT_REVERTABLE", str(e))
    except ValueError as e:
        return fail("TRANSITION_FAILED", f"복귀 실패(상태 변경 없음): {e}")
