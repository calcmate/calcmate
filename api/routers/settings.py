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


class CalculatorDisplaySettingsUpdate(BaseModel):
    """부분 업데이트(PATCH) 전용. 필드를 아예 보내지 않으면(None) 변경하지
    않는다. 명시적으로 빈 문자열을 보내면 그 값(빈 문자열)으로 저장한다.
    허용하지 않은 필드는 422로 거부한다(extra="forbid")."""
    model_config = ConfigDict(extra="forbid")

    site_mode: Literal["pre_adsense", "adsense", "cpa", "full"] | None = None
    show_share: bool | None = None
    show_pwa: bool | None = None
    show_result_save: bool | None = None
    show_faq: bool | None = None
    show_notice: bool | None = None
    show_related: bool | None = None
    show_detail: bool | None = None
    show_adsense: bool | None = None
    show_cpa: bool | None = None
    result_export_type: Literal["png", "pdf", "both", "none"] | None = None
    kakao_js_key: str | None = None
    calculator_version: str | None = None
    law_version: str | None = None


@router.get("/calculator-display")
def get_calculator_display_settings(user: CurrentUser = Depends(require_admin)):
    return ok(ConfigService().get_calculator_display_settings())


@router.patch("/calculator-display")
def patch_calculator_display_settings(
    body: CalculatorDisplaySettingsUpdate,
    user: CurrentUser = Depends(require_admin),
):
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    updates = {}
    field_map = {
        "site_mode": "SITE_MODE",
        "show_share": "SHOW_SHARE",
        "show_pwa": "SHOW_PWA",
        "show_result_save": "SHOW_RESULT_SAVE",
        "show_faq": "SHOW_FAQ",
        "show_notice": "SHOW_NOTICE",
        "show_related": "SHOW_RELATED",
        "show_detail": "SHOW_DETAIL",
        "show_adsense": "SHOW_ADSENSE",
        "show_cpa": "SHOW_CPA",
        "result_export_type": "RESULT_EXPORT_TYPE",
        "kakao_js_key": "KAKAO_JS_KEY",
        "calculator_version": "CALCULATOR_VERSION",
        "law_version": "LAW_VERSION",
    }
    for field, value in data.items():
        if field in field_map:
            updates[field_map[field]] = value

    result = ConfigService().patch_calculator_display_settings(updates)
    return ok(result)


# CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01: dashboard.py "🔧 설정"의 블로그
# 파이프라인 모델 매칭(3101-3133)/운영 설정(3216-3231)/TELEGRAM_EVENTS(3252-3261)/
# 텔레그램 테스트 전송(3241-3251) 이관. 허용값 검증은 operations_settings_service가
# 원본 옵션 그대로 수행한다(AI_ROLES와는 별개의 flat 키).
_OPERATIONS_FIELD_TO_CONFIG_KEY = {
    "orchestrator_provider": "ORCHESTRATOR_PROVIDER",
    "model_orchestrator": "MODEL_ORCHESTRATOR",
    "planner_provider": "PLANNER_PROVIDER",
    "model_planner": "MODEL_PLANNER",
    "writer_provider": "WRITER_PROVIDER",
    "model_writer": "MODEL_WRITER",
    "editor_provider": "EDITOR_PROVIDER",
    "model_editor": "MODEL_EDITOR",
    "model_cleaner": "MODEL_CLEANER",
    "model_editor_fallback": "MODEL_EDITOR_FALLBACK",
    "adsense_mode": "ADSENSE_MODE",
    "dlq_threshold": "DLQ_THRESHOLD",
    "auto_topic_expansion": "AUTO_TOPIC_EXPANSION",
    "enable_strategy_room": "ENABLE_STRATEGY_ROOM",
    "telegram_events": "TELEGRAM_EVENTS",
}


class OperationsSettingsUpdate(BaseModel):
    """부분 업데이트(PATCH) 전용. 미전송/None 필드는 변경하지 않는다.
    허용하지 않은 필드는 422로 거부한다(extra="forbid")."""
    model_config = ConfigDict(extra="forbid")

    orchestrator_provider: Literal[_AI_PROVIDERS] | None = None
    model_orchestrator: str | None = None
    planner_provider: Literal[_AI_PROVIDERS] | None = None
    model_planner: str | None = None
    writer_provider: Literal[_AI_PROVIDERS] | None = None
    model_writer: str | None = None
    editor_provider: Literal[_AI_PROVIDERS] | None = None
    model_editor: str | None = None
    model_cleaner: str | None = None
    model_editor_fallback: str | None = None
    adsense_mode: Literal["pre", "post"] | None = None
    dlq_threshold: int | None = Field(default=None, ge=1, le=10)
    auto_topic_expansion: bool | None = None
    enable_strategy_room: bool | None = None
    telegram_events: dict[str, bool] | None = None


@router.get("/operations")
def get_operations_settings(user: CurrentUser = Depends(require_admin)):
    from api.services import operations_settings_service
    return ok(operations_settings_service.get_operations_settings())


@router.patch("/operations")
def patch_operations_settings(
    body: OperationsSettingsUpdate,
    user: CurrentUser = Depends(require_admin),
):
    from api.services import operations_settings_service
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    updates = {_OPERATIONS_FIELD_TO_CONFIG_KEY[field]: value for field, value in data.items()}
    try:
        result = operations_settings_service.patch_operations_settings(updates)
    except ValueError as e:
        return fail("VALIDATION_ERROR", str(e))
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="settings_patch_operations",
        resource="settings", resource_id="operations", result="success",
    ))
    return ok(result)


class TelegramTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


@router.post("/telegram/test")
def post_telegram_test(
    body: TelegramTestRequest,
    user: CurrentUser = Depends(require_admin),
):
    from api.services import operations_settings_service
    try:
        result = operations_settings_service.send_telegram_test(
            body.telegram_bot_token, body.telegram_chat_id)
    except ValueError as e:
        return fail("TELEGRAM_NOT_CONFIGURED", str(e))
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="settings_telegram_test",
        resource="settings", resource_id="telegram", result="success",
    ))
    return ok(result)


class WordPressTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wordpress_url: str | None = None
    wordpress_username: str | None = None
    wordpress_app_password: str | None = None


@router.post("/wordpress/test")
def post_wordpress_test(
    body: WordPressTestRequest,
    user: CurrentUser = Depends(require_admin),
):
    from api.services import operations_settings_service as ops
    try:
        result = ops.check_wordpress_connection(
            body.wordpress_url, body.wordpress_username, body.wordpress_app_password)
    except ops.WordPressTestNotConfigured as e:
        return fail("WORDPRESS_NOT_CONFIGURED", str(e))
    except ops.WordPressTestInvalidUrl as e:
        return fail("VALIDATION_ERROR", str(e))
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="settings_wordpress_test",
        resource="settings", resource_id="wordpress",
        result="success" if result.get("ok") else "failed",
    ))
    return ok(result)


@router.get("/{section}")
def get_settings_section(section: str):
    try:
        return ok(ConfigService().get_section(section))
    except ConfigSectionNotAllowed as e:
        return fail("SECTION_NOT_ALLOWED", str(e))
