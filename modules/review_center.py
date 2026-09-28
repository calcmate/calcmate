# -*- coding: utf-8 -*-
"""
modules/review_center.py — Phase3-3 검토센터 핵심 로직

설계 기준: docs/PHASE3_3_DESIGN.md
- 체크리스트 자동 추출 (규칙 기반)
- Build 사전 QA 6단계
- slug 중복 차단
- Tier AI 추천
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# D-2: 법령 검토가 🔴 필수인 카테고리 목록
CRITICAL_CATEGORIES = frozenset({
    "세금/세법", "노동/고용법", "복지/사회보험", "병역/공무",
    "세금/정부혜택", "노무/급여", "고용/보험", "노무/급여/보험",
})

# D-4: Tier2-B 감지 키워드 (rule-based, AI 이전 단계)
TIER2B_KEYWORDS = ["날짜", "기간", "전역일", "만료일", "종료일", "d-day", "디데이", "복무", "개월수"]

# STEP 25-2: Mode 추천 후처리용 법령/규정성 신호 키워드 (rule-based, B→A 오판 보정)
LEGAL_SIGNAL_KEYWORDS = [
    "법령", "법률", "법정", "규정", "근로기준법", "병역법", "소득세법",
    "요율", "세율", "보험료율", "상한", "하한", "연도별", "예외", "특례",
]

# STEP 28-208: DB formula가 비어 있고 실제 계산이 modules/app_generator.py의 slug
# 조건부 코드 분기로 구현된 App Factory 계산기 명시적 allowlist(추측 감지 방지,
# STEP 28-207 설계 확정). formula가 falsy이고 이 집합에 있는 slug에 한해서만
# formula_accuracy/rate_constant를 "코드 구현 존재" 기준으로 생성한다 — 그 외에는
# 기존 "DB formula 존재" 기준 동작을 그대로 유지한다.
CODE_BASED_SLUGS = frozenset({
    "자동차_취등록세_계산기",
    "연금저축_irp_세액공제_계산기",
    # IRP-24: 신규 생성 계산기. Contract formula가 삼항 조건식(IfExp)을 포함해
    # 안전식 평가기가 거부(_formula_valid=False) — 실제 계산은 위 IRP와 동일한
    # slug 조건부 코드 분기(modules/app_generator.py)로 구현됨.
    "irp-tax-credit-v2",
})

# STEP 28-208: 위 계산기들의 formula_accuracy/rate_constant display_value.
# 실제 파일 경로/테스트 파일명/legal_master entity_id를 그대로 사용 — 추측 문구 없음.
CODE_BASED_EVIDENCE = {
    "자동차_취등록세_계산기": {
        "formula_accuracy": (
            "⚠️ DB formula 없음(formula={}) — 실제 계산 로직은 "
            "modules/app_generator.py의 slug 조건부 분기(자동차_취등록세_계산기)에 구현됨. "
            "검증: tests/test_step28_193_car_tax_compute.py(33개), "
            "tests/test_car_tax_input_validation.py(8개) 전체 PASS."
        ),
        "rate_constant": (
            "⚠️ DB formula 없음 — 코드 내 RATE_MAP={1:0.07,2:0.04,3:0.04,4:0.05,5:0.02}, "
            "경차 감면 한도 750,000원, 친환경차 감면 한도 1,400,000원(modules/app_generator.py). "
            "근거: legal_master local_tax_act_12, local_tax_special_act_67, "
            "local_tax_special_act_66_4. 검증: tests/test_step28_193_car_tax_compute.py."
        ),
    },
    # IRP-10/11: DB calculators.formula는 여전히 옛 공식(min(7000000, ...,
    # 0.12*annual_income))이 남아 있으나(IRP-04에서 의도적으로 미변경 — DB 수정
    # 금지 원칙), 실제 계산은 modules/app_generator.py의 slug 조건부 분기가
    # 전담하며 이 옛 DB formula는 전혀 읽지 않는다. 아래 evidence는 그 실제
    # 분기 코드(_compute_js(), 약 1066행)의 상수를 그대로 인용한다.
    "연금저축_irp_세액공제_계산기": {
        "formula_accuracy": (
            "⚠️ DB calculators.formula는 옛 공식(min(7000000, pension_contribution + "
            "irp_contribution, 0.12 * annual_income) 등)이 남아 있으나 공식 계산 근거가 "
            "아님 — 실제 계산 로직은 modules/app_generator.py의 slug 조건부 분기"
            "(연금저축_irp_세액공제_계산기)에 구현됨. "
            "검증: tests/test_irp_tax_credit_compute.py(13개) 전체 PASS."
        ),
        "formula_cap": (
            "⚠️ DB formula의 min(7000000, ..., 0.12*annual_income) cap은 실제 코드에 "
            "존재하지 않음(IRP-02에서 법적 근거 없음 확정, IRP-04에서 제거됨) — 실제 상한은 "
            "코드 내 PENSION_CAP=6,000,000(연금저축 인정액), TOTAL_CAP=9,000,000"
            "(연금저축+IRP 합산 인정액)이며 소득 대비 비율 cap은 없음(modules/app_generator.py). "
            "검증: tests/test_irp_tax_credit_compute.py."
        ),
        "rate_constant": (
            "⚠️ DB formula 내 상수(0.12/0.15/0.12)는 옛 공식의 것으로 공식 근거가 아님 — "
            "실제 코드 내 INCOME_THRESHOLD=55,000,000 기준 annual_income<=threshold면 "
            "세율 0.15, 초과면 0.12(modules/app_generator.py). "
            "근거: legal_master income_tax_act_137(연금계좌세액공제 서브항목, 소득세법 "
            "제59조의3). 검증: tests/test_irp_tax_credit_compute.py."
        ),
    },
    # IRP-24: Contract(build_contract) formula 원안은 삼항 조건식을 포함해 build_calculator()의
    # Formula Hard Gate(안전식 평가기)가 거부했다(_formula_valid=False, "허용되지 않은 식:
    # IfExp"). 원안에서 삼항식만 제거한 단순화(세율 0.12 고정) 근사식으로 DB
    # calculators.formula를 정리했다 — 연금저축_irp_세액공제_계산기의 "옛 공식이 남아있으나
    # 공식 계산 근거가 아님"과 동일한 성격(Hard Gate/QA 통과용 근사치일 뿐 실제 계산 근거
    # 아님). 실제 계산은 modules/app_generator.py의 slug 조건부 분기(irp-tax-credit-v2)가
    # 전담하며 조건부 세율(0.15/0.12)을 정확히 반영한다.
    "irp-tax-credit-v2": {
        "formula_accuracy": (
            "⚠️ DB calculators.formula는 삼항식(조건부 세율)을 제거한 단순화 근사치"
            "(세율 0.12 고정)일 뿐 공식 계산 근거가 아님 — 실제 계산 로직은 modules/"
            "app_generator.py의 slug 조건부 분기(irp-tax-credit-v2)에 구현되어 있으며 "
            "총급여 5,500만원 기준 0.15/0.12 조건부 세율을 정확히 반영함. "
            "검증: tests/test_irp_tax_credit_v2_compute.py 전체 PASS."
        ),
        "formula_cap": (
            "실제 상한은 코드 내 PENSION_ANNUAL_CAP=6,000,000(연금저축 인정액), "
            "COMBINED_ANNUAL_CAP=9,000,000(연금저축+IRP 합산 인정액)이며 소득 대비 "
            "비율 cap은 없음(modules/app_generator.py). "
            "검증: tests/test_irp_tax_credit_v2_compute.py."
        ),
        "rate_constant": (
            "코드 내 HIGH_INCOME_LINE=55,000,000 기준 annual_income<=threshold면 "
            "세율 0.15, 초과면 0.12(modules/app_generator.py). "
            "근거: legal_master income_tax_act_137(연금계좌세액공제 서브항목, 소득세법 "
            "제59조의3). 검증: tests/test_irp_tax_credit_v2_compute.py."
        ),
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pj(v, default=None):
    """JSON 문자열/딕셔너리 안전 파싱. 순수 수식 문자열은 그대로 반환."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return default if default is not None else {}
        try:
            return json.loads(s)  # JSON dict/list인 경우
        except Exception:
            return v  # 수식 문자열 등은 그대로 반환
    return default if default is not None else {}


# ─────────────────────────────────────────────────────────────
# 1. 검토 체크리스트 자동 추출
# ─────────────────────────────────────────────────────────────

def extract_checklist(app: dict, tier: str = "Tier2-A", category: str = "") -> list[dict]:
    """
    계산기 데이터에서 검토 체크리스트 항목을 규칙 기반으로 추출.
    app: generate_app() 또는 DB 계산기 dict
    tier: "Tier2-A" | "Tier2-B" | "Tier1"
    category: 계산기 카테고리 문자열
    반환: list of ChecklistItem dict
    """
    items = []
    formula = _pj(app.get("formula"), "")
    legal_refs = app.get("legal_refs") or []
    compute_rules = _pj(app.get("compute_rules"), {})
    input_schema = _pj(app.get("input_schema"), {})
    slug = str(app.get("slug", ""))

    is_date_based = (app.get("compute_type") == "date_based" or tier == "Tier2-B")
    # STEP 28-208: formula가 비어 있어도 CODE_BASED_SLUGS에 등록된 계산기는
    # formula_accuracy/rate_constant를 코드 구현 근거로 생성한다.
    # IRP-11: 이전에는 "formula가 비어 있을 때만" 코드 기반으로 인정했으나(자동차_
    # 취등록세_계산기는 실제로 DB formula가 비어 있어 이 조건으로도 충분했음),
    # IRP처럼 DB formula가 옛 값으로 남아있는(비어있지 않은) 코드 기반 계산기도
    # 있으므로 "CODE_BASED_SLUGS 등록 여부"만으로 판정한다 — formula 존재 자체는
    # 더 이상 code-based 판정을 막지 않는다(자동차_취등록세_계산기는 formula가
    # 원래 비어 있으므로 이 변경으로 동작이 바뀌지 않음).
    is_code_based = slug in CODE_BASED_SLUGS

    # D-2: 카테고리 기반 법적 근거 등급 결정
    legal_severity = "critical" if (not category or category in CRITICAL_CATEGORIES) else "advisory"

    # ─ formula_accuracy: Tier2-A + formula 있는 경우 (STEP 28-208: 코드 기반
    # 계산기는 formula가 비어 있어도 코드 구현 근거로 이 항목을 생성한다)
    if (formula or is_code_based) and not is_date_based:
        if is_code_based:
            display_value = CODE_BASED_EVIDENCE[slug]["formula_accuracy"]
            auto_source = "code_branch_field"
        else:
            formula_str = (json.dumps(formula, ensure_ascii=False)
                           if isinstance(formula, dict) else str(formula))
            display_value = formula_str[:400]
            auto_source = "formula_field"
        items.append({
            "id": "formula_accuracy",
            "severity": "critical",
            "label": "계산 공식 정확성",
            "display_value": display_value,
            "auto_source": auto_source,
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ legal_basis: 항상 추가 (등급은 카테고리로 결정)
    if not legal_refs:
        disp = "⚠️ legal_refs 미입력 — 근거 법령이 있으면 입력 필요"
        src = "legal_refs_empty"
    else:
        disp = str(legal_refs)
        src = "legal_refs_present"
    items.append({
        "id": "legal_basis",
        "severity": legal_severity,
        "label": "법적 근거 (법령/조항)",
        "display_value": disp,
        "auto_source": src,
        "checked": False, "checked_by": None, "checked_at": None,
    })

    # ─ formula_cap: formula에 min()/max() cap 함수가 포함된 경우 (법정 상한/하한 유지 확인)
    # IRP-11: 코드 기반 계산기는 DB formula의 stale cap이 아니라 CODE_BASED_EVIDENCE의
    # "formula_cap" 근거를 사용한다(있는 경우에만 — 자동차_취등록세_계산기처럼 evidence에
    # 이 키가 없으면 기존과 동일하게 항목 자체를 생성하지 않는다, 그 계산기는 formula도
    # 비어 있어 애초에 이 블록 자체가 실행되지 않았던 것과 동일한 결과).
    if is_code_based and not is_date_based:
        cap_evidence = CODE_BASED_EVIDENCE.get(slug, {}).get("formula_cap")
        if cap_evidence:
            items.append({
                "id": "formula_cap",
                "severity": "critical",
                "label": "공식 상한/하한(cap) 유지 확인",
                "display_value": cap_evidence,
                "auto_source": "code_branch_cap",
                "checked": False, "checked_by": None, "checked_at": None,
            })
    elif formula and not is_date_based:
        formula_str_for_cap = (json.dumps(formula, ensure_ascii=False)
                               if isinstance(formula, dict) else str(formula))
        if re.search(r'\bmin\s*\(|\bmax\s*\(', formula_str_for_cap):
            items.append({
                "id": "formula_cap",
                "severity": "critical",
                "label": "공식 상한/하한(cap) 유지 확인",
                "display_value": (f"cap 함수 감지 — 아래 공식에서 min()/max() 적용 범위를 직접 확인:\n"
                                  f"{formula_str_for_cap[:400]}"),
                "auto_source": "formula_cap_detected",
                "checked": False, "checked_by": None, "checked_at": None,
            })

    # ─ rate_constant: formula에 소수점 상수 포함 시 (STEP 28-208: 코드 기반
    # 계산기는 formula 정규식 추출 대신 코드 내 상수를 근거로 생성한다)
    if is_code_based and not is_date_based:
        items.append({
            "id": "rate_constant",
            "severity": "critical",
            "label": "적용 세율/계수 확인",
            "display_value": CODE_BASED_EVIDENCE[slug]["rate_constant"],
            "auto_source": "code_branch_constants",
            "checked": False, "checked_by": None, "checked_at": None,
        })
    elif formula and not is_date_based:
        constants = re.findall(r'\b\d+\.\d+\b', str(formula))
        if constants:
            items.append({
                "id": "rate_constant",
                "severity": "critical",
                "label": "적용 세율/계수 확인",
                "display_value": f"공식 내 상수: {constants}",
                "auto_source": "formula_constants",
                "checked": False, "checked_by": None, "checked_at": None,
            })

    # ─ base_year: 🔴 카테고리 계산기에만. IRP-09: compute_rules.tax_year가 있으면
    # 실제 기준연도를 표시값에 반영한다(legal_master의 last_verified는 큐레이터
    # 확인일일 뿐 세율 적용 연도가 아니므로 여기서 참조하지 않는다). 값이 있어도
    # "checked"는 여전히 False — tax_year 존재는 메타데이터 존재를 의미할 뿐
    # 운영자의 법령 검토 승인을 대신하지 않는다.
    if legal_severity == "critical":
        tax_year = compute_rules.get("tax_year")
        if tax_year:
            disp_year = f"{tax_year}년 기준 — compute_rules.tax_year 선언됨(운영자 검토 필요)"
            src_year = "tax_year_field"
        else:
            disp_year = "직접 확인 필요 — 법령 시행일 또는 세율 적용 연도"
            src_year = "critical_category"
        items.append({
            "id": "base_year",
            "severity": "critical",
            "label": "기준 연도/시행일 확인",
            "display_value": disp_year,
            "auto_source": src_year,
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ default_values: input_schema에 default 있는 경우
    defaults = {k: v.get("default") for k, v in input_schema.items()
                if isinstance(v, dict) and "default" in v}
    if defaults:
        items.append({
            "id": "default_values",
            "severity": "critical",
            "label": "기본 입력값 타당성",
            "display_value": str(defaults),
            "auto_source": "input_defaults",
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ input_validation_review: compute_rules 유무와 무관하게 항상 생성.
    # edge_cases(아래)는 compute_rules가 "있을 때" 그 구체적 내용을 검토하는 항목이고,
    # 이 항목은 compute_rules가 "있든 없든" 검증 정책 자체를 사람이 확인했는지를 검토한다
    # (STEP 28-128 설계 확정: 부재 자체를 오류로 취급하지 않되, 사람이 확인하기 전까지
    # READY 승격을 차단하기 위함 — promote_to_ready()는 이 항목이 checklist에 존재하기만
    # 하면 기존 critical 미체크 차단 로직을 그대로 적용하므로 별도 분기 추가 불필요).
    if compute_rules:
        _ivr_display = f"설정된 검증 규칙: {str(compute_rules)[:300]}"
    else:
        _ivr_display = "⚠️ 설정된 입력값 검증 규칙 없음 — 의도적인지 확인 필요"
    items.append({
        "id": "input_validation_review",
        "severity": "critical",
        "label": "입력값 검증 정책 확인",
        "display_value": _ivr_display,
        "auto_source": "compute_rules_presence",
        "checked": False, "checked_by": None, "checked_at": None,
    })

    # ─ edge_cases: compute_rules 있는 경우
    if compute_rules:
        items.append({
            "id": "edge_cases",
            "severity": "critical",
            "label": "예외조건 처리 확인",
            "display_value": str(compute_rules)[:300],
            "auto_source": "compute_rules",
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ schema_match: Contract vs AI 생성 결과 필드명 비교 결과가 있을 때 (🔴 필수)
    # generate_app_with_contract()가 embed한 _schema_drift가 있는 경우에만 발생.
    # 드리프트 있으면 변경 내역을 표시, 없으면 일치 확인 메시지 표시.
    schema_drift = app.get("_schema_drift")
    if schema_drift is not None:
        if schema_drift.get("drifted"):
            change_lines = []
            for c in schema_drift.get("changes", []):
                t = c.get("type", "")
                if "input_missing" in t:
                    change_lines.append(f"입력 필드 누락: Contract의 {c['contract']!r}")
                elif "input_extra" in t:
                    change_lines.append(f"입력 필드 추가: AI의 {c['ai']!r} (Contract에 없음)")
                elif "output_missing" in t:
                    change_lines.append(f"출력 필드 누락: Contract의 {c['contract']!r}")
                elif "output_extra" in t:
                    change_lines.append(f"출력 필드 추가: AI의 {c['ai']!r} (Contract에 없음)")
            disp_drift = "⚠️ AI가 필드명을 변경했습니다:\n" + "\n".join(change_lines)
        else:
            disp_drift = "✅ Schema 일치 — Contract 확정 필드명과 동일"
        items.append({
            "id": "schema_match",
            "severity": "critical",
            "label": "Schema 일치 확인 (Contract vs AI 생성)",
            "display_value": disp_drift,
            "auto_source": "contract_schema_drift",
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ 🟡 권장: 화면 안내문 확인 (description / seo_desc)
    desc_text = (app.get("description") or app.get("desc") or app.get("seo_desc") or "")
    if desc_text:
        items.append({
            "id": "description_text",
            "severity": "advisory",
            "label": "화면 안내문 확인",
            "display_value": str(desc_text)[:200],
            "auto_source": "description_field",
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ 🟡 권장: SEO
    if app.get("seo_title"):
        items.append({
            "id": "seo_title",
            "severity": "advisory",
            "label": "SEO 제목 검토",
            "display_value": str(app["seo_title"]),
            "auto_source": "seo_title_field",
            "checked": False, "checked_by": None, "checked_at": None,
        })

    # ─ 🟡 권장: FAQ
    faq_raw = app.get("faq") or app.get("faq_template")
    if faq_raw:
        faq = _pj(faq_raw, []) if isinstance(faq_raw, str) else faq_raw
        if isinstance(faq, list) and faq:
            faq_qs = [f.get("q", f.get("question", "")) for f in faq[:3]]
            items.append({
                "id": "faq_content",
                "severity": "advisory",
                "label": "FAQ 내용 검토",
                "display_value": str(faq_qs),
                "auto_source": "faq_field",
                "checked": False, "checked_by": None, "checked_at": None,
            })

    return items


def detect_tier2b_keywords(name: str, desc: str = "") -> bool:
    """이름/설명에서 Tier2-B 키워드 감지."""
    text = ((name or "") + " " + (desc or "")).lower()
    return any(kw in text for kw in TIER2B_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# 2. Tier AI 추천
# ─────────────────────────────────────────────────────────────

def suggest_tier(cfg: dict, name: str, desc: str = "") -> dict:
    """
    AI(GPT-4o)가 계산기 이름/설명 기반으로 Tier 추천.
    반환: {"tier": str, "reason": str, "confidence": str}
    """
    from modules.app_factory import _chat
    from modules.json_utils import parse_json_lenient

    sys_prompt = (
        "너는 한국 웹 계산기 분류 전문가다.\n\n"
        "Tier2-A: 단순 산술/비율 공식으로 표현 가능. 날짜 계산 없음. 구간 요율 없음.\n"
        "         예: 원천징수(총액×3.3%), 전세 기회비용(금액×이율÷12)\n"
        "Tier2-B: 핵심 로직이 날짜 덧셈/기간 계산. 단순 산술로 표현 불가.\n"
        "         예: 복무 만료일, 육아휴직 종료일, D-Day 계산기\n"
        "Tier1:   날짜 계산, 구간별 누진 요율, 다단계 법령 분기 등 복잡한 로직.\n"
        "         예: 퇴직금(30일평균임금×근속연수), 실업급여(수급자격+구간급여)\n\n"
        'JSON만 반환: {"tier": "Tier2-A", "reason": "이유 1~2문장", "confidence": "high|medium|low"}'
    )
    user_prompt = f"계산기명: {name}\n설명: {desc or '(없음)'}"

    try:
        text, _, _ = _chat(cfg, "orchestrator", sys_prompt, user_prompt, 300)
        result = parse_json_lenient(text)
        tier = result.get("tier", "Tier2-A")
        if tier not in ("Tier2-A", "Tier2-B", "Tier1"):
            tier = "Tier2-A"
        return {
            "tier": tier,
            "reason": result.get("reason", ""),
            "confidence": result.get("confidence", "medium"),
        }
    except Exception as e:
        return {"tier": "Tier2-A", "reason": f"추천 실패: {e}", "confidence": "low"}


def detect_legal_signal_keywords(name: str, desc: str = "") -> bool:
    """이름/설명에서 법령/규정성 신호 키워드 감지 (rule-based, Mode 추천 후처리용)."""
    text = ((name or "") + " " + (desc or "")).lower()
    return any(kw.lower() in text for kw in LEGAL_SIGNAL_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# 2b. Mode(A/B) AI 추천 (STEP 25-2)
# ─────────────────────────────────────────────────────────────

def suggest_mode(cfg: dict, name: str, category: str = "", desc: str = "") -> dict:
    """
    AI(GPT-4o)가 계산기 이름/카테고리/설명 기반으로 Mode(A/B)를 추천한다.

    Mode A(자유 생성)는 legal_refs 입력 경로와 check_hold_rules() 사전 게이트가 없고,
    Mode B(Contract 기반 생성)만 이를 제공한다(STEP 25-1 진단). 따라서 B→A 오판이
    A→B 오판보다 구조적으로 더 위험하며, 이 함수는 그 비대칭을 반영해 법령/규정
    의존 가능성이 조금이라도 있으면 Mode B 쪽으로 보수적으로 판단한다.

    이 함수는 추천값만 반환한다. generate_app()/generate_app_with_contract()/
    save_app() 호출, legal_refs 자동 선택/확정, test_cases 자동 생성에는
    일체 관여하지 않는다 — 그 판단과 실행은 항상 사용자가 직접 수행한다.

    반환: {"mode": "A"|"B", "reason": str, "confidence": "high"|"medium"|"low"}
    """
    from modules.app_factory import _chat
    from modules.json_utils import parse_json_lenient

    sys_prompt = (
        "너는 한국 웹 계산기의 생성 방식(Mode) 분류 전문가다.\n\n"
        "Mode A(자유 생성): 단순 산술, 입력→출력 직접 계산, 법령/행정 규정 의존 없음, "
        "요율/상한/하한 등 외부 값 의존 없음, 복잡한 예외/특례 없음.\n"
        "         예: BMI, 단순 비율 계산기\n"
        "Mode B(Contract 확정 생성): 법령/행정 규정 의존 가능성, 법정 요율, "
        "연도별 변경 가능 값, 상한/하한, 복잡한 조건/예외, 날짜 기반 복잡 계산, "
        "외부 기준표/규정 의존.\n"
        "         예: 퇴직금, 실업급여, 전역일 계산기\n\n"
        "법령 또는 규정 의존 가능성이 조금이라도 있으면 Mode A보다 Mode B를 "
        "보수적으로 추천한다.\n\n"
        'JSON만 반환: {"mode": "A", "reason": "이유 1~2문장", "confidence": "high|medium|low"}'
    )
    user_prompt = f"계산기명: {name}\n카테고리: {category or '(없음)'}\n설명: {desc or '(없음)'}"

    try:
        text, _, _ = _chat(cfg, "orchestrator", sys_prompt, user_prompt, 300)
        result = parse_json_lenient(text)
        # STEP 25-2: 비대칭 위험 보정 — 판단 불가/미제공 시 안전한 쪽(B)으로 기본값
        mode = result.get("mode", "B")
        if mode not in ("A", "B"):
            mode = "B"
        confidence = result.get("confidence", "medium")
        reason = result.get("reason", "")
    except Exception as e:
        return {"mode": "B", "reason": f"추천 실패(안전 기본값 B로 보수적 대체): {e}", "confidence": "low"}

    # STEP 25-2: 법령/규정성 키워드가 감지되는데 AI가 A/HIGH를 반환하면 MEDIUM으로 강등
    if mode == "A" and confidence == "high" and detect_legal_signal_keywords(name, desc):
        confidence = "medium"
        reason = (reason + " " if reason else "") + \
            "(법령/규정성 키워드 감지로 신뢰도를 MEDIUM으로 보수적 조정함)"

    return {"mode": mode, "reason": reason, "confidence": confidence}


# ─────────────────────────────────────────────────────────────
# 3. slug 중복 차단
# ─────────────────────────────────────────────────────────────

def check_slug_conflict(slug: str, cfg: dict) -> tuple[str, bool, str]:
    """
    slug와 기존 Registry v3 + DB를 대조.
    반환: (slug, is_conflict, message)
    """
    from modules.registry_loader import load_registry_v3
    try:
        v3 = load_registry_v3(force=True)
        v3_slugs = set(v3.keys())
    except Exception:
        v3_slugs = set()

    try:
        from adapters.db.factory import get_db_adapter
        from repositories.calculator_repository import CalculatorRepository
        db_calcs = CalculatorRepository(get_db_adapter(cfg)).get_all()
        db_slugs = {c.get("slug", "") for c in db_calcs if c.get("slug")}
    except Exception:
        db_slugs = set()

    all_slugs = v3_slugs | db_slugs

    if slug and slug in all_slugs:
        return slug, True, f"'{slug}' 슬러그가 이미 존재합니다."
    return slug, False, ""


# ─────────────────────────────────────────────────────────────
# 4. Build 사전 QA 6단계 (D-4 반영)
# ─────────────────────────────────────────────────────────────

def _js_smoke_test(js_content: str, ins: dict, date_fields: list) -> tuple:
    """실제 생성된 script.js 전체 번들을 Node.js에서 그대로 실행해 window.computeResult()가
    예외 없이 반환하는지 확인. 반환값의 정확성(기대값 비교)은 검증하지 않음 —
    실행 가능 여부만 보는 스모크 테스트.
    반환: (passed: bool|None, detail: str). passed=None이면 skip(환경상 실행 불가).

    STEP 28-160/161: 이전에는 computeResult 함수 블록만 중괄호 매칭으로 잘라내
    독립 실행했다(공통 컴포넌트는 document/window DOM에 의존하므로 전체를 그대로
    실행하면 Node.js에 document가 없어 항상 실패한다는 이유). 하지만 STEP 28-140에서
    BMI의 computeResult가 components.js 공유 helper pyRound()를 호출하게 되면서
    이 전제가 깨졌다 — pyRound 정의(및 window.pyRound export)가 통째로 잘려나가
    "ReferenceError: pyRound is not defined"가 발생했다. computeResult만 잘라내는
    대신, tests/test_nan_infinity_guard.py::_run_compute_result()에서 이미 검증된
    DOM/window 스텁으로 전체 번들(js_content)을 그대로 실행한다 — pyRound를 이
    함수 안에 별도로 재구현하거나 stub으로 대체하지 않고, 실제 components.js가
    그대로 로드되어 진짜 구현이 실행되게 한다."""
    import subprocess
    import tempfile
    import os as _os

    dom_stub = (
        "globalThis.window = globalThis;\n"
        "globalThis.document = {\n"
        "  getElementById: function () { return null; },\n"
        "  querySelector: function () { return null; },\n"
        "  querySelectorAll: function () { return []; },\n"
        "  createElement: function () { return { classList: { add: function () {}, remove: function () {} }, style: {} }; },\n"
        "  addEventListener: function () {},\n"
        "  readyState: 'complete',\n"
        "};\n"
        "globalThis.addEventListener = function () {};\n"
        "globalThis.requestAnimationFrame = function () {};\n"
        "globalThis.localStorage = { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} };\n"
        "globalThis.navigator = { userAgent: 'node-test' };\n"
        "globalThis.location = { pathname: '/test', href: 'http://localhost/test' };\n"
    )

    dummy = {}
    date_pool = ["2015-01-01", "2024-01-01"]
    _di = 0
    for k, v in ins.items():
        # input_schema 값은 {"type":"date"} 딕셔너리가 아니라 "date"/"number" 같은
        # 단순 문자열인 경우가 실제로 더 흔함(app_generator._form_fields_v2와 동일 관례) — 둘 다 처리.
        is_date = (k in (date_fields or ())) or ("date" in str(v).lower())
        if is_date:
            dummy[k] = date_pool[min(_di, len(date_pool) - 1)]
            _di += 1
        elif isinstance(v, dict):
            raw = v.get("default", 1000)
            try:
                dummy[k] = float(raw) if raw not in (None, "") else 1000
            except (TypeError, ValueError):
                dummy[k] = 1000
        else:
            dummy[k] = 1000

    harness = (
        dom_stub + "\n" + js_content + "\n"
        + f"var out = window.computeResult({json.dumps(dummy, ensure_ascii=False)});\n"
        + "process.stdout.write(JSON.stringify(out));\n"
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(harness)
        # encoding 명시 필수: 생성된 JS에 한글 notice 문자열이 포함될 수 있어
        # Windows 기본 로케일(cp949)로 stdout/stderr를 디코딩하면 깨짐/예외 발생.
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10)
        if r.returncode != 0:
            return False, f"JS 실행 오류(더미 입력 {dummy}): {r.stderr.strip()[:200]}"
        try:
            parsed = json.loads(r.stdout.strip() or "null")
        except Exception:
            return False, f"JS 반환값 파싱 실패: {r.stdout.strip()[:200]}"
        return True, f"더미 입력 {dummy} → computeResult() 정상 실행, 반환: {str(parsed)[:150]}"
    except FileNotFoundError:
        return None, "Node.js 미설치 — 스모크 테스트 건너뜀(환경 제약)"
    except subprocess.TimeoutExpired:
        return False, "JS 실행 타임아웃(10초 초과) — 무한루프 가능성"
    finally:
        try:
            _os.unlink(path)
        except Exception:
            pass


def _extract_rate_constants(js_or_html: str) -> dict:
    """JS/HTML 안의 대문자 상수 선언(예: NP_RATE=0.045, DAILY_MAX = 66000)을 추출.
    요율/기준값 변경 감지(Step 8)용 — 완전한 파서가 아닌 휴리스틱."""
    consts = {}
    for m in re.finditer(r'\b([A-Z][A-Z0-9_]{2,})\s*=\s*([0-9]+(?:\.[0-9]+)?)', js_or_html or ""):
        consts[m.group(1)] = m.group(2)
    return consts


def pre_build_qa(calc: dict, cfg: dict, prev_files: dict = None) -> list[dict]:
    """
    Build 전 사전 검사(기존 6단계 + Phase E 확장 2단계).
    calc: DB 계산기 record (slug, formula, input_schema, output_schema 등)
    prev_files: 직전 확정 스냅샷(_site/{slug}/에서 읽은 {index.html,style.css,script.js}).
                없으면(None) Step 8은 비교 대상 없음으로 skip.
    반환: [{"step": int, "label": str, "passed": bool, "skipped": bool, "detail": str}]
    """
    from modules.app_generator import generate_calculator, _validation_mode
    from modules.registry_loader import load_registry_v3

    results = []

    # DB record 자체의 compute_type/date_fields는 비어있는 경우가 많아(확인됨) 불안정.
    # _validation_mode()는 app_generator.py가 실제 생성 시 쓰는 동일한 판별 기준(registry
    # validation_mode)이라 더 신뢰 가능 — 기존 두 조건에 OR로 추가(기존 감지 경로는 유지).
    is_date_based = (str(calc.get("compute_type", "")) == "date_based" or
                     bool(calc.get("date_fields")) or
                     _validation_mode(calc) == "skip")
    _slug = str(calc.get("slug", ""))
    is_tier2b = (load_registry_v3().get(_slug) or {}).get("tier_subtype") == "B"

    ins = _pj(calc.get("input_schema"), {})
    outs = _pj(calc.get("output_schema"), {})
    formula = _pj(calc.get("formula"), "")

    # ── Step 1: input_schema 존재 ──────────────────────────────
    passed1 = bool(ins)
    results.append({
        "step": 1, "label": "입력 스키마 존재",
        "passed": passed1, "skipped": False,
        "detail": (f"입력 항목 {len(ins)}개: {list(ins.keys())}"
                   if passed1 else "input_schema 없음 — generate_app() 재실행 필요"),
    })

    # ── Step 2: output_schema 존재 ────────────────────────────
    passed2 = bool(outs)
    results.append({
        "step": 2, "label": "출력 스키마 존재",
        "passed": passed2, "skipped": False,
        "detail": (f"출력 항목 {len(outs)}개: {list(outs.keys())}"
                   if passed2 else "output_schema 없음"),
    })

    if not (passed1 and passed2):
        for s, l in [(3, "HTML 출력 요소 1:1 대응"), (4, "JS 다중 출력 처리"),
                     (5, "복수 출력 완전성"), (6, "기본값 계산 실행"),
                     (7, "JS 실행 스모크 테스트"), (8, "요율/기준값 변경 감지"),
                     (9, "HTML 입력 필드 ↔ JS 입력 키 일치"), (10, "FAQ/본문 금칙 문구 검사")]:
            results.append({"step": s, "label": l, "passed": False, "skipped": True,
                            "detail": "Step 1/2 실패로 건너뜀"})
        return results

    # generate_calculator로 파일 생성 (Step 3~8에서 사용)
    try:
        files = generate_calculator(calc, cfg)
        html = files.get("index.html", "")
        js = files.get("script.js", "")
        gen_ok = True
    except Exception as e:
        gen_ok = False
        gen_err = str(e)
        html, js = "", ""

    if not gen_ok:
        for s, l in [(3, "HTML 출력 요소 1:1 대응"), (4, "JS 다중 출력 처리"),
                     (5, "복수 출력 완전성"), (6, "기본값 계산 실행"),
                     (7, "JS 실행 스모크 테스트"), (8, "요율/기준값 변경 감지"),
                     (9, "HTML 입력 필드 ↔ JS 입력 키 일치"), (10, "FAQ/본문 금칙 문구 검사")]:
            results.append({"step": s, "label": l, "passed": False, "skipped": False,
                            "detail": f"generate_calculator() 실패: {gen_err}"})
        return results

    # ── Tier2-B(예: 군인 전역일)는 표준 폼/수식 전제인 Step 3~6이 애초에 맞지 않음.
    # 잘못된 FAIL 표시를 막기 위해 여기서 skip 처리하고 Step 7/8로 넘어간다.
    if is_tier2b:
        for s, l in [(3, "HTML 출력 요소 1:1 대응"), (4, "JS 다중 출력 처리"),
                     (5, "복수 출력 완전성"), (6, "기본값 계산 실행")]:
            results.append({"step": s, "label": l, "passed": True, "skipped": True,
                            "detail": "Tier2-B — 표준 폼/수식 기반 검사 대상 아님(DB 템플릿 직접 사용)"})
        _step7_tier2b = (True, "Tier2-B — 별도 script.js 없음(자체완결형 HTML), 스모크 테스트 대상 아님")
        results.append({"step": 7, "label": "JS 실행 스모크 테스트",
                        "passed": _step7_tier2b[0], "skipped": True, "detail": _step7_tier2b[1]})
        prev_content = (prev_files or {}).get("index.html") or ""
        if not prev_content:
            results.append({"step": 8, "label": "요율/기준값 변경 감지",
                            "passed": True, "skipped": True,
                            "detail": "직전 스냅샷 없음(최초 생성) — 비교 대상 없음"})
        else:
            _old_c = _extract_rate_constants(prev_content)
            _new_c = _extract_rate_constants(html)
            _changed = {k: (_old_c.get(k), _new_c.get(k)) for k in set(_old_c) | set(_new_c)
                       if _old_c.get(k) != _new_c.get(k)}
            if _changed:
                _d8 = "; ".join(f"{k}: {o} → {n}" for k, (o, n) in sorted(_changed.items()))
                results.append({"step": 8, "label": "요율/기준값 변경 감지",
                                "passed": False, "skipped": False,
                                "detail": f"이전 스냅샷 대비 상수 변경 감지(의도한 변경인지 확인 필요) — {_d8}"})
            else:
                results.append({"step": 8, "label": "요율/기준값 변경 감지",
                                "passed": True, "skipped": False,
                                "detail": "이전 스냅샷과 요율/기준값 동일"})
        # Tier2-B는 별도 script.js가 없는 자체완결형 HTML — Step 9(HTML↔JS)는 대상 아님.
        results.append({"step": 9, "label": "HTML 입력 필드 ↔ JS 입력 키 일치",
                        "passed": True, "skipped": True,
                        "detail": "Tier2-B — 별도 script.js 없음(자체완결형 HTML), 검사 대상 아님"})
        # Step 10(FAQ 금칙 문구)은 HTML 텍스트 검사라 Tier2-B에도 그대로 적용 가능.
        _passed10, _detail10 = _faq_forbidden_phrase_check(calc, html)
        results.append({"step": 10, "label": "FAQ/본문 금칙 문구 검사",
                        "passed": _passed10[0], "skipped": _passed10[1], "detail": _detail10})
        return results

    # ── Step 3: output_schema ↔ HTML id="out_*" 1:1 대응 ─────
    if is_date_based:
        results.append({
            "step": 3, "label": "HTML 출력 요소 1:1 대응",
            "passed": True, "skipped": True,
            "detail": "날짜형 계산기 — HTML ID 직접 확인 필요 (D-4: 자동 검사 건너뜀)",
        })
    else:
        html_out_ids = set(re.findall(r'id="out_([^"]+)"', html))
        schema_keys = set(outs.keys())
        missing = schema_keys - html_out_ids
        extra = html_out_ids - schema_keys
        passed3 = not missing
        detail3 = (f"✅ {len(schema_keys)}개 출력 모두 HTML에 존재" if passed3 else
                   f"HTML에 없는 출력 ID: {missing}" +
                   (f" | HTML에만 있는 ID: {extra}" if extra else ""))
        results.append({"step": 3, "label": "HTML 출력 요소 1:1 대응",
                        "passed": passed3, "skipped": False, "detail": detail3})

    # ── Step 4: formula dict keys가 JS에서 처리되는지 ─────────
    if is_date_based:
        results.append({"step": 4, "label": "JS 다중 출력 처리",
                        "passed": True, "skipped": True,
                        "detail": "날짜형 계산기 — 자동 검사 건너뜀 (D-4)"})
    elif isinstance(formula, dict):
        js_out_keys = set(re.findall(r'out\["([^"]+)"\]', js))
        js_out_keys -= {"notices"}
        js_out_keys = {k for k in js_out_keys if not k.startswith("_")}
        missing_js = set(formula.keys()) - js_out_keys
        passed4 = not missing_js
        detail4 = (f"✅ formula dict {len(formula)}개 키 모두 JS에서 처리" if passed4 else
                   f"JS에서 누락된 출력 키: {missing_js}")
        results.append({"step": 4, "label": "JS 다중 출력 처리",
                        "passed": passed4, "skipped": False, "detail": detail4})
    else:
        results.append({"step": 4, "label": "JS 다중 출력 처리",
                        "passed": True, "skipped": False,
                        "detail": "단일 출력 formula — 해당 없음 (PASS)"})

    # ── Step 5: 복수 출력 완전성 ──────────────────────────────
    if is_date_based:
        results.append({"step": 5, "label": "복수 출력 완전성",
                        "passed": True, "skipped": True,
                        "detail": "날짜형 계산기 — 자동 검사 건너뜀 (D-4)"})
    else:
        schema_keys = set(outs.keys())
        html_out_ids = set(re.findall(r'id="out_([^"]+)"', html))
        passed5 = not (len(schema_keys) > 1 and len(html_out_ids) < len(schema_keys))
        detail5 = (f"✅ 출력 {len(schema_keys)}개, HTML {len(html_out_ids)}개 ID" if passed5 else
                   f"출력 {len(schema_keys)}개 중 HTML ID {len(html_out_ids)}개만 존재")
        results.append({"step": 5, "label": "복수 출력 완전성",
                        "passed": passed5, "skipped": False, "detail": detail5})

    # ── Step 6: 기본 입력값으로 계산 실행 ────────────────────
    # is_date_based 계산기는 Step 3~5와 동일한 이유(실제 계산이 formula 필드가 아니라
    # _compute_js()의 하드코딩 JS로 수행됨)로 execute_formula() 재현이 애초에 맞지 않는
    # 검사임 — Step 3~5와 일관되게 skip 처리(기존 알려진 한계, Phase E에서 수정 범위 아님).
    # IRP-27: CODE_BASED_SLUGS(실제 계산이 DB formula가 아니라 _compute_js()의 slug
    # 조건부 분기로 수행되는 계산기)도 동일한 이유로 execute_formula() 재현이 맞지 않는
    # 검사임(IRP-26 진단: DB formula가 비어있으면 falsy로 오탐 FAIL, 옛 stale formula가
    # 남아있으면 틀린 값으로도 우연히 PASS — 어느 쪽도 실제 계산 정확성과 무관).
    # 실제 계산 정확성은 slug 전용 pytest(예: tests/test_step28_193_car_tax_compute.py,
    # tests/test_irp_tax_credit_v2_compute.py)가 별도로 검증한다.
    if is_date_based or _slug in CODE_BASED_SLUGS:
        _reason = ("날짜형 계산기 — 실제 계산은 하드코딩 JS(_compute_js)로 수행되어 "
                   "formula 재현 검사가 맞지 않음(기존 알려진 한계, Step 3~5와 동일 사유로 skip)"
                   if is_date_based else
                   "CODE_BASED_SLUGS 계산기 — 실제 계산은 DB formula가 아니라 "
                   "_compute_js()의 slug 조건부 분기로 수행되어 formula 재현 검사가 맞지 않음"
                   "(IRP-26/27, 계산 정확성은 slug 전용 pytest가 별도 검증)")
        results.append({"step": 6, "label": "기본값 계산 실행",
                        "passed": True, "skipped": True,
                        "detail": _reason})
    else:
        try:
            from modules.formula_engine import execute_formula
            dummy = {}
            for k, v in ins.items():
                if isinstance(v, dict):
                    raw = v.get("default", 1.0)
                    try:
                        dummy[k] = float(raw) if raw not in (None, "") else 1.0
                    except (TypeError, ValueError):
                        dummy[k] = 1.0
                else:
                    dummy[k] = 1.0
            result6 = execute_formula(formula, dummy, outs if isinstance(outs, dict) else None)
            passed6 = isinstance(result6, dict) and result6
            detail6 = f"✅ 계산 성공: {str(result6)[:80]}" if passed6 else f"계산 결과 이상: {result6}"
        except Exception as e:
            passed6 = False
            detail6 = f"계산 오류: {e}"
        results.append({"step": 6, "label": "기본값 계산 실행",
                        "passed": passed6, "skipped": False, "detail": detail6})

    # ── Step 7: 실제 script.js 실행 스모크 테스트(Node.js) ───────
    if not (js or "").strip():
        results.append({"step": 7, "label": "JS 실행 스모크 테스트",
                        "passed": True, "skipped": True,
                        "detail": "script.js 없음 — 검사 대상 아님"})
    else:
        _p7, _d7 = _js_smoke_test(js, ins, calc.get("date_fields") or [])
        results.append({"step": 7, "label": "JS 실행 스모크 테스트",
                        "passed": True if _p7 is None else _p7,
                        "skipped": _p7 is None, "detail": _d7})

    # ── Step 8: 직전 스냅샷 대비 요율/기준값 변경 감지 ────────────
    prev_js = (prev_files or {}).get("script.js") or (prev_files or {}).get("index.html") or ""
    if not prev_js:
        results.append({"step": 8, "label": "요율/기준값 변경 감지",
                        "passed": True, "skipped": True,
                        "detail": "직전 스냅샷 없음(최초 생성) — 비교 대상 없음"})
    else:
        _old_c = _extract_rate_constants(prev_js)
        _new_c = _extract_rate_constants(js or html)
        _changed = {k: (_old_c.get(k), _new_c.get(k)) for k in set(_old_c) | set(_new_c)
                   if _old_c.get(k) != _new_c.get(k)}
        if _changed:
            _d8 = "; ".join(f"{k}: {o} → {n}" for k, (o, n) in sorted(_changed.items()))
            results.append({"step": 8, "label": "요율/기준값 변경 감지",
                            "passed": False, "skipped": False,
                            "detail": f"이전 스냅샷 대비 상수 변경 감지(의도한 변경인지 확인 필요) — {_d8}"})
        else:
            results.append({"step": 8, "label": "요율/기준값 변경 감지",
                            "passed": True, "skipped": False,
                            "detail": "이전 스냅샷과 요율/기준값 동일"})

    # ── Step 9(STEP 15-H): 생성된 HTML 입력 필드 ↔ JS가 읽는 입력 키 일치 확인 ──
    # validate_formula()(formula ↔ input_schema)와는 별개 검사 — 이건 실제
    # 렌더링된 <input id="in_*"> 필드와 script.js의 inputs["..."] 참조를 직접 비교한다.
    # STEP 15-E에서 발견된 사고(HTML=years_of_service, JS=months_of_service)를
    # 발생 시점(생성 직후)에 자동으로 잡기 위한 검사.
    passed9, detail9 = _html_js_input_consistency(html, js)
    results.append({"step": 9, "label": "HTML 입력 필드 ↔ JS 입력 키 일치",
                    "passed": passed9, "skipped": False, "detail": detail9})

    # ── Step 10(STEP 15-H): FAQ/본문에 SSOT forbidden_phrases 재등장 여부 ──
    passed10, detail10 = _faq_forbidden_phrase_check(calc, html)
    results.append({"step": 10, "label": "FAQ/본문 금칙 문구 검사",
                    "passed": passed10[0], "skipped": passed10[1], "detail": detail10})

    return results


def _html_js_input_consistency(html: str, js: str) -> tuple:
    """생성된 HTML의 입력 필드(id="in_*")와 실제 script.js가 읽는 inputs["..."] 키를
    비교한다. 출력 필드(id="out_*")는 별도 접두사라 여기 섞이지 않는다.
    반환: (passed: bool, detail: str)."""
    html_keys = set(re.findall(r'id="in_([^"]+)"', html or ""))
    js_keys = set(re.findall(r'inputs\["([^"]+)"\]', js or ""))
    html_only = html_keys - js_keys
    js_only = js_keys - html_keys
    passed = not html_only and not js_only
    if passed:
        detail = f"✅ 입력 필드 일치({len(html_keys)}개): {sorted(html_keys)}"
    else:
        parts = []
        if html_only:
            parts.append(f"HTML에만 있는 필드(JS가 읽지 않음): {sorted(html_only)}")
        if js_only:
            parts.append(f"JS만 참조하는 필드(HTML에 없음): {sorted(js_only)}")
        parts.append(f"HTML={sorted(html_keys)} / JS={sorted(js_keys)}")
        detail = " | ".join(parts)
    return passed, detail


def _faq_forbidden_phrase_check(calc: dict, html: str) -> tuple:
    """SSOT(legal_basis.master.yaml의 계산기별 forbidden_phrases +
    legal_master/*.yaml의 legal_refs 연결 엔티티별 forbidden_phrases)에 등록된
    금칙 문구가 생성된 HTML(FAQ/본문 포함)에 등장하는지 검사.
    반환: ((passed, skipped), detail)."""
    from modules.registry_loader import load_registry, load_registry_v3, load_legal_master

    slug = str(calc.get("slug", ""))
    forbidden = set()

    # (a) 구 registry(legal_basis.master.yaml) — 계산기 slug에 직접 forbidden_phrases
    old_entry = load_registry().get(slug) or {}
    forbidden.update(old_entry.get("forbidden_phrases") or [])

    # (b) v3 registry의 legal_refs → legal_master 엔티티별 forbidden_phrases
    v3_entry = load_registry_v3().get(slug) or {}
    legal_refs = v3_entry.get("legal_refs") or []
    if legal_refs:
        lm = load_legal_master()
        for ref in legal_refs:
            forbidden.update((lm.get(ref) or {}).get("forbidden_phrases") or [])

    if not forbidden:
        return (True, True), "이 계산기에 등록된 forbidden_phrases 없음(SSOT 미연결 또는 금칙 문구 미등록) — 검사 대상 아님"

    hit = [p for p in forbidden if p and p in (html or "")]
    if hit:
        return (False, False), f"금칙 문구 발견: {hit}"
    return (True, False), f"✅ 등록된 금칙 문구 {len(forbidden)}개 전부 미발견"


# ══════════════════════════════════════════════════════════════════
# STEP 17-C — 콘텐츠/문맥/UX 품질 QA (기존 pre_build_qa() 1~10단계와
# 완전히 분리된 별도 계층). 기존 함수는 한 줄도 수정하지 않는다.
#
# 배경: STEP 16-Y에서 발견된 두 문제(① 노무용 공용 안내문구가 부동산
# 계산기에 그대로 노출, ② 숫자 코드(1/2) 입력의 의미가 화면에 없음)는
# 기존 QA 1~10단계(전부 "이름/개수가 시스템 간에 일치하는가"만 검사하는
# 구조 검증)로는 원천적으로 탐지 불가능했다(STEP 17-B 진단). 이 섹션은
# "사람이 읽었을 때 말이 되는가"를 검사하는 4개의 독립 함수 + 이를 묶는
# content_quality_qa() 진입점을 추가한다.
# ══════════════════════════════════════════════════════════════════

# 카테고리별 전형어(소규모 큐레이션). 오탐 방지를 위해 해당 분야에서만
# 쓰이는 명확한 용어만 포함한다(범용 단어 제외).
_DOMAIN_TERMS: dict = {
    "노무/급여": ["근로계약", "퇴직금", "임금체불", "통상임금", "평균임금"],
    "고용/보험": ["구직급여", "실업급여"],
    "노무/급여/보험": ["산재보험", "육아휴직급여"],
    "세금/정부혜택": ["원천징수", "종합소득세", "과세표준"],
    "부동산/임대": ["중개보수", "전월세전환율"],
    "병역/공무": ["전역일", "군복무"],
}


def _category_word_leakage_check(calc: dict, html: str) -> tuple:
    """calc의 category와 무관한 다른 분야의 전형어가 본문에 등장하는지 검사.
    카테고리 문자열에 공통 토큰이 하나도 없는 완전 무관 분야 용어는 강한
    오염 신호(FAIL), 토큰이 일부 겹치는 인접 분야 용어는 WARNING(오탐
    방지 — 예: '고용/보험' 계산기에 '노무/급여/보험' 전형어가 섞이는
    경우는 실제 흔히 있는 정상적 인접 언급일 수 있음).
    반환: (passed: bool, hits: list[str], detail: str)."""
    category = str(calc.get("category", ""))
    cat_tokens = set(category.split("/")) if category else set()
    html = html or ""
    # 사이트 공통 CTA(related-card/result-cta/inline-cta/footer-cta 등, 위치가
    # 여러 곳에 흩어져 있고 계속 늘어날 수 있음 — STEP 17-C에서 severance-pay의
    # "실업급여도 계산해 보기" 문구로 실제 확인)를 하나씩 제거 목록에 추가하는
    # 방식은 취약하다고 판단해, 반대로 "이 계산기의 고유 콘텐츠 영역"만
    # 화이트리스트로 추출하는 방식으로 전환한다: 제목/설명(hero), 안내문구
    # (notice), 본문(article), FAQ만 대상으로 삼는다. 마커를 하나도 찾지 못하면
    # (템플릿 구조가 다른 경우) 안전하게 원본 html 그대로 검사한다(폴백).
    parts = []
    for pattern in (
        r"<header class=\"sm-hero\">.*?</header>",
        r"<div class=\"sm-notice\" role=\"note\">.*?</div>",
        r"<section class=\"sm-card sm-article\">.*?</section>",
        r"<section class=\"sm-card\" id=\"faq-card\">.*?</section>",
    ):
        m = re.search(pattern, html, flags=re.S)
        if m:
            parts.append(m.group(0))
    # 화이트리스트 마커를 하나도 못 찾은 경우(예: Tier2-B 날짜형 계산기처럼
    # 표준 템플릿과 구조가 다른 경우) 원본 html로 폴백하되, 최소한 사이트
    # 공통 <script>(JSON-LD 슬로건 등)는 제거해 명백한 오탐을 피한다.
    html = "\n".join(parts) if parts else re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    hits = []
    for cat, terms in _DOMAIN_TERMS.items():
        if cat == category:
            continue
        for term in terms:
            if term in html:
                hits.append((cat, term))
    if not hits:
        return True, [], "✅ 타 분야 전형어 미발견"
    strong = [h for h in hits if not (cat_tokens & set(h[0].split("/")))]
    hit_labels = [f"{c}:{t}" for c, t in hits]
    if strong:
        detail = "; ".join(f"'{t}'({c} 분야 전형어)" for c, t in strong)
        return False, hit_labels, f"❌ 문맥 오염 의심(계산기 분야={category or '미지정'}): {detail}"
    detail = "; ".join(f"'{t}'({c} 분야, 인접 분야이므로 확인만 권장)" for c, t in hits)
    return True, hit_labels, f"⚠️ {detail}"


def _input_semantic_select_check(calc: dict, contract: dict = None) -> tuple:
    """Contract의 test_cases에서 입력 필드가 실제로는 소수의 정수값만 갖는
    선택형(enum) 성격인지 휴리스틱으로 탐지한다. select: 접두사가 이미
    적용된 필드나 Contract 자체가 없는 경우(자동 생성 계산기 등)는 대상에서
    제외한다 — 오탐/자동 FAIL 방지를 위해 이 검사는 항상 WARNING만 반환하고
    passed=True를 유지한다(하드 게이트 아님).
    반환: (passed: True 고정, warn_fields: list[str], detail: str)."""
    if not contract or not contract.get("test_cases"):
        return True, [], "skipped: Contract test_cases 없음(자동 생성 계산기이거나 Contract 미보유)"
    ins = _pj(calc.get("input_schema"), {})
    values_by_field: dict = {}
    for tc in contract.get("test_cases", []):
        for k, v in (tc.get("input") or {}).items():
            values_by_field.setdefault(k, set()).add(v)
    candidates = []
    for k, values in values_by_field.items():
        spec = str(ins.get(k, ""))
        if spec.lower().startswith("select:") or "date" in spec.lower():
            continue
        is_small_int_set = (
            1 <= len(values) <= 4
            and all(isinstance(v, (int, float)) and float(v) == int(v) for v in values)
            and max(int(v) for v in values) <= 10
        )
        if is_small_int_set:
            candidates.append(k)
    if candidates:
        return True, candidates, f"⚠️ 선택형(enum) 가능성 있는 필드: {candidates} — select: 타입 사용 검토 권장"
    return True, [], "✅ enum 후보 없음(또는 이미 select 처리됨)"


def _internal_name_leakage_check(calc: dict, html: str) -> tuple:
    """input_schema/output_schema의 내부 필드 키가 id=/name= 속성이 아닌
    사용자에게 보이는 텍스트(라벨/FAQ/본문)에 그대로 노출되는지 검사.
    반환: (passed: bool, hits: list[str], detail: str)."""
    ins = _pj(calc.get("input_schema"), {})
    outs = _pj(calc.get("output_schema"), {})
    keys = set(ins.keys()) | set(outs.keys())
    if not keys:
        return True, [], "skipped: input/output schema 없음"
    visible = re.sub(r'\bid="[^"]*"', "", html or "")
    visible = re.sub(r'\bname="[^"]*"', "", visible)
    visible = re.sub(r"<script[^>]*>.*?</script>", "", visible, flags=re.S)
    hits = [k for k in keys if re.search(rf'(?<![\w"]){re.escape(k)}(?![\w"])', visible)]
    if hits:
        return False, hits, f"❌ 내부 필드명이 사용자 텍스트에 노출: {sorted(hits)}"
    return True, [], "✅ 내부 필드명 노출 없음"


def _legal_citation_cross_check(calc: dict, html: str) -> tuple:
    """HTML에 표시되는 'OO법 제OO조' 패턴을 추출해 legal_refs → legal_master의
    law+article과 실제로 일치하는지 검사. legal_refs가 없거나 정규식으로
    인용 여부를 확정하기 어려운 경우는 추측해서 FAIL시키지 않고 skip 처리한다.
    반환: (passed: bool, cited: list[str], detail: str)."""
    from modules.registry_loader import load_registry_v3, load_legal_master

    slug = str(calc.get("slug", ""))
    v3_entry = load_registry_v3().get(slug) or {}
    legal_refs = v3_entry.get("legal_refs") or []
    cited = sorted(set(re.findall(r"[가-힣]+법(?:\s*시행규칙)?\s*제\d+조", html or "")))

    if not legal_refs:
        if cited:
            return True, cited, f"⚠️ legal_refs 미등록 상태에서 법률 문구 발견(확인 권장): {cited}"
        return True, [], "skipped: legal_refs 없음, 법률 인용 문구도 없음"

    if not cited:
        return True, [], "skipped: 법률 인용 문구가 HTML에서 정규식으로 확정되지 않음"

    lm = load_legal_master()
    expected = set()
    for ref in legal_refs:
        entity = lm.get(ref) or {}
        law, article = entity.get("law", ""), entity.get("article", "")
        if law and article:
            expected.add(f"{law} {article}".replace(" ", ""))

    matched = any(any(exp in c.replace(" ", "") for exp in expected) for c in cited)
    if matched:
        return True, cited, f"✅ 인용 법률 일치: {cited}"
    return False, cited, f"❌ 인용 법률 불일치 — HTML 인용: {cited} / legal_refs 기대: {sorted(expected)}"


def content_quality_qa(calc: dict, html: str, js: str = "", contract: dict = None) -> list[dict]:
    """STEP 17-C: 콘텐츠/문맥/UX 품질 QA 진입점. pre_build_qa()의 반환 형식
    ([{"step","label","passed","skipped","detail"}])과 동일한 리스트를
    반환하되, 이 함수는 pre_build_qa() 내부에서 호출되지 않는 완전히
    독립적인 검사 계층이다(기존 10단계 미변경, 별도 호출 필요).
    """
    results = []

    p1, hits1, d1 = _category_word_leakage_check(calc, html)
    results.append({"step": "CQ1", "label": "카테고리-문맥 오염 검사(category word leakage)",
                    "passed": p1, "skipped": False, "detail": d1})

    p2, hits2, d2 = _input_semantic_select_check(calc, contract)
    results.append({"step": "CQ2", "label": "입력 필드 선택형(enum) 의미 검사",
                    "passed": p2, "skipped": d2.startswith("skipped"), "detail": d2})

    p3, hits3, d3 = _internal_name_leakage_check(calc, html)
    results.append({"step": "CQ3", "label": "내부 필드명 노출 검사",
                    "passed": p3, "skipped": d3.startswith("skipped"), "detail": d3})

    p4, hits4, d4 = _legal_citation_cross_check(calc, html)
    results.append({"step": "CQ4", "label": "법률 인용 교차검증",
                    "passed": p4, "skipped": d4.startswith("skipped"), "detail": d4})

    return results


# ══════════════════════════════════════════════════════════════════
# P0-1 — HTML/JS 생성 완결성 검증 가드
#
# 배경: React Dashboard 실제 수동 생성 E2E(STEP 참고)에서 app_factory.
# generate_app()의 "code"(HTML) 단계가 _chat(...,"code",...,max_tokens=4000)
# 토큰 한도 부근에서 응답이 잘려, 미종료 template literal이 남은 채로
# save_app()까지 그대로 저장된 사례가 실측 확인됐다(연금저축·IRP 세액공제
# 계산기, 자동차 취등록세 계산기 — 둘 다 </html> 없이 <script> 중간에서
# 끊김). 이 함수는 pre_build_qa()(계산기 관리 탭의 app_generator 템플릿
# HTML을 검사하는 기존 10단계 QA)와는 **다른 대상**을 검사한다 — 여기서
# 검사하는 것은 generate_app()이 만든 raw AI HTML(app_templates.
# html_template에 저장될 원본)이며, app_generator.generate_calculator()가
# formula/schema로부터 별도로 다시 만드는 배포용 HTML이 아니다. 두 HTML을
# 같은 것으로 취급하지 않는다(코드 추적으로 확인된 사실).
#
# pre_build_qa()의 6단계 이하 구조(step/label/passed/skipped/detail)를
# 그대로 재사용해 반환 형식을 통일한다 — 새 QA 계층을 만들지 않는다.
# ══════════════════════════════════════════════════════════════════

_NON_JS_SCRIPT_TYPES = (
    "application/ld+json", "application/json", "text/template",
    "text/x-handlebars-template", "text/html",
)


def _extract_script_blocks(html: str) -> tuple[list[str], bool]:
    """<script>...</script> 블록 중 실제 JavaScript인 것만 내용 추출(문법검증 대상).
    반환: (JS 블록 리스트, 태그_균형_여부).

    태그_균형(opens==closes)은 <script type="application/ld+json"> 같은 비-JS
    블록도 포함해 전체 <script> 태그 자체가 구조적으로 안 끊겼는지를 본다
    (실제 배포된 계산기(app_generator 산출물)는 JSON-LD 구조화 데이터 +
    외부 스크립트(src=)를 함께 쓰므로 이를 감안하지 않으면 오탐이 발생함 —
    실측: annual-leave-remaining의 <script type="application/ld+json"> 3개를
    JS 문법검사에 그대로 합치면 "Unexpected token ':'"로 거짓 FAIL됨).
    JS 문법 검증 대상(블록 리스트)에서는 다음을 제외한다:
      - type이 application/ld+json 등 비-JS인 블록(내용이 JSON이라 문법이 다름)
      - src=가 있는 외부 스크립트(인라인 내용이 없어 검사 대상 아님)."""
    open_tags = re.findall(r"<script(\s[^>]*)?>", html, flags=re.IGNORECASE)
    closes = len(re.findall(r"</script\s*>", html, flags=re.IGNORECASE))
    balanced = (len(open_tags) == closes)

    js_blocks = []
    for m in re.finditer(r"<script(\s[^>]*)?>(.*?)</script\s*>", html,
                         flags=re.IGNORECASE | re.DOTALL):
        attrs, content = m.group(1) or "", m.group(2)
        type_match = re.search(r'type\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
        script_type = (type_match.group(1).strip().lower() if type_match else "")
        has_src = bool(re.search(r'\bsrc\s*=', attrs, flags=re.IGNORECASE))
        if has_src:
            continue  # 외부 스크립트 — 인라인 내용 없음, 검사 대상 아님
        if script_type in _NON_JS_SCRIPT_TYPES:
            continue  # JSON-LD 등 비-JS 블록 — JS 문법검사 대상 아님
        js_blocks.append(content)
    return js_blocks, balanced


def _check_js_syntax(js: str) -> tuple[bool, bool, str]:
    """node --check로 JS 문법 검증. 반환: (passed, skipped, detail).
    Node 미존재 환경에서는 skip 처리(무거운 신규 의존성 추가 대신 기존
    환경의 node를 그대로 사용 — 프로젝트 .venv/frontend가 이미 Node 필요)."""
    import shutil
    import subprocess
    import tempfile

    node_path = shutil.which("node")
    if not node_path:
        return True, True, "Node.js 미발견 — JS 문법 검증 건너뜀(구조 검사만 적용)"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(js)
            tmp_path = f.name
        result = subprocess.run(
            [node_path, "--check", tmp_path],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return True, False, "✅ JS 문법 검증 통과(node --check)"
        err_lines = (result.stderr or "").strip().splitlines()
        # node --check의 실제 오류 원인은 "SyntaxError:"/"...Error:" 줄에 있고,
        # stderr 마지막 줄은 버전 배너("Node.js vX.Y.Z")일 뿐이라 마지막 줄을
        # 그대로 쓰면 안 된다 — Error 줄을 찾아 우선 사용한다.
        reason = next((l.strip() for l in err_lines if "Error" in l), None)
        if not reason:
            reason = err_lines[-1] if err_lines else "알 수 없는 문법 오류"
        # unterminated template literal은 대개 "Unexpected end of input"으로 표면화됨
        return False, False, f"❌ JS 문법 오류(node --check): {reason}"
    except Exception as e:
        return True, True, f"JS 문법 검증 실행 실패(구조 검사만 적용): {e}"
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except Exception:
            pass


def validate_html_js_completeness(html: str) -> tuple[bool, str, list[dict]]:
    """generate_app()이 만든 raw HTML이 저장 가능한 수준으로 완결됐는지 검사.
    save_app() 호출 이전에 실행되어야 하는 게이트(호출측 책임 — 이 함수 자체는
    아무것도 차단하지 않고 결과만 반환한다).

    반환: (ok, message, steps) — steps는 pre_build_qa()와 동일한
    {"step","label","passed","skipped","detail"} 리스트.
    ok=False면 호출측이 save_app()을 호출하지 않아야 한다.
    """
    steps: list[dict] = []
    html = html or ""

    # Step 1: 비어있지 않음
    p1 = bool(html.strip())
    steps.append({"step": 1, "label": "HTML 비어있지 않음", "passed": p1, "skipped": False,
                 "detail": f"길이 {len(html)}자" if p1 else "HTML이 비어 있음"})
    if not p1:
        for s, l in [(2, "<html> 루트 태그 존재"), (3, "</html> 닫힘 존재"),
                     (4, "<script>/</script> 태그 균형"), (5, "미종료 template literal/문자열 없음"),
                     (6, "계산기 핵심 구조(입력/버튼) 존재"), (7, "JS 문법 검증")]:
            steps.append({"step": s, "label": l, "passed": False, "skipped": True,
                         "detail": "Step 1 실패로 건너뜀"})
        return False, "HTML이 비어 있음", steps

    # Step 2: <html> 루트 태그
    p2 = bool(re.search(r"<html(\s|>)", html, flags=re.IGNORECASE))
    steps.append({"step": 2, "label": "<html> 루트 태그 존재", "passed": p2, "skipped": False,
                 "detail": "✅ 발견" if p2 else "❌ <html> 태그를 찾을 수 없음"})

    # Step 3: </html> 닫힘 — 문자열 끝부분에 존재해야 함(중간에서 잘린 경우 탐지)
    tail = html.rstrip()[-200:].lower()
    p3 = "</html>" in tail
    steps.append({"step": 3, "label": "</html> 닫힘 존재", "passed": p3, "skipped": False,
                 "detail": "✅ 문서 끝에서 발견" if p3 else
                           "❌ </html>이 문서 끝부분에 없음 — 응답이 중간에서 잘렸을 가능성"})

    # Step 4: <script>/</script> 태그 균형
    blocks, balanced = _extract_script_blocks(html)
    p4 = balanced and len(blocks) >= 1
    steps.append({"step": 4, "label": "<script>/</script> 태그 균형", "passed": p4, "skipped": False,
                 "detail": (f"✅ script 블록 {len(blocks)}개, 태그 균형 정상" if p4 else
                           "❌ <script>/</script> 개수 불일치 또는 script 블록 없음"
                           " — 미종료 스크립트 블록 의심")})

    # Step 5: 미종료 template literal/문자열(백틱 짝수 개 — 휴리스틱, Step 7이 최종 판정)
    if blocks:
        joined_js = "\n".join(blocks)
        backtick_count = joined_js.count("`")
        p5 = (backtick_count % 2 == 0)
        steps.append({"step": 5, "label": "미종료 template literal 없음(휴리스틱)",
                     "passed": p5, "skipped": False,
                     "detail": (f"✅ 백틱 {backtick_count}개(짝수)" if p5 else
                               f"❌ 백틱 {backtick_count}개(홀수) — template literal이 닫히지 않았을 가능성")})
    else:
        joined_js = ""
        steps.append({"step": 5, "label": "미종료 template literal 없음(휴리스틱)",
                     "passed": False, "skipped": True,
                     "detail": "Step 4 실패(script 블록 추출 불가)로 건너뜀"})

    # Step 6: 계산기 핵심 구조 — 입력 필드 + 버튼(generate_app() sys2 프롬프트가
    # 항상 "입력폼+계산버튼+결과영역"을 요구하므로 이 구조는 정상 생성물의 불변 조건)
    has_input = bool(re.search(r"<input\b", html, flags=re.IGNORECASE))
    has_button = bool(re.search(r"<button\b", html, flags=re.IGNORECASE))
    p6 = has_input and has_button
    steps.append({"step": 6, "label": "계산기 핵심 구조(입력/버튼) 존재", "passed": p6, "skipped": False,
                 "detail": (f"✅ input {'있음' if has_input else '없음'}, button {'있음' if has_button else '없음'}"
                           if p6 else
                           f"❌ input {'있음' if has_input else '없음'}, button {'있음' if has_button else '없음'}"
                           " — 계산기 필수 요소 누락")})

    # Step 7: JS 문법 검증(node --check) — script 추출 성공한 경우만 시도
    if blocks and balanced:
        p7, skipped7, d7 = _check_js_syntax(joined_js)
    else:
        p7, skipped7, d7 = False, False, "Step 4 실패(script 블록 추출 불가)로 실행 불가 — FAIL 처리"
    steps.append({"step": 7, "label": "JS 문법 검증(node --check)",
                 "passed": p7, "skipped": skipped7, "detail": d7})

    ok = all(s["passed"] or s["skipped"] for s in steps)
    if ok:
        message = "✅ HTML/JS 완결성 검증 통과"
    else:
        failed_labels = [s["label"] for s in steps if not s["passed"] and not s["skipped"]]
        message = "HTML/JS 완결성 검증 실패: " + "; ".join(failed_labels)
    return ok, message, steps
