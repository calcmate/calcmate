# -*- coding: utf-8 -*-
"""modules/content_qa.py — P0-4: 계산기 콘텐츠 생성(SEO/FAQ/본문/이미지) 전용 QA.

modules/content_integrity.py(G-CALC/G-NUMCON/G-LEGAL/... — 블로그 본문 전반의 법적/수치
정합성 게이트, 이미 검증된 콘텐츠 기준으로 설계되어 미검증 콘텐츠에는 false positive가
있음이 STEP 28-20에서 확인되어 비차단으로만 연결되어 있다)와는 별개로, 이 모듈은
"이 콘텐츠가 실제로 이 계산기에 대한 것이 맞는가"만 최소/결정적으로 검사한다.

배경: content/calculator/writer.py::generate_article()에 OPENAI_API_KEY 미설정 시
계산기 종류와 무관하게 하드코딩된 "주휴수당 계산기" mock 본문을 반환하던 버그가 있었다
(P0-4에서 제거). 이 모듈의 cross-calculator contamination 검사는 그런 종류의 문제
(다른 계산기 콘텐츠가 섞여 저장되는 것)를 일반적으로 차단하기 위한 것이다.
"""
from __future__ import annotations
import re

from modules.publish_quality import _plain_text

# 계산기 이름에서 identity 비교에 방해되는 공통 접미사를 제거한다.
_NAME_SUFFIXES = ("계산기", "계산", "안내")

# 제거된 mock/개발용 문구 — 혹시 다른 경로로 재유입되면 즉시 탐지하기 위한 방어적 시그니처.
_KNOWN_MOCK_SIGNATURES = (
    "주휴수당 계산기</h1>",
    "[계산기 링크]",
    "HACK: Mocking",
)

_DEV_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.I),
    re.compile(r"lorem ipsum", re.I),
    re.compile(r"\[여기에.*?\]"),
    re.compile(r"\bFIXME\b", re.I),
)

_MIN_CORE_LEN = 2  # 이 길이 미만인 core는 오탐 위험이 커서 identity/contamination 비교에서 제외


def _core_name(name: str) -> str:
    """계산기명에서 비교용 핵심 키워드를 뽑는다('주휴수당 계산기' -> '주휴수당')."""
    core = (name or "").strip()
    for suf in _NAME_SUFFIXES:
        if core.endswith(suf):
            core = core[: -len(suf)].strip()
            break
    return core


def _core_tokens(core: str) -> list[str]:
    """core('연차 잔여일')를 공백 기준 토큰으로 분리한다('연차', '잔여일').
    실제 생성 콘텐츠는 정확한 전체 구문을 그대로 반복하지 않고 개별 단어를 자연스럽게
    섞어 쓰는 경우가 많으므로(예: '연차를 계산하는 방법'), identity 판정은 전체 구문
    일치가 아니라 토큰 단위 일치로 판단한다 — 실 E2E에서 발견된 오탐 수정."""
    return [t for t in re.split(r"\s+", core) if len(t) >= _MIN_CORE_LEN]


def _combined_text(seo: dict | None, faq: list | None, article: str | None) -> str:
    parts = []
    if seo:
        parts.append(str(seo.get("seo_title", "")))
        parts.append(str(seo.get("seo_description", "")))
    for item in (faq or []):
        if isinstance(item, dict):
            parts.append(str(item.get("question", item.get("q", ""))))
            parts.append(str(item.get("answer", item.get("a", ""))))
    if article:
        parts.append(_plain_text(article))
    return " ".join(p for p in parts if p)


def check_empty_content(seo: dict | None, faq: list | None, article: str | None,
                         img: dict | None = None, *, require_article: bool = False) -> list[dict]:
    """빈 콘텐츠 차단(§5 기본구조). 개별 endpoint는 자신이 생성한 필드만 검사하도록
    호출측이 필요한 인자만 채워서 넘긴다(나머지는 None)."""
    fails: list[dict] = []
    if seo is not None:
        if not str(seo.get("seo_title", "")).strip():
            fails.append({"gate": "EMPTY", "grade": "critical", "detail": "seo_title이 비어있음"})
        if not str(seo.get("seo_description", "")).strip():
            fails.append({"gate": "EMPTY", "grade": "critical", "detail": "seo_description이 비어있음"})
    if faq is not None:
        if not isinstance(faq, list) or len(faq) == 0:
            fails.append({"gate": "EMPTY", "grade": "critical", "detail": "FAQ가 비어있음"})
    if article is not None:
        text = _plain_text(article).strip()
        if not text:
            fails.append({"gate": "EMPTY", "grade": "critical", "detail": "본문이 비어있음"})
        elif require_article and len(text) < 300:
            fails.append({"gate": "EMPTY", "grade": "major",
                          "detail": f"본문이 지나치게 짧음({len(text)}자 — 최소 300자 권장)"})
    if img is not None:
        if not str(img.get("thumbnail", "")).strip() or not str(img.get("body", "")).strip():
            fails.append({"gate": "EMPTY", "grade": "critical", "detail": "이미지 프롬프트가 비어있음"})
    return fails


def check_mock_or_dev_markers(seo: dict | None, faq: list | None, article: str | None) -> list[dict]:
    """제거된 하드코딩 mock 시그니처 + 일반 개발용 placeholder 문구(TODO/lorem ipsum 등) 탐지."""
    fails: list[dict] = []
    text = _combined_text(seo, faq, article)
    raw_html = article or ""
    for sig in _KNOWN_MOCK_SIGNATURES:
        if sig in raw_html or sig in text:
            fails.append({"gate": "MOCK_SIGNATURE", "grade": "critical",
                          "detail": f"제거된 mock/개발용 시그니처 '{sig}' 탐지"})
    for pat in _DEV_PLACEHOLDER_PATTERNS:
        if pat.search(text):
            fails.append({"gate": "MOCK_SIGNATURE", "grade": "major",
                          "detail": f"개발용 placeholder 패턴 탐지: {pat.pattern}"})
    return fails


def check_identity_and_contamination(calc: dict, seo: dict | None = None, faq: list | None = None,
                                      article: str | None = None,
                                      other_calc_names: list[str] | None = None,
                                      require_identity: bool = True) -> list[dict]:
    """생성된 콘텐츠가 이 계산기 자신에 대한 것인지(identity), 다른 계산기 내용이
    섞여 있지 않은지(cross-calculator contamination) 결정적으로 검사한다.

    - identity: own_core 토큰이 결합 텍스트 어디에도 없으면 critical(무관 콘텐츠 의심).
      require_identity=False면 건너뛴다 — 이미지 프롬프트는 영문으로 시각적 개념을
      묘사하도록 설계되어 있어(modules/calculator_image_prompt_generator.py) 계산기의
      한글 이름/핵심어가 문자 그대로 등장할 필요가 없다(실 E2E에서 발견된 오탐 수정).
    - contamination: 다른 계산기의 핵심 키워드(own_core와 겹치지 않는 것)가 결합
      텍스트에 등장하면 critical(예: A 계산기 생성 결과에 B 계산기 이름이 섞임) —
      이미지 프롬프트에도 계속 적용한다(다른 계산기의 한글 키워드가 섞여 있으면
      여전히 유효한 오염 신호이기 때문).
    """
    fails: list[dict] = []
    text = _combined_text(seo, faq, article)
    if not text.strip():
        return fails  # 빈 콘텐츠는 check_empty_content가 이미 처리

    own_name = calc.get("name", "")
    own_core = _core_name(own_name)

    if require_identity:
        own_tokens = _core_tokens(own_core)
        if own_tokens and not any(tok in text for tok in own_tokens):
            fails.append({
                "gate": "IDENTITY", "grade": "critical",
                "detail": f"생성된 콘텐츠에 계산기 자신의 핵심어({own_tokens})가 하나도 등장하지 않음 — 다른 주제의 콘텐츠일 가능성",
            })

    for other_name in (other_calc_names or []):
        if other_name == own_name:
            continue
        other_core = _core_name(other_name)
        if not other_core or len(other_core) < _MIN_CORE_LEN or other_core == own_core:
            continue
        if other_name in text or other_core in text:
            fails.append({
                "gate": "CROSS_CONTAMINATION", "grade": "critical",
                "detail": f"다른 계산기 '{other_name}' 관련 내용이 이 계산기({own_name})의 생성 결과에 감지됨",
            })
    return fails


def run_generation_qa(calc: dict, *, seo: dict | None = None, faq: list | None = None,
                       article: str | None = None, img: dict | None = None,
                       other_calc_names: list[str] | None = None,
                       require_article: bool = False,
                       require_identity: bool = True) -> tuple[bool, list[dict]]:
    """개별/전체 생성 endpoint가 공통으로 호출하는 진입점.
    require_identity=False는 이미지 프롬프트처럼 영문으로 시각적 개념만 묘사하는
    콘텐츠에 사용한다(cross-calculator contamination 검사는 계속 적용됨).
    Returns: (passed: bool, fails: list[dict])"""
    fails: list[dict] = []
    fails.extend(check_empty_content(seo, faq, article, img, require_article=require_article))
    fails.extend(check_mock_or_dev_markers(seo, faq, article))
    fails.extend(check_identity_and_contamination(
        calc, seo, faq, article, other_calc_names, require_identity=require_identity))
    return (len(fails) == 0, fails)
