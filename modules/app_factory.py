# -*- coding: utf-8 -*-
"""
modules/app_factory.py — 계산기 자동 생성 (v12.0)

흐름: GPT(총괄 spec) → Claude(코드 HTML/CSS/JS) → GPT(SEO/FAQ/블로그초안)
      → Gemini(이미지 프롬프트) → calculators + app_templates 저장
      → v3 Registry 즉시 기록(status=HOLD) → legal 검증 → READY 전환

모든 AI 호출은 ai_roles(=ai_provider) 경유, 데이터 저장은 Repository 경유.
gspread/Drive 직접 호출 없음.
"""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

# v3 Registry 경로 (docs/registry/*.yaml SSOT)
_REG_DIR = Path(__file__).resolve().parent.parent / "docs" / "registry"

# Contract Schema 경로 (docs/contract_schema/ — CA-2-4)
_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs" / "contract_schema"

# category → _af yaml 파일명(확장자 제외). 미매핑은 labor_af 폴백.
_CATEGORY_AF_YAML_MAP: dict[str, str] = {
    "세금/정부혜택": "tax_af",
    "노무/급여": "labor_af",
    "고용/보험": "employment_af",
    "노무/급여/보험": "insurance_af",
    "부동산/임대": "realty_af",
    "병역/공무": "defense_af",
}

from adapters.db.factory import get_db_adapter, get_template_storage_adapter, get_calculator_storage_adapter
from repositories.calculator_repository import CalculatorRepository
from repositories.template_repository import TemplateRepository
from .ai_roles import make_provider
from .json_utils import parse_json_lenient
from .logger import get_logger, BudgetTracker

LOG = get_logger()

# App Factory 세션 초기화 대상 키 (폐기 & 초기화 버튼에서 사용)
AF_SESSION_DISCARD_KEYS: tuple[str, ...] = (
    "af_result",                  # AI 생성 결과 전체
    "af_name",                    # 계산기명 입력
    "af_cat",                     # 카테고리 입력
    "af_desc",                    # 설명 입력
    "af_tier",                    # Tier 라디오 선택
    "af_slug",                    # slug 입력
    "af_keyword",                 # 키워드 입력
    "af_tier_suggest",            # AI Tier 추천 상태
    "_af_last_slug_for",          # slug 자동완성 내부 추적
    "af_seo",                     # SEO 제목 표시 (af_result 소멸 시 자동 소멸)
    "af_discard_confirm",         # 폐기 확인 대화창 플래그
    # ── Contract 모드(Mode B) 전용 키 ───────────────────────────
    "af_contract",                # build_contract() 결과 객체
    "af_contract_slug_pre",       # 생성 전 확정 slug
    "af_contract_input_fields",   # 확정 입력 필드 (쉼표 구분 문자열)
    "af_contract_output_fields",  # 확정 출력 필드 (쉼표 구분 문자열)
    "af_contract_formula",        # 확정 formula (str 또는 JSON)
    "af_contract_test_cases",     # 검증 케이스 (JSON 배열 문자열)
    # ── Formula lifecycle 보조 키 (CA-3-1/CA-3-4) ────────────
    "af_formula_confirmed_text",  # operator_confirmed 시점의 raw formula
    "af_formula_validation",      # [🔍 Formula 검증] 결과 dict
    "af_formula_ai_suggested_text",  # AI 제안 추적 (ai_suggested 수정 감지용)
    "_af_ai_suggest_override",    # 2-click 덮어쓰기 확인 플래그
    # ── Tier2-B (날짜형) 전용 키 ─────────────────────────────
    "af_contract_is_tier2b",      # Tier2-B 체크박스 상태
)


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", (text or "").strip()).strip("_").lower()
    return s or datetime.now().strftime("%H%M%S")


def _pj(v, default=None):
    """JSON 문자열/딕셔너리 안전 파싱(기존 계산기 input_schema 요약용)."""
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if v else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}


def _strip_fence(text: str) -> str:
    """```html ... ``` 코드블록 펜스 제거."""
    s = (text or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    return s


def _chat(cfg, role, system, user, max_tokens=1200):
    provider, model = make_provider(cfg, role)
    text, tokens = provider.chat(system, user, model, max_tokens=max_tokens)
    try:
        BudgetTracker(cfg).record(model, tokens)
    except Exception as _e:
        LOG.warning("토큰 비용 기록/조회 실패: %s", _e)
    return text, model, tokens


def _category_to_af_yaml(category: str) -> str:
    """category → _af yaml 파일명(확장자 제외). 미매핑 시 labor_af 폴백."""
    return _CATEGORY_AF_YAML_MAP.get(str(category).strip(), "labor_af")


def _next_display_order() -> int:
    """v3 registry 전체(기존+_af 파일 포함) 최대 display_order + 1. 없으면 10."""
    from .registry_loader import load_registry_v3, invalidate
    invalidate()
    v3 = load_registry_v3(force=True)
    orders = [e.get("display_order", 0) for e in v3.values()
              if isinstance(e.get("display_order"), int)]
    return max(orders, default=9) + 1


_CARD_DESC_MAX = 45
_SENTENCE_END_RE = re.compile(r"[.!?。！？](?=\s|$)")


def _make_card_desc(desc: str, limit: int = _CARD_DESC_MAX) -> str:
    """desc → 카드 UI용 짧은 설명. limit자 이내면 그대로, 초과 시 첫 문장이
    limit자 이내면 문장 전체를 우선 사용하고, 그렇지 않으면 단어 경계에서
    잘라 '…'를 붙인다(단어 중간 절단 금지)."""
    desc = (desc or "").strip()
    if len(desc) <= limit:
        return desc
    m = _SENTENCE_END_RE.search(desc)
    if m and m.end() <= limit:
        return desc[:m.end()].strip()
    truncated = desc[:limit].rstrip()
    cut = truncated.rfind(" ")
    if cut > 0:
        truncated = truncated[:cut]
    truncated = truncated.rstrip(" .,!?、，。！？…")
    return (truncated or desc[:limit]) + "…"


def _build_v3_entry(app: dict, slug: str, tier: int = 2, contract: dict = None) -> dict:
    """v3 Registry(docs/registry/*_af.yaml)에 기록할 엔트리 생성.
    기존 8개 계산기 형식과 동일 스키마 + status/tier/source 추가.
    contract: Mode B(generate_app_with_contract) 경로에서만 전달. None이면 Mode A(기존 동작 유지)."""
    _c = contract or {}
    ins = app.get("input_schema", {}) or {}
    outs = app.get("output_schema", {}) or {}
    date_fields, compute_type, validation_mode, difficulty = _infer_registry_meta(
        ins, outs, app.get("formula", ""))
    name = app.get("name", "")
    desc = (app.get("description", "") or app.get("seo_desc", "") or "").strip()
    card_desc = _make_card_desc(desc)
    entry = {
        "name": name,
        "slug": slug,
        "category": app.get("category", ""),
        "emoji": "🧮",
        "card_label": name,
        "compute_type": compute_type,
        "date_fields": date_fields,
        "validation_mode": validation_mode,
        "field_labels": app.get("labels", {}) or {},
        "input_labels": list(_c.get("input_fields", []) or []),
        "output_labels": list(_c.get("output_fields", []) or []),
        "display_order": _next_display_order(),
        "card_desc": card_desc,
        "difficulty": difficulty,
        "difficulty_status": "provisional",
        "status": "HOLD",
        "tier": tier,
        "source": "app_factory",
        "content": {"evergreen": True, "update_cycle": None, "content_caveat": None},
        "related_slugs": [],
        "legal_refs": list(_c.get("legal_refs", []) or []),
        "writer_context": {
            "emphasize": [],
            "example_patterns": [desc[:60]] if desc else [],
            "calculation_story": [],
        },
        "contract_source": {
            "contract_slug":    _c.get("slug", ""),
            "input_fields":     list(_c.get("input_fields",     []) or []),
            "output_fields":    list(_c.get("output_fields",    []) or []),
            "formula_status":   _c.get("formula_status",   "not_generated"),
            "test_cases_status":_c.get("test_cases_status","not_generated"),
        } if _c else None,
    }
    if app.get("compute_rules"):
        entry["compute_rules"] = app["compute_rules"]
    # Tier2-B 날짜형: Registry에 추가 메타 필드 기록
    if _c.get("tier") == "Tier2-B" or app.get("compute_type") == "date_based_custom":
        entry["tier_subtype"] = "B"
        entry["html_source"] = "template_db"
        entry["compute_type"] = "date_based_custom"
    return entry


def _write_registry_v3(slug: str, entry: dict, category: str) -> None:
    """docs/registry/<category>_af.yaml에 slug 엔트리를 추가.
    _af.yaml은 App Factory 전용 — 기존 registry/*.yaml은 절대 수정하지 않음.
    기존 v3 slug(기존 8개 포함)와 중복 시 ValueError."""
    import yaml
    from .registry_loader import load_registry_v3, invalidate

    # 기존 v3 slug 보호 — 기존 8개 + 이미 등록된 _af 엔트리 모두 포함
    existing_v3 = load_registry_v3(force=True)
    if slug in existing_v3:
        raise ValueError(f"v3 Registry에 이미 존재하는 slug: '{slug}'")

    yaml_name = _category_to_af_yaml(category)
    yaml_file = _REG_DIR / f"{yaml_name}.yaml"

    # 기존 _af 파일 로드 (없으면 빈 dict)
    try:
        existing = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        if not isinstance(existing, dict):
            existing = {}
    except FileNotFoundError:
        existing = {}

    existing[slug] = entry
    _AF_HEADER = (
        f"# registry/{yaml_name}.yaml — App Factory 자동생성 계산기 (v3 SSOT)\n"
        "# ⚠️ 이 파일은 App Factory(modules/app_factory)가 자동으로 씁니다. 직접 편집 주의.\n"
        "# status: HOLD = legal 검증 대기 중 (index/sitemap 비노출)\n"
        "# status: READY = 공개 (index/sitemap 포함, CalcMate 정적 사이트 빌드 대상)\n"
    )
    body = yaml.dump(existing, allow_unicode=True, sort_keys=False, default_flow_style=False)
    yaml_file.write_text(_AF_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    LOG.info("v3 Registry 기록(HOLD): %s → %s", slug, yaml_file.name)


def _delete_from_registry_v3(slug: str, category: str) -> bool:
    """_af.yaml에서 slug 엔트리를 제거. 파일 없거나 slug 없으면 False 반환."""
    import yaml
    from .registry_loader import invalidate

    yaml_name = _category_to_af_yaml(category)
    yaml_file = _REG_DIR / f"{yaml_name}.yaml"
    if not yaml_file.exists():
        return False

    try:
        existing = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return False

    if not isinstance(existing, dict) or slug not in existing:
        return False

    del existing[slug]
    _AF_HEADER = (
        f"# registry/{yaml_name}.yaml — App Factory 자동생성 계산기 (v3 SSOT)\n"
        "# ⚠️ 이 파일은 App Factory(modules/app_factory)가 자동으로 씁니다. 직접 편집 주의.\n"
        "# status: HOLD = legal 검증 대기 중 (index/sitemap 비노출)\n"
        "# status: READY = 공개 (index/sitemap 포함, CalcMate 정적 사이트 빌드 대상)\n"
    )
    body = yaml.dump(existing, allow_unicode=True, sort_keys=False, default_flow_style=False)
    yaml_file.write_text(_AF_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    LOG.info("v3 Registry 엔트리 제거: %s → %s", slug, yaml_file.name)
    return True


def promote_to_ready(slug: str) -> tuple:
    """App Factory 계산기의 v3 status를 HOLD → READY로 전환.
    legal 검증 완료 후 호출. 기존 8개 계산기(source != app_factory)에는 동작 거부."""
    import yaml
    from .registry_loader import load_registry_v3, invalidate

    v3 = load_registry_v3(force=True)
    entry = v3.get(slug)
    if entry is None:
        return False, f"v3 Registry에 '{slug}' 없음"
    if entry.get("source") != "app_factory":
        return False, f"'{slug}'은 App Factory 생성 계산기가 아닙니다 (기존 계산기 수정 금지)"
    if entry.get("status") == "READY":
        return True, f"'{slug}'은 이미 READY 상태입니다"

    # 체크리스트 🔴 필수 항목 완료 여부 검증
    checklist = entry.get("review_checklist") or []
    if checklist:
        incomplete = [i.get("label", i.get("id", "?")) for i in checklist
                      if i.get("severity") == "critical" and not i.get("checked")]
        if incomplete:
            return False, (f"🔴 필수 검토 항목 미완료 ({len(incomplete)}개): "
                           f"{incomplete} — 대시보드에서 체크 완료 후 재시도")

    category = entry.get("category", "")
    yaml_name = _category_to_af_yaml(category)
    yaml_file = _REG_DIR / f"{yaml_name}.yaml"

    try:
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return False, f"Registry 파일 읽기 실패: {e}"
    if not isinstance(data, dict) or slug not in data:
        return False, f"'{slug}'이 {yaml_file.name}에 없음"

    data[slug]["status"] = "READY"
    _AF_HEADER = (
        f"# registry/{yaml_name}.yaml — App Factory 자동생성 계산기 (v3 SSOT)\n"
        "# ⚠️ 이 파일은 App Factory(modules/app_factory)가 자동으로 씁니다. 직접 편집 주의.\n"
        "# status: HOLD = legal 검증 대기 중 (index/sitemap 비노출)\n"
        "# status: READY = 공개 (index/sitemap 포함, CalcMate 정적 사이트 빌드 대상)\n"
    )
    body = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    yaml_file.write_text(_AF_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    LOG.info("v3 Registry HOLD→READY: %s", slug)
    return True, f"✅ '{slug}' HOLD → READY 전환 완료. 사이트 재빌드 후 index/sitemap에 반영됩니다."


def build_contract(
    slug: str,
    name: str,
    category: str = "",
    tier: str = "Tier2-A",
    input_fields: list = None,
    output_fields: list = None,
    formula=None,
    formula_status: str = None,
    scope_exclusions: list = None,
    test_cases: list = None,
    desc: str = "",
    legal_refs: list = None,
) -> dict:
    """운영자가 확정한 계산기 스펙을 Contract 객체로 생성.

    Contract는 AI 생성 결과의 기준점이다 — slug/필드명/formula가 AI에 의해
    변경됐는지 validate_against_contract()로 검증한다.

    slug:             확정 URL 식별자 (소문자 영문-숫자-하이픈)
    input_fields:     확정 입력 필드명 리스트 (예: ["years_of_service", "used_days"])
    output_fields:    확정 출력 필드명 리스트 (예: ["total_days", "remaining_days"])
    formula:          확정 수식 (str 또는 dict)
    formula_status:   명시적 상태 ("not_generated"/"ai_suggested"/"pending_validation"/"operator_confirmed").
                      None이면 formula 존재 여부로 자동 도출:
                        formula 있음 → "pending_validation"
                        formula 없음 → "not_generated"
    scope_exclusions: 명시적 제외 조건 (화면 안내문 표시용)
    test_cases:       검증 케이스 [{"input": {...}, "expected": {...}}]
    desc:             계산기 설명 (AI 생성 시 u1/u3 프롬프트에 삽입됨)
    legal_refs:       법령 entity_id 리스트 (legal_master/*.yaml의 entity_id)
    """
    has_formula = formula is not None and formula != ""
    if formula_status is None:
        derived_status = "pending_validation" if has_formula else "not_generated"
    else:
        derived_status = formula_status
    return {
        "slug": str(slug).strip().lower(),
        "name": str(name).strip(),
        "category": str(category).strip(),
        "tier": str(tier).strip(),
        "input_fields": list(input_fields or []),
        "output_fields": list(output_fields or []),
        "formula": formula,
        "formula_status": derived_status,
        "scope_exclusions": list(scope_exclusions or []),
        "test_cases": list(test_cases or []),
        "test_cases_status": "operator_confirmed" if test_cases else "not_generated",
        "desc": str(desc).strip(),
        "legal_refs": list(legal_refs or []),
    }


def check_hold_rules(contract: dict) -> dict:
    """Pre-generation Soft Gate — CA-1A §5 hold_rules 중 HOLD-1/2/3 평가.

    생성 전 운영자에게 위험 요소를 알리기 위한 경고 함수.
    Hard block이 아님. 운영자가 경고를 확인하고 진행 여부를 결정한다.

    반환: {
        "held": bool,           # True이면 경고 있음 (생성 진행은 운영자 결정)
        "rules": list[str],     # 발동된 rule id 목록 (예: ["HOLD-1", "HOLD-3"])
        "messages": list[str],  # 운영자에게 표시할 경고 메시지
    }
    """
    from modules.review_center import CRITICAL_CATEGORIES
    from modules.registry_loader import load_legal_master

    rules, messages = [], []

    # HOLD-1: formula 미확정 또는 검증 미완료 (operator_confirmed만 통과)
    if contract.get("formula_status", "not_generated") != "operator_confirmed":
        rules.append("HOLD-1")
        messages.append(
            "HOLD-1: formula가 운영자 확정 상태가 아닙니다. "
            "수식 없이 생성하면 AI가 임의 수식을 사용할 수 있습니다."
        )

    # HOLD-2: critical category + test_cases 미확정
    if (contract.get("test_cases_status", "not_generated") == "not_generated"
            and contract.get("category", "") in CRITICAL_CATEGORIES):
        rules.append("HOLD-2")
        messages.append(
            f"HOLD-2: '{contract.get('category', '')}' 카테고리는 법령 계산기입니다. "
            "테스트 케이스 없이 생성하면 수식 정확성을 사전 검증할 수 없습니다."
        )

    # HOLD-3: legal_refs entity의 confidence=medium (경고)
    legal_refs = contract.get("legal_refs") or []
    if legal_refs:
        lm = load_legal_master()
        medium_refs = [
            ref for ref in legal_refs
            if (lm.get(ref) or {}).get("confidence") == "medium"
        ]
        if medium_refs:
            rules.append("HOLD-3")
            messages.append(
                f"HOLD-3: 참조 법령 {medium_refs}의 confidence=medium — "
                "법적 불확실성이 있습니다. 내용을 확인하고 진행하세요."
            )

    return {
        "held": bool(rules),
        "rules": rules,
        "messages": messages,
    }


def validate_against_contract(contract: dict, ai_app: dict) -> dict:
    """AI 생성 결과를 Contract와 비교하여 불일치 항목을 반환.

    slug, input/output 필드명, formula 세 축을 비교한다.
    불일치가 있으면 status_hint="INVALID" + messages에 상세 내용을 담아 반환.
    저장(save_app)을 직접 차단하지 않으며 운영자 검토 후 진행하도록 설계됨.

    반환: {
        "valid": bool,
        "slug_mismatch": bool,
        "slug_contract": str,
        "slug_ai": str,
        "schema_drift": dict,   # detect_schema_drift() 결과
        "formula_changed": bool,
        "status_hint": "VALID" | "INVALID",
        "messages": list[str],
    }
    """
    from .formula_engine import detect_schema_drift

    messages = []

    contract_slug = str(contract.get("slug", "")).strip().lower()
    ai_slug = str(ai_app.get("slug", "") or "").strip().lower()
    slug_mismatch = bool(ai_slug and ai_slug != contract_slug)
    if slug_mismatch:
        messages.append(f"slug 불일치: Contract={contract_slug!r} → AI={ai_slug!r}")

    drift = detect_schema_drift(contract, ai_app)
    for change in drift.get("changes", []):
        t = change.get("type", "")
        f_c, f_a = change.get("contract"), change.get("ai")
        if "input_missing" in t:
            messages.append(f"입력 필드 누락: Contract의 {f_c!r}가 AI 결과에 없음")
        elif "input_extra" in t:
            messages.append(f"입력 필드 추가: AI가 {f_a!r}를 추가 (Contract에 없음)")
        elif "output_missing" in t:
            messages.append(f"출력 필드 누락: Contract의 {f_c!r}가 AI 결과에 없음")
        elif "output_extra" in t:
            messages.append(f"출력 필드 추가: AI가 {f_a!r}를 추가 (Contract에 없음)")

    contract_formula = contract.get("formula")
    ai_formula = ai_app.get("formula")
    formula_changed = False
    if contract_formula is not None:
        def _norm(f):
            if isinstance(f, dict):
                return json.dumps(f, ensure_ascii=False, sort_keys=True)
            return str(f or "").strip()
        formula_changed = _norm(contract_formula) != _norm(ai_formula)
        if formula_changed:
            messages.append("formula 변경: AI가 Contract 확정 formula를 수정했습니다")

    valid = not slug_mismatch and not drift["drifted"] and not formula_changed
    return {
        "valid": valid,
        "slug_mismatch": slug_mismatch,
        "slug_contract": contract_slug,
        "slug_ai": ai_slug,
        "schema_drift": drift,
        "formula_changed": formula_changed,
        "status_hint": "VALID" if valid else "INVALID",
        "messages": messages,
    }


# ── CA-3-3: Type D 식별 키워드 ─────────────────────────────────────────────
_TYPE_D_FLOW_KEYWORDS: frozenset = frozenset({
    "매년 변경", "별표", "테이블", "나이·피보험기간",
})


def _is_type_d_flow(calc_flows: list) -> bool:
    """calculation_flow에 Type D 식별자(연도 변경/별표/테이블)가 있으면 True."""
    for item in (calc_flows or []):
        for kw in _TYPE_D_FLOW_KEYWORDS:
            if kw in str(item):
                return True
    return False


def suggest_formula(
    cfg: dict,
    name: str,
    category: str = "",
    desc: str = "",
    input_fields: list = None,
    output_fields: list = None,
    legal_refs: list = None,
    calculation_flow: list = None,
    scope_exclusions: list = None,
    slug: str = None,
) -> dict:
    """Contract 기반 AI Formula 제안 (CA-3-3).

    기존 generate_app() 전체 생성과 무관한 독립 함수.
    AI 호출 1회 (max_tokens=300).

    반환 status:
      "ai_suggested"  — AI 제안 성공
      "not_generated" — 차단/실패

    반환 형식:
    {
        "success": bool,
        "formula": str | dict | None,
        "reason":  str,
        "assumptions": list,
        "warnings":    list[str],
        "status":  "ai_suggested" | "not_generated",
    }

    중요: success=True 라도 "operator_confirmed"가 아니다.
    최종 확정은 반드시 운영자 행동(Dashboard [✅ Formula 확정])으로 이루어진다.
    """
    from modules.formula_engine import CUSTOM_COMPUTE_SLUGS, validate_formula

    input_fields = list(input_fields or [])
    output_fields = list(output_fields or [])

    def _fail(reason: str, warnings: list = None) -> dict:
        LOG.info("suggest_formula 실패: %s", reason)
        return {
            "success": False, "formula": None, "reason": reason,
            "assumptions": [], "warnings": list(warnings or []),
            "status": "not_generated",
        }

    # ── Type D 차단 1: CUSTOM_COMPUTE_SLUGS ───────────────────────
    if slug and slug in CUSTOM_COMPUTE_SLUGS:
        return _fail(
            "이 계산기는 커스텀 계산 로직이 필요하여 AI Formula 자동 제안을 지원하지 않습니다.",
            ["CUSTOM_COMPUTE_SLUGS 대상 계산기"],
        )

    # ── 필수 입력 확인 ─────────────────────────────────────────────
    if not input_fields:
        return _fail("input_fields가 비어 있습니다. Formula 제안에 필요합니다.")
    if not output_fields:
        return _fail("output_fields가 비어 있습니다. Formula 제안에 필요합니다.")

    # ── legal_master에서 calculation_flow 조회 ──────────────────────
    calc_flows = list(calculation_flow or [])
    if legal_refs and not calc_flows:
        try:
            from modules.registry_loader import load_legal_master
            lm = load_legal_master()
            for ref in legal_refs:
                calc_flows.extend((lm.get(ref) or {}).get("calculation_flow") or [])
        except Exception as _e:
            LOG.warning("legal_master 로드 실패: %s", _e)

    # ── Type D 차단 2: calculation_flow 키워드 기반 ─────────────────
    if _is_type_d_flow(calc_flows):
        return _fail(
            "이 계산기는 테이블/법령 기준값 또는 연도별 변경 데이터가 필요하여 "
            "AI Formula 자동 제안을 지원하지 않습니다.",
            ["calculation_flow에 테이블/매년 변경 항목 포함"],
        )

    # ── Prompt 구성 ────────────────────────────────────────────────
    multi_output = len(output_fields) > 1
    if multi_output:
        output_format_rule = (
            f"5. 복수 출력이므로 JSON 형식으로 반환: "
            + json.dumps({k: "산술식" for k in output_fields}, ensure_ascii=False)
            + " (출력 변수 목록과 키 이름 일치)\n"
        )
    else:
        output_format_rule = "5. 단일 출력: 산술 표현식 문자열\n"

    sys_suggest = (
        "너는 계산기 Formula 제안 도우미다.\n"
        "제공된 Contract와 법적 근거 정보만 사용한다.\n"
        "존재하지 않는 입력 변수나 출력 변수를 만들지 않는다.\n"
        "제공되지 않은 법률 규칙, 요율, 기준값을 임의로 생성하지 않는다.\n"
        "계산 규칙이 충분하지 않으면 Formula를 추측하지 않는다.\n"
        "AI의 제안은 운영자의 최종 확정이 아니며, 검증되지 않은 Formula임을 전제로 한다.\n\n"
        f"입력 변수(이것만 사용 가능): {', '.join(input_fields)}\n"
        f"출력 변수: {', '.join(output_fields)}\n"
        + (f"카테고리: {category}\n" if category else "")
        + (f"설명: {desc}\n" if desc else "")
        + (
            "법령 계산 흐름(참고):\n"
            + "\n".join(f"  - {f}" for f in calc_flows)
            + "\n"
            if calc_flows else ""
        )
        + "\n규칙:\n"
        "1. 입력 변수 목록 외 변수 절대 금지\n"
        "2. 대입문(=), 세미콜론(;), 함수 정의, 외부 함수 호출 금지\n"
        "3. 허용 함수: min, max, round, abs, int, float 만\n"
        "4. calculation_flow에 없는 상수·요율 추가 금지\n"
        + output_format_rule
        + "\n반드시 아래 JSON 형식으로만 응답하라:\n"
        '{"formula": "...", "reason": "...", "assumptions": [], "warnings": []}\n'
        "계산 근거가 불충분하면:\n"
        '{"formula": null, "reason": "근거 부족 이유", "assumptions": [], "warnings": ["..."]}'
    )
    u_suggest = f"계산기명: {name}"

    # ── AI 호출 (1회, max_tokens=300) ─────────────────────────────
    try:
        raw_text, _, _ = _chat(cfg, "orchestrator", sys_suggest, u_suggest, 300)
    except Exception as exc:
        LOG.error("suggest_formula AI 호출 실패: %s", exc)
        return _fail(f"AI 호출 실패: {exc}", [str(exc)])

    # ── 빈 응답 처리 ───────────────────────────────────────────────
    if not raw_text or not raw_text.strip():
        return _fail("AI가 빈 응답을 반환했습니다.")

    # ── 응답 파싱 (JSON 우선, raw string 폴백) ─────────────────────
    parsed_formula = None
    reason = ""
    assumptions: list = []
    warnings: list = []

    try:
        obj = parse_json_lenient(raw_text)
        if isinstance(obj, dict):
            parsed_formula = obj.get("formula")
            reason = str(obj.get("reason") or "")
            assumptions = list(obj.get("assumptions") or [])
            warnings = list(obj.get("warnings") or [])
        else:
            parsed_formula = str(obj).strip() if obj is not None else None
    except Exception:
        parsed_formula = raw_text.strip().strip("\"'")

    # ── formula null/빈 처리 ───────────────────────────────────────
    if parsed_formula is None or parsed_formula == "" or parsed_formula == "null":
        return _fail(reason or "AI가 Formula를 생성하지 못했습니다.", warnings)

    # ── dict formula: JSON 문자열이면 파싱 ─────────────────────────
    if isinstance(parsed_formula, str) and parsed_formula.strip().startswith("{"):
        try:
            parsed_formula = json.loads(parsed_formula)
        except Exception:
            pass

    # ── R-2: dict formula 출력 키 검증 ────────────────────────────
    if isinstance(parsed_formula, dict) and output_fields:
        expected_keys = set(output_fields)
        actual_keys = set(parsed_formula.keys())
        extra = actual_keys - expected_keys
        if extra:
            return _fail(
                f"AI가 정의되지 않은 출력 변수를 사용했습니다: {extra}",
                [f"output_fields에 없는 키: {extra}"],
            )

    # ── R-1: 입력 변수 검증 (validate_formula 재사용) ──────────────
    schema = {f: "number" for f in input_fields}
    ok, msg = validate_formula(parsed_formula, schema)
    if not ok:
        return _fail(
            f"AI Formula 변수 검증 실패: {msg}",
            [f"변수 검증 오류: {msg}"],
        )

    return {
        "success": True,
        "formula": parsed_formula,
        "reason": reason,
        "assumptions": assumptions,
        "warnings": warnings,
        "status": "ai_suggested",
    }


# ── Tier2-B: 군인전역일 계산기 HTML 템플릿 ──────────────────────────────────────
# 전역일 = 입영일 + N개월 - 1일 (민간 관행식, 병무청 공식 미확인)
# 민법 제160조 준용: 월 가산 시 해당 월에 대응하는 날이 없으면 그 달의 마지막 날
_MILITARY_DISCHARGE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>군인 전역일 계산기 — CalcMate</title>
<meta name="description" content="입영일과 군별(육군·해군·공군·해병대·사회복무요원)을 선택하면 예상 전역일과 남은 복무일을 계산합니다.">
<style>
:root{--primary:#2563eb;--primary-dark:#1d4ed8;--bg:#f8fafc;--card:#fff;--border:#e2e8f0;--text:#1e293b;--sub:#64748b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:2rem 1rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:2rem;width:100%;max-width:480px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h1{font-size:1.4rem;font-weight:700;margin-bottom:.25rem}
.sub{color:var(--sub);font-size:.85rem;margin-bottom:1.5rem}
.field{margin-bottom:1rem}
label{display:block;font-size:.85rem;font-weight:600;margin-bottom:.35rem;color:var(--sub)}
input[type=date],select{width:100%;padding:.6rem .8rem;border:1px solid var(--border);border-radius:8px;font-size:1rem;outline:none;transition:border .2s}
input[type=date]:focus,select:focus{border-color:var(--primary)}
.btn{width:100%;padding:.75rem;background:var(--primary);color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:.5rem;transition:background .2s}
.btn:hover{background:var(--primary-dark)}
.result{margin-top:1.5rem;padding:1.25rem;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;display:none}
.result-row{display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid #e0f2fe}
.result-row:last-of-type{border-bottom:none}
.result-label{font-size:.85rem;color:var(--sub)}
.result-value{font-size:1.05rem;font-weight:700}
.progress-bar{margin-top:.75rem;background:#e0f2fe;border-radius:99px;height:8px;overflow:hidden}
.progress-fill{height:100%;background:var(--primary);border-radius:99px;transition:width .4s}
.disclaimer{margin-top:1rem;font-size:.78rem;color:var(--sub);line-height:1.5;padding:.75rem;background:#fefce8;border:1px solid #fde68a;border-radius:6px}
</style>
</head>
<body>
<div class="card">
  <h1>군인 전역일 계산기</h1>
  <p class="sub">입영일과 군별을 선택하면 예상 전역일을 계산합니다.</p>
  <div class="field">
    <label for="enlistment_date">입영일</label>
    <input type="date" id="enlistment_date">
  </div>
  <div class="field">
    <label for="branch">군별 / 복무형태</label>
    <select id="branch">
      <option value="army">육군 (18개월)</option>
      <option value="marine">해병대 (18개월)</option>
      <option value="navy">해군 (20개월)</option>
      <option value="air_force">공군 (21개월)</option>
      <option value="social_service">사회복무요원 (21개월)</option>
    </select>
  </div>
  <button class="btn" onclick="calculate()">계산하기</button>
  <div class="result" id="result">
    <div class="result-row">
      <span class="result-label">예상 전역일</span>
      <span class="result-value" id="discharge_date">—</span>
    </div>
    <div class="result-row">
      <span class="result-label">복무 기간</span>
      <span class="result-value" id="service_period">—</span>
    </div>
    <div class="result-row">
      <span class="result-label">남은 일수</span>
      <span class="result-value" id="remaining_days">—</span>
    </div>
    <div class="result-row">
      <span class="result-label">복무 진행률</span>
      <span class="result-value" id="progress_pct">—</span>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progress_fill" style="width:0%"></div></div>
    <div class="disclaimer">
      <strong>참고용 계산 결과</strong> — 관행적 계산 방법(입영일+복무기간-1일)에 따른 결과입니다.
      <strong>실제 전역일은 병무청 확인이 필요합니다.</strong>
      군기교육·복무이탈·개인별 조정 등은 반영되지 않습니다.
    </div>
  </div>
</div>
<script>
var MONTHS={army:18,marine:18,navy:20,air_force:21,social_service:21};
var NAMES={army:'육군',marine:'해병대',navy:'해군',air_force:'공군',social_service:'사회복무요원'};
function addMonths(d,n){
  var sd=d.getDate(),tm=d.getMonth()+n,ty=d.getFullYear()+Math.floor(tm/12),nm=((tm%12)+12)%12;
  var ld=new Date(ty,nm+1,0).getDate();
  return new Date(ty,nm,Math.min(sd,ld));
}
function fmt(d){return d.getFullYear()+'년 '+(d.getMonth()+1)+'월 '+d.getDate()+'일';}
function calculate(){
  var s=document.getElementById('enlistment_date').value;
  var b=document.getElementById('branch').value;
  if(!s){alert('입영일을 선택해 주세요.');return;}
  var en=new Date(s+'T00:00:00'),m=MONTHS[b];
  var dc=addMonths(en,m);dc.setDate(dc.getDate()-1);
  var today=new Date();today.setHours(0,0,0,0);
  var tot=Math.round((dc-en)/86400000)+1;
  var rem=Math.round((dc-today)/86400000);
  var srv=Math.min(Math.max(0,Math.round((today-en)/86400000)),tot);
  var pct=Math.min(100,Math.max(0,Math.round(srv/tot*100)));
  document.getElementById('discharge_date').textContent=fmt(dc);
  document.getElementById('service_period').textContent=NAMES[b]+' '+m+'개월';
  document.getElementById('remaining_days').textContent=rem>0?'D-'+rem:rem===0?'D-Day (오늘 전역)':'전역 완료';
  document.getElementById('progress_pct').textContent=pct+'%';
  document.getElementById('progress_fill').style.width=pct+'%';
  document.getElementById('result').style.display='block';
}
</script>
</body>
</html>"""


def _build_tier2b_app(contract: dict) -> dict:
    """Tier2-B(날짜형) 계산기 — AI 없이 결정적 HTML 생성.

    군인전역일 전용. 입영일+N개월-1일 관행 계산식을 JS로 구현한 HTML을
    app_templates.html_template에 저장한다.
    """
    name = contract.get("name", "군인 전역일 계산기")
    category = contract.get("category", "")
    desc = (contract.get("desc") or "").strip()
    seo_title = f"{name} | CalcMate"
    seo_desc = (
        desc
        or "입영일과 군별(육군·해군·공군·해병대·사회복무요원)을 선택하면 "
           "예상 전역일과 남은 복무일을 계산합니다."
    )
    return {
        "name": name,
        "category": category,
        "calculator_type": "date_based",
        "compute_type": "date_based_custom",
        "tier": 2,
        "html": _MILITARY_DISCHARGE_HTML,
        "css": "",
        "js": "",
        "faq": [],
        "seo_title": seo_title,
        "seo_desc": seo_desc,
        "input_schema": {
            "enlistment_date": {"type": "date", "label": "입영일"},
            "branch": {
                "type": "select",
                "label": "군별",
                "options": ["army", "marine", "navy", "air_force", "social_service"],
            },
        },
        "output_schema": {
            "discharge_date": {"label": "예상 전역일"},
            "remaining_days": {"label": "남은 일수"},
            "progress_pct": {"label": "복무 진행률"},
        },
        "formula": None,
        "labels": {
            "enlistment_date": "입영일",
            "branch": "군별",
            "discharge_date": "예상 전역일",
            "remaining_days": "남은 일수",
            "progress_pct": "복무 진행률",
        },
        "_tokens": 0,
        "_steps": [("Tier2-B 날짜형 결정적 생성", "내부 생성 (AI 없음)", 0)],
        "_formula_valid": True,
        "_formula_msg": "",
        "description": desc,
    }


def generate_app_with_contract(cfg: dict, contract: dict) -> dict:
    """Contract 기반 계산기 생성.

    generate_app()을 호출한 뒤 Contract와 비교 — AI 결과의 slug/필드명/formula가
    Contract를 벗어나면 _contract_validation["valid"]=False로 기록한다.
    운영자가 불일치를 검토·수정한 후 save_app()을 호출하도록 설계됨.
    자동 저장 없음, 자동 승인 없음.
    """
    name = contract.get("name", "")
    category = contract.get("category", "")
    tier_str = contract.get("tier", "Tier2-A")
    tier_int = 1 if tier_str == "Tier1" else 2
    desc = contract.get("desc", "")

    # Tier2-B: AI 없이 결정적 HTML 생성 (날짜형 계산기)
    if tier_str == "Tier2-B":
        result = _build_tier2b_app(contract)
        result["_contract"] = contract
        result["_contract_validation"] = {"valid": True, "messages": [], "schema_drift": {}}
        result["_schema_drift"] = {}
        result["legal_refs"] = list(contract.get("legal_refs") or [])
        return result

    result = generate_app(cfg, name, category=category, desc=desc, tier=tier_int,
                          _contract=contract)

    validation = validate_against_contract(contract, result)
    result["_contract"] = contract
    result["_contract_validation"] = validation
    result["_schema_drift"] = validation["schema_drift"]

    # CA-4-A Gap A: Contract의 legal_refs를 app dict로 전달 — save_app() →
    # extract_checklist() 경로에서 실제 법적 근거가 표시되도록 한다.
    # (Mode A는 _contract 없이 generate_app()만 사용하므로 이 함수를 거치지 않아 무영향)
    result["legal_refs"] = list(contract.get("legal_refs") or [])

    if not validation["valid"]:
        LOG.warning(
            "Contract 불일치 — 운영자 검토 필요: %s → %s",
            name, validation["messages"],
        )
    return result


def _build_contract_enforcement_prompt(contract: dict) -> str:
    """Contract 기반 생성 시 sys1에 삽입되는 스펙 고정 지시문.

    Contract의 input_fields/output_fields/formula/test_cases를 AI에게 명시적으로 전달해
    AI가 Contract를 무시하거나 필드를 누락하는 것을 방지한다.
    """
    input_fields = contract.get("input_fields") or []
    output_fields = contract.get("output_fields") or []
    formula = contract.get("formula")
    test_cases = contract.get("test_cases") or []

    lines = [
        "━━━━ CONTRACT LOCK — 운영자 사전 확정 사양 (절대 변경 금지) ━━━━",
        "아래 스펙은 운영자가 법령·취업규칙에 근거해 AI 호출 전에 확정한 것이다.",
        "AI는 이 스펙을 그대로 구현해야 한다. 협상·간소화·자체 재설계 금지.",
        "",
        f"[고정 입력 필드 {len(input_fields)}개] input_schema 키를 정확히 아래와 일치시켜라:",
        "  " + ", ".join(input_fields),
        "  (키 이름 변경·추가·삭제 절대 금지)",
        "",
        f"[고정 출력 필드 {len(output_fields)}개] output_schema 키를 정확히 아래와 일치시켜라:",
        "  " + ", ".join(output_fields),
        "  (키 이름 변경·추가·삭제 절대 금지)",
        f"  ※ 특히 출력 필드 {len(output_fields)}개를 모두 output_schema에 포함해야 한다 — 하나라도 누락 금지.",
    ]

    if formula is not None:
        formula_str = (json.dumps(formula, ensure_ascii=False)
                       if isinstance(formula, dict) else str(formula))
        lines += [
            "",
            "[고정 Formula] 아래 수식을 그대로 사용해야 한다:",
            f"  {formula_str}",
            "  (변수명·출력 키명·계산 구조 변경 금지)",
            "  (구현 불가 시 임의 수정 말고 생성 실패로 처리할 것)",
        ]

    if test_cases:
        lines += [
            "",
            f"[검증 케이스 {len(test_cases)}개] 아래 입력에 대해 expected 결과가 반드시 나와야 한다:",
        ]
        for tc in test_cases:
            lines.append(f"  입력 {tc.get('input')} → 예상 {tc.get('expected')}")
        lines.append("  (참고가 아니라 필수 통과 기준 — 이 값이 나오지 않으면 formula가 틀린 것이다)")

    # CA-1B-4 P1-B: scope_exclusions — 생성 텍스트 제한 (계산 범위/계산식 제외 아님)
    se_a, se_b, se_o = _scope_exclusions_by_type(
        contract.get("scope_exclusions"), contract.get("legal_refs"))
    if se_a or se_b or se_o:
        se_lines = [
            "",
            "[CONTRACT SCOPE EXCLUSIONS — 생성 텍스트 제한 (계산 범위/계산식 제외 조건이 아님)]",
        ]
        if se_a:
            se_lines += [
                "[인용 금지 조항] — 설명/안내/법적 근거 텍스트에서 아래 조항을 인용하거나 근거로 제시하지 말 것:",
                *[f"  - {x}" for x in se_a],
            ]
        if se_b:
            se_lines += [
                "[사용 금지 표현] — 설명/안내/FAQ/콘텐츠 텍스트에서 아래 표현을 사용하지 말 것:",
                *[f"  - {x}" for x in se_b],
            ]
        if se_o:
            se_lines += [
                "[기타 제한] — 아래 제한을 원문 그대로 준수할 것:",
                *[f"  - {x}" for x in se_o],
            ]
        lines += se_lines

    lines += [
        "",
        "【핵심 규칙】",
        "1. input_schema 키는 위 고정 입력 필드와 완전히 일치해야 한다.",
        "2. output_schema 키는 위 고정 출력 필드와 완전히 일치해야 하며, 하나라도 빠뜨리면 오답이다.",
        "3. formula는 위에 명시된 것을 그대로 사용한다. 자체 재설계 금지.",
        "4. Contract는 협상 대상이 아니다 — 이 규칙을 어긴 응답은 계약 위반이다.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def _suggest_spec(cfg: dict, name: str, category: str, desc: str, tier: int,
                   existing: list, _contract: dict = None) -> tuple:
    """AI(GPT)로 계산기 스펙(input/output schema, formula, labels)을 설계한다.

    generate_app()의 스펙 설계 단계(구 1)/2))를 순수 추출한 헬퍼 — 프롬프트·검증·
    재시도 로직을 한 글자도 바꾸지 않고 그대로 옮긴 것이며 동작은 완전히 동일하다.
    STEP 24-1: 향후 "필드 자동 제안" 미리보기 등에서 이 헬퍼만 재사용하기 위한
    순수 추출이며, 이번 STEP에서는 generate_app() 외의 신규 호출부를 추가하지 않는다.

    반환: (spec: dict, steps: list[(단계, 모델, 토큰)])
    """
    # 기존 계산기 목록 요약(중복 회피 컨텍스트) — sys1에 주입
    existing_summary = "\n".join(
        f"- {c.get('name','')} ({c.get('category','')}): 입력항목 {list(_pj(c.get('input_schema'), {}).keys())}"
        for c in existing
    ) or "(없음)"

    # 1) 총괄(GPT): 스펙 설계 (입력/출력 스키마 + 산식)
    _tier_note = (
        "[Tier2 — 단순 산술/일반 공식] 복잡한 조건분기·날짜 계산 최소화. 수식으로 표현 가능한 계산 위주."
        if tier == 2 else
        "[Tier1 — 법령/조건분기/복잡 계산] 다단계 조건, 날짜 기반, 법령 규정 적용이 필요한 계산."
    )
    # Contract 기반 생성(Mode B)일 때 CONTRACT LOCK 섹션을 sys1에 삽입
    _contract_lock_section = (
        _build_contract_enforcement_prompt(_contract) + "\n\n"
    ) if _contract else ""

    sys1 = (
        f"너는 웹 계산기 기획자다. 주어진 계산기에 대해 입력/출력 스키마와 산식을 설계하라.\n"
        f"계산기 Tier: {_tier_note}\n"
        f"{_contract_lock_section}"
        "요구사항:\n"
        "1. formula 규칙:\n"
        "   - 단일 출력: input_schema 변수만 사용한 단일 산술 표현식(문자열).\n"
        "   - 복수 출력: {출력키: 산술식} JSON 객체. 각 식은 반드시 input_schema 변수만 사용.\n"
        "     (다른 출력키 참조 절대 금지. 예: net_income = gross * 0.967, gross - withholding 방식 금지)\n"
        "   대입문(=), 세미콜론(;), 함수 정의, 미정의 함수 호출 금지.\n"
        "   허용 함수: min, max, round, abs, int, float 만 사용 가능.\n"
        "2. input_schema/output_schema의 모든 키는 반드시 한국어 라벨을 'labels' 필드에 매핑하라 "
        '(예: {"monthly_salary": "월급"}).\n'
        "3. 반드시 아래 JSON 형식으로만 응답하라 — 설명문·거부 메시지 절대 금지:\n"
        '{"calculator_type":"","input_schema":{},"output_schema":{},"formula":"또는{}","labels":{}}\n'
        f"다음은 이미 등록된 계산기 목록이다:\n{existing_summary}\n"
        "위 목록을 참고해 겹치지 않는 스키마를 설계하라. "
        "어떠한 경우에도 위 JSON 형식으로만 응답하라."
    )
    u1 = f"계산기명: {name}\n카테고리: {category}\n설명: {desc}"
    steps = []  # (단계, 모델, 토큰)
    t1, m1, k1 = _chat(cfg, "orchestrator", sys1, u1, 800)
    spec = parse_json_lenient(t1)
    steps.append(("총괄(스펙)", m1, k1))

    # [2] 저장 전 formula 검증 (실패 시 실패사유 알려주고 1회 재시도)
    from .formula_engine import validate_formula
    ok, msg = validate_formula(spec.get("formula", ""), spec.get("input_schema", {}))
    if not ok:
        retry_sys = sys1 + (f"\n\n[재설계] 직전 응답의 formula가 검증 실패했다(사유: {msg}). "
                            "요구사항(단일 산술 표현식 · input_schema 변수만 · 허용 함수만)을 반드시 지켜 다시 설계하라.")
        try:
            t1b, m1b, k1b = _chat(cfg, "orchestrator", retry_sys, u1, 800)
            steps.append(("총괄(재시도)", m1b, k1b))
            spec2 = parse_json_lenient(t1b)
            ok2, msg2 = validate_formula(spec2.get("formula", ""), spec2.get("input_schema", {}))
            if ok2:
                spec, ok, msg = spec2, ok2, msg2   # 유효하면 재시도 결과 채택
            else:
                ok, msg = ok2, msg2                # 여전히 실패 → 원 spec 유지, 검증결과만 갱신
        except Exception as e:
            msg = f"{msg} / 재시도 오류: {e}"
    spec["_formula_valid"] = ok
    spec["_formula_msg"] = msg
    return spec, steps


def generate_app(cfg: dict, name: str, category: str = "", desc: str = "", tier: int = 2,
                 _contract: dict = None) -> dict:
    """계산기 1종을 AI로 생성하여 dict 반환(저장은 save_app).

    _contract: Contract 기반 생성 시 내부적으로 전달되는 확정 스펙 dict.
               Mode A(자동 생성) 호출 시 전달하지 않음 — 기존 동작 그대로 유지.
               Mode B(generate_app_with_contract) 호출 시만 사용.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("계산기명을 입력하세요.")
    steps = []  # (단계, 모델, 토큰)

    # [0] 기존 계산기 목록 로드 — 사전 중복 확인 + GPT 컨텍스트
    try:
        existing = CalculatorRepository(get_db_adapter(cfg)).get_all()
    except Exception:
        existing = []

    # [0-A] 사전 중복 차단 — AI 호출 전, 이름 일치 시 즉시 중단 (AI 토큰 낭비 방지)
    _name_norm = re.sub(r"\s+", "", name).lower()
    for _c in existing:
        if re.sub(r"\s+", "", _c.get("name", "")).lower() == _name_norm:
            raise ValueError(
                f"이미 등록된 계산기와 이름이 동일합니다: '{_c.get('name')}'. "
                "AI 호출 없이 차단됩니다. 다른 이름을 사용하거나 기존 계산기를 검토하세요."
            )

    # [1] 스펙 설계(입력/출력 스키마 + 산식) — STEP 24-1: _suggest_spec()으로 순수 추출
    spec, _spec_steps = _suggest_spec(cfg, name, category, desc, tier, existing, _contract)
    steps.extend(_spec_steps)

    # 2) 코드(Claude): 단일 자가완결 HTML (인라인 CSS/JS) — JSON 미사용(견고)
    sys2 = ("너는 프론트엔드 개발자다. 아래 스펙으로 동작하는 계산기를 "
            "단일 HTML 문서로 만들어라. <style>와 <script>를 인라인으로 포함하고, "
            "입력폼+계산버튼+결과영역을 갖춘다. 설명/마크다운 코드블록 없이 HTML 코드만 출력하라.")
    u2 = (f"계산기명: {name}\n"
          f"input_schema: {json.dumps(spec.get('input_schema', {}), ensure_ascii=False)}\n"
          f"output_schema: {json.dumps(spec.get('output_schema', {}), ensure_ascii=False)}\n"
          f"formula: {spec.get('formula','')}")
    t2, m2, k2 = _chat(cfg, "code", sys2, u2, 4000)
    code = {"html": _strip_fence(t2), "css": "", "js": ""}  # CSS/JS는 HTML에 인라인
    steps.append(("코드(HTML)", m2, k2))

    # 3) 작성(GPT): SEO + FAQ + 블로그 초안
    sys3 = ("너는 SEO 카피라이터다. 아래 계산기에 대한 SEO와 FAQ, 블로그 초안을 작성하라. "
            "순수 JSON만 반환: "
            '{"seo_title":"","seo_desc":"","faq":[{"q":"","a":""}],"blog_draft":""}')
    # CA-1B-4 P1-B: writer 단계(설명/SEO/FAQ/블로그)에 생성 텍스트 제한 전달
    _se3_a, _se3_b, _se3_o = _scope_exclusions_by_type(
        (_contract or {}).get("scope_exclusions"), (_contract or {}).get("legal_refs"))
    _se3_block = ""
    if _se3_a or _se3_b or _se3_o:
        _se3_lines = [
            "",
            "[Contract 생성 텍스트 제한 — 반드시 준수]",
            "(계산 범위/계산식 제외 조건이 아니라 생성 텍스트에 대한 제한이다)",
        ]
        if _se3_a:
            _se3_lines += ["[인용 금지 조항]", *[f"- {x}" for x in _se3_a]]
        if _se3_b:
            _se3_lines += ["[사용 금지 표현]", *[f"- {x}" for x in _se3_b]]
        if _se3_o:
            _se3_lines += ["[기타]", *[f"- {x}" for x in _se3_o]]
        _se3_block = "\n" + "\n".join(_se3_lines)
    u3 = f"계산기명: {name}\n카테고리: {category}\n설명: {desc}" + _se3_block
    t3, m3, k3 = _chat(cfg, "writer", sys3, u3, 1500)
    seo = parse_json_lenient(t3)
    steps.append(("작성(SEO/FAQ/초안)", m3, k3))

    # 4) 이미지(Gemini): 이미지 프롬프트
    sys4 = ("너는 이미지 프롬프트 디자이너다. 썸네일/본문용 영문 이미지 프롬프트를 만들어라. "
            "순수 JSON만 반환: {\"image_prompt_thumbnail\":\"\",\"image_prompt_body\":\"\"}")
    try:
        t4, m4, k4 = _chat(cfg, "image", sys4, f"계산기: {name} ({category})", 400)
        imgp = parse_json_lenient(t4)
        steps.append(("이미지 프롬프트", m4, k4))
    except Exception as e:
        LOG.warning("이미지 프롬프트 생성 실패(무시): %s", e)
        imgp = {"image_prompt_thumbnail": "", "image_prompt_body": ""}

    return {
        "name": name, "category": category, "description": desc,
        "calculator_type": spec.get("calculator_type", "general"),
        "input_schema": spec.get("input_schema", {}),
        "output_schema": spec.get("output_schema", {}),
        "formula": spec.get("formula", ""),
        "labels": spec.get("labels", {}),
        "html": code.get("html", ""), "css": code.get("css", ""), "js": code.get("js", ""),
        "seo_title": seo.get("seo_title", ""), "seo_desc": seo.get("seo_desc", ""),
        "faq": seo.get("faq", []), "blog_draft": seo.get("blog_draft", ""),
        "image_prompt_thumbnail": imgp.get("image_prompt_thumbnail", ""),
        "image_prompt_body": imgp.get("image_prompt_body", ""),
        "_formula_valid": spec.get("_formula_valid", True),
        "_formula_msg": spec.get("_formula_msg", ""),
        "_steps": steps,
        "_tokens": sum(s[2] for s in steps),
        "tier": tier,
    }


def suggest_idea(cfg: dict, keyword: str = "") -> dict:
    """기존 계산기 목록을 참고해 AI가 새 계산기 아이디어(이름/카테고리/설명)를 제안.
    keyword가 주어지면 그 키워드를 중심으로 구체화, 없으면 자유 제안."""
    try:
        existing = CalculatorRepository(get_db_adapter(cfg)).get_all()
    except Exception:
        existing = []
    existing_summary = "\n".join(
        f"- {c.get('name','')} ({c.get('category','')})" for c in existing
    ) or "(없음)"
    keyword = (keyword or "").strip()
    keyword_line = (
        f"\n사용자가 준 키워드: \"{keyword}\" — 이 키워드를 중심으로 "
        "계산기 아이디어를 구체화하라." if keyword else
        "\n키워드가 주어지지 않았으므로 자유롭게 새 아이디어를 제안하라."
    )
    sys0 = (
        "너는 대한민국 노무/급여/세금/정부혜택 분야 웹 계산기 기획자다. "
        "아래는 이미 존재하는 계산기 목록이다:\n" + existing_summary + "\n"
        "이 목록과 겹치지 않는 새로운 실용적인 계산기 아이디어 1개를 제안하라. "
        "직장인이 실제로 검색할 만한 주제로 한정한다."
        + keyword_line +
        "\n순수 JSON만 반환: {\"name\":\"\",\"category\":\"\",\"desc\":\"\"}"
    )
    # 기존 sys1과 동일 provider/모델(orchestrator) 재사용
    text, _m, _k = _chat(cfg, "orchestrator", sys0, "새 계산기 아이디어 1개를 제안하라.", 400)
    d = parse_json_lenient(text)
    return {"name": d.get("name", ""), "category": d.get("category", ""), "desc": d.get("desc", "")}


def _infer_registry_meta(input_schema: dict, output_schema: dict, formula) -> tuple:
    """registry 자동추론(작업지시서 E §3): (date_fields, compute_type, validation_mode, difficulty).
    - date_fields: input_schema 값에 'date' 포함하는 키(app_generator의 date 판정과 동일 기준)
    - compute_type: date 필드 있으면 date_based / formula가 dict거나 출력 2+면 dict / 그 외 single
    - validation_mode: date_based면 skip(날짜 코드계산, formula 미사용), 아니면 formula
    - difficulty: date_based→date_based / dict→multi_output / 그 외 simple
    ※ compute_type의 single/dict는 현재 코드가 소비 안 함(date_based만 소비) — 추론 오차 리스크 낮음."""
    ins = input_schema or {}
    outs = output_schema or {}
    date_fields = [k for k, v in ins.items() if "date" in str(v).lower()]
    if date_fields:
        compute_type = "date_based"
    elif isinstance(formula, dict) or len(outs) >= 2:
        compute_type = "dict"
    else:
        compute_type = "single"
    validation_mode = "skip" if compute_type == "date_based" else "formula"
    difficulty = {"date_based": "date_based", "dict": "multi_output"}.get(compute_type, "simple")
    return date_fields, compute_type, validation_mode, difficulty


def _build_registry_entry(app: dict, slug: str) -> dict:
    """save_app이 registry_auto.yaml에 쓸 자동 엔트리(작업지시서 E §3).
    identity/compute/labels/meta는 자동, legal 전체는 null(사람이 나중에 채움), needs_human_legal=true."""
    ins = app.get("input_schema", {}) or {}
    outs = app.get("output_schema", {}) or {}
    date_fields, compute_type, validation_mode, difficulty = _infer_registry_meta(
        ins, outs, app.get("formula", ""))
    name = app.get("name", "")
    entry = {
        "slug": slug,
        "name": name,
        "category": app.get("category", ""),
        "emoji": "🧮",
        "card_label": name,
        "compute_type": compute_type,
        "date_fields": date_fields,
        "validation_mode": validation_mode,
        "field_labels": app.get("labels", {}) or {},
        "difficulty": difficulty,
        "difficulty_status": "provisional",
        "needs_human_legal": True,
        # legal — 전부 null/빈값(사람이 legal_basis.draft.yaml로 승격하며 채움)
        "law": None, "article": None, "authority": None,
        "related_articles": [],
        "writer_note": None,
        "reviewer_expectation": [],
        "forbidden_articles": [],
        "forbidden_phrases": [],
        "confidence": None,
        "last_verified": None,
        "verification_source": [],
        "content": {"evergreen": None, "update_cycle": None},
        "related_slugs": [],
    }
    if app.get("compute_rules"):
        entry["compute_rules"] = app["compute_rules"]
    return entry


_CALC_INDEX_PATH = Path(__file__).resolve().parent.parent / "docs" / "calculator_index.json"


def _write_calculator_index(cfg: dict) -> None:
    """slug ↔ 한글 name 매핑을 docs/calculator_index.json에 전량 재생성(개발 편의용 인덱스).
    ※ 순수 참조 문서 — 기존 로직(registry/파이프라인/UI)은 이 파일을 읽지 않는다.
       slug=내부식별자(폴더/URL), name=화면표시(한글)의 대응을 한눈에 보기 위한 것."""
    repo = CalculatorRepository(get_db_adapter(cfg))
    idx = {}
    for c in repo.get_all():
        s = str(c.get("slug", "")).strip()
        if s:
            idx[s] = {"name": c.get("name", ""), "category": c.get("category", "")}
    _CALC_INDEX_PATH.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _update_contract_registry(calc_slug: str, contract: dict, generated_at: str) -> None:
    """docs/contract_schema/registry.yaml에 calc_slug 항목 추가/갱신."""
    import yaml
    registry_path = _SCHEMA_DIR / "registry.yaml"
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    instances = data.get("instances") or {}
    instances[calc_slug] = {
        "contract_slug":      contract.get("slug", calc_slug),
        "generated_at":       generated_at,
        "formula_status":     contract.get("formula_status", "not_generated"),
        "test_cases_status":  contract.get("test_cases_status", "not_generated"),
    }
    data["instances"] = instances
    _SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _save_contract_instance(calc_slug: str, contract: dict) -> None:
    """Contract 전체를 docs/contract_schema/instances/{calc_slug}.yaml에 영속화.

    calc_slug : 계산기 slug (Registry v3 key, 파일 인덱스 기준)
    contract  : build_contract() 반환 dict. None/빈 dict이면 noop.
    저장 순서: instances/ 파일 → registry.yaml 인덱스 갱신.
    실패 시 예외를 발생시킨다 — 호출자(save_app)가 LOG.warning으로 처리.
    """
    import yaml
    from datetime import timezone, timedelta
    if not contract:
        return
    KST = timezone(timedelta(hours=9))
    generated_at = datetime.now(KST).isoformat()
    instance = dict(contract)
    instance["generated_at"] = generated_at
    instances_dir = _SCHEMA_DIR / "instances"
    instances_dir.mkdir(parents=True, exist_ok=True)
    instance_path = instances_dir / f"{calc_slug}.yaml"
    with open(instance_path, "w", encoding="utf-8") as f:
        yaml.dump(instance, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    _update_contract_registry(calc_slug, contract, generated_at)
    LOG.info("Contract Instance 저장 완료: %s → %s", calc_slug, instance_path)


def _delete_contract_instance(calc_slug: str) -> bool:
    """Contract Instance를 docs/contract_schema/instances/{calc_slug}.yaml에서 삭제.

    파일이 없으면 조용히 False 반환(오류 없음).
    registry.yaml 항목도 함께 제거.
    반환: True=파일이 존재해 삭제됨, False=파일 없었음.
    """
    import yaml
    instance_path = _SCHEMA_DIR / "instances" / f"{calc_slug}.yaml"
    existed = instance_path.exists()
    if existed:
        instance_path.unlink()
        LOG.info("Contract Instance 파일 삭제: %s", instance_path)
    registry_path = _SCHEMA_DIR / "registry.yaml"
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        instances = data.get("instances") or {}
        if calc_slug in instances:
            del instances[calc_slug]
            data["instances"] = instances
            with open(registry_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            LOG.info("Contract Registry 항목 제거: %s", calc_slug)
    return existed


# ── CA-1B-3-A: Registry→Contract 프리필 브릿지 + Instance Loader ─────────


def _scope_exclusions_by_type(scope_exclusions, legal_refs=None,
                               legal_master: dict = None):
    """Contract scope_exclusions를 TYPE A(인용 금지 조항)/TYPE B(사용 금지 표현)/기타로 분류.

    CA-1B-4 P1-B: Prompt에 유형을 구분해 전달하기 위한 분류기.
    임의 추론이 아니라 legal_master의 forbidden_articles/forbidden_phrases 값과
    데이터 매칭으로 분류한다. 어느 집합에도 없는 값(운영자 수동 추가 등)은
    '기타'로 분리해 원문 그대로 보존한다 — 임의 분류하지 않는다.

    scope_exclusions: Contract의 list (문자열)
    legal_refs:       Contract의 legal_master entity_id 목록 (분류 기준 조회용)
    legal_master:     entity_id → 법령필드 dict. None이면 load_legal_master() 기본 사용.

    반환: (인용_금지_조항_list, 사용_금지_표현_list, 기타_list)
    """
    if legal_master is None:
        from .registry_loader import load_legal_master
        legal_master = load_legal_master()

    articles, phrases = set(), set()
    for ref in (legal_refs or []):
        entity = (legal_master or {}).get(ref)
        if not isinstance(entity, dict):
            continue
        articles.update(str(x) for x in (entity.get("forbidden_articles") or []))
        phrases.update(str(x) for x in (entity.get("forbidden_phrases") or []))

    type_a, type_b, other = [], [], []
    for item in (scope_exclusions or []):
        s = str(item)
        if s in articles:
            type_a.append(s)
        elif s in phrases:
            type_b.append(s)
        else:
            other.append(s)
    return type_a, type_b, other


def _collect_scope_exclusions(entry: dict, legal_master: dict = None) -> list:
    """Registry 엔트리의 legal_refs → legal_master의 forbidden_articles/phrases 수집 (CA-1B-3-B P1).

    변환 규칙 (CA1A 설계):
      Registry entry.legal_refs (entity_id 목록)
        → docs/legal_master/*.yaml 각 entity의
            forbidden_articles + forbidden_phrases 값을 그대로 수집
        → 중복 제거 + 문서 순서 유지 (deterministic)

    - 원본 YAML 값을 그대로 사용하며 법률 문구를 임의로 생성하지 않는다.
    - 데이터가 없으면 빈 리스트 (추측 금지).
    - 존재하지 않는 legal_ref는 임의 추측하지 않고 LOG.warning 후 건너뛴다.

    entry:        Registry v3 엔트리 dict
    legal_master: entity_id → 법령필드 dict. None이면 load_legal_master() 기본 사용.
    """
    if legal_master is None:
        from .registry_loader import load_legal_master
        legal_master = load_legal_master()

    legal_refs = list((entry or {}).get("legal_refs") or [])
    if not legal_refs:
        return []

    collected: list = []
    seen: set = set()
    for ref in legal_refs:
        entity = (legal_master or {}).get(ref)
        if not isinstance(entity, dict):
            LOG.warning("legal_master에 없는 legal_ref 무시: %s", ref)
            continue
        for key in ("forbidden_articles", "forbidden_phrases"):
            for item in entity.get(key) or []:
                if isinstance(item, str) and item.strip() and item not in seen:
                    seen.add(item)
                    collected.append(item)
    return collected


def prefill_contract_from_registry(slug: str, registry: dict = None,
                                   legal_master: dict = None) -> dict:
    """Registry v3 엔트리의 input_labels/output_labels로 Contract 프리필 데이터 생성.

    CA-1B-3-A: Registry → Contract 자동 프리필 브릿지.
    CA-1B-3-B P1: legal_refs → legal_master forbidden_articles/phrases →
                  scope_exclusions 자동 매핑 추가.
    build_contract()를 직접 수정하지 않고, 프리필 데이터 dict를 반환한다.
    Registry에 없는 slug나 metadata는 추측하지 않고 빈 리스트로 처리한다.

    slug:          Registry v3 key (예: "weekly-holiday-allowance")
    registry:      로더 결과 dict. None이면 load_registry_v3() 기본 사용.
    legal_master:  entity_id → 법령필드 dict. None이면 load_legal_master() 기본 사용.
                   (테스트/주입용 선택 파라미터 — 기존 호출부 영향 없음)

    반환:
      {
        "found": bool,          # Registry에 slug 존재 여부
        "entry": dict|None,     # Registry 엔트리 전체 (없으면 None)
        "slug": str, "name": str, "category": str,
        "input_fields": list,   # ← Registry input_labels
        "output_fields": list,  # ← Registry output_labels
        "scope_exclusions": list,  # ← CA-1B-3-B P1: legal_refs → 법령 제외 조건
        "legal_refs": list,     # ← CA-1B-4 P1-D: Registry legal_refs (HOLD-3/Type D/분류용)
        "message": str,         # 실패 사유 (없으면 "")
      }

    원칙: 프리필은 기본값일 뿐 강제 overwrite가 아니다.
    - Registry에 slug 없음 → found=False, 빈 리스트 (호출자가 기존 입력 유지)
    - input_labels/output_labels 없음 → 빈 리스트 (추측 금지)
    - legal_refs/forbidden 없음 → scope_exclusions 빈 리스트 (추측 금지)
    """
    from .registry_loader import load_registry_v3

    reg = dict(registry) if registry is not None else load_registry_v3()
    clean_slug = str(slug or "").strip()
    entry = (reg or {}).get(clean_slug)
    if entry is None:
        return {"found": False, "entry": None, "slug": clean_slug,
                "name": "", "category": "",
                "input_fields": [], "output_fields": [],
                "scope_exclusions": [], "legal_refs": [],
                "message": f"Registry v3에 '{slug}' 엔트리가 없습니다"}
    return {
        "found": True,
        "entry": entry,
        "slug": entry.get("slug") or clean_slug,
        "name": entry.get("name", ""),
        "category": entry.get("category", ""),
        "input_fields": list(entry.get("input_labels") or []),
        "output_fields": list(entry.get("output_labels") or []),
        "scope_exclusions": _collect_scope_exclusions(entry, legal_master),
        "legal_refs": list(entry.get("legal_refs") or []),
        "message": "",
    }


def _safe_contract_slug(slug) -> str:
    """Contract instance 파일명에 사용할 안전한 slug 검증.

    Registry v3 slug 규칙(한글/영문/숫자/_/-)과 동일한 문자만 허용해
    filesystem path traversal("/", "\\", "..")을 차단한다.
    """
    s = str(slug or "").strip()
    if not s:
        raise ValueError("slug가 비어 있습니다")
    if not re.fullmatch(r"[0-9a-zA-Z가-힣_\-]+", s):
        raise ValueError(f"slug에 허용되지 않은 문자가 있습니다: {slug!r}")
    return s


_FORMULA_STATUS_ALLOWED = {"not_generated", "ai_suggested", "pending_validation", "operator_confirmed"}
_TEST_CASES_STATUS_ALLOWED = {"not_generated", "operator_confirmed"}


def validate_contract_instance(data) -> list:
    """Contract instance의 최소 필수 구조/타입 검증 (CA-1B-3-B P0).

    잘못된 instance를 기본값으로 보정하지 않는다 — 오류 메시지 리스트를 반환하고
    호출자(load_contract_instance)가 ValueError로 처리한다.

    반환: 오류 메시지 list[str]. 비어 있으면 검증 통과.
    """
    errors = []
    if not isinstance(data, dict) or not data:
        return ["Contract instance가 dict가 아닙니다 (또는 비어 있습니다)"]

    # slug — str, 빈 문자열 금지
    slug = data.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        errors.append("slug: str 타입의 비어있지 않은 값이어야 합니다")

    # name — str, 빈 문자열 금지
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name: str 타입의 비어있지 않은 값이어야 합니다")

    # formula_status — runtime vocabulary만 허용
    formula_status = data.get("formula_status")
    if formula_status not in _FORMULA_STATUS_ALLOWED:
        errors.append(
            f"formula_status: 허용 값이 아닙니다: {formula_status!r} "
            f"(허용: {sorted(_FORMULA_STATUS_ALLOWED)})"
        )

    # test_cases_status — not_generated / operator_confirmed
    test_cases_status = data.get("test_cases_status")
    if test_cases_status not in _TEST_CASES_STATUS_ALLOWED:
        errors.append(
            f"test_cases_status: 허용 값이 아닙니다: {test_cases_status!r} "
            f"(허용: {sorted(_TEST_CASES_STATUS_ALLOWED)})"
        )

    # list 타입 필드
    for field in ("input_fields", "output_fields", "scope_exclusions", "legal_refs"):
        if not isinstance(data.get(field), list):
            errors.append(f"{field}: list 타입이어야 합니다")

    # generated_at — str + ISO datetime
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        errors.append("generated_at: str 타입의 ISO datetime이어야 합니다")
    else:
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"generated_at: ISO datetime 형식이 아닙니다: {generated_at!r}")

    # formula — optional. 존재하면 str 또는 dict, None 허용.
    if "formula" in data and data["formula"] is not None:
        if not isinstance(data["formula"], (str, dict)):
            errors.append("formula: str 또는 dict (또는 None)이어야 합니다")

    return errors


def load_contract_instance(slug: str) -> dict | None:
    """docs/contract_schema/instances/{slug}.yaml에서 Contract instance를 읽는다.

    CA-1B-3-A: _save_contract_instance()에 대응하는 로더.
    - 파일 없음 → None
    - YAML malformed → ValueError (명확한 오류)
    - instance 구조가 dict가 아님 → ValueError
    - validate_contract_instance() 실패 → ValueError (CA-1B-3-B P0)
    예외를 무시하고 빈 Contract를 만들어 반환하지 않는다.
    """
    import yaml
    safe = _safe_contract_slug(slug)
    instance_path = _SCHEMA_DIR / "instances" / f"{safe}.yaml"
    if not instance_path.exists():
        return None
    try:
        data = yaml.safe_load(instance_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Contract instance YAML 파싱 실패: {safe} — {e}") from e
    if not isinstance(data, dict) or not data:
        raise ValueError(f"Contract instance 구조가 올바르지 않습니다: {safe}")
    errors = validate_contract_instance(data)
    if errors:
        raise ValueError(
            f"Contract instance 스키마 검증 실패: {safe} — " + "; ".join(errors)
        )
    return data


def load_contract_registry() -> dict:
    """docs/contract_schema/registry.yaml의 instances 매핑을 읽는다.

    CA-1B-3-A: _update_contract_registry()가 쓰는 인덱스를 읽는 로더.
    - 파일 없음 → {} (빈 인덱스)
    - YAML malformed → ValueError
    반환: {calc_slug: {contract_slug, generated_at, formula_status, test_cases_status}}
    """
    import yaml
    registry_path = _SCHEMA_DIR / "registry.yaml"
    if not registry_path.exists():
        return {}
    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ValueError(f"Contract Schema Registry YAML 파싱 실패: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Contract Schema Registry 구조가 올바르지 않습니다")
    instances = data.get("instances") or {}
    return instances if isinstance(instances, dict) else {}


def contract_instance_restore(slug: str) -> dict:
    """저장된 Contract instance를 Dashboard 복원용 dict로 정규화 (CA-1B-4 P0).

    load_contract_instance()의 반환값을 위젯 복원에 필요한 형태로 정리한다.
    예외를 전파하지 않고 found=False + message로 변환해 UI에서 안전하게 표시한다.

    - 파일 없음 + Registry contract_source 존재 → Registry snapshot 부분 복원 (CA-1B-4 P1-E)
    - 파일 없음 / slug 안전성 오류 / malformed / 스키마 오류 → found=False + message
    - 정상 → found=True + input/output/scope_exclusions/formula/formula_status/test_cases

    반환:
      {
        "found": bool,
        "instance": dict|None,     # 로드된 원본 instance (없으면 None)
        "slug": str,
        "name": str,
        "input_fields": list,
        "output_fields": list,
        "scope_exclusions": list,
        "formula": str|dict|None,
        "formula_status": str,
        "test_cases": list,
        "message": str,             # 실패 사유 (없으면 "")
      }
    """
    clean_slug = str(slug or "").strip()
    try:
        instance = load_contract_instance(clean_slug)
    except ValueError as e:
        return {"found": False, "instance": None, "slug": clean_slug,
                "name": "", "input_fields": [], "output_fields": [],
                "scope_exclusions": [], "formula": None, "formula_status": "",
                "test_cases": [], "message": str(e)}
    if instance is None:
        # CA-1B-4 P1-E: Registry contract_source fallback
        # instance 파일이 없어도 Registry에 저장된 최소 snapshot으로 부분 복원(프리필 지원).
        # 발동 조건: slug의 instance 파일 없음 AND Registry entry 존재 AND
        #           entry["contract_source"]가 dict (Mode B 저장분만. Mode A는 null → 미발동).
        # formula/test_cases는 snapshot에 없으므로 추측하지 않는다(항상 None/[]).
        from .registry_loader import load_registry_v3
        try:
            _reg = load_registry_v3() or {}
        except Exception as _re:
            LOG.warning("contract_source fallback Registry 조회 실패(무시): %s", _re)
            _reg = {}
        _entry = (_reg or {}).get(clean_slug)
        _cs = (_entry or {}).get("contract_source") if isinstance(_entry, dict) else None
        if isinstance(_cs, dict) and _cs:
            return {
                "found": True,
                "instance": None,   # 실제 instance 파일 없음 — Registry snapshot 기반
                "slug": _cs.get("contract_slug") or clean_slug,
                "name": _entry.get("name", ""),
                "input_fields": list(_cs.get("input_fields") or []),
                "output_fields": list(_cs.get("output_fields") or []),
                "scope_exclusions": _collect_scope_exclusions(_entry),
                "legal_refs": list(_entry.get("legal_refs") or []),
                "formula": None,
                "formula_status": _cs.get("formula_status", "not_generated"),
                "test_cases_status": _cs.get("test_cases_status", "not_generated"),
                "test_cases": [],
                "message": ("Registry contract_source snapshot으로 부분 복원 "
                             f"(instance 파일 없음: '{clean_slug}')"),
            }
        return {"found": False, "instance": None, "slug": clean_slug,
                "name": "", "input_fields": [], "output_fields": [],
                "scope_exclusions": [], "formula": None, "formula_status": "",
                "test_cases": [], "message": f"Contract instance가 없습니다: '{clean_slug}'"}
    return {
        "found": True,
        "instance": instance,
        "slug": instance.get("slug") or clean_slug,
        "name": instance.get("name", ""),
        "input_fields": list(instance.get("input_fields") or []),
        "output_fields": list(instance.get("output_fields") or []),
        "scope_exclusions": list(instance.get("scope_exclusions") or []),
        "formula": instance.get("formula"),
        "formula_status": instance.get("formula_status", "not_generated"),
        "test_cases": list(instance.get("test_cases") or []),
        "message": "",
    }


# ── STEP 4-H-4 P1: save_app() 동시 실행 직렬화 ──────────────────────────
# save_app()은 "중복 확인(read) → DB/Registry 기록(write)" 구간에 락이 없어
# 동시에 같은/다른 slug로 두 요청이 들어오면 (a) 동일 slug가 DB에 중복 저장되고
# (b) v3 Registry(_af.yaml)는 전체 파일을 매번 다시 써서(부분 병합이 아님)
# 나중에 쓴 쪽이 먼저 쓴 쪽의 엔트리를 통째로 덮어써 조용히 유실시킬 수 있음이
# STEP 4-H-4에서 실제로(threading + barrier) 재현됨. 이 프로젝트는 현재
# uvicorn을 단일 프로세스로만 구동하므로(.claude/launch.json, --workers 미지정)
# 프로세스 간 락은 불필요하고 프로세스 내부 Lock으로 충분하다고 판단했다
# (FastAPI의 동기 라우트는 스레드풀에서 실행되므로 같은 프로세스 안에서도
# 실제 스레드 동시 실행이 가능해 in-process Lock이 여전히 필요함).
# 기존 로직은 전혀 바꾸지 않고 함수 전체를 이 락으로 감싸기만 한다.
_SAVE_APP_LOCK = threading.Lock()


def save_app(cfg: dict, app: dict, site_id: str = "", slug: str = None) -> tuple:
    """생성 결과를 calculators + app_templates 시트에 저장(Repository 경유).
    slug: 신규 계산기의 영문 식별자(폴더/URL/내부참조). 미지정 시 _slug(name)로 폴백(하위호환).
    ※ 기존 계산기 slug는 절대 변경하지 않음 — 이 함수는 '신규 저장' 경로에만 관여.
    동시 호출은 _SAVE_APP_LOCK으로 직렬화된다(STEP 4-H-4) — 실제 저장 로직은
    _save_app_locked()에 그대로 있으며 여기서는 변경하지 않았다."""
    with _SAVE_APP_LOCK:
        return _save_app_locked(cfg, app, site_id=site_id, slug=slug)


def _save_app_locked(cfg: dict, app: dict, site_id: str = "", slug: str = None) -> tuple:
    db = get_db_adapter(cfg)
    calc_repo = CalculatorRepository(db)
    tpl_repo = TemplateRepository(db)
    name = app.get("name", "")
    new_slug = (slug or "").strip().lower() or _slug(name)   # 명시 영문 slug 우선, 없으면 기존 방식
    # ── CA-1B-4 P1-C: Mode B(Contract 기반) 전용 formula_status Hard-Gate ──
    # operator_confirmed 상태에서만 저장 허용. Mode A(_contract 없음)는 기존 동작 100% 유지.
    _contract = app.get("_contract")
    if _contract:
        _fs = _contract.get("formula_status")
        if _fs != "operator_confirmed":
            _fs_msg = {
                "not_generated": "Contract Formula가 아직 생성되지 않아 저장할 수 없습니다. "
                                 "Formula를 생성하고 검증을 완료한 후 확정하세요.",
                "ai_suggested": "AI가 제안한 Formula가 아직 확정되지 않아 저장할 수 없습니다. "
                                "Formula 검증 후 Operator Confirm을 완료하세요.",
                "pending_validation": "Formula가 변경되었지만 아직 검증 및 확정되지 않아 저장할 수 없습니다. "
                                       "Formula 검증을 완료한 후 Operator Confirm을 수행하세요.",
            }.get(_fs, "Contract Formula 상태가 유효하지 않아 저장할 수 없습니다.")
            return False, f"🔒 {_fs_msg} (현재 상태: {_fs})"
    try:
        _all = calc_repo.get_all()
    except Exception as e:
        return False, f"기존 계산기 조회 실패(시트 권한 확인): {e}"

    try:
        from .registry_loader import load_registry_v3
        _v3_has_slug = new_slug in load_registry_v3(force=True)
    except Exception:
        _v3_has_slug = None  # Registry 조회 실패 — 판단 불가(고아 자동 정리 비활성, 기존 동작과 동일)

    _existing_by_slug = next(
        (c for c in _all if str(c.get("slug", "")).strip().lower() == new_slug), None)

    # ── STEP 4-H-3 P0: 고아 레코드(DB에만 존재) 자동 정리 ──────────────────
    # 이전 save_app() 호출이 DB 저장(calculators/app_templates)까지는 성공했지만
    # v3 Registry 기록([Step B])에서 실패하면, 계산기는 DB에만 남고 v3 Registry/
    # registry_auto에는 없어 계산기 관리 화면·FastAPI 어디에도 보이지 않는 "고아"
    # 상태가 된다. 이 상태에서는 동일 slug로 재시도해도 아래 "이미 등록됨(DB)"에
    # 막혀 영구히 복구 불가능했다(STEP 4-H-3 진단에서 발견 — P0). v3 Registry에
    # 실제로 없음이 확인된 경우에만(_v3_has_slug is False — 조회 자체가 실패한
    # None은 제외해 오탐/오삭제 방지) delete_app()과 동일한 정리 대상(calculators/
    # app_templates/registry_auto)을 제거하고 정상적으로 재시도를 진행한다.
    if _existing_by_slug is not None and _v3_has_slug is False:
        try:
            _orphan_tpl_id = _existing_by_slug.get("template_id")
            if _orphan_tpl_id:
                db.delete("app_templates", _orphan_tpl_id)
            calc_repo.delete(_existing_by_slug.get("id"))
            try:
                from .registry_loader import remove_auto_entry
                remove_auto_entry(new_slug)
            except Exception:
                pass
            LOG.warning("고아 레코드 자동 정리 완료(이전 Registry 기록 실패분으로 추정): slug=%s", new_slug)
        except Exception as _cleanup_e:
            return False, (
                f"'{new_slug}'는 DB에만 존재하는 고아 레코드로 추정되나 자동 정리에 실패했습니다: "
                f"{_cleanup_e} — 수동 확인 필요"
            )
        _all = [c for c in _all if c.get("id") != _existing_by_slug.get("id")]

    # 중복 체크(이름)
    if any(str(c.get("name", "")).strip().lower() == name.lower() for c in _all):
        return False, f"중복 계산기명: '{name}' 이미 등록됨"
    # 중복 체크(slug) — DB + v3 Registry 모두 확인(기존 8개 포함)
    if any(str(c.get("slug", "")).strip().lower() == new_slug for c in _all):
        return False, f"중복 슬러그: '{new_slug}' 이미 등록됨 (DB)"
    if _v3_has_slug:
        return False, f"중복 슬러그: '{new_slug}' 이미 v3 Registry에 존재"

    try:
        # 템플릿 먼저 저장 → template_id 확보
        tpl_id = tpl_repo.save({
            "template_name": f"{name} 템플릿",
            "template_type": app.get("calculator_type", "general"),
            "html_template": app.get("html", ""),
            "seo_template": json.dumps(
                {"seo_title": app.get("seo_title", ""), "seo_desc": app.get("seo_desc", ""),
                 "css": app.get("css", ""), "js": app.get("js", "")}, ensure_ascii=False),
            "faq_template": json.dumps(app.get("faq", []), ensure_ascii=False),
            "status": "active",
        })
        _formula = app.get("formula", "")
        _formula_stored = (json.dumps(_formula, ensure_ascii=False)
                           if isinstance(_formula, dict) else (_formula or ""))
        calc_repo.save({
            "name": name, "slug": new_slug, "category": app.get("category", ""),
            "calculator_type": app.get("calculator_type", "general"),
            "template_id": tpl_id, "site_id": site_id,
            "formula": _formula_stored,
            "labels": json.dumps(app.get("labels", {}), ensure_ascii=False),
            "faq": json.dumps(app.get("faq", []), ensure_ascii=False),
            "input_schema": json.dumps(app.get("input_schema", {}), ensure_ascii=False),
            "output_schema": json.dumps(app.get("output_schema", {}), ensure_ascii=False),
            "seo_title": app.get("seo_title", ""), "seo_desc": app.get("seo_desc", ""),
            "status": "active",
        })
    except Exception as e:
        return False, f"저장 실패(시트 권한 확인): {e}"
    # [Step A] registry_auto.yaml — 스테이징 레이어(기존 경로 유지)
    _v3_warn = ""
    try:
        from .registry_loader import add_auto_entry
        add_auto_entry(new_slug, _build_registry_entry(app, new_slug))
        LOG.info("registry_auto 엔트리 기록(스테이징): %s", new_slug)
    except Exception as _re:
        LOG.warning("registry_auto 기록 실패(무시): %s", _re)
    # [Step B] v3 Registry 즉시 기록 — 프로덕션 SSOT(Plan A: save_app() 즉시)
    # 실패해도 계산기 DB 저장은 유효(경고 반환)
    try:
        _tier = app.get("tier", 2)
        _v3_entry = _build_v3_entry(app, new_slug, tier=_tier, contract=app.get("_contract"))
        _write_registry_v3(new_slug, _v3_entry, app.get("category", ""))
        LOG.info("v3 Registry 기록(HOLD): %s", new_slug)
    except Exception as _v3e:
        _v3_warn = f" ⚠️ v3 Registry 기록 실패({_v3e}) — 사이트 관리 탭에서 수동 확인 필요"
        LOG.warning("v3 Registry 기록 실패(계산기 저장은 완료됨): %s", _v3e)
    # [Step B'] Contract Instance 영속화 (Mode B만 해당, Registry 성공 시)
    # Registry 실패(_v3_warn 있음) 시 Contract Instance도 저장하지 않아 고아 파일 방지.
    if not _v3_warn and app.get("_contract"):
        try:
            _save_contract_instance(new_slug, app["_contract"])
        except Exception as _cie:
            LOG.warning("Contract Instance 저장 실패(무시): %s", _cie)
    # calculator_index.json 갱신(개발 편의용)
    try:
        _write_calculator_index(cfg)
    except Exception as _ie:
        LOG.warning("calculator_index 갱신 실패(무시): %s", _ie)
    LOG.info("App Factory 저장 완료: %s (tpl=%s)", name, tpl_id)
    _msg = f"✅ '{name}' 계산기 + 템플릿 저장 완료 (template_id={tpl_id})"
    _msg += " | v3 Registry HOLD 등록 완료. legal 검증 후 READY 전환 필요." if not _v3_warn else _v3_warn
    # [Step C] 검토 체크리스트 자동 추출 + _af.yaml에 저장
    if not _v3_warn:
        try:
            from modules.review_center import extract_checklist
            _tier_str = f"Tier{_tier}-A" if _tier == 2 else "Tier1"
            _checklist = extract_checklist(app, tier=_tier_str, category=app.get("category", ""))
            save_af_checklist(new_slug, _checklist)
            LOG.info("검토 체크리스트 저장 완료: %s (%d 항목)", new_slug, len(_checklist))
        except Exception as _ce:
            # ── STEP 4-H-3 P0: 체크리스트 폴백 — Legal Hold 우회 방지 ──────────
            # promote_to_ready()는 review_checklist가 비어 있으면(`if checklist:`)
            # critical 미완료 검사 자체를 건너뛴다 — 즉 이 예외를 그냥 삼키면
            # (기존 동작) checklist가 아예 기록되지 않아 이후 아무 검증 없이
            # READY 승격이 가능해진다(STEP 4-H-3 진단에서 발견 — P0). checklist
            # 구조/판정 로직(promote_to_ready)은 건드리지 않고, 그 로직이 이미
            # 전제하는 "critical 미체크 항목이 있으면 차단" 규칙이 항상 성립하도록
            # 폴백 항목 하나를 대신 기록해 승격을 계속 차단한다.
            LOG.warning("체크리스트 자동 추출/저장 실패 — 승인 차단용 폴백 항목 기록: %s", _ce)
            try:
                _fallback_checklist = [{
                    "id": "checklist_generation_failed",
                    "severity": "critical",
                    "label": "체크리스트 자동 생성 실패 — 수동 검토 필요",
                    "display_value": f"자동 추출/저장 중 오류 발생: {_ce}",
                    "auto_source": "fallback_on_error",
                    "checked": False, "checked_by": None, "checked_at": None,
                }]
                save_af_checklist(new_slug, _fallback_checklist)
            except Exception as _ce2:
                LOG.error(
                    "폴백 체크리스트 저장도 실패 — READY 전환 시 Legal Hold 검증이 우회될 수 있음. "
                    "수동 확인 필요: slug=%s, error=%s", new_slug, _ce2,
                )
    return True, _msg


def delete_app(cfg: dict, slug: str) -> tuple[bool, str]:
    """App Factory 계산기 전체 삭제 (테스트 정리용).
    삭제 대상: calculators + app_templates (DB), registry_auto.yaml, _af.yaml v3 Registry.
    기존 8개 계산기(source != app_factory) 보호 — v3에 있는데 source가 app_factory가 아니면 거부."""
    from .registry_loader import load_registry_v3, invalidate, remove_auto_entry

    v3 = load_registry_v3(force=True)
    entry_v3 = v3.get(slug)
    if entry_v3 is not None and entry_v3.get("source") != "app_factory":
        return False, f"'{slug}'은 App Factory 계산기가 아닙니다(source={entry_v3.get('source')!r}) — 삭제 거부"

    db = get_db_adapter(cfg)
    calc_repo = CalculatorRepository(db)

    rows = db.get_where("calculators", {"slug": slug})
    if not rows:
        return False, f"calculators에서 '{slug}' 조회 실패 — 이미 삭제됐거나 존재하지 않음"

    row = rows[0]
    calc_id = row.get("id")
    tpl_id = row.get("template_id")
    category = row.get("category", "")

    if tpl_id:
        try:
            db.delete("app_templates", tpl_id)
            LOG.info("app_templates 삭제 완료: %s", tpl_id)
        except Exception as e:
            LOG.warning("app_templates 삭제 실패(계속 진행): %s", e)

    try:
        calc_repo.delete(calc_id)
        LOG.info("calculators 삭제 완료: %s (%s)", slug, calc_id)
    except Exception as e:
        return False, f"calculators 삭제 실패: {e}"

    try:
        removed = remove_auto_entry(slug)
        LOG.info("registry_auto 엔트리 제거: %s (%s)", slug, "제거됨" if removed else "없었음")
    except Exception as e:
        LOG.warning("registry_auto 엔트리 제거 실패(계속 진행): %s", e)

    try:
        _cat = entry_v3.get("category", category) if entry_v3 else category
        removed_v3 = _delete_from_registry_v3(slug, _cat)
        LOG.info("v3 Registry 엔트리 제거: %s (%s)", slug, "제거됨" if removed_v3 else "없었음")
    except Exception as e:
        LOG.warning("v3 Registry 엔트리 제거 실패(계속 진행): %s", e)

    # Contract Instance 정리 (없으면 조용히 종료 — delete_app() 성공/실패에 영향 없음)
    try:
        _delete_contract_instance(slug)
    except Exception as e:
        LOG.warning("Contract Instance 정리 실패(계속 진행): %s", e)

    try:
        _write_calculator_index(cfg)
    except Exception as e:
        LOG.warning("calculator_index 재생성 실패(무시): %s", e)

    invalidate()
    LOG.info("App Factory 계산기 삭제 완료: %s (calc_id=%s, tpl_id=%s)", slug, calc_id, tpl_id)
    return True, f"✅ '{slug}' 삭제 완료 (calc_id={calc_id}, tpl_id={tpl_id})"


def get_af_checklist(slug: str) -> list[dict]:
    """Registry v3에서 slug의 review_checklist 반환. 없으면 []."""
    from .registry_loader import load_registry_v3
    v3 = load_registry_v3(force=True)
    entry = v3.get(slug, {})
    return list(entry.get("review_checklist", []) or [])


def save_af_checklist(slug: str, checklist: list[dict]) -> None:
    """_af.yaml에서 slug 엔트리의 review_checklist를 갱신."""
    import yaml
    from .registry_loader import load_registry_v3, invalidate

    v3 = load_registry_v3(force=True)
    entry = v3.get(slug)
    if entry is None or entry.get("source") != "app_factory":
        raise ValueError(f"'{slug}'은 App Factory 계산기가 아니거나 존재하지 않음")

    category = entry.get("category", "")
    yaml_name = _category_to_af_yaml(category)
    yaml_file = _REG_DIR / f"{yaml_name}.yaml"

    try:
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise RuntimeError(f"Registry 파일 읽기 실패: {e}")

    if not isinstance(data, dict) or slug not in data:
        raise ValueError(f"'{slug}'이 {yaml_file.name}에 없음")

    data[slug]["review_checklist"] = checklist
    _AF_HEADER = (
        f"# registry/{yaml_name}.yaml — App Factory 자동생성 계산기 (v3 SSOT)\n"
        "# ⚠️ 이 파일은 App Factory(modules/app_factory)가 자동으로 씁니다. 직접 편집 주의.\n"
        "# status: HOLD = legal 검증 대기 중 (index/sitemap 비노출)\n"
        "# status: READY = 공개 (index/sitemap 포함, CalcMate 정적 사이트 빌드 대상)\n"
    )
    body = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    yaml_file.write_text(_AF_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    LOG.info("체크리스트 갱신: %s", slug)


def update_compute_rules(slug: str, rules: dict) -> tuple[bool, str]:
    """기존 App Factory 계산기의 compute_rules를 v2(registry_auto.yaml)와
    v3(docs/registry/*_af.yaml)에 동시에 반영한다(STEP 28-130).

    이 함수는 Validation 정책을 추론/생성하지 않는다 — rules는 이미 사람이 확정한
    내용을 그대로 받아 두 registry에 정확히 기록하는 것이 유일한 역할이다.
    compute_rules 외의 다른 필드(name/category/field_labels/formula/law/status/
    review_checklist 등)는 절대 건드리지 않는다.

    사전 검증을 전부 통과해야만 쓰기를 시작한다(한쪽만 갱신되는 사고 방지):
      1. rules가 dict가 아니면 TypeError.
      2. slug가 v2(registry_auto.yaml)에 없으면 ValueError — v3도 쓰지 않는다.
      3. slug가 v3(docs/registry/*_af.yaml)에 없거나 source != app_factory면
         ValueError — v2도 쓰지 않는다(save_af_checklist()와 동일한 보호 기준).

    rules={} 는 기존 시스템의 "compute_rules 없음"과 동일한 의미(falsy)로
    그대로 저장한다 — 별도의 특수 처리를 하지 않는다."""
    import yaml
    from .registry_loader import _read_yaml, _AUTO_PATH, add_auto_entry, load_registry_v3, invalidate

    if not isinstance(rules, dict):
        raise TypeError(f"compute_rules는 dict여야 합니다: {type(rules)!r}")

    # ── 1) v2 엔트리 존재 확인(읽기만 — 아직 아무것도 쓰지 않는다) ──
    v2_data = _read_yaml(_AUTO_PATH)
    if slug not in v2_data or not isinstance(v2_data.get(slug), dict):
        raise ValueError(f"v2 Registry(registry_auto.yaml)에 '{slug}' 없음 — 갱신 거부")
    v2_entry = dict(v2_data[slug])  # 얕은 복사 — compute_rules 외 필드 보존용

    # ── 2) v3 엔트리 존재 확인(읽기만) ──
    v3_index = load_registry_v3(force=True)
    v3_meta = v3_index.get(slug)
    if v3_meta is None or v3_meta.get("source") != "app_factory":
        raise ValueError(f"'{slug}'은 v3 Registry에 없거나 App Factory 계산기가 아님 — 갱신 거부")

    category = v3_meta.get("category", "")
    yaml_name = _category_to_af_yaml(category)
    yaml_file = _REG_DIR / f"{yaml_name}.yaml"
    try:
        v3_file_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ValueError(f"v3 Registry 파일 없음: {yaml_file.name} — 갱신 거부")
    if not isinstance(v3_file_data, dict) or slug not in v3_file_data:
        raise ValueError(f"'{slug}'이 {yaml_file.name} 파일 내용에 없음 — 갱신 거부")

    # ── 사전 검증 통과 — 여기서부터 실제 쓰기 시작 ──
    # v2: 기존 add_auto_entry()는 엔트리 전체를 교체하므로, 반드시 기존 엔트리를
    # 얕은 복사해 compute_rules만 바꾼 뒤 전달한다(다른 필드 보존).
    v2_entry["compute_rules"] = rules
    add_auto_entry(slug, v2_entry)

    # v3: save_af_checklist()와 동일한 방식으로 해당 slug의 compute_rules만 갱신.
    v3_file_data[slug]["compute_rules"] = rules
    _AF_HEADER = (
        f"# registry/{yaml_name}.yaml — App Factory 자동생성 계산기 (v3 SSOT)\n"
        "# ⚠️ 이 파일은 App Factory(modules/app_factory)가 자동으로 씁니다. 직접 편집 주의.\n"
        "# status: HOLD = legal 검증 대기 중 (index/sitemap 비노출)\n"
        "# status: READY = 공개 (index/sitemap 포함, CalcMate 정적 사이트 빌드 대상)\n"
    )
    body = yaml.dump(v3_file_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    yaml_file.write_text(_AF_HEADER + "\n" + body, encoding="utf-8")
    invalidate()
    LOG.info("compute_rules 갱신(v2+v3): %s", slug)
    return True, f"'{slug}' compute_rules를 v2/v3 registry에 동시 반영 완료"
