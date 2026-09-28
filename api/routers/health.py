"""api/routers/health.py — 헬스체크 라우터.

/health, /health/details는 외부 API를 호출하지 않는다. STEP 18-M: /health/details는
로컬 application/data 상태만 조회한다(WordPress/GitHub/Cloudflare/Sheets/Telegram
등 외부 호출 없음).

STEP S3: /health/external, /health/external/run은 실제 외부 서비스(OpenAI/Claude/
Gemini/Google Sheets/Drive/WordPress/Service Account)를 호출하는 Streamlit
"🏥 헬스체크 센터"의 이관이다 — 비용/시간이 드는 관리자 전용 작업이므로 require_admin.
"""
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok
from api.services.health_service import (
    get_external_health_cache,
    get_health_details,
    run_external_health_check,
)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def get_health():
    return ok({"status": "ok", "service": "calcmate-api"})


@router.get("/health/details")
def get_health_details_endpoint():
    return ok(get_health_details())


@router.get("/health/external")
def get_health_external(user: CurrentUser = Depends(require_admin)):
    return ok(get_external_health_cache())


@router.post("/health/external/run")
def post_health_external_run(user: CurrentUser = Depends(require_admin)):
    return ok(run_external_health_check())
