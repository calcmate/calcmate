"""
cleaner.py — STEP 2: 행정 용어 청소 / STEP 9: 정규식 파싱
프롬프트: PART 3-B
"""
import json, re
from .ai_provider import build_provider, retry_call
from .utils.parser import parse_json_lenient

SYSTEM_CLEANER = """너는 정부 정책 원문 데이터를 AI 파이프라인이 처리할 수 있는 순수한 정보 단위로 정제하는 데이터 클리너다.
아래에 입력된 RSS 원문 데이터를 분석하고, 불필요한 행정 수식어를 제거한 뒤 지정된 JSON 구조로만 출력하라.

[정제 규칙]
1. 행정 수식어 제거: "이번에","적극적으로","관련하여","지원하고자","추진 중인","해당되는 분들께서는" 등 제거
2. 핵심 정보 추출: 정책명, 지원 대상, 지원 내용, 신청 기간, 마감일 식별. 없으면 null.
3. 중립적 서술어: 모든 문장을 "~임","~함","~가능" 형태 명사형 단문으로 축약
4. clean_summary: 100자 이상 200자 이하
5. 카테고리: [복지,고용,창업,교육,주거,금융,의료,환경,농업,기타] 중 1개

인사말 없이 순수 JSON만 반환하라:
{"clean_policy_name":"","clean_summary":"","clean_category":"","clean_target":null,"clean_period":null,"clean_deadline":null,"clean_benefit":null,"source_url":""}"""

def clean_rss_item(item: dict, cfg: dict) -> dict:
    provider = build_provider(cfg["ORCHESTRATOR_PROVIDER"], cfg)  # MODEL_CLEANER용
    model = cfg["MODEL_CLEANER"]
    user_msg = f"원문제목: {item['title']}\n원문요약: {item['description']}\n출처URL: {item['link']}\n카테고리추정: {item['category']}"

    def _call():
        text, tokens = provider.chat(SYSTEM_CLEANER, user_msg, model, max_tokens=800)
        return text, tokens

    raw, tokens = retry_call(_call, cfg.get("MAX_RETRY_COUNT", 3))
    try:
        data = parse_json_lenient(raw)
    except Exception:
        # JSON 파싱 실패 시 원본 반환
        data = {"clean_policy_name": item["title"], "clean_summary": item["description"][:200],
                "clean_category": "기타", "clean_target": None, "clean_period": None,
                "clean_deadline": None, "clean_benefit": None, "source_url": item["link"]}
    data["_tokens"] = tokens
    return data

def parse_html_body(text: str) -> str:
    """STEP 9: [BODY_HTML_START]~[BODY_HTML_END] (또는 <BODY_HTML_START>~<BODY_HTML_END>) 구분자 추출"""
    m = re.search(r"[\[<]\s*BODY_HTML_START\s*[\]>](.*?)[\[<]\s*BODY_HTML_END\s*[\]>]", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


# Gate A-1: 프롬프트 내부 지시어가 H2/H3 제목으로 노출된 경우 제거/정리.
# 삭제 대상: CTA·행동유도·할인혜택·계산기연결 전용 헤딩.
_ARTIFACT_LABEL_H_RE = re.compile(
    r'<h([23])[^>]*>\s*(?:\d+[\.\)]\s*)?'
    r'(?:CTA|행동\s*유도(?:\s*\(CTA\))?|할인\s*혜택|계산기\s*연결)'
    r'\s*</h\1>',
    re.I
)
# 번호 prefix 제거: <h2>3. 계산 원리</h2> → <h2>계산 원리</h2>
_NUMBERED_H_RE = re.compile(r'(<h[23][^>]*>)\s*\d+[\.\)]\s+', re.I)


def strip_prompt_artifacts(html: str) -> str:
    """H2/H3에서 프롬프트 내부 지시어 제거: 번호 prefix 및 CTA·행동유도 전용 헤딩."""
    if not html:
        return html
    html = _ARTIFACT_LABEL_H_RE.sub('', html)
    html = _NUMBERED_H_RE.sub(r'\1', html)
    return html


# ── HTML 출력 정규화(Markdown/모바일 overflow 재발 방지) ──
# AI가 "HTML로 출력하라"는 지시를 받고도 비결정적으로 Markdown 문법을 섞어 낼 때가 있다.
# 여기서 최종 저장/발행 직전에 deterministic하게 정규화해 방어선을 둔다.

# **text** → <strong>text</strong>. 캡처 범위에서 *, <, >, 개행을 제외해
# 이미 존재하는 <strong> 태그나 다른 HTML 태그 경계를 침범하지 않는다.
_MD_BOLD_RE = re.compile(r'\*\*([^*\n<>]+?)\*\*')


def normalize_bold_markdown(html: str) -> str:
    """Markdown bold(**text**)를 <strong>text</strong>로 변환. 기존 HTML 구조는 보존한다."""
    if not html or '**' not in html:
        return html
    return _MD_BOLD_RE.sub(r'<strong>\1</strong>', html)


# <pre> 내부에 실제 코드/스크립트로 볼 수 있는 토큰이 있으면 <pre>를 유지한다.
_PRE_CODE_MARKER_RE = re.compile(
    r'(function\s|def\s+\w|class\s+\w|\{|\}|;|<\?php|SELECT\s|import\s|```|//|#!|==|->|::|\$\w)',
    re.I
)
_PRE_BLOCK_RE = re.compile(r'<pre[^>]*>(.*?)</pre>', re.DOTALL | re.I)


def normalize_pre_blocks(html: str) -> str:
    """일반 계산식이 담긴 <pre>를 <p>로 변환해 모바일 가로 overflow를 예방한다.
    실제 코드/고정폭 표현으로 판단되는 <pre>(코드 토큰 포함)는 그대로 둔다."""
    if not html or '<pre' not in html.lower():
        return html

    def _replace(m):
        inner = m.group(1)
        text = inner.strip()
        if not text:
            return m.group(0)
        if _PRE_CODE_MARKER_RE.search(text):
            return m.group(0)
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        if not lines:
            return m.group(0)
        return ''.join(f'<p>{ln}</p>' for ln in lines)

    return _PRE_BLOCK_RE.sub(_replace, html)


def normalize_html_output(html: str) -> str:
    """콘텐츠 생성 최종 단계의 HTML 정규화 진입점.
    <pre> 정규화 후 Markdown bold 정규화 순으로 적용한다.
    malformed closing tag(</</p>, </</dd> 등)도 정리한다."""
    if not html:
        return html
    html = normalize_pre_blocks(html)
    html = normalize_bold_markdown(html)
    # malformed closing tag 방어: </</tag> → </tag>
    html = re.sub(r'</</([a-zA-Z][a-zA-Z0-9]*)>', r'</\1>', html)
    return html
