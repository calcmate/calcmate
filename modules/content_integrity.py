# -*- coding: utf-8 -*-
"""
Phase 5-E 자동 정합성 검증 게이트

G-CALC   : 검증된 예시 result 값 vs 본문 서술 정합성
G-NUMCON : 본문 내 명시적 산술식 오류 검출
G-LEGAL  : 법적 근거 오인용 / 무관 키워드 검출
G-STYLE+ : AI 문체 잔존 강화 검사 (G7 보완)
"""
from __future__ import annotations
import hashlib
import re
import sys
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from modules.publish_quality import _plain_text as _strip_html


# ═══════════════════════════════════════════════════════════════════════════
# 공통 유틸리티
# ═══════════════════════════════════════════════════════════════════════════

# 자연어 기간 표현 → 표준 형태 (G-LEGAL-CURRENT/G-CONSISTENCY 검증용)
_DURATION_SYNONYMS = {
    "일주일": "7일",
    "보름": "15일",
}


def _normalize_duration_text(text: str) -> str:
    """
    법정 기간·요율·금액의 자연어 변형을 표준 형태로 정규화한다.
    SSOT 대조 전용이므로 문맥 무관 전역 치환해도 안전하다.

    - 일주일 → 7일, 보름 → 15일
    - '안에' → '이내' (예: '7일 안에' → '7일 이내')
    - 'N일 내(에)' → 'N일 이내(에)'
    - 'N일이내' → 'N일 이내' (공백 통일)
    - '3.595 %' → '3.595%' (요율 공백 제거)
    - '150만 원' → '150만원', '13,977 원' → '13,977원' (금액 공백 제거)
    """
    out = text
    for src, dst in _DURATION_SYNONYMS.items():
        out = out.replace(src, dst)
    out = out.replace("안에", "이내")
    out = re.sub(r"(\d+)\s*일\s*내(?=에|$)", r"\1일 이내", out)
    out = re.sub(r"(\d+)\s*일\s*이내", r"\1일 이내", out)
    out = re.sub(r"(\d+\.?\d*)\s*%", r"\1%", out)
    out = re.sub(r"([\d,]+)\s*만\s*원", r"\1만원", out)
    out = re.sub(r"([\d,]+)\s*원", r"\1원", out)
    return out


# 금액(만원·원) 패턴 — forbid_amounts 정책(금액 미언급) 검사용
_AMOUNT_RE = re.compile(r"(\d[\d,]*)\s*(만\s*원|원)")
_AMOUNT_BAN_THRESHOLD = 10_000  # 1만원 미만 소액은 오탐 방지를 위해 제외


def _find_amounts(text: str) -> list[tuple[int, str]]:
    """텍스트에서 금액(만원/원) 추출 → [(원 단위 금액, 정규화된 원문)]"""
    found: list[tuple[int, str]] = []
    for m in _AMOUNT_RE.finditer(text):
        try:
            num = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).replace(" ", "")
        if unit == "만원":
            num *= 10_000
        found.append((num, m.group(0).replace(" ", "")))
    return found


def _format_krw(amount: int) -> list[str]:
    """
    정수 원화 금액 → 본문에서 검색 가능한 표기 변형 목록.
    14400000 → ['1,440만원', '1,440만 원', '1440만원', ...]
    105600   → ['105,600원', '105600원']
    """
    variants: list[str] = []
    if amount <= 0:
        return variants

    if amount >= 10_000 and amount % 10_000 == 0:
        man = amount // 10_000
        variants += [f"{man:,}만원", f"{man:,}만 원", f"{man}만원", f"{man}만 원"]
    elif amount >= 10_000:
        man = amount // 10_000
        rem = amount % 10_000
        variants += [f"{man:,}만 {rem:,}원", f"{man}만 {rem}원"]

    variants += [f"{amount:,}원", f"{amount}원"]
    return variants


# ═══════════════════════════════════════════════════════════════════════════
# G-CALC : 검증된 예시 결과값 정합성
# ═══════════════════════════════════════════════════════════════════════════

_SMALL_AMOUNT_THRESHOLD = 10_000  # 1만원 미만 소액(단순 요율값 등) 제외


def _pick_check_amounts(result: dict | int | float) -> list[tuple[str, int]]:
    """
    result에서 실제 검증할 금액 목록을 선별한다.
    - result dict에 'total' 키가 있으면 total만
    - result가 scalar면 그 값만
    - 그 외(복수 컴포넌트 dict)는 모든 양수 금액
    """
    if isinstance(result, (int, float)):
        if result >= _SMALL_AMOUNT_THRESHOLD:
            return [("result", int(result))]
        return []

    if isinstance(result, dict):
        # 'total' 키 우선
        if "total" in result:
            v = result["total"]
            if isinstance(v, (int, float)) and v >= _SMALL_AMOUNT_THRESHOLD:
                return [("total", int(v))]
            return []
        # 'total' 없으면 모든 양수 컴포넌트 (계산기 intent 등)
        return [
            (k, int(v))
            for k, v in result.items()
            if isinstance(v, (int, float)) and v >= _SMALL_AMOUNT_THRESHOLD
        ]
    return []


def check_g_calc(
    body_html: str,
    example_context: dict | None,
    intent: str | None = None,
) -> list[dict]:
    """
    example_context.examples[].result 의 검증된 금액이
    본문 텍스트에 하나 이상 등장하는지 확인한다.

    - documents intent: 절차 안내 글이므로 계산 결과 미인용 — 면제
    - total 필드 있으면 total만, 없으면 개별 컴포넌트 전체 검사

    Returns: gate fail dict 목록
    """
    if intent == "documents":
        return []  # 서류 안내 글은 계산 결과 인용 불필요

    fails: list[dict] = []
    examples = (example_context or {}).get("examples") or []
    if not examples:
        return fails

    text = _strip_html(body_html)

    for idx, ex in enumerate(examples):
        result = ex.get("result") or {}
        if not result:
            continue

        amounts = _pick_check_amounts(result)
        for field, amount in amounts:
            variants = _format_krw(amount)
            if not any(v in text for v in variants):
                fails.append({
                    "gate": "G-CALC",
                    "grade": "major",
                    "detail": (
                        f"예시 {idx + 1}번 '{field}' = {amount:,}원 -> "
                        f"본문에 미등장 (예상 표기: {variants[:2]})"
                    ),
                })
    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-NUMCON : 본문 내 산술식 모순 검사
# ═══════════════════════════════════════════════════════════════════════════

# "A만원 × B = C만원"  (B: 소수 0.X 또는 % 형식)
_ARITH2_RE = re.compile(
    r"([\d,]+)\s*만\s*원\s*[×x×]\s*([\d.]+)(?:%|\s*)\s*=\s*(?:약\s*)?([\d,]+)\s*만\s*원"
)
# "A만원 × B × C일 = D만원" (3항 곱셈 – 일수 포함)
_ARITH3_RE = re.compile(
    r"([\d,]+)\s*만\s*원\s*[×x×]\s*([\d.]+)\s*[×x×]\s*([\d,]+)\s*일\s*=\s*(?:약\s*)?([\d,]+)\s*만\s*원"
)

_ARITH_TOL = 0.015  # 1.5% 허용 오차 (반올림 차이 흡수)


def _check_mul(a_man: int, b: float, c_man_stated: int, label: str) -> dict | None:
    """a(만원) × b 의 예상값과 c_man_stated(만원)을 비교. 오차 초과 시 fail dict 반환."""
    if b > 1 and b < 100:  # % 표기 (e.g. "60" → 0.6)
        b /= 100
    expected = a_man * b
    if expected == 0:
        return None
    rel_err = abs(c_man_stated - expected) / expected
    if rel_err > _ARITH_TOL:
        return {
            "gate": "G-NUMCON",
            "grade": "major",
            "detail": (
                f"산술 오류 ({label}): {a_man}만원 × {b:.4g} "
                f"= {c_man_stated}만원 (계산값: {expected:,.1f}만원, 오차 {rel_err*100:.1f}%)"
            ),
        }
    return None


def check_g_numcon(body_html: str) -> list[dict]:
    """본문 내 명시적 산술식 정합성 검사."""
    fails: list[dict] = []
    text = _strip_html(body_html)

    # 3항 패턴 먼저
    for m in _ARITH3_RE.finditer(text):
        a = int(m.group(1).replace(",", ""))
        b = float(m.group(2))
        days = int(m.group(3).replace(",", ""))
        d_stated = int(m.group(4).replace(",", ""))
        if b > 1:
            b /= 100
        expected = a * b * days
        rel_err = abs(d_stated - expected) / max(expected, 1)
        if rel_err > _ARITH_TOL:
            fails.append({
                "gate": "G-NUMCON",
                "grade": "major",
                "detail": (
                    f"산술 오류: {m.group(1)}만원 × {m.group(2)} × {days}일 "
                    f"= {m.group(4)}만원 (계산값: {expected:,.0f}만원)"
                ),
            })

    # 2항 패턴
    for m in _ARITH2_RE.finditer(text):
        a = int(m.group(1).replace(",", ""))
        b = float(m.group(2))
        c = int(m.group(3).replace(",", ""))
        f = _check_mul(a, b, c, f"{m.group(1)}만원 × {m.group(2)}")
        if f:
            fails.append(f)

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-LEGAL : 법적 근거 오인용 검사
# ═══════════════════════════════════════════════════════════════════════════

# slug → [(금지 키워드, 설명)]
_LEGAL_FORBIDDEN: dict[str, list[tuple[str, str]]] = {
    "severance-pay": [
        (
            "근로기준법 제36조",
            "퇴직금 지급기한은 근로자퇴직급여보장법 제9조 소관 (근기법 제36조는 임금 일반)",
        ),
        (
            "근로자퇴직급여 보장법 제8조",
            "지급기한 조항은 제9조 (제8조는 퇴직금 지급의무 규정)",
        ),
    ],
    "four-insurances": [
        (
            "부가가치세",
            "4대보험 취득신고와 무관한 부가가치세 언급",
        ),
    ],
}


def check_g_legal(body_html: str, slug: str | None) -> list[dict]:
    """법적 근거 오인용·무관 키워드 검출."""
    fails: list[dict] = []
    rules = _LEGAL_FORBIDDEN.get(slug or "", [])
    if not rules:
        return fails
    text = _strip_html(body_html)
    for keyword, reason in rules:
        if keyword in text:
            fails.append({
                "gate": "G-LEGAL",
                "grade": "major",
                "detail": f"오인용 키워드 '{keyword}' — {reason}",
            })
    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-STYLE+ : AI 문체 잔존 강화 검사
# ═══════════════════════════════════════════════════════════════════════════

_AI_STYLE_EXTRA = [
    "살펴보겠습니다",
    "알아보겠습니다",
    "살펴봅시다",
    "알아봅시다",
    "이해하셨을 것입니다",
    "이해할 수 있습니다",
    "생각해보면",
]


def check_g_style_plus(body_html: str) -> list[dict]:
    """G7 보완: 추가 AI 문체 패턴 검출."""
    fails: list[dict] = []
    text = _strip_html(body_html)
    hits = [p for p in _AI_STYLE_EXTRA if p in text]
    if hits:
        fails.append({
            "gate": "G-STYLE+",
            "grade": "minor",
            "detail": f"AI 문체 잔존 {len(hits)}건: {', '.join(hits)}",
        })
    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-AI-LINK : AI 본문 내 링크 삽입 검출 (STEP150)
# ═══════════════════════════════════════════════════════════════════════════
# run_integrity_gates()는 build_blog_html() 호출 이전의 raw article만 이 함수에
# 전달한다(content/blog/writer.py::auto_generate_blog_all() 순서 확인됨) — 따라서
# build_blog_html()이 이후 단계에서 코드로 삽입하는 CTA/기관 공식 링크는 이 시점에는
# 아직 본문에 존재하지 않아, 검사 대상과 시점상 자동으로 분리된다.

_HTML_A_TAG_RE = re.compile(r"<a[\s>]", re.I)
_MD_LINK_RE = re.compile(r"\[[^\]\n]+\]\(\s*(?:https?://|/)[^)\s]+\)")
# <a>/Markdown 링크로 감싸이지 않은 순수 텍스트 URL 언급 — 정상 문장과 구분이
# 어려워 major가 아닌 minor(WARN)로만 표시한다.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def check_g_ai_link(body_html: str) -> list[dict]:
    """AI가 작성한 raw 본문에 링크가 없는지 검사한다("AI 본문에는 링크가 없어야
    한다"는 _NO_LINK_RULE을 코드로 강제). <a> 태그·Markdown 링크는 명백한 위반이므로
    major(BLOCK). 태그/Markdown 문법 없이 텍스트로만 등장하는 URL은 major로 단정하기
    애매해 minor(WARN)로만 남긴다."""
    fails: list[dict] = []

    a_hits = _HTML_A_TAG_RE.findall(body_html)
    if a_hits:
        fails.append({
            "gate": "G-AI-LINK",
            "grade": "major",
            "detail": f"AI 본문에 <a> 태그 {len(a_hits)}건 — 링크는 시스템이 자동 삽입하므로 AI가 작성하면 안 됨",
        })

    md_hits = _MD_LINK_RE.findall(body_html)
    if md_hits:
        fails.append({
            "gate": "G-AI-LINK",
            "grade": "major",
            "detail": f"AI 본문에 Markdown 링크 {len(md_hits)}건: {md_hits[:3]}",
        })

    if not a_hits and not md_hits:
        bare = _BARE_URL_RE.findall(body_html)
        if bare:
            fails.append({
                "gate": "G-AI-LINK",
                "grade": "minor",
                "detail": f"본문에 URL 문자열 언급 {len(bare)}건(태그/Markdown 형태 아님, 확인 필요): {bare[:3]}",
            })

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-HTML-CLEAN : AI 본문 HTML/Markdown 오염 검출 (STEP150)
# ═══════════════════════════════════════════════════════════════════════════
# 참고: modules/cleaner.py::strip_prompt_artifacts()/normalize_bold_markdown()가
# generate_article() 내부에서 이미 같은 종류의 오염(프롬프트 지시어 헤딩, 번호
# prefix, **bold**)을 본문에서 조용히 제거한다 — 즉 이 게이트가 받는 body_html은
# 이미 1차 정제를 거친 상태다. 아래 검사는 그 정제가 놓친 잔여 패턴을 잡아내는
# 안전망이며, cleaner의 정확 일치 정규식보다 다소 넓게(레이블 뒤 텍스트가 붙은
# 경우도 포함) 검사해 실질적인 2차 방어 효과를 갖도록 했다. placeholder/Markdown
# heading/코드펜스/문서 wrapper 태그는 cleaner.py가 다루지 않는 영역이라 이 게이트가
# 유일한 방어선이다.

_PROMPT_ARTIFACT_HEADING_RE = re.compile(
    r"<h[23][^>]*>[^<]*(?:CTA|행동\s*유도|할인\s*혜택|계산기\s*연결)[^<]*</h[23]>",
    re.I,
)
_NUMBERED_HEADING_RE = re.compile(r"<h[23][^>]*>\s*\d+[\.\)]\s+", re.I)
_PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}|data-ph\s*=\s*\"")
_MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S")
_CODE_FENCE_RE = re.compile(r"```")
_DOC_WRAPPER_RE = re.compile(r"<(?:html|body|!DOCTYPE)\b", re.I)


def check_g_html_clean(body_html: str) -> list[dict]:
    """AI 본문에 프롬프트 지시어 노출·미치환 placeholder·Markdown 잔여 문법이
    없는지 검사한다. 명백한 패턴만 major(BLOCK)로 판정하며, 오탐 소지가 있는
    패턴(일반 괄호·정상 수식·해시태그형 '#단어' 등)은 이번 STEP에서 규칙에
    포함하지 않았다. Markdown 링크([텍스트](URL))는 G-AI-LINK가 이미 검사하므로
    여기서 중복 판정하지 않는다."""
    fails: list[dict] = []

    artifact_hits = (_PROMPT_ARTIFACT_HEADING_RE.findall(body_html)
                     + _NUMBERED_HEADING_RE.findall(body_html))
    if artifact_hits:
        fails.append({
            "gate": "G-HTML-CLEAN",
            "grade": "major",
            "detail": f"프롬프트 지시어/번호 prefix가 H2·H3 제목에 노출 {len(artifact_hits)}건",
        })

    ph_hits = _PLACEHOLDER_RE.findall(body_html)
    if ph_hits:
        fails.append({
            "gate": "G-HTML-CLEAN",
            "grade": "major",
            "detail": f"미치환 placeholder {len(ph_hits)}건: {ph_hits[:3]}",
        })

    md_heading_hits = _MD_HEADING_RE.findall(body_html)
    if md_heading_hits:
        fails.append({
            "gate": "G-HTML-CLEAN",
            "grade": "major",
            "detail": f"Markdown heading(#) 잔여 {len(md_heading_hits)}건",
        })

    code_fence_hits = _CODE_FENCE_RE.findall(body_html)
    if code_fence_hits:
        fails.append({
            "gate": "G-HTML-CLEAN",
            "grade": "major",
            "detail": f"Markdown 코드펜스(```) 잔여 {len(code_fence_hits)}건",
        })

    doc_wrapper_hits = _DOC_WRAPPER_RE.findall(body_html)
    if doc_wrapper_hits:
        fails.append({
            "gate": "G-HTML-CLEAN",
            "grade": "major",
            "detail": f"불필요한 문서 wrapper 태그 잔존: {doc_wrapper_hits[:3]}",
        })

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-LEGAL-CURRENT : 법정수치 최신성 검사 (SSOT 대조)
# ═══════════════════════════════════════════════════════════════════════════

def check_g_legal_current(
    body_html: str,
    slug: str | None,
    intent: str | None = None,
) -> list[dict]:
    """
    G-LEGAL-CURRENT: SSOT 기반 법정수치 최신성 검사.

    1. 블랙리스트 검사: forbidden_in_content 값이 본문에 있으면 CRITICAL fail.
       자연어 변형(일주일/안에/내 등)은 정규화 후 대조한다.
    2. 긍정검증: requires_in_content_for_intents 항목의 현행값이 본문에 없으면 major fail.
    3. 금액 금지(forbid_amounts): SSOT에 금액 미언급 정책이면 금액 자체 등장 시 CRITICAL fail.
    """
    if not slug:
        return []
    try:
        from modules.law_ssot import (
            get_forbidden_in_content,
            get_positive_check_items,
            get_amount_ban_flag,
        )
        forbidden = get_forbidden_in_content(slug)
        positive = get_positive_check_items(slug, intent or "") if intent else []
        amount_ban = get_amount_ban_flag(slug)
    except Exception:
        return []

    fails: list[dict] = []
    text = _strip_html(body_html)
    norm_text = _normalize_duration_text(text)

    # 1. 블랙리스트 검사 (자연어 변형 정규화 후)
    for entry in forbidden:
        if entry["value"] in norm_text:
            fails.append({
                "gate": "G-LEGAL-CURRENT",
                "grade": "critical",
                "detail": (
                    f"금지 수치 '{entry['value']}' 탐지 ({entry['item']}): "
                    f"현행 값 '{entry['current']}' 사용 필요 "
                    f"[근거: {entry['legal_basis']}]"
                ),
            })

    # 2. 긍정검증 (intent 해당 항목만, 자연어 변형 허용)
    for entry in positive:
        current_val = entry["value"]
        if current_val and current_val not in norm_text:
            fails.append({
                "gate": "G-LEGAL-CURRENT",
                "grade": "major",
                "detail": (
                    f"현행 법정수치 '{current_val}' 미등장 ({entry['item']}): "
                    f"본문에 반드시 포함 필요 "
                    f"[근거: {entry['legal_basis']}]"
                ),
            })

    # 3. 금액 금지 규칙 (forbid_amounts — 접두어 없는 파생계산값 포함)
    if amount_ban:
        for amount, raw in _find_amounts(norm_text):
            if amount >= _AMOUNT_BAN_THRESHOLD:
                fails.append({
                    "gate": "G-LEGAL-CURRENT",
                    "grade": "critical",
                    "detail": (
                        f"금액 미언급 정책 위반: '{raw}' 탐지 — "
                        f"이 글에서는 구체 금액을 언급하지 않고 소관기관 최신 안내를 참고하도록 서술해야 합니다"
                    ),
                })

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# STEP 28-52 : 콘텐츠 SSOT 추적 필드
# ═══════════════════════════════════════════════════════════════════════════

def build_content_tracking_fields(article_html: str, slug: str, content_source: str) -> dict:
    """저장 payload에 병합할 콘텐츠 SSOT 추적 필드를 계산한다.

    check_g_legal_current()를 그대로 재사용(신규 파서 없음)해 검증하고,
    _legal_current_passed/_legal_current_failures 같은 내부 실패 상세 리스트는
    반환값에 포함하지 않는다(기존 로그/출력 방식 유지, DB에는 상태 문자열만 저장).
    """
    from .law_ssot import content_ssot_hash

    article_html = article_html or ""
    ssot_hash = content_ssot_hash(slug) if slug else ""
    if not slug:
        status = "NOT_CHECKED"
    else:
        fails = check_g_legal_current(article_html, slug)
        status = "PASS" if not fails else "FAIL"

    return {
        "content_hash": hashlib.sha256(article_html.encode("utf-8")).hexdigest(),
        "content_source": content_source,
        "content_ssot_hash": ssot_hash,
        "legal_validated_at": datetime.now().isoformat(),
        "legal_validated_ssot_hash": ssot_hash,
        "legal_validation_status": status,
    }


def get_content_freshness(row: dict) -> str:
    """STEP 28-52: DB row 1건의 SSOT 신선도를 read-only로 판정.

    우선순위: NO_SSOT → NEEDS_REVIEW → STALE → MATCH.
    실제 DB 값을 수정하지 않으며, 기존 17개 row처럼 추적 필드가 없는 경우는
    STALE로 단정하지 않고 NEEDS_REVIEW로 분류한다.
    """
    from .law_ssot import get_slug_ssot, content_ssot_hash

    slug = row.get("slug", "")
    if not get_slug_ssot(slug).get("items", []):
        return "NO_SSOT"

    validated_hash = row.get("legal_validated_ssot_hash")
    validation_status = row.get("legal_validation_status")
    if not validated_hash or not row.get("content_ssot_hash") or not validation_status:
        return "NEEDS_REVIEW"

    current_hash = content_ssot_hash(slug)
    if current_hash != validated_hash:
        return "STALE"

    if validation_status == "PASS":
        return "MATCH"
    return "NEEDS_REVIEW"


# ═══════════════════════════════════════════════════════════════════════════
# G-CONSISTENCY : FAQ 수치 ↔ 본문 수치 일관성 검사
# ═══════════════════════════════════════════════════════════════════════════

# 보험료율 범위 (0.5%~30%) — 이 범위 내 퍼센트만 비교
_RATE_RE = re.compile(r'(\d+\.?\d*)%')
_RATE_RANGE = (0.5, 30.0)

# "상한[액] N만원" / "상한[액] N원" / "하한[액] ..." 패턴 (법정 상한/하한 금액)
_CEIL_FLOOR_RE = re.compile(r'(?:상한액?|하한액?)\s*([\d,]+)\s*(만\s*원|원)')

# "N일 이내" / "N일이내" 패턴 (법정기간)
_PERIOD_DAY_RE = re.compile(r'(\d+)\s*일\s*이내')

# 파생금액 식: "A(만)원 × R% = C(만)원" (R가 명시적 %인 경우만)
_DERIVED_RATE_RE = re.compile(
    r'([\d,]+)\s*(?:만\s*원|원)\s*[×x×]\s*([\d.]+)%\s*=\s*(?:약\s*)?([\d,]+)\s*(?:만\s*원|원)'
)


def _extract_insurance_rates(text: str) -> set[str]:
    """텍스트에서 보험료율 범위(0.5%~30%)의 퍼센트 값 추출."""
    rates: set[str] = set()
    for m in _RATE_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if _RATE_RANGE[0] <= v <= _RATE_RANGE[1]:
            rates.add(m.group(0))  # e.g. "3.595%"
    return rates


def _extract_legal_ceilings(text: str) -> set[int]:
    """텍스트에서 '상한[액] N만원' / '상한[액] N원' 금액(원 단위) 추출."""
    result: set[int] = set()
    for m in _CEIL_FLOOR_RE.finditer(text):
        try:
            num = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).replace(" ", "")
        if unit == "만원":
            num *= 10_000
        result.add(num)
    return result


def _check_derived_amount_ssot(body_text: str, slug: str) -> list[dict]:
    """
    파생금액 식에 쓰인 요율(%)이 SSOT 금지(구)값이면 major fail.
    예: '107,850원 × 12.96% = 13,977원' — 12.96%가 SSOT 금지값이면 탐지.
    일반 사용자 계산 예시(임의 급여 × 임의 요율)는 SSOT 금지값과 무관하면 통과.
    """
    try:
        from modules.law_ssot import get_forbidden_in_content
        forbidden = get_forbidden_in_content(slug)
    except Exception:
        return []
    if not forbidden:
        return []
    forbidden_rates = {f["value"] for f in forbidden if "%" in f["value"]}
    if not forbidden_rates:
        return []

    fails: list[dict] = []
    norm_text = _normalize_duration_text(body_text)
    for m in _DERIVED_RATE_RE.finditer(norm_text):
        base = m.group(1)
        rate_pct = m.group(2) + "%"
        result = m.group(3)
        if rate_pct in forbidden_rates:
            fails.append({
                "gate": "G-CONSISTENCY",
                "grade": "major",
                "detail": (
                    f"파생계산식에 금지 요율 '{rate_pct}' 사용 "
                    f"({base} × {rate_pct} = {result}) — SSOT 현행값으로 대체 필요"
                ),
            })
    return fails


def _extract_legal_periods(text: str) -> set[int]:
    """텍스트에서 'N일 이내' 법정기간 일수 추출."""
    result: set[int] = set()
    for m in _PERIOD_DAY_RE.finditer(text):
        try:
            result.add(int(m.group(1)))
        except ValueError:
            pass
    return result


def check_g_consistency(body_html: str, slug: str | None = None) -> list[dict]:
    """
    FAQ ↔ 본문 수치 일관성 검사.
    비교 대상: 보험료율(%), 법정 상한/하한 금액(원), 법정기간(N일 이내).
    동일한 법정 사실끼리만 비교 — FAQ에만 있고 본문에 없는 값 = 불일치.
    추가로 파생금액 식의 요율이 SSOT 금지(구)값이면 탐지.
    """
    faq_match = re.search(r'<h2[^>]*>FAQ</h2>(.*)', body_html, re.I | re.S)
    if not faq_match:
        return []

    faq_text = _strip_html(faq_match.group(1))
    body_text = _strip_html(body_html[:faq_match.start()])

    # 자연어 변형 정규화 (일주일/안에/N일내/금액 공백 등)
    faq_text = _normalize_duration_text(faq_text)
    body_text = _normalize_duration_text(body_text)

    if not body_text.strip():
        return []

    fails: list[dict] = []

    # --- 0. 파생금액 식의 요율 ↔ SSOT 금지값 대조 (본문 기준) ---
    if slug:
        fails.extend(_check_derived_amount_ssot(body_text, slug))

    # --- 1. 보험료율(%) 비교 ---
    faq_rates = _extract_insurance_rates(faq_text)
    body_rates = _extract_insurance_rates(body_text)
    only_in_faq_rates = faq_rates - body_rates
    if only_in_faq_rates and body_rates:
        for rate in sorted(only_in_faq_rates):
            fails.append({
                "gate": "G-CONSISTENCY",
                "grade": "major",
                "detail": (
                    f"FAQ 요율 {rate}가 본문에 없음 "
                    f"(본문 요율: {', '.join(sorted(body_rates)[:3])})"
                ),
            })

    # --- 2. 법정 상한/하한 금액(원) 비교 ---
    faq_ceilings = _extract_legal_ceilings(faq_text)
    body_ceilings = _extract_legal_ceilings(body_text)
    only_in_faq_ceil = faq_ceilings - body_ceilings
    if only_in_faq_ceil and body_ceilings:
        for amt in sorted(only_in_faq_ceil):
            fails.append({
                "gate": "G-CONSISTENCY",
                "grade": "major",
                "detail": (
                    f"FAQ 법정금액 {amt:,}원이 본문에 없음 "
                    f"(본문 법정금액: {', '.join(f'{a:,}원' for a in sorted(body_ceilings)[:3])})"
                ),
            })

    # --- 3. 법정기간(N일 이내) 비교 ---
    faq_periods = _extract_legal_periods(faq_text)
    body_periods = _extract_legal_periods(body_text)
    only_in_faq_periods = faq_periods - body_periods
    if only_in_faq_periods and body_periods:
        for days in sorted(only_in_faq_periods):
            fails.append({
                "gate": "G-CONSISTENCY",
                "grade": "major",
                "detail": (
                    f"FAQ 법정기간 {days}일 이내가 본문에 없음 "
                    f"(본문 법정기간: {', '.join(f'{d}일 이내' for d in sorted(body_periods)[:3])})"
                ),
            })

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-H2 : intent별 필수 H2 구조 검증
# ═══════════════════════════════════════════════════════════════════════════

_INTENT_REQUIRED_H2: dict[str, list[str]] = {
    "eligibility": ["지급 대상", "제외 대상", "계산 방법", "FAQ"],
    "howto":       ["이용 절차", "계산 예시", "FAQ"],
    "documents":   ["필수 서류 목록", "서류 발급 방법", "FAQ"],
    "calculator":  ["계산 원리", "지급 조건", "FAQ"],
}

# 구 파이프라인 H2 패턴 (확장) — 이 패턴이 등장하면 FAIL
_LEGACY_H2_RE = re.compile(
    r'<h2[^>]*>\s*(?:계산기\s*소개|입력\s*방법|결과\s*확인|'
    r'계산기\s*이용\s*방법|이용\s*방법|사용\s*방법|사용\s*안내)\s*</h2>',
    re.I,
)


def check_g_h2_structure(body_html: str, intent: str | None) -> list[dict]:
    """
    intent별 필수 H2가 존재하는지 + 구 파이프라인 H2 패턴이 없는지 검사.
    """
    fails: list[dict] = []

    # 구 패턴 탐지
    legacy_hits = _LEGACY_H2_RE.findall(body_html)
    if legacy_hits:
        fails.append({
            "gate": "G-H2",
            "grade": "major",
            "detail": f"구 파이프라인 H2 패턴 탐지: {legacy_hits}",
        })

    # intent별 필수 H2 검사
    required = _INTENT_REQUIRED_H2.get(intent or "", [])
    actual_h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', body_html, re.I | re.S)
    actual_texts = [_strip_html(h).strip() for h in actual_h2s]

    for req in required:
        if not any(req in t for t in actual_texts):
            fails.append({
                "gate": "G-H2",
                "grade": "major",
                "detail": f"필수 H2 '{req}' 없음 (intent={intent})",
            })

    return fails


# ═══════════════════════════════════════════════════════════════════════════
# G-HEALTH-DISCLAIMER : health_metric 전용 안전 고지 존재 검사 (STEP156, P1-D)
# ═══════════════════════════════════════════════════════════════════════════
# STEP155에서 확정한 정책: "위험 표현(진단/확정 등) 탐지"는 부정문(예: "진단하는
# 도구가 아닙니다")까지 오탐하는 근본적 한계가 있어 채택하지 않는다. 대신 "안전
# 고지가 존재하는가"만 결정론적으로 확인한다 — 부재(존재하지 않음)를 근거로 WARN할
# 뿐, 특정 단독 키워드(건강/질병/진단/위험/비만 등) 존재만으로 판정하지 않는다.
# intent == "health_metric"에만 적용되며, 그 외 intent는 항상 no-op이다.

# 1) 참고용/보조지표 계열 — "참고용" 자체, 또는 "단순한 지표...함께 고려/판단" 조합
#    (Draft585 실제 표현 "BMI는 단순한 지표일 뿐, ...다른 건강 지표와 함께 고려하는
#    것이 좋습니다"이 이 패턴으로 PASS 처리됨을 실측 확인).
_HEALTH_DISCLAIMER_REFERENCE_RE = re.compile(
    r"참고\s*(용|만|자료|지표)|단순한\s*지표.{0,80}(함께|고려|판단)|보조\s*지표"
)
# 2) 비진단 계열 — "진단(하는 도구가) 아닙니다/할 수 없습니다", "단정할 수 없습니다" 등.
#    "아닙니다"는 활용형 축약으로 "아니"가 아니라 "아닙"으로 시작하므로(아니다→아닙니다)
#    두 형태를 모두 포함한다.
_HEALTH_DISCLAIMER_NON_DIAGNOSTIC_RE = re.compile(
    r"진단[^.]{0,15}(아니|아닙|불가|어렵)|진단할\s*수\s*없|단정[^.]{0,10}(아니|아닙|할\s*수\s*없|어렵)"
)
# 3) 전문가 상담 계열 — "전문가/의사/의료진/병원 ... 상담/진료/방문"
_HEALTH_DISCLAIMER_EXPERT_RE = re.compile(
    r"(전문가|의사|의료진|병원).{0,10}(상담|진료|방문)"
)


def check_g_health_disclaimer(body_html: str, intent: str | None = None) -> list[dict]:
    """health_metric 콘텐츠에 안전 고지(참고용/비진단/전문가 상담 중 하나)가
    있는지 검사한다. intent가 health_metric이 아니면 항상 no-op. 안전 고지가
    하나라도 발견되면 PASS([]), 전혀 없으면 minor(WARN)만 반환한다 — 이번 STEP
    범위에서는 critical/major로 절대 승격하지 않는다."""
    if intent != "health_metric":
        return []

    text = _strip_html(body_html)
    has_disclaimer = bool(
        _HEALTH_DISCLAIMER_REFERENCE_RE.search(text)
        or _HEALTH_DISCLAIMER_NON_DIAGNOSTIC_RE.search(text)
        or _HEALTH_DISCLAIMER_EXPERT_RE.search(text)
    )
    if has_disclaimer:
        return []

    return [{
        "gate": "G-HEALTH-DISCLAIMER",
        "grade": "minor",
        "detail": (
            "health_metric 콘텐츠에 안전 고지(참고용/보조지표, 비진단, 전문가 상담 권고 중 "
            "어느 것도)가 발견되지 않음(경고, 발행 차단 아님)"
        ),
    }]


# ═══════════════════════════════════════════════════════════════════════════
# 통합 실행 함수
# ═══════════════════════════════════════════════════════════════════════════

_ALL_GATES = {
    "G-CALC", "G-NUMCON", "G-LEGAL", "G-STYLE+",
    "G-LEGAL-CURRENT", "G-CONSISTENCY", "G-H2",
    # STEP150
    "G-AI-LINK", "G-HTML-CLEAN",
    # STEP156
    "G-HEALTH-DISCLAIMER",
}


def run_integrity_gates(
    body_html: str,
    slug: str | None = None,
    example_context: dict | None = None,
    intent: str | None = None,
) -> tuple[list[str], list[dict]]:
    """
    모든 정합성 게이트 실행.
    Returns: (passed_gate_names, failed_gate_dicts)
    """
    all_failed: list[dict] = []
    all_failed.extend(check_g_numcon(body_html))
    all_failed.extend(check_g_calc(body_html, example_context, intent=intent))
    all_failed.extend(check_g_legal(body_html, slug))
    all_failed.extend(check_g_style_plus(body_html))
    all_failed.extend(check_g_legal_current(body_html, slug, intent=intent))
    all_failed.extend(check_g_consistency(body_html, slug=slug))
    all_failed.extend(check_g_h2_structure(body_html, intent))
    all_failed.extend(check_g_ai_link(body_html))
    all_failed.extend(check_g_html_clean(body_html))
    all_failed.extend(check_g_health_disclaimer(body_html, intent=intent))

    failed_names = {f["gate"] for f in all_failed}
    passed = sorted(_ALL_GATES - failed_names)
    return passed, all_failed
