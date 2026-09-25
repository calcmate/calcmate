"""api/routers/settings.py — 통합 Settings 조회 라우터 (STEP 18-M)
+ General Settings 조회/저장 (STEP 4-F).

STEP 18-M 조회 4종(BLOG_SCHEDULE 등)은 여전히 read-only이며 기존
ConfigService.get_section()을 그대로 재사용한다(재구현하지 않음).
Blog Scheduler 설정 변경은 여전히 PATCH /api/scheduler/blog/config
(STEP 18-E, api/routers/scheduler.py) 하나만 사용한다.

STEP 4-F에서 이 라우터에 처음으로 쓰기 endpoint(PATCH /general)가 추가된다 —
API 키/WordPress URL·계정/Telegram/Budget/AI Roles 전용이며 require_admin() 뒤에서만
실행된다(Publish/Trash와 동일한 인증 패턴 재사용, 새 인증 체계를 만들지 않음).

STEP P2-14에서 GET/PATCH /image-google이 추가된다 — Image-gen AI(IMAGE_PROVIDER/
MODEL_IMAGE/IMAGE_SIZE/IMAGE_QUALITY)와 Google 연동(GOOGLE_SHEET_ID/
GOOGLE_DRIVE_ROOT_ID/GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID) 7개 필드 전용이며
GeneralSettingsUpdate/patch_general_settings()는 전혀 수정하지 않는다(완료된
STEP 4-F 코드 무변경 — api/services/config_service.py에 새 메서드만 추가).
이 7개는 secret이 아니므로(마스킹 대상 아님) 응답에 원문 그대로 반환한다.

라우트 등록 순서 주의: "/general"·"/image-google"은 반드시 "/{section}" 동적
라우트보다 먼저 선언해야 한다 — 그렇지 않으면 그 문자열이 section 파라미터로
캐치되어 ConfigSectionNotAllowed로 잘못 처리된다.
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth.dependencies import require_admin
from api.auth.models import CurrentUser
from api.auth.service import record_audit_event
from api.auth.models import AuditEvent
from api.dependencies import ok, fail
from api.services.config_service import ALLOWED_SECTIONS, ConfigSectionNotAllowed, ConfigService
from modules.ai_roles import ROLE_KEYS

router = APIRouter(prefix="/api/settings", tags=["settings"])

_AI_PROVIDERS = ("openai", "claude", "gemini")

_FIELD_TO_CONFIG_KEY = {
    "openai_api_key": "OPENAI_API_KEY",
    "claude_api_key": "CLAUDE_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "wordpress_url": "WORDPRESS_URL",
    "wordpress_username": "WORDPRESS_USERNAME",
    "wordpress_app_password": "WORDPRESS_APP_PASSWORD",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "daily_ai_budget": "DAILY_AI_BUDGET",
    "monthly_ai_budget": "MONTHLY_AI_BUDGET",
}

# STEP P2-14: Image-gen AI/Google 연동 전용 — dashboard.py:3153,3175,3183의
# selectbox 옵션을 그대로 가져온다(추측 아님, 원본보다 더 엄격한 값을 새로
# 추가하지 않는다).
_IMAGE_PROVIDER_CHOICES = ("free_pollinations", "gemini", "openai")
_IMAGE_SIZE_CHOICES = ("auto", "1024x1024", "1792x1024")
_IMAGE_QUALITY_CHOICES = ("standard", "hd")

_IMAGE_GOOGLE_FIELD_TO_CONFIG_KEY = {
    "image_provider": "IMAGE_PROVIDER",
    "image_model": "MODEL_IMAGE",
    "image_size": "IMAGE_SIZE",
    "image_quality": "IMAGE_QUALITY",
    "google_sheet_id": "GOOGLE_SHEET_ID",
    "google_drive_root_id": "GOOGLE_DRIVE_ROOT_ID",
    "google_drive_placeholder_folder_id": "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID",
}


class AIRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str

    @field_validator("provider")
    @classmethod
    def _valid_provider(cls, v: str) -> str:
        if v not in _AI_PROVIDERS:
            raise ValueError(f"provider must be one of {_AI_PROVIDERS}")
        return v


class GeneralSettingsUpdate(BaseModel):
    """부분 업데이트(PATCH) 전용. 미전송/None 필드는 변경하지 않는다.
    허용하지 않은 필드는 422로 거부한다(extra="forbid")."""
    model_config = ConfigDict(extra="forbid")

    openai_api_key: str | None = None
    claude_api_key: str | None = None
    gemini_api_key: str | None = None
    wordpress_url: str | None = None
    wordpress_username: str | None = None
    wordpress_app_password: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    daily_ai_budget: int | None = Field(default=None, ge=1, le=1000)
    monthly_ai_budget: int | None = Field(default=None, ge=1, le=10000)
    ai_roles: dict[str, AIRoleUpdate] | None = None

    @field_validator("ai_roles")
    @classmethod
    def _valid_roles(cls, v):
        if v is None:
            return v
        for role in v:
            if role not in ROLE_KEYS:
                raise ValueError(f"unknown role: {role} (must be one of {ROLE_KEYS})")
        return v


@router.get("")
def get_all_settings():
    svc = ConfigService()
    return ok({section: svc.get_section(section) for section in sorted(ALLOWED_SECTIONS)})


@router.get("/general")
def get_general_settings():
    return ok(ConfigService().get_general_settings())


@router.patch("/general")
def patch_general_settings(
    body: GeneralSettingsUpdate,
    user: CurrentUser = Depends(require_admin),
):
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    updates = {}
    for field, value in data.items():
        if field == "ai_roles":
            updates["AI_ROLES"] = {role: dict(spec) for role, spec in value.items()}
        else:
            updates[_FIELD_TO_CONFIG_KEY[field]] = value

    result = ConfigService().patch_general_settings(updates)
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="settings_patch_general",
        resource="settings", resource_id="general", result="success",
    ))
    return ok(result)


class ImageGoogleSettingsUpdate(BaseModel):
    """부분 업데이트(PATCH) 전용. 필드를 아예 보내지 않으면(None) 변경하지
    않는다. 명시적으로 빈 문자열을 보내면 그 값(빈 문자열)으로 저장한다 —
    이 7개는 secret이 아니므로 GeneralSettingsUpdate의 falsy-필터링과 달리
    "빈 문자열=재전송 안 함"으로 취급하지 않는다(원본 텍스트 입력을 비우면
    그대로 빈 문자열이 저장되는 동작과 동일, api/services/config_service.py
    모듈 docstring 참고). 허용하지 않은 필드는 422로 거부한다(extra="forbid")."""
    model_config = ConfigDict(extra="forbid")

    image_provider: Literal[_IMAGE_PROVIDER_CHOICES] | None = None
    image_model: str | None = None
    image_size: Literal[_IMAGE_SIZE_CHOICES] | None = None
    image_quality: Literal[_IMAGE_QUALITY_CHOICES] | None = None
    google_sheet_id: str | None = None
    google_drive_root_id: str | None = None
    google_drive_placeholder_folder_id: str | None = None


@router.get("/image-google")
def get_image_google_settings(user: CurrentUser = Depends(require_admin)):
    return ok(ConfigService().get_image_google_settings())


@router.patch("/image-google")
def patch_image_google_settings(
    body: ImageGoogleSettingsUpdate,
    user: CurrentUser = Depends(require_admin),
):
    data = body.model_dump(exclude_unset=True)
    updates = {
        _IMAGE_GOOGLE_FIELD_TO_CONFIG_KEY[field]: value
        for field, value in data.items()
        if value is not None
    }

    result = ConfigService().patch_image_google_settings(updates)
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="settings_patch_image_google",
        resource="settings", resource_id="image-google", result="success",
    ))
    return ok(result)


@router.get("/{section}")
def get_settings_section(section: str):
    try:
        return ok(ConfigService().get_section(section))
    except ConfigSectionNotAllowed as e:
        return fail("SECTION_NOT_ALLOWED", str(e))
