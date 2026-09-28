"""api/routers/strategy_room.py — Strategy Room(전략회의실) 실행 라우터.

STEP S8: dashboard.py "🧠 전략회의실" 탭의 "▶ 전략회의실 실행" 버튼과 동일한
실행 의미를 재현한다. AI API 호출(비용 발생)이 있으므로 require_admin.
입력 body 없음 — 기존 Streamlit도 사용자 입력을 받지 않는다(불필요한 입력
필드를 새로 만들지 않는다).
"""
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok
from api.services import strategy_room_service

router = APIRouter(prefix="/api", tags=["strategy-room"])


@router.post("/strategy-room/run")
def post_strategy_room_run(user: CurrentUser = Depends(require_admin)):
    return ok(strategy_room_service.run_strategy_room_analysis())
