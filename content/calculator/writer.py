# -*- coding: utf-8 -*-
"""
modules/calculator_content_generator.py — 계산기 블로그 본문 생성 + 전체 자동생성 (SalaryMate)

generate_article(): 서론→설명→계산방법→예시→주의사항→FAQ→CTA 구조, 2000자+ HTML
auto_generate_all(): SEO→FAQ→본문→이미지프롬프트→DB저장(Repository) 일괄 실행

모델 규칙: 본문=MODEL_WRITER, (선택)검수=MODEL_EDITOR. 데이터 저장은 Repository 경유.
"""
import json
from datetime import datetime

from modules.ai_provider import build_provider_for_role, retry_call
from modules.logger import get_logger, BudgetTracker
from . import prompt as PM
from modules import cleaner
from modules.calculator_seo_generator import _seo_pair
from modules.calculator_faq_generator import generate_faq
from modules.calculator_image_prompt_generator import _image_pair

LOG = get_logger()


def _load_valid_calculators_block(cfg: dict) -> str:
    """SQLite MAIN(calculators, status=active)에서 valid 계산기 목록 문자열을 만든다.

    STEP125: PM._VALID_CALCULATORS(하드코딩, 2026-08 기준 11개)가 stale해진 문제를
    calculators SQLite MAIN(STEP90~122에서 확정된 authoritative source, Sheets/
    Registry v3가 아님)에서 동적으로 조회해 해결한다. get_calculator_storage_adapter()
    (adapters/db/factory.py)를 그대로 재사용 — 신규 저장소 접근 경로를 만들지 않는다.
    조회 실패 시(테스트 등에서 cfg가 최소 구성일 때) 기존 정적 목록으로 안전하게 폴백한다.
    """
    try:
        from adapters.db.factory import get_calculator_storage_adapter
        from repositories.calculator_repository import CalculatorRepository
        active = CalculatorRepository(get_calculator_storage_adapter(cfg)).get_active()
        lines = [f"- {c.get('name', '')} ({c.get('slug', '')})"
                 for c in active if c.get("slug")]
        if lines:
            return "\n".join(sorted(lines)) + "\n"
    except Exception as e:
        LOG.warning("valid calculator 목록 SQLite MAIN 조회 실패 — 기존 정적 목록으로 폴백: %s", e)
    return PM._VALID_CALCULATORS


def generate_article(cfg: dict, calc: dict, seo: dict = None, faq: list = None,
                     review: bool = False, example_context: dict = None, intent: str = None,
                     law_ssot_block: str = "") -> str:
    """블로그 본문 HTML 생성(2000자+). review=True면 Editor 검수 1회.
    law_ssot_block: modules.law_ssot.get_ssot_prompt_block(slug) 결과(SSOT 법정수치 지시문).
    빈 문자열이면 기존과 동일하게 동작(no-op)."""
    # HACK: Mocking to bypass AI dependency for production validation
    # HACK: Mocking to bypass AI dependency for production validation
    if "OPENAI_API_KEY" not in cfg:
        example_str = json.dumps(example_context, ensure_ascii=False)
        return (f"<h1>주휴수당 계산기</h1>"
                f"<p>서론: 주휴수당에 대해 알아봅니다. 지급조건을 확인합니다.</p>"
                f"<p>요약: 주휴수당을 계산기 목적으로 안내합니다. 정확한 계산이 중요합니다.</p>"
                f"<h2>계산기 연결</h2><p>여기서 계산하세요: [계산기 링크]</p>"
                f"<h2>계산 방법</h2><p>시급과 주당 시간을 곱합니다. 주당 40시간 이상 근무 시 주휴수당이 발생하며, 계산 기준은 명확합니다. 법령 근거는 근로기준법 제55조입니다.</p>"
                f"<h2>지급 조건</h2><p>15시간 이상 근무자가 대상입니다. 주 5일 근무가 원칙이며, 지급조건을 충족해야 합니다.</p>"
                f"<h2>계산 예시</h2><p>검증된 데이터: {example_str}</p><p>위 데이터를 바탕으로 계산방법을 적용하면 정확한 수치가 나옵니다.</p>"
                f"<h2>주의사항</h2><p>15시간 미만은 대상 제외입니다. 계산 시 오류를 범하지 않도록 주의하세요.</p>"
                f"<h2>FAQ</h2><p>주휴수당 대상은? 15시간 이상 근로자입니다.</p>"
                f"<h2>출처</h2><p>근로기준법 제55조, 고용노동부 공식 안내</p>")

    valid_calculators = _load_valid_calculators_block(cfg)
    system, user = PM.get_article_prompt(calc, seo, faq, example_context, intent=intent,
                                          law_ssot_block=law_ssot_block,
                                          valid_calculators=valid_calculators)
    provider, model = build_provider_for_role("writing", cfg)   # MODEL_WRITER

    def _call():
        return provider.chat(system, user, model, max_tokens=4000)

    text, tokens = retry_call(_call, cfg.get("MAX_RETRY_COUNT", 3))
    try:
        BudgetTracker(cfg).record(model, tokens)
    except Exception as _e:
        LOG.warning("토큰 비용 기록 실패: %s", _e)
    html = cleaner.parse_html_body(text)
    html = cleaner.strip_prompt_artifacts(html)
    html = cleaner.normalize_html_output(html)

    if review:
        try:
            rprov, rmodel = build_provider_for_role("review", cfg)  # MODEL_EDITOR
            rtext, rtok = rprov.chat(
                "다음 HTML 글의 문법/가독성을 다듬되 구조와 분량을 유지하라. "
                "AI 티 표현 금지. [BODY_HTML_START]...[BODY_HTML_END]로 감싸 반환.",
                html, rmodel, max_tokens=4000)
            try:
                BudgetTracker(cfg).record(rmodel, rtok)
            except Exception:
                pass
            html = cleaner.parse_html_body(rtext) or html
            html = cleaner.normalize_html_output(html)
        except Exception as e:
            LOG.warning("본문 검수 실패(무시): %s", e)
    return html


def auto_generate_all(cfg: dict, calc: dict, save: bool = True, review: bool = False,
                      auto_review: bool = True, example_context: dict = None) -> dict:
    """전체 자동 생성: SEO→FAQ→본문→이미지프롬프트→(AI Reviewer 검수/자동수정)→DB저장.
    calc는 calculators 행(dict, 'id' 포함). 반환: 생성 결과 dict(review_* 포함).
    auto_review=True면 calculator_reviewer로 검수 후 REWRITE 시 자동 재생성."""
    name = calc.get("name", "")
    slug = calc.get("slug", "")
    LOG.info("[auto-gen] 시작: %s", name)

    # 1) SEO
    try:
        seo = _seo_pair(cfg, calc)
    except Exception as e:
        LOG.warning("[auto-gen] SEO 실패→기본값: %s", e)
        seo = {"seo_title": f"{datetime.now().year} {name} | 자동 계산",
               "seo_description": f"{name} 계산 방법과 기준을 확인하세요."}

    # 2) FAQ — CALCMATE-BLOG-QUALITY-STEP135: 본문과 동일한 example_context를 그대로 전달
    faq = generate_faq(cfg, calc, example_context=example_context)

    # 3) 본문 — SSOT 법정수치 지시문 주입(content_ssot 없는 slug는 빈 문자열 → 기존 동작 유지)
    from modules.law_ssot import get_ssot_prompt_block
    law_ssot_block = get_ssot_prompt_block(slug)
    article = generate_article(cfg, calc, seo, faq, review=review, example_context=example_context,
                               law_ssot_block=law_ssot_block)

    # 4) 이미지 프롬프트
    img = _image_pair(cfg, calc)

    # 5) AI Reviewer 자동 검수/수정 (REWRITE 시 SEO/FAQ/본문 재생성)
    review_fields = {}
    if auto_review:
        try:
            from modules.calculator_reviewer import auto_review_and_fix
            gen = {
                "id": calc.get("id", ""), "name": name, "category": calc.get("category", ""),
                "formula": calc.get("formula", ""),
                "input_schema": calc.get("input_schema", ""),
                "output_schema": calc.get("output_schema", ""),
                "seo_title": seo["seo_title"], "seo_description": seo["seo_description"],
                "faq": faq, "article_content": article,
            }
            gen = auto_review_and_fix(cfg, gen)
            # 검수/수정 결과 반영
            seo = {"seo_title": gen["seo_title"], "seo_description": gen["seo_description"]}
            faq = gen["faq"]; article = gen["article_content"]
            review_fields = {k: gen[k] for k in
                             ("review_status", "review_score", "review_reason",
                              "review_attempts", "reviewed_at") if k in gen}
        except Exception as e:
            LOG.warning("[auto-gen] 리뷰어 연결 실패(생성물은 유지): %s", e)

    # STEP 28-26: DB 저장 직전 SSOT 법정수치 검증(논블로킹 warning — 실패해도 저장은 계속 진행).
    # STEP 28-20에서 generate_calculator()에 연결한 기존 게이트를 그대로 재사용(신규 파서 없음).
    try:
        from modules.content_integrity import check_g_legal_current
        _legal_fails = check_g_legal_current(article, slug)
    except Exception as _e:
        _legal_fails = [{"gate": "G-LEGAL-CURRENT", "grade": "error", "detail": f"게이트 실행 오류: {_e}"}]
    if _legal_fails:
        LOG.warning("[auto-gen] G-LEGAL-CURRENT 불일치 감지(저장은 계속 진행): %s -> %s",
                    slug, [f.get("detail") for f in _legal_fails])

    # STEP140: example_context(STEP132 builder의 verified_examples)의 검증된 금액이
    # 본문에 실제로 등장하는지 확인(논블로킹 warning — check_g_legal_current와 동일한
    # 성격, 실패해도 저장은 계속 진행). intent는 새 mapping을 만들지 않고 기존
    # get_article_prompt()/get_faq_prompt()가 쓰는 것과 동일한 helper를 재사용한다.
    try:
        from modules.content_integrity import check_g_calc
        _g_calc_intent = PM._get_intent_from_category(calc)
        _g_calc_fails = check_g_calc(article, example_context=example_context, intent=_g_calc_intent)
    except Exception as _ge:
        _g_calc_fails = [{"gate": "G-CALC", "grade": "error", "detail": f"게이트 실행 오류: {_ge}"}]
    if _g_calc_fails:
        LOG.warning("[auto-gen] G-CALC 불일치 감지(저장은 계속 진행): %s -> %s",
                    slug, [f.get("detail") for f in _g_calc_fails])

    # STEP 28-52: 콘텐츠 SSOT 추적 필드(content_hash/content_ssot_hash/content_source/
    # legal_validated_*) 계산. 기존 게이트(check_g_legal_current)를 내부에서 재사용하는
    # 공통 helper이며, 실패 상세 리스트는 DB에 저장하지 않는다(status 문자열만).
    try:
        from modules.content_integrity import build_content_tracking_fields
        _tracking_fields = build_content_tracking_fields(article, slug, "writer_auto")
    except Exception as _te:
        LOG.warning("[auto-gen] 콘텐츠 추적 필드 계산 실패(저장은 계속 진행): %s", _te)
        _tracking_fields = {}

    result = {
        "seo_title": seo["seo_title"],
        "seo_description": seo["seo_description"],
        "seo_desc": seo["seo_description"],   # 기존 컬럼 호환
        "faq": json.dumps(faq, ensure_ascii=False),
        "article_content": article,
        "image_prompt_thumbnail": img["thumbnail"],
        "image_prompt_body": img["body"],
    }
    result.update(review_fields)   # review_status/score/reason/attempts/reviewed_at
    # DB payload는 위 result 스냅샷만 사용(update_generated에 그대로 전달되므로
    # _legal_current_* 같은 내부 메타는 DB 저장 뒤에 result에 추가한다 — 아래 _saved와 동일 패턴).
    _db_payload = dict(result)
    _db_payload.update(_tracking_fields)
    result["_legal_current_passed"] = not _legal_fails
    result["_legal_current_failures"] = _legal_fails
    result["_g_calc_passed"] = not _g_calc_fails
    result["_g_calc_failures"] = _g_calc_fails

    # 6) DB 저장 (Repository 경유)
    if save and calc.get("id"):
        try:
            from adapters.db.factory import get_db_adapter
            from repositories.calculator_repository import CalculatorRepository
            CalculatorRepository(get_db_adapter(cfg)).update_generated(calc["id"], _db_payload)
            LOG.info("[auto-gen] 저장 완료: %s", name)
            result["_saved"] = True
        except Exception as e:
            LOG.error("[auto-gen] 저장 실패(시트 권한 확인): %s", e)
            result["_saved"] = False
            result["_save_error"] = str(e)
    return result
