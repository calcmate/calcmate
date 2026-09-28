"""api/routers/sites.py — Site Management 조회/생성/수정 라우터.

STEP P2-04: dashboard.py "🌐 사이트 관리" 탭의 사이트 목록 조회 이관(GET 전용).

STEP P2-06: 사이트 생성(POST /api/sites)과 Import(POST /api/sites/import)만
추가로 이관한다. Update/Delete/Archive/Restore/Clone/Calculator 등록·삭제/
Override는 이번 STEP에서도 만들지 않는다.

STEP P2-07: 사이트 기본 정보 수정(PUT /api/sites/{site_id})과 Site Settings
Override 저장/초기화(POST /api/sites/{site_id}/override, POST /api/sites/
{site_id}/override/reset)만 추가로 이관한다. Delete/Archive/Restore/Clone/
Calculator 등록·삭제/Export는 이번 STEP에서도 만들지 않는다. GET /api/sites/
{site_id}(단일 사이트 상세, 신규)는 Override 폼이 현재 값을 불러오기 위한
READ-ONLY 조회다.

STEP P2-08: Activate(POST .../activate)/Deactivate(POST .../deactivate)/
Archive(POST .../archive)/Restore(POST .../restore)만 추가로 이관한다.
Hard Delete/Clone/Calculator 등록·삭제/Export는 이번 STEP에서도 만들지
않으며, P2-07의 PUT/override/override-reset은 변경하지 않는다. 4개 전부
"/{site_id}/<action>" 형태로 "/import"(단일 세그먼트 리터럴 경로)와 경로가
겹치지 않는다 — 순서 문제 없음을 확인함(재확인, 추측 아님).

STEP P2-09: Hard Delete(DELETE /api/sites/{site_id})와 Clone(POST
/api/sites/{site_id}/clone)만 추가로 이관한다. P2-04~P2-08의 구현은
변경하지 않는다. DELETE는 이 프로젝트 전체에서 처음 등록되는 메서드다
(test_fastapi_route_security.py의 "DELETE 어디에도 없음" 불변식이 PUT 때와
동일한 방식으로 예외 1개를 허용하도록 갱신 필요 — §13). Hard Delete는
STEP 18-R의 Trash/Restore와 동일한 confirmation 문자열 패턴(정확히
"DELETE"와 일치)을 요구한다 — 원본 dashboard.py의 텍스트 입력 확인
(dashboard.py:1403-1410)을 서버 레이어로 그대로 옮긴 것이다.

라우트 등록 순서 주의: "/import"는 반드시 "/{site_id}" 계열보다 먼저 등록되어
있다(calculators.py의 기존 관례와 동일 — 이미 P2-06에서 그렇게 등록됨, 이번
STEP에서 순서를 바꾸지 않는다).

require_admin 전부 적용 — Dashboard 운영 정보에 이미 일관되게 적용해 온
정책(P2-01/P2-02/P2-04/P2-06)을 그대로 따른다.
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.dependencies import ok, fail
from api.services import site_service

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("")
def get_sites(user: CurrentUser = Depends(require_admin)):
    return ok({"sites": site_service.get_sites()})


class SiteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type_label: Literal["블로그", "계산기", "정책정보", "금융", "제휴마케팅", "사용자정의"]
    site_name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    category: str = ""
    platforms: list[str] = Field(default_factory=list)
    wp_url: str = ""
    wp_user: str = ""
    wp_app_password: str = ""
    rss_sources: str = ""
    research_ai: str = ""
    writing_ai: str = ""
    review_ai: str = ""


@router.post("")
def post_create_site(body: SiteCreateRequest, user: CurrentUser = Depends(require_admin)):
    try:
        result = site_service.create_site(body.type_label, body.model_dump(exclude={"type_label"}))
        return ok(result)
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))
    except site_service.SiteCreateBusy as e:
        return fail("LOCK_CONFLICT", str(e))


class SiteImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict] = Field(default_factory=list)


@router.post("/import")
def post_import_sites(body: SiteImportRequest, user: CurrentUser = Depends(require_admin)):
    return ok(site_service.import_sites(body.rows))


# ── STEP P2-07: 사이트 기본 정보 수정 + Site Settings Override ──────────────
# AI_PROFILES/이미지/Telegram·Analytics 허용값은 dashboard.py:1016-1017,
# 1115, 1123(재확인)의 값을 그대로 가져온다 — 원본에 없는 값을 추가하지 않는다.
_AI_PROFILE_CHOICES = (
    "", "gemini_flash", "gemini_pro", "gpt4o", "gpt4o_mini",
    "claude_sonnet", "claude_haiku", "claude_opus",
)
_IMAGE_MODE_CHOICES = ("", "free_pollinations", "openai", "none")
_ON_OFF_CHOICES = ("", "ON", "OFF")


@router.get("/{site_id}")
def get_site(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.get_site(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))


class SiteUpdateBasicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_name: str = ""
    domain: str = ""
    category: str = ""


@router.put("/{site_id}")
def put_update_site(site_id: str, body: SiteUpdateBasicRequest, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.update_site_basic(site_id, body.model_dump()))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


class SiteOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_ai: Literal[_AI_PROFILE_CHOICES] = ""
    writing_ai: Literal[_AI_PROFILE_CHOICES] = ""
    review_ai: Literal[_AI_PROFILE_CHOICES] = ""
    wordpress_url: str = ""
    site_tags: str = ""
    seo_keyword_count: str = ""
    seo_length: str = ""
    daily_override: str = ""
    image_mode: Literal[_IMAGE_MODE_CHOICES] = ""
    telegram_enabled: Literal[_ON_OFF_CHOICES] = ""
    analytics_enabled: Literal[_ON_OFF_CHOICES] = ""
    calc_active: list[str] = Field(default_factory=list)


@router.post("/{site_id}/override")
def post_save_override(site_id: str, body: SiteOverrideRequest, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.save_override(site_id, body.model_dump()))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.post("/{site_id}/override/reset")
def post_reset_override(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.reset_override(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


# ── STEP P2-08: Activate/Deactivate/Archive/Restore ─────────────────────────
# 요청 body 없음(dashboard.py의 버튼들도 site_id 외 별도 입력을 받지 않는다).

@router.post("/{site_id}/activate")
def post_activate_site(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.activate_site(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.post("/{site_id}/deactivate")
def post_deactivate_site(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.deactivate_site(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.post("/{site_id}/archive")
def post_archive_site(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.archive_site(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


@router.post("/{site_id}/restore")
def post_restore_site(site_id: str, user: CurrentUser = Depends(require_admin)):
    try:
        return ok(site_service.restore_site(site_id))
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


# ── STEP P2-09: Hard Delete/Clone ────────────────────────────────────────

class SiteDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str


@router.delete("/{site_id}")
def delete_site(site_id: str, body: SiteDeleteRequest, user: CurrentUser = Depends(require_admin)):
    try:
        site_service.delete_site_hard(site_id, body.confirmation)
        return ok({"site_id": site_id, "deleted": True})
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))


class SiteCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    wp_url: str = ""
    wp_user: str = ""
    wp_app_password: str = ""


@router.post("/{site_id}/clone")
def post_clone_site(site_id: str, body: SiteCloneRequest, user: CurrentUser = Depends(require_admin)):
    try:
        result = site_service.clone_site(site_id, body.model_dump())
        return ok(result)
    except site_service.SiteNotFound as e:
        return fail("NOT_FOUND", str(e))
    except site_service.SiteValidationError as e:
        return fail("VALIDATION_ERROR", str(e))
    except site_service.SiteCreateBusy as e:
        return fail("LOCK_CONFLICT", str(e))
