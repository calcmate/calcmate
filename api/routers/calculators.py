"""api/routers/calculators.py — Calculator 조회 라우터 (STEP 18-F)
+ Formula 조회/저장 (STEP 4-G) + READY 승인(promote) (STEP 4-H-1)
+ Legal Hold 체크리스트 조회/수정 (STEP 4-H-2)
+ 생성(Mode A, 비동기 Job) (STEP 4-H-5).

STEP 18-F 조회 4종은 여전히 read-only이며 재구현하지 않는다. 삭제(DELETE)/
배포(POST .../deploy)/Build endpoint는 이번 STEP에서도 만들지 않는다 — 이
라우터의 쓰기는 PATCH /{slug}/formula(STEP 4-G), POST /{slug}/promote
(STEP 4-H-1), PATCH /{slug}/checklist(STEP 4-H-2), POST /generate
(STEP 4-H-5) 넷뿐이며, 전부 require_admin() 뒤에서만 실행된다(Publish/Trash/
Settings와 동일한 인증 패턴 재사용, 새 인증 체계 없음). GET /{slug}/checklist는
다른 조회 endpoint와 동일하게 인증 없이 공개된다.

/generate, /generate/{job_id}는 /{slug} 계열보다 먼저 등록한다 — job_id가
32자리 hex라 실제로 충돌하진 않지만, "/generate/status" 같은 경로가
"/{slug}/status"(slug="generate")로도 구조적으로 해석될 수 있어 등록 순서로
명확히 우선순위를 고정한다(Starlette는 먼저 등록된 route를 우선 매칭).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import AuditEvent, CurrentUser
from api.auth.service import record_audit_event
from api.dependencies import ok, fail
from api.services import calculator_service

router = APIRouter(prefix="/api/calculators", tags=["calculators"])


class CalculatorGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str = ""
    description: str = ""
    tier: int = Field(default=2, ge=1, le=2)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]*$")


@router.post("/generate")
def post_calculator_generate(
    body: CalculatorGenerateRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.submit_calculator_generation(
            body.name, body.category, body.description, body.tier, body.slug,
        )
    except calculator_service.CalculatorGenerateBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_generate_submit",
        resource="calculator", resource_id=result.get("job_id", ""), result="success",
    ))
    return ok(result)


@router.get("/generate/{job_id}")
def get_calculator_generate_job(
    job_id: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        return ok(calculator_service.get_calculator_generation_job(job_id))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")


# ── SMALL-GAPS-02: Mode A 생성 → 검토 → 저장/폐기(dashboard.py "🏭 자동 생성" 흐름).
# 기존 POST /generate(생성+저장 일괄)는 변경하지 않는다. 진행 상태 조회는 같은 Job
# store를 쓰는 GET /generate/{job_id}를 그대로 사용한다.
class CalculatorPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str = ""
    description: str = ""
    tier: int = Field(default=2, ge=1, le=2)


@router.post("/generate/preview")
def post_calculator_generate_preview(
    body: CalculatorPreviewRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.submit_calculator_preview_generation(
            body.name, body.category, body.description, body.tier,
        )
    except calculator_service.CalculatorGenerateBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_preview_submit",
        resource="calculator", resource_id=result.get("job_id", ""), result="success",
    ))
    return ok(result)


class CalculatorPreviewSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")


@router.post("/generate/preview/{job_id}/save")
def post_calculator_preview_save(
    job_id: str,
    body: CalculatorPreviewSaveRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.save_calculator_preview(job_id, body.slug)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")
    except calculator_service.CalculatorPreviewError as e:
        return fail("PREVIEW_STATE_INVALID", str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_preview_save",
        resource="calculator", resource_id=body.slug,
        result="success" if result.get("ok") else "blocked",
    ))
    return ok(result)


@router.post("/generate/preview/{job_id}/discard")
def post_calculator_preview_discard(
    job_id: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.discard_calculator_preview(job_id)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")
    except calculator_service.CalculatorPreviewError as e:
        return fail("PREVIEW_STATE_INVALID", str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_preview_discard",
        resource="calculator", resource_id=job_id, result="success",
    ))
    return ok(result)


# ── APP-FACTORY-02: App Factory AI 추천(dashboard.py L1940-2376) ──────────────
# 추천은 표시용이며 생성/저장/배포를 일으키지 않는다. AI 비용이 발생하므로 기존
# App Factory endpoint와 같이 전부 require_admin. 실패 시 예외 원문은 노출하지 않는다.
class AiIdeaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str | None = None


class AiModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str = ""
    description: str = ""


class AiTierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str = ""


class AiTier2bRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    description: str = ""


class AiSpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str = ""
    description: str = ""
    tier: str = Field(default="Tier2-A", pattern=r"^(Tier1|Tier2-A|Tier2-B)$")


class AiFormulaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    category: str = ""
    description: str = ""
    input_fields: list[str] = []
    output_fields: list[str] = []
    legal_refs: list[str] = []
    slug: str | None = None


def _ai_audit(user: CurrentUser, action: str, result: str = "success") -> None:
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action=action,
        resource="calculator", resource_id="app_factory_ai", result=result,
    ))


@router.post("/ai/suggest-idea")
def post_ai_suggest_idea(body: AiIdeaRequest, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.ai_suggest_idea(body.keyword or "")
    except calculator_service.CalculatorAiSuggestError as e:
        _ai_audit(user, "calculator_ai_suggest_idea", "failed")
        return fail("AI_SUGGEST_FAILED", str(e))
    _ai_audit(user, "calculator_ai_suggest_idea")
    return ok(result)


@router.post("/ai/suggest-mode")
def post_ai_suggest_mode(body: AiModeRequest, user: CurrentUser = Depends(require_admin)):
    result = calculator_service.ai_suggest_mode(body.name, body.category, body.description)
    _ai_audit(user, "calculator_ai_suggest_mode")
    return ok(result)


@router.post("/ai/suggest-tier")
def post_ai_suggest_tier(body: AiTierRequest, user: CurrentUser = Depends(require_admin)):
    result = calculator_service.ai_suggest_tier(body.name, body.description)
    _ai_audit(user, "calculator_ai_suggest_tier")
    return ok(result)


@router.post("/ai/tier2b-keywords")
def post_ai_tier2b_keywords(body: AiTier2bRequest, user: CurrentUser = Depends(require_admin)):
    # 규칙 기반(AI 호출 없음). 키워드 목록은 서버(review_center.TIER2B_KEYWORDS)에만 둔다.
    return ok(calculator_service.detect_tier2b(body.name, body.description))


@router.post("/ai/suggest-spec")
def post_ai_suggest_spec(body: AiSpecRequest, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.ai_suggest_spec(body.name, body.category, body.description, body.tier)
    except calculator_service.CalculatorAiSuggestError as e:
        _ai_audit(user, "calculator_ai_suggest_spec", "failed")
        return fail("AI_SUGGEST_FAILED", str(e))
    _ai_audit(user, "calculator_ai_suggest_spec")
    return ok(result)


@router.post("/ai/suggest-formula")
def post_ai_suggest_formula(body: AiFormulaRequest, user: CurrentUser = Depends(require_admin)):
    result = calculator_service.ai_suggest_formula(
        body.name, body.category, body.description, body.input_fields, body.output_fields,
        body.legal_refs, body.slug,
    )
    _ai_audit(user, "calculator_ai_suggest_formula", "success" if result.get("success") else "failed")
    return ok(result)


# ── P0-5: Mode B(Contract 기반 생성) — /generate/contract* 는 더 구체적인 경로이므로
# /generate/{job_id}(2-segment)와 세그먼트 수가 달라 실제로 충돌하지 않지만, 파일
# 전체의 기존 관례(구체적 정적 경로를 먼저 등록)를 따라 이 블록도 /{slug} 계열보다
# 앞에 둔다. 전부 require_admin() — AI 생성/저장을 유발할 수 있는 쓰기 endpoint.

class ContractSlugCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1)


@router.post("/generate/contract/slug-check")
def post_contract_slug_check(
    body: ContractSlugCheckRequest,
    user: CurrentUser = Depends(require_admin),
):
    return ok(calculator_service.check_contract_slug_conflict(body.slug))


class ContractFormulaValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formula: str | dict
    input_fields: list[str] = Field(min_length=1)
    test_cases: list[dict] = []


@router.post("/generate/contract/validate")
def post_contract_formula_validate(
    body: ContractFormulaValidateRequest,
    user: CurrentUser = Depends(require_admin),
):
    result = calculator_service.validate_contract_formula(
        body.formula, body.input_fields, body.test_cases)
    return ok(result)


@router.get("/generate/contract/prefill/{slug}")
def get_contract_prefill(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    return ok(calculator_service.get_contract_prefill(slug))


@router.get("/generate/contract/instance/{slug}")
def get_contract_instance(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    return ok(calculator_service.get_contract_instance(slug))


class ContractGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    category: str = ""
    description: str = ""
    tier: str = Field(default="Tier2-A", pattern=r"^(Tier1|Tier2-A|Tier2-B)$")
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    input_fields: list[str] = Field(min_length=1)
    output_fields: list[str] = Field(min_length=1)
    formula: str | dict | None = None
    test_cases: list[dict] = []
    scope_exclusions: list[str] = []
    legal_refs: list[str] = []


@router.post("/generate/contract")
def post_contract_generate(
    body: ContractGenerateRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.submit_contract_generation(
            name=body.name, category=body.category, description=body.description,
            tier=body.tier, slug=body.slug, input_fields=body.input_fields,
            output_fields=body.output_fields, formula=body.formula,
            test_cases=body.test_cases, scope_exclusions=body.scope_exclusions,
            legal_refs=body.legal_refs,
        )
    except calculator_service.ContractGenerateBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_contract_generate_submit",
        resource="calculator", resource_id=result.get("job_id", ""), result="success",
    ))
    return ok(result)


@router.get("/generate/contract/{job_id}")
def get_contract_generate_job(
    job_id: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        return ok(calculator_service.get_contract_generation_job(job_id))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")


class ContractSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")


@router.post("/generate/contract/{job_id}/save")
def post_contract_save(
    job_id: str,
    body: ContractSaveRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.submit_contract_save(job_id, body.slug)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_contract_save",
        resource="calculator", resource_id=body.slug,
        result="success" if result.get("ok") else "blocked",
    ))
    return ok(result)


# ── APP-FACTORY-02: Mode B 확정 slug 자동 제안 / Formula 운영자 확정 ──────────
class ContractSlugSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""


@router.post("/generate/contract/slug-suggest")
def post_contract_slug_suggest(
    body: ContractSlugSuggestRequest,
    user: CurrentUser = Depends(require_admin),
):
    # dashboard.py L2106-2109와 동일한 generate_slug()(결정적, AI 없음). 중복 확인은
    # 기존 /generate/contract/slug-check를 그대로 쓴다.
    return ok(calculator_service.suggest_contract_slug(body.name))


@router.post("/generate/contract/{job_id}/confirm-formula")
def post_contract_confirm_formula(
    job_id: str,
    user: CurrentUser = Depends(require_admin),
):
    # body 없음 — 서버가 job에 저장된 Contract formula를 다시 검증해 상태를 결정한다.
    try:
        result = calculator_service.confirm_contract_formula(job_id)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"generation job not found: {job_id}")
    except calculator_service.ContractFormulaConfirmError as e:
        return fail("CONTRACT_STATE_INVALID", str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_contract_formula_confirm",
        resource="calculator", resource_id=job_id,
        result="success" if result.get("ok") else "blocked",
    ))
    return ok(result)


class CalculatorFormulaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formula: str = Field(min_length=1)


class ChecklistItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    checked: bool


class CalculatorChecklistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ChecklistItemUpdate] = Field(min_length=1)


@router.get("")
def get_calculators():
    return ok({"calculators": calculator_service.list_calculators()})


@router.get("/{slug}")
def get_calculator(slug: str):
    try:
        return ok(calculator_service.get_calculator(slug))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")


@router.get("/{slug}/content")
def get_calculator_content(slug: str):
    try:
        return ok(calculator_service.get_calculator_content(slug))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")


@router.get("/{slug}/status")
def get_calculator_status(slug: str):
    try:
        return ok(calculator_service.get_calculator_status(slug))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")


@router.get("/{slug}/formula")
def get_calculator_formula(slug: str):
    try:
        return ok(calculator_service.get_calculator_formula(slug))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")


@router.patch("/{slug}/formula")
def patch_calculator_formula(
    slug: str,
    body: CalculatorFormulaUpdate,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.update_calculator_formula(slug, body.formula)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    except calculator_service.CalculatorFormulaValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_formula_patch",
        resource="calculator", resource_id=slug, result="success",
    ))
    return ok(result)


@router.get("/{slug}/checklist")
def get_calculator_checklist(slug: str):
    try:
        return ok(calculator_service.get_calculator_checklist(slug))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")


@router.patch("/{slug}/checklist")
def patch_calculator_checklist(
    slug: str,
    body: CalculatorChecklistUpdate,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.update_calculator_checklist(
            slug,
            [item.model_dump() for item in body.items],
            actor_id=user.id,
        )
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    except calculator_service.CalculatorChecklistError as e:
        raise HTTPException(status_code=400, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_checklist_update",
        resource="calculator", resource_id=slug, result="success",
    ))
    return ok(result)


@router.post("/{slug}/promote")
def post_calculator_promote(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.promote_calculator_to_ready(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    except calculator_service.CalculatorPromoteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_promote",
        resource="calculator", resource_id=slug, result="success",
    ))
    return ok(result)


@router.post("/{slug}/build")
def post_calculator_build(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    """P0-2: dashboard.py의 "🧮 생성" 버튼과 동일 함수(app_generator.
    generate_calculator)를 재사용해 정적 웹앱을 재생성하고, Formula Hard Gate +
    HTML/JS 완결성(P0-1) + 기존 pre_build_qa를 통과한 경우에만 스냅샷을 쓴다.
    차단(ok=False)도 200으로 반환한다 — "차단됨"은 오류가 아니라 정상적으로
    검증된 결과이며, React가 각 게이트의 상세 사유를 그대로 보여줘야 하기 때문."""
    try:
        result = calculator_service.build_calculator(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_build",
        resource="calculator", resource_id=slug,
        result="success" if result["ok"] else "blocked",
    ))
    return ok(result)


@router.post("/{slug}/deploy")
def post_calculator_deploy(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    """P0-2: dashboard.py의 "🚀 배포" 버튼과 동일 함수(github_deployer.deploy_app)를
    재사용한다. HOLD/needs_human_legal/Build 실패 중 하나라도 있으면 deploy_app()
    자체를 호출하지 않는다(§ deploy_calculator 참고). GITHUB_TOKEN 미설정 환경에서는
    deploy_app()이 실제 네트워크 호출 없이 (False, "GITHUB_TOKEN 미설정...")을
    반환한다(기존 동작, 이 STEP에서 변경하지 않음)."""
    try:
        result = calculator_service.deploy_calculator(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_deploy",
        resource="calculator", resource_id=slug,
        result="success" if result["ok"] else "blocked",
    ))
    return ok(result)


# ── STEP S1: Human Review Approval — dashboard.py "👤 사람 검수" 단계 복원.
# GET은 다른 조회 endpoint와 동일하게 인증 없이 공개(읽기 전용). 승인/취소는
# require_admin — Build/Deploy/Promote와 동일한 인증 패턴.

@router.get("/{slug}/review")
def get_calculator_review(slug: str):
    try:
        result = calculator_service.get_calculator_review_status(slug)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")
    return ok(result)


@router.post("/{slug}/review/approve")
def post_calculator_review_approve(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.approve_calculator_review(slug, user.id)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_review_approve",
        resource="calculator", resource_id=slug,
        result="success" if result["ok"] else "blocked",
    ))
    return ok(result)


@router.post("/{slug}/review/unapprove")
def post_calculator_review_unapprove(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.unapprove_calculator_review(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")

    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action="calculator_review_unapprove",
        resource="calculator", resource_id=slug, result="success",
    ))
    return ok(result)


@router.get("/{slug}/preview")
def get_calculator_preview(slug: str):
    """P0-3: dashboard.py "🔎 앱 미리보기"와 동일한 modules.app_generator.
    render_inline_calculator()를 재사용해, Build가 실제로 쓴 확정 스냅샷을
    자체완결 HTML로 반환한다. 다른 GET 조회 endpoint와 동일하게 인증 없이
    공개한다(읽기 전용, 쓰기 없음). Build 결과가 없거나 렌더링에 실패하면
    "previewable": False로 응답한다 — 이 경우도 HTTP 200이다(오류가 아니라
    정상적으로 판정된 "미리보기 불가" 상태)."""
    try:
        result = calculator_service.preview_calculator(slug)
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", f"calculator not found: {slug}")
    return ok(result)


# ── P0-4: 콘텐츠 생성(SEO/FAQ/본문/이미지/전체) — 전부 require_admin, AI 호출 및
# 저장 가능성이 있는 쓰기 endpoint이므로 Build/Deploy/Promote와 동일한 인증 패턴.
# 차단(ok=False 또는 saved=False)도 200으로 반환한다 — React가 QA 실패/AI Review
# 미통과 사유를 그대로 보여줘야 하기 때문(Build/Deploy와 동일한 설계).

def _content_audit_and_ok(user: CurrentUser, slug: str, action: str, result: dict):
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action=action,
        resource="calculator", resource_id=slug,
        result="success" if result.get("saved") else "blocked",
    ))
    return ok(result)


@router.post("/{slug}/content/seo")
def post_calculator_content_seo(slug: str, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.generate_calculator_content_seo(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    return _content_audit_and_ok(user, slug, "calculator_content_seo_generate", result)


@router.post("/{slug}/content/faq")
def post_calculator_content_faq(slug: str, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.generate_calculator_content_faq(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    return _content_audit_and_ok(user, slug, "calculator_content_faq_generate", result)


@router.post("/{slug}/content/body")
def post_calculator_content_body(slug: str, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.generate_calculator_content_body(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    return _content_audit_and_ok(user, slug, "calculator_content_body_generate", result)


@router.post("/{slug}/content/image")
def post_calculator_content_image(slug: str, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.generate_calculator_content_image(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    return _content_audit_and_ok(user, slug, "calculator_content_image_generate", result)


@router.post("/{slug}/content/generate")
def post_calculator_content_generate(slug: str, user: CurrentUser = Depends(require_admin)):
    try:
        result = calculator_service.generate_calculator_content_full(slug)
    except calculator_service.CalculatorNotFound:
        raise HTTPException(status_code=404, detail=f"calculator not found: {slug}")
    return _content_audit_and_ok(user, slug, "calculator_content_full_generate", result)


# ── CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01 ─────────────
# GAP-01 상태토글 / GAP-02 삭제(2단계: 서버 발급 토큰 → slug 재입력 확인). 전부 require_admin.
# 업무 오류는 HTTP 200 + fail(code), 예상 밖 예외는 500(내용 비노출).

class CalculatorStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=16)


class CalculatorDeleteConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    confirm_slug: str = Field(min_length=1, max_length=128)


def _calc_audit(user: CurrentUser, action: str, slug: str, result: str) -> None:
    record_audit_event(AuditEvent(
        actor_id=user.id, actor_role=user.role.value, action=action,
        resource="calculator", resource_id=slug, result=result,
    ))


@router.post("/{slug}/status")
def post_calculator_status(
    slug: str,
    body: CalculatorStatusRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.set_calculator_status(slug, body.status)
    except calculator_service.CalculatorValidationError as e:
        return fail("VALIDATION_ERROR", str(e))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", "계산기를 찾을 수 없습니다.")
    _calc_audit(user, "calculator_status_set", slug, "success")
    return ok(result)


@router.post("/{slug}/delete/prepare")
def post_calculator_delete_prepare(
    slug: str,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.prepare_calculator_delete(slug, user.id)
    except calculator_service.CalculatorValidationError as e:
        return fail("VALIDATION_ERROR", str(e))
    except calculator_service.CalculatorNotFound:
        return fail("NOT_FOUND", "계산기를 찾을 수 없습니다.")
    except calculator_service.CalculatorDeleteError as e:
        _calc_audit(user, "calculator_delete_prepare", slug, "blocked")
        return fail(e.code, str(e))
    _calc_audit(user, "calculator_delete_prepare", slug, "success")
    return ok(result)


@router.post("/{slug}/delete/confirm")
def post_calculator_delete_confirm(
    slug: str,
    body: CalculatorDeleteConfirmRequest,
    user: CurrentUser = Depends(require_admin),
):
    try:
        result = calculator_service.confirm_calculator_delete(slug, body.token, body.confirm_slug, user.id)
    except calculator_service.CalculatorValidationError as e:
        return fail("VALIDATION_ERROR", str(e))
    except calculator_service.CalculatorNotFound:
        _calc_audit(user, "calculator_delete", slug, "not_found")
        return fail("NOT_FOUND", "계산기를 찾을 수 없습니다.")
    except calculator_service.CalculatorDeleteError as e:
        _calc_audit(user, "calculator_delete", slug, "failed" if e.code in ("DELETE_FAILED", "DELETE_VERIFY_FAILED") else "blocked")
        return fail(e.code, str(e))
    _calc_audit(user, "calculator_delete", slug, "success")
    return ok(result)
