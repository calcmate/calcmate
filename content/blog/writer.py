# -*- coding: utf-8 -*-
"""
content/blog/writer.py — 블로그 콘텐츠 생성 어댑터

Golden 10 블로그 콘텐츠 재현성을 위한 최소 writer.
content.calculator.writer.generate_article()를 intent와 함께 호출하는 얇은 어댑터.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from content.calculator.writer import generate_article
from content.calculator.prompt import get_article_prompt, QUALITY
from content.blog.template import build_blog_html
from modules.logger import get_logger
from modules.content_integrity import _strip_html
from modules.law_ssot import get_positive_check_items

LOG = get_logger()


def _resolve_calculator_slug(blog_slug: str) -> str:
    """블로그 slug → SSOT 조회에 사용할 계산기 slug.

    "-howto"/"-documents" 등 접미사가 붙은 Golden10 블로그 slug는 별도 계산기가
    아니라 같은 계산기를 다루는 다른 intent의 글이므로, content.blog의 기존
    BLOG_TO_CALCULATOR_SLUG 매핑(get_related_calculator_slug)을 그대로 재사용해
    실제 계산기 slug로 변환한다. 매핑에 없으면(= blog slug 자체가 계산기 slug인
    경우) blog_slug를 그대로 사용한다.
    """
    from content.blog import get_related_calculator_slug
    return get_related_calculator_slug(blog_slug) or blog_slug


def _mock_generate_intent(post: dict, seo: dict, faq: list, intent: str) -> str:
    """Mock: OPENAI_API_KEY 없을 때 intent별 고정 콘텐츠 생성.

    calculator.writer.generate_article()의 mock 경로는 intent를 무시하므로,
    블로그 라인에서는 intent별 prompt 템플릿의 구조를 그대로 따르는
    확정론적 mock을 사용한다.
    """
    name = post.get("name", "")
    example_str = json.dumps(post.get("example_context", {}), ensure_ascii=False)

    faq_html = ""
    if faq:
        faq_items = ""
        for item in faq[:5]:
            q = item.get("question", "")
            a = item.get("answer", "")
            if q and a:
                faq_items += f"<dt>{q}</dt><dd>{a}</dd>"
        if faq_items:
            faq_html = f"<dl>{faq_items}</dl>"

    if intent == "eligibility":
        # severance-pay eligibility는 주거 목적 중간정산 요건(무주택자, 주택구입/전세보증금) 필수 포함
        housing_interim = ""
        if post.get("slug") == "severance-pay":
            housing_interim = (
                f"<h2>주거 목적 중간정산</h2><p>무주택 세대주가 <strong>주택 구입</strong> 또는 "
                f"<strong>전세보증금</strong> 마련을 위해 퇴직금 중간정산을 청구할 수 있습니다"
                f"(근로자퇴직급여보장법 시행령 제3조). 별도 근속 기간 조건은 없습니다.</p>"
            )
        return (
            f"<p>{name}의 지급 대상과 수급 자격을 확인합니다.</p>"
            f"<h2>지급 대상</h2><p>{name}의 지급 대상은 근로기준법 등 관련 법령에 따라 판정합니다."
            f"근로자가 신청할 수 있는지, 고용주가 지급할 의무가 있는지를 함께 확인해야 합니다.</p>"
            f"<h2>근로시간 조건</h2><p>주 15시간 이상 근무 및 6개월 이상 근속이 기본 조건입니다."
            f"근로시간에 따라 지급액이 달라지므로 정확한 확인이 필요합니다.</p>"
            f"<h2>제외 대상</h2><p>특정 조건을 충족하지 못하면 지급받을 수 없습니다."
            f"사업장 규모, 근무 기간, 고용 형태 등에 따라 달라집니다.</p>"
            f"{housing_interim}"
            f"<h2>계산 방법</h2><p>기본 계산 공식에 따라 산정됩니다.</p>"
            f"<p>검증된 데이터: {example_str}</p>"
            f"<h2>FAQ</h2>{faq_html}"
        )
    elif intent == "howto":
        return (
            f"<p>{name}의 이용 방법과 절차를 안내합니다.</p>"
            f"<h2>이용 절차</h2><p>1단계: 필요한 정보를 확인합니다. "
            f"2단계: 계산기를 이용하여 결과를 확인합니다. "
            f"3단계: 결과를 바탕으로 판단합니다.</p>"
            f"<h2>계산 예시</h2><p>검증된 데이터를 바탕으로 실제 계산합니다.</p>"
            f"<p>검증된 데이터: {example_str}</p>"
            f"<h2>주의사항</h2><p>입력값 오류에 주의하세요. 법령 기준이 변경될 수 있습니다.</p>"
            f"<h2>FAQ</h2>{faq_html}"
        )
    elif intent == "documents":
        return (
            f"<p>{name}과 관련된 필요 서류와 제출 방법을 안내합니다.</p>"
            f"<h2>필수 서류 목록</h2><p>신청 및 처리에 필요한 서류를 확인합니다.</p>"
            f"<h2>서류 발급 방법</h2><p>각 서류의 발급처와 발급 절차를 안내합니다.</p>"
            f"<h2>제출 기한 및 절차</h2><p>서류 제출 방법과 기한을 확인합니다.</p>"
            f"<h2>주의사항</h2><p>서류 미비 시 처리가 지연될 수 있습니다.</p>"
            f"<h2>FAQ</h2>{faq_html}"
        )
    else:  # calculator
        return (
            f"<p>{name}의 계산 원리와 방법을 설명합니다.</p>"
            f"<h2>계산 원리</h2><p>법적 근거와 계산 단계를 설명합니다.</p>"
            f"<h2>지급 조건</h2><p>대상 조건과 제외 조건을 확인합니다.</p>"
            f"<h2>주의사항</h2><p>자주 발생하는 오류와 주의점을 안내합니다.</p>"
            f"<h2>FAQ</h2>{faq_html}"
        )


def generate_blog_article(cfg: dict, post: dict, intent: str = None,
                          *, _metadata_sink: dict = None) -> str:
    """블로그 콘텐츠 생성 — content.calculator.writer 재사용 + intent 전달.

    OPENAI_API_KEY가 있으면 calculator.writer.generate_article()을 경유.
    없으면 intent별 mock을 사용 (재현성 테스트용).

    Args:
        cfg: 설정 dict (OPENAI_API_KEY 등)
        post: 계산기 dict (name, category, seo_desc, formula 등)
        intent: eligibility / howto / documents / calculator 중 하나
        _metadata_sink: CALCMATE-BLOG-GEN-METADATA-03 — generate_article()로 그대로
            전달만 하는 선택적 keyword-only 인자(반환형 무변경). mock 경로에서는
            채워지지 않는다(호출 자체가 발생하지 않으므로).

    Returns:
        생성된 HTML 문자열
    """
    seo = {}
    if post.get("seo_title"):
        seo["seo_title"] = post["seo_title"]
    if post.get("seo_description"):
        seo["seo_description"] = post["seo_description"]

    faq = post.get("faq") or []
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except Exception:
            faq = []

    example_context = post.get("example_context")

    # OPENAI_API_KEY가 없으면 intent별 mock 사용 (calculator.writer mock은 intent 무시)
    if "OPENAI_API_KEY" not in cfg:
        return _mock_generate_intent(post, seo, faq, intent)

    # SSOT 법정수치 지시문 주입 — calculator pipeline(auto_generate_all)이 이미 사용하는
    # get_ssot_prompt_block() 패턴을 블로그 라인에도 그대로 재사용한다.
    # content_ssot 없는 slug는 빈 문자열을 반환하므로 기존 동작과 동일(no-op).
    from modules.law_ssot import get_ssot_prompt_block
    calc_slug = _resolve_calculator_slug(post.get("slug", ""))
    law_ssot_block = get_ssot_prompt_block(calc_slug)

    return generate_article(
        cfg, post,
        seo=seo,
        faq=faq,
        example_context=example_context,
        intent=intent,
        law_ssot_block=law_ssot_block,
    )


_INPUT_HASH_FIELDS = (
    "slug", "name", "category", "formula", "input_schema", "output_schema",
)


def _compute_input_hash(post: dict, intent: str) -> str:
    """CALCMATE-BLOG-GEN-METADATA-03: generation input 재현성 signature.

    slug/name/category/formula/input_schema/output_schema/intent/example_context만
    사용한다(updated_at 등 실행 메타 필드 제외). valid_calculators/law_ssot_block처럼
    prompt에는 영향을 주지만 이 whitelist 밖인 값은 prompt_hash가 별도로 포괄하므로,
    "input_hash + prompt_hash"를 함께 봐야 완전한 재현성 신호가 된다(input_hash 단독
    으로는 불충분 — METADATA-02에서 확인된 경계를 그대로 반영).
    modules.law_ssot.content_ssot_hash()와 동일한 canonicalization 관례(sort_keys/
    ensure_ascii/구분자 없는 separators)를 그대로 재사용한다."""
    payload = {field: post.get(field) for field in _INPUT_HASH_FIELDS}
    payload["intent"] = intent
    payload["example_context"] = post.get("example_context")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_prompt_hash(system: str, user: str) -> str:
    """실제 LLM에 전달된 최종 (system, user)의 재현성 signature.
    _metadata_sink를 통해 generate_article() 내부에서 캡처된 값만 사용한다
    (외부에서 프롬프트를 재조립하지 않음 — valid_calculators가 매 호출 DB 조회라
    재현이 보장되지 않기 때문)."""
    canonical = json.dumps({"system": system, "user": user},
                           sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_prompt_hash(system: str, user: str) -> str:
    """실제 LLM에 전달된 최종 (system, user)의 재현성 signature.
    _metadata_sink를 통해 generate_article() 내부에서 캡처된 값만 사용한다
    (외부에서 프롬프트를 재조립하지 않음 — valid_calculators가 매 호출 DB 조회라
    재현이 보장되지 않기 때문)."""
    canonical = json.dumps({"system": system, "user": user},
                           sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_legal_requirements_section(missing_items: list[dict]) -> str:
    """누락된 필수 법률 항목을 보완하기 위한 전용 섹션 HTML 생성.
    
    Args:
        missing_items: get_positive_check_items()에서 반환된 누락 항목 리스트.
                       각 항목은 dict(value, item, legal_basis, effective_year).
    
    Returns:
        HTML 문자열: <section><h2>법적 기준 안내</h2>... 구조.
    """
    if not missing_items:
        return ""
    
    parts = ['<section class="legal-requirements">']
    parts.append('<h2>법적 기준 안내</h2>')
    parts.append('<ul>')
    for item in missing_items:
        val = item.get("value", "")
        item_name = item.get("item", "")
        basis = item.get("legal_basis", "")
        line = f"<li><strong>{val}</strong>"
        if item_name and item_name != val:
            line += f" ({item_name})"
        if basis:
            line += f" — 근거: {basis}"
        line += "</li>"
        parts.append(line)
    parts.append('</ul>')
    parts.append('</section>')
    return "\n".join(parts)


def _supplement_legal_requirements(article: str, slug: str, intent: str) -> str:
    """SSOT 필수 법률 항목이 누락된 경우 전용 섹션으로 보완.
    
    - 이미 존재하는 값은 중복 삽입하지 않음 (idempotent).
    - 누락된 SSOT value만 별도 structured section으로 추가.
    - 자연어 치환/수정 금지, SSOT value만 structured section으로 보완.
    
    Args:
        article: 원본 article HTML.
        slug: 계산기 slug.
        intent: 생성 intent.
    
    Returns:
        보완된 article HTML.
    """
    if not article:
        return article
    
    # 1. SSOT에서 현재 intent에 필수인 positive check items 조회
    positive_items = get_positive_check_items(slug, intent)
    if not positive_items:
        return article
    
    # 2. Gate와 동일한 정규화 기준으로 본문 텍스트 추출
    plain_text = _strip_html(article)
    
    # 3. 누락된 필수 value 식별
    missing_items = []
    for item in positive_items:
        val = item.get("value", "")
        if val and val not in plain_text:
            missing_items.append(item)
    
    if not missing_items:
        return article  # 이미 모두 존재 → 변경 없음
    
    # 4. 누락된 항목만 전용 섹션으로 보완
    legal_section = _build_legal_requirements_section(missing_items)
    
    # 5. 마지막 H2 직전이나 마지막에 섹션 삽입
    # 마지막 </h2> 태그를 찾아 그 앞에 삽입, 없으면 마지막에 추가
    import re
    last_h2_end = max([m.end() for m in re.finditer(r"</h2\s*>", article, re.IGNORECASE)], default=-1)
    if last_h2_end > 0:
        # 마지막 H2 종료 태그 바로 뒤에 삽입
        article = article[:last_h2_end] + "\n" + legal_section + article[last_h2_end:]
    else:
        article = article + "\n" + legal_section
    
    return article


def auto_generate_blog_all(cfg: dict, post: dict, save: bool = True,
                           intent: str = None, *, driver_id: str = None) -> dict:
    """블로그 콘텐츠 자동 생성 — 단일 콘텐츠 생성 + 정합성 검증 + template 조립.

    DB 저장은 하지 않는다 (isolated reproduction 테스트용).

    STEP125: 기존 check_g_legal_current() 단독 호출을 modules.content_integrity의
    기존 7-gate run_integrity_gates()(G-NUMCON/G-CALC/G-LEGAL/G-STYLE+/
    G-LEGAL-CURRENT/G-CONSISTENCY/G-H2)로 확장한다(새 gate 신설 없음, 기존 함수
    그대로 재사용). STEP124에서 확인된 _phase5e_golden_standard.py의 기존 판정
    관례를 그대로 적용한다: critical/major → 발행 차단(article_content=""),
    minor → 경고만 하고 계속 진행. 통과 시 기존 build_blog_html()로 기관 링크/
    계산기 CTA를 복원한 최종 HTML을 반환한다(원본 AI 본문은 raw_article_content로
    별도 보존 — 이중 wrapping 방지를 위해 build_blog_html은 정확히 1회만 호출).

    driver_id: CALCMATE-BLOG-GEN-METADATA-03 — 선택적 keyword-only 인자. 이 생성을
    실행한 driver/script를 호출자가 명시할 때만 값이 채워지며, 전달하지 않으면
    "unknown"으로 기록된다(기존 호출부는 전혀 수정할 필요 없음).
    """
    generation_started_at = datetime.now(timezone.utc).isoformat()
    generation_mode = "mock" if ("OPENAI_API_KEY" not in cfg) else "llm"

    _sink: dict = {}
    if generation_mode == "llm":
        article = generate_blog_article(cfg, post, intent=intent, _metadata_sink=_sink)
    else:
        article = generate_blog_article(cfg, post, intent=intent)

    # SSOT 필수 법률 항목 deterministic 보완 (Gate 실행 직전, LLM 모드만)
    if generation_mode == "llm":
        calc_slug = _resolve_calculator_slug(post.get("slug", ""))
        article = _supplement_legal_requirements(article, calc_slug, intent)

    # STEP153: build_blog_html()에 넘기던 FAQ 파싱을 run_integrity_gates() 호출 이전으로
    # 옮겨 G-FAQ-DUP(calculator_faq)에도 재사용한다 — 새 DB 조회 없음, 기존 post.get("faq")
    # 그대로, 파싱 로직 자체도 변경 없음(위치만 이동).
    faq = post.get("faq") or []
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except Exception:
            faq = []

    calc_slug = _resolve_calculator_slug(post.get("slug", ""))
    try:
        from modules.content_integrity import run_integrity_gates, measure_faq_duplicate_qa
        _faq_duplicate_qa = measure_faq_duplicate_qa(article)
        _passed, _failed = run_integrity_gates(
            body_html=article, slug=calc_slug,
            example_context=post.get("example_context"), intent=intent,
            calculator_faq=faq,
        )
    except Exception as _e:
        _passed = []
        _failed = [{"gate": "INTEGRITY_GATES", "grade": "error", "detail": f"게이트 실행 오류: {_e}"}]
        _faq_duplicate_qa = {
            "gate": "FAQ_DUP_QA_WARNING",
            "body_faq_exact_sentence_matches": 0,
            "body_faq_exact_paragraph_matches": 0,
            "faq_internal_exact_pair_matches": 0,
            "cross_post_exact_pair_matches": 0,
            "severity": "minor",
            "blocking": False,
        }

    _critical = [f for f in _failed if f.get("grade") == "critical"]
    _major = [f for f in _failed if f.get("grade") == "major"]
    _minor = [f for f in _failed if f.get("grade") == "minor"]
    _blocked = bool(_critical or _major)

    if _failed:
        LOG.warning("[blog-auto-gen] integrity gate 불일치 감지(slug=%s, blocked=%s): %s",
                    post.get("slug", ""), _blocked, [f.get("detail") for f in _failed])

    final_html = ""
    if not _blocked:
        final_html = build_blog_html(article, faq=faq, calc_slug=post.get("slug", ""),
                                     calc_name=post.get("name", ""))

    # CALCMATE-BLOG-GEN-METADATA-03: 기존 반환 dict에 additive하게만 추가한다.
    # 위 article/final_html/_blocked/_passed/_failed 계산 로직은 한 줄도 바뀌지 않았다.
    if generation_mode == "llm" and _sink:
        provider = _sink.get("provider")
        model = _sink.get("model")
        prompt_hash = _compute_prompt_hash(_sink.get("system", ""), _sink.get("user", ""))
    else:
        # mock 경로, 또는 LLM 경로였으나 예외적으로 sink가 채워지지 않은 경우
        # (예: 검수 전 예외) — 실제 사용값을 확신할 수 없으므로 None으로 안전하게 처리.
        provider = None
        model = None
        prompt_hash = None

    generation_metadata = {
        "provider": provider,
        "model": model,
        "generation_mode": generation_mode,
        "prompt_hash": prompt_hash,
        "input_hash": _compute_input_hash(post, intent),
        "generation_started_at": generation_started_at,
        "generation_completed_at": datetime.now(timezone.utc).isoformat(),
        "config_source": cfg.get("_config_source", "unknown"),
        "driver_id": driver_id if driver_id is not None else "unknown",
    }

    return {
        "slug": post.get("slug", ""),
        "name": post.get("name", ""),
        "intent": intent,
        "article_content": final_html,
        "raw_article_content": article,
        "len": len(final_html),
        "blocked": _blocked,
        "integrity_passed": _passed,
        "integrity_failed": _failed,
        "legal_current_fails": [f for f in _failed if f.get("gate") == "G-LEGAL-CURRENT"],
        "faq_duplicate_qa": _faq_duplicate_qa,
        "generation_metadata": generation_metadata,
    }
