"""api/routers/dashboard.py — Dashboard 상태 라우터 (STEP 18-C 최소 골격).

STEP 18-C에서는 실제 Dashboard 전체 KPI를 구현하지 않았다.

STEP P2-01: dashboard.py의 render_kpi_cards()(운영센터 홈 5개 KPI 카드)를 GET
/kpi로 이관한다(api/services/dashboard_kpi_service.py 경유). KPI에 AI 비용
(budget/cost) 데이터가 포함되므로, /api/costs와 동일한 기존 정책(STEP S4:
"비용 데이터는 운영 정보이므로 admin 전용")에 맞춰 require_admin을 적용한다 —
다른 KPI(시스템/Workflow/오늘 발행 수 등) 자체는 공개 endpoint(/api/pipeline/
status, /api/scheduler/blog/today 등)에도 있지만, 이 endpoint는 그것들을 비용
데이터와 함께 하나의 응답으로 묶어 반환하므로 전체를 admin 전용으로 통일한다.

STEP P2-02: dashboard.py의 render_pipeline_status()(⛓️ Workflow 파이프라인
다이어그램)와 render_progress()(📈 진행 현황)를 GET /pipeline-status, GET
/progress로 이관한다(api/services/dashboard_status_service.py 경유). 기존
GET /status(STEP 18-C 골격)와 이름이 겹치지 않도록 별도 경로를 사용한다.

STEP P2-10: dashboard.py의 "📊 현황" 탭(dashboard.py:562-584)을 GET
/status-summary로 이관한다(api/services/dashboard_status_service.py의
get_status_summary() 경유, P2-02의 get_progress()와는 별개 함수/별개 데이터
source — 혼동 금지). READ-ONLY이며 P2-01/P2-02와 동일하게 운영 상태 정보이므로
require_admin을 유지한다.

STEP P2-11: dashboard.py의 "📊 AI Pipeline" 탭(dashboard.py:2875-2901)을 GET
/ai-pipeline로 이관한다(api/services/dashboard_status_service.get_ai_pipeline_
status() 경유 — api/services/log_service.get_pipeline_status()를 재구현 없이
그대로 호출하는 thin wrapper). 기존 GET /api/pipeline/status(api/routers/
logs.py)는 동일한 함수를 호출하지만 require_admin이 없는 공개 endpoint다 —
이 STEP은 그 기존 endpoint를 수정하지 않고(완료된 STEP 수정 금지), cost/
token 데이터를 admin 전용으로도 노출하기 위한 새 경로만 추가한다.
"""
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok
from api.services import dashboard_kpi_service
from api.services import dashboard_status_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/status")
def get_dashboard_status():
    return ok({
        "api": "ok",
        "dashboard": "fastapi",
        "workers": {},
    })


@router.get("/kpi")
def get_dashboard_kpi(user: CurrentUser = Depends(require_admin)):
    return ok(dashboard_kpi_service.get_kpi())


# ── STEP P2-02: 순수 상태/진행 표시(render_pipeline_status()/render_progress())
# 이관 — 둘 다 GET/READ-ONLY. P2-01과 동일하게 운영 상태 정보이므로 require_admin
# 정책을 유지한다(api/services/dashboard_status_service.py 경유).


@router.get("/pipeline-status")
def get_dashboard_pipeline_status(user: CurrentUser = Depends(require_admin)):
    return ok(dashboard_status_service.get_pipeline_status_diagram())


@router.get("/progress")
def get_dashboard_progress(user: CurrentUser = Depends(require_admin)):
    return ok(dashboard_status_service.get_progress())


# ── STEP P2-10: "📊 현황" 탭(상태별 개수/오늘 발행/목표/진행률) 이관 — GET/
# READ-ONLY. P2-02의 get_progress()(scheduler 기반)와는 다른 데이터
# source(articles 테이블)를 쓰는 별개 함수다.


@router.get("/status-summary")
def get_dashboard_status_summary(user: CurrentUser = Depends(require_admin)):
    return ok(dashboard_status_service.get_status_summary())


# ── STEP P2-11: "📊 AI Pipeline Monitor" 이관 — GET/READ-ONLY. 기존 공개
# GET /api/pipeline/status와 동일한 데이터를 admin 전용 경로로도 제공한다
# (기존 공개 endpoint 자체는 변경하지 않음).


@router.get("/ai-pipeline")
def get_dashboard_ai_pipeline(user: CurrentUser = Depends(require_admin)):
    return ok(dashboard_status_service.get_ai_pipeline_status())
