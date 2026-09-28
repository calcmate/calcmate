"""api/routers/publish.py — Article Publish/Trash 라우터 (STEP 18-P 조회 + STEP 18-R 쓰기).

조회 3개(GET)는 인증을 요구하지 않는다(STEP 18-Q §7 원칙 유지).
쓰기 3개(POST)는 전부 require_admin() 뒤에서만 실행된다:
  POST /api/publish/{id}/edit
  POST /api/trash/{id}
  POST /api/trash/{id}/restore
인증 실패(401)/권한 부족(403)/리소스 없음(404)/입력값·확인문구 오류(400) 단계에서는
publish_service의 실제 write 함수(및 그 안의 modules.publisher, ArticleRepository
write 메서드)가 절대 호출되지 않는다 — FastAPI Depends 체인이 라우트 핸들러 진입
자체를 막기 때문이다(§4).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import fail, ok
from api.services import publish_service

# §8: 대상 없음=404, 확인문구 불일치=400. STEP 18-Q의 401/403과 동일하게
# HTTPException으로 표현한다(이 프로젝트의 기존 ok()/fail() 200-envelope 관례는
# "작업은 시도됐고 그 결과가 실패"인 경우에만 쓴다 — 여기 두 경우는 애초에
# 작업 자체를 시도하지 않았으므로 실제 HTTP status로 구분한다).

router = APIRouter(prefix="/api", tags=["publish"])


@router.get("/publish")
def get_publish_overview():
    return ok(publish_service.get_all_articles())


@router.get("/publish/articles")
def get_publish_articles():
    return ok(publish_service.get_publish_articles())


@router.get("/trash")
def get_trash():
    return ok(publish_service.get_trash_articles())


# ── STEP 18-R: 쓰기 3종(전부 admin 전용) ──────────────────────────────────

class PublishEditRequest(BaseModel):
    # None = 수정 안 함(미전송), ""(빈 문자열) = 명시적으로 비움 — publisher.update_post()와
    # 동일한 의미론을 그대로 유지한다(§5, 필드를 새로 만들지 않음).
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None


class ConfirmationRequest(BaseModel):
    confirmation: str


@router.post("/publish/{article_id}/edit")
def post_publish_edit(
    article_id: str,
    body: PublishEditRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = publish_service.edit_article(
            article_id, body.title, body.content, body.excerpt,
            actor_id=user.id, actor_role=user.role.value,
        )
    except publish_service.ArticleNotFound:
        raise HTTPException(status_code=404, detail=f"article not found: {article_id}")
    except publish_service.ArticleValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("success"):
        return fail("PUBLISHER_ERROR", str(result.get("error", "")))
    return ok(result)


@router.post("/trash/{article_id}")
def post_trash(
    article_id: str,
    body: ConfirmationRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = publish_service.trash_article(
            article_id, body.confirmation,
            actor_id=user.id, actor_role=user.role.value,
        )
    except publish_service.ArticleNotFound:
        raise HTTPException(status_code=404, detail=f"article not found: {article_id}")
    except publish_service.ArticleValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("success"):
        return fail("PUBLISHER_ERROR", str(result.get("error", "")))
    return ok(result)


@router.post("/trash/{article_id}/restore")
def post_trash_restore(
    article_id: str,
    body: ConfirmationRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = publish_service.restore_article(
            article_id, body.confirmation,
            actor_id=user.id, actor_role=user.role.value,
        )
    except publish_service.ArticleNotFound:
        raise HTTPException(status_code=404, detail=f"article not found: {article_id}")
    except publish_service.ArticleValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("success"):
        return fail("PUBLISHER_ERROR", str(result.get("error", "")))
    return ok(result)
