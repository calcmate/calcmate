# -*- coding: utf-8 -*-
"""
modules/law_ssot.py — LAW_SSOT 로더

legal_basis.master.yaml의 content_ssot 섹션에서 slug별 법정수치 SSOT를 로드.
G-LEGAL-CURRENT Gate 및 생성 프롬프트 주입에서 사용한다.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
from functools import lru_cache

_MASTER_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "legal_basis.master.yaml"

# 수동 캐시: {mtime: parsed_dict}
_MASTER_CACHE: dict = {}


def _load_master() -> dict:
    """YAML 파일을 로드하되, mtime이 변경되면 캐시 무효화."""
    global _MASTER_CACHE
    try:
        current_mtime = _MASTER_PATH.stat().st_mtime
    except Exception:
        current_mtime = 0.0

    # 캐시에 현재 mtime이 있으면 그대로 반환
    if current_mtime in _MASTER_CACHE:
        return _MASTER_CACHE[current_mtime]

    # mtime 변경 또는 첫 로드 → 새로 파싱
    import yaml
    raw = _MASTER_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw) or {}

    # 이전 캐시 정리 (최신 1개만 유지)
    _MASTER_CACHE = {current_mtime: parsed}
    return parsed


def clear_ssot_cache() -> None:
    """law_ssot 캐시 초기화 (외부 호출용)."""
    global _MASTER_CACHE
    _MASTER_CACHE = {}


def get_slug_entry(slug: str) -> dict:
    """slug의 전체 master 항목 반환. 없으면 {}"""
    return _load_master().get(slug, {})


def get_slug_ssot(slug: str) -> dict:
    """slug의 content_ssot 섹션 반환. 없으면 {}"""
    return get_slug_entry(slug).get("content_ssot", {})


def get_forbidden_in_content(slug: str) -> list[dict]:
    """
    slug에서 콘텐츠 본문에 등장해서는 안 되는 항목 목록 반환.
    각 항목: {value, item, current, effective_year, legal_basis}
    """
    ssot = get_slug_ssot(slug)
    result: list[dict] = []
    for item in ssot.get("items", []):
        for forbidden in item.get("forbidden_in_content", []):
            result.append({
                "value": str(forbidden),
                "item": item.get("item", ""),
                "current": item.get("value", ""),
                "effective_year": item.get("effective_year"),
                "legal_basis": item.get("legal_basis", ""),
            })
    return result



def get_forbidden_as_tuples(slug: str) -> list[tuple[str, str]]:
    """
    check_g_legal()용: slug의 forbidden 항목을 (keyword, reason) 튜플 리스트로 반환.
    reason은 legal_basis + item 정보를 포함.
    """
    ssot = get_slug_ssot(slug)
    result: list[tuple[str, str]] = []
    for item in ssot.get("items", []):
        for forbidden in item.get("forbidden_in_content", []):
            keyword = str(forbidden)
            item_name = item.get("item", "")
            legal_basis = item.get("legal_basis", "")
            reason = legal_basis
            if item_name:
                reason += f" ({item_name})"
            result.append((keyword, reason))
    return result


def get_positive_check_items(slug: str, intent: str) -> list[dict]:
    """
    content_ssot.items 중 requires_in_content_for_intents에 intent가 포함된 항목 반환.
    각 항목: {value, item, effective_year, legal_basis}
    """
    ssot = get_slug_ssot(slug)
    result: list[dict] = []
    for item in ssot.get("items", []):
        required_for = item.get("requires_in_content_for_intents", [])
        if intent in required_for:
            result.append({
                "value": item.get("value", ""),
                "item": item.get("item", ""),
                "effective_year": item.get("effective_year"),
                "legal_basis": item.get("legal_basis", ""),
            })
    return result


def get_ssot_prompt_block(slug: str) -> str:
    """
    생성 프롬프트에 주입할 SSOT 블록 문자열 반환.
    content_ssot.items의 item/value/legal_basis를 한국어 지시문으로 변환.
    없으면 빈 문자열.
    """
    ssot = get_slug_ssot(slug)
    items = ssot.get("items", [])
    if not items:
        return ""

    year = ssot.get("effective_year", "현행")
    lines = [f"[{year}년 현행 법정수치 — 이 값만 사용, AI 추측 절대 금지]"]
    
    # 필수 포함 항목 식별
    mandatory_items = [it for it in items if it.get("requires_in_content_for_intents")]
    has_mandatory = bool(mandatory_items)
    
    # 필수 포함 항목이 있으면 최상단에 별도 강조
    if has_mandatory:
        lines.append("\n=== 필수 포함 항목 (누락 시 발행 차단) ===")
        for it in mandatory_items:
            line = f"- {it['item']}: {it['value']}  ← 반드시 본문에 포함"
            if it.get("legal_basis"):
                line += f"  (근거: {it['legal_basis']})"
            lines.append(line)
        lines.append("")
    
    # Payment deadline legal basis note (severance-pay)
    # Find item that forbids 근로기준법 제36조 and has legal_basis 근로자퇴직급여보장법 제9조
    for it in items:
        if it.get("legal_basis") == "근로자퇴직급여보장법 제9조" and "지급기한" in it.get("applies_to", ""):
            correct_basis = it.get("legal_basis")
            forbidden_phrase = it.get("value")
            lines.append(
                f"\n[법적 근거 확인]\n"
                f"- 퇴직금 지급기한 관련 법적 근거: {correct_basis}\n"
                f"- 사용 금지: {forbidden_phrase}\n"
            )
            break

    for it in items:
        line = f"- {it['item']}: {it['value']}"
        if it.get("requires_in_content_for_intents"):
            line += " [필수 포함]"
        if it.get("legal_basis"):
            line += f"  (근거: {it['legal_basis']})"
        lines.append(line)

    # 필수 포함 항목이 있으면 안내 추가
    if has_mandatory:
        lines.append(
            "\n[필수 포함 안내]\n"
            "위 '[필수 포함]' 표시된 항목들은 해당 intent의 생성 본문에 반드시 포함해야 합니다.\n"
            "누락 시 Legal Gate(G-LEGAL-CURRENT)에서 차단되어 발행되지 않습니다.\n"
            "각 항목의 'value' 값을 본문 내 자연스러운 문맥에서 반드시 언급하십시오."
        )

    # 출력 전 필수 체크리스트 (생성 직전 반드시 확인)
    if has_mandatory:
        mandatory_values = [it['value'] for it in mandatory_items]
        checklist = "\n=== 출력 전 필수 체크리스트 (출력하기 전 반드시 확인) ===\n"
        for val in mandatory_values:
            checklist += f"☐ '{val}' 이(가) 본문 어디엔가 포함되었는가?\n"
        checklist += "위 항목 중 하나라도 누락되면 발행 차단됩니다. 출력 전 반드시 모두 체크하십시오.\n"
        lines.append(checklist)

    # 금액 미언급 정책(forbid_amounts)이면 강력한 금지 지시문 추가
    if get_amount_ban_flag(slug):
        lines.append(
            "\n[금액 미언급 필수 지시 — 반드시 준수]\n"
            "- 이 글에는 어떤 금액(만원·원 단위)도 절대 언급하지 않는다.\n"
            "- 계산 예시를 들 때도 통상임금·급여를 숫자로 쓰지 않고 '통상임금'이라고만 표현한다.\n"
            "- '금액은 고용노동부 최신 안내를 참고' 취지로 서술한다."
        )
    
    # 주거 목적 중간정산 특화 지시 (severance-pay eligibility용)
    mandatory_values = [it['value'] for it in items if it.get("requires_in_content_for_intents")]
    if "무주택 세대주" in mandatory_values and "주택 구입" in mandatory_values and "전세보증금" in mandatory_values:
        lines.append(
            "\n=== 주거 목적 중간정산 특화 지시 ===\n"
            "이 글은 퇴직금 중간정산 자격 요건을 다루고 있습니다. 다음 세 가지를 반드시 포함하십시오:\n"
            "1. '무주택 세대주' - 자격 요건의 핵심\n"
            "2. '주택 구입' - 중간정산 사유 1\n"
            "3. '전세보증금' - 중간정산 사유 2\n"
            "이 세 가지가 모두 본문에 없으면 Legal Gate에서 차단됩니다."
        )
    
    return "\n".join(lines)


def get_amount_ban_flag(slug: str) -> bool:
    """
    slug의 content_ssot 항목 중 forbid_amounts: true 가 있는지 여부.
    True면 게시물 본문/FAQ에 금액(만원·원 단위) 자체가 등장해서는 안 된다.
    """
    ssot = get_slug_ssot(slug)
    return any(
        item.get("forbid_amounts")
        for item in ssot.get("items", [])
    )


def get_related_slugs(slug: str) -> list[str]:
    """slug의 related_slugs 반환 (내부링크 자동삽입 용)."""
    return get_slug_entry(slug).get("related_slugs", [])


def get_calc_name(slug: str) -> str:
    """slug의 계산기 이름 반환. 없으면 slug 그대로."""
    return get_slug_entry(slug).get("name", slug)


def content_ssot_hash(slug: str) -> str:
    """STEP 28-52: slug의 content_ssot.items[]를 정규화해 SHA256 hex digest로 반환.
    dict key 순서나 YAML의 formatting/공백/주석 변경에는 영향받지 않고, items의
    실제 값이 바뀔 때만 달라진다(confidence/last_verified 등 메타데이터는
    get_slug_ssot()가 반환하는 content_ssot 블록 중 items만 사용하므로 무관).
    신규 YAML 파서 없이 기존 get_slug_ssot()만 재사용한다."""
    items = get_slug_ssot(slug).get("items", [])
    normalized = json.dumps(items, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
