# -*- coding: utf-8 -*-
"""
modules/calculator_pipeline.py — 계산기 콘텐츠 파이프라인 (v12.0)

흐름: Calculator(DB) → Keyword(Collector) → 점수(strategist_calculator)
      → SEO/FAQ 생성 → SEO 블로그 글 작성(calculator_writer_prompt)
      → 계산기 위젯(template_engine) CTA 삽입 → ArticleRepository 저장 → 발행

기존 run_once(정책/RSS)와 분리된 별도 경로. 모든 데이터 접근 Repository/Adapter 경유.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

from adapters.db.factory import get_db_adapter
from repositories.calculator_repository import CalculatorRepository
from repositories.article_repository import ArticleRepository
from .collector.factory import get_collector
from .ai_roles import make_provider
from .calculator_seo_generator import generate_seo
from .calculator_faq_generator import generate_faq
from .strategist_calculator import score_keywords
from . import cleaner
from . import content_quality
from .logger import get_logger, BudgetTracker
from . import telegram_ops as tops

LOG = get_logger()
_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "calculator_writer_prompt.txt"

CTA_TEXT = "아래 CalcMate 계산기를 이용하면 자동으로 계산할 수 있습니다."


def _load_prompt() -> str:
    try:
        return _PROMPT.read_text(encoding="utf-8")
    except Exception:
        return ("너는 SEO 에디터다. 주어진 키워드로 2500~3500자 한국어 블로그 글을 작성하라. "
                "계산기 CTA/위젯은 시스템이 본문 뒤에 자동 삽입한다. "
                "[BODY_HTML_START]...[BODY_HTML_END]로 감싸라.")


def _prompt_version() -> str:
    """writer 프롬프트 내용 해시(sha1[:8]). 내용이 바뀌면 값이 바뀌어 HOLD 재평가 판단에 사용.
    (하위호환 유지 — 현재 REWRITE HOLD 서명은 _quality_signature로 확장됨. legal sentinel과 구분)"""
    return hashlib.sha1(_load_prompt().encode("utf-8")).hexdigest()[:8]


# 품질 재평가 서명에 포함하는 legal_basis 필드(G8/writer 판정에 실제 영향 주는 것만).
# 표시용 필드(name/category/emoji 등)는 제외 → 불필요한 재평가/재생성 방지.
_LEGAL_SIG_FIELDS = ("law", "article", "related_articles", "authority",
                     "forbidden_articles", "forbidden_phrases", "needs_human_legal", "writer_note")


def _quality_signature(cfg: dict, calc: dict) -> str:
    """품질 재평가 서명(sha1[:8]). REWRITE HOLD의 quality_prompt_version에 저장된다.

    이 값이 바뀌면 기존 HOLD의 저장 서명과 달라져 has_quality_hold 재평가 게이트가
    자동으로 '재도전'을 허용한다(운영자 개입 없이 다음 스케줄에서 재생성).
    포함: writer 프롬프트 + 품질 게이트(QUALITY_GATE)/스코어(QUALITY_SCORE) 규칙
          + G7 금지문체(AI_STYLE_BLOCKLIST) + 해당 계산기 legal_basis(판정영향 필드).
    slug 단위 — 수정한 계산기만 서명이 바뀌어 그 계산기만 재도전(불필요한 전체 재생성 방지)."""
    lb = _load_legal_basis().get(str(calc.get("slug", "")).strip()) or {}
    payload = {
        "prompt": _load_prompt(),
        "gate": cfg.get("QUALITY_GATE", {}) or {},
        "score": cfg.get("QUALITY_SCORE", {}) or {},
        "style": cfg.get("AI_STYLE_BLOCKLIST", []) or [],
        "legal": {k: lb.get(k) for k in _LEGAL_SIG_FIELDS},
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def _notify_critical_hold(cfg: dict, calc: dict, critical_gates: list, exhausted: bool) -> None:
    """Critical 반복실패로 HOLD된 경우 운영 알림. exhausted(Critical 연속 임계 초과)일 때만.
    telegram_ops 표준 헬퍼만 사용(raw send 직접호출 금지). 실패해도 발행 흐름 무영향."""
    if not exhausted:
        return
    LOG.warning("[품질] Critical HOLD 알림 대상: %s (slug=%s, critical=%s)",
                calc.get("name", ""), calc.get("slug", ""), critical_gates or "-")
    try:
        from . import telegram_ops as TOPS
        TOPS.notify_quality_hold(cfg, calc.get("name", ""), calc.get("slug", ""),
                                 critical_gates, datetime.now().isoformat(timespec="minutes"))
    except Exception as _e:
        LOG.warning("품질 HOLD Telegram 알림 실패(무시): %s", _e)


def _style_block(cfg: dict) -> str:
    """config AI_STYLE_BLOCKLIST를 프롬프트에 주입(하드코딩 대신 설정 단일소스)."""
    patterns = cfg.get("AI_STYLE_BLOCKLIST") or []
    if not patterns:
        return ""
    items = "\n".join(f"- {p}" for p in patterns)
    return ("\n[금지 문체 — 아래 표현/패턴은 절대 사용하지 말 것]\n" + items)


def _rewrite_block(failed_rules) -> str:
    """재생성 시 failed_rules(priority 정렬)를 '우선순위 순 보완 지시'로 주입."""
    if not failed_rules:
        return ""
    lines = []
    for r in failed_rules:
        lines.append(f"{r.get('priority','?')}. [{r.get('gate','')}] {r.get('detail','')}")
    return ("\n[재생성 지시] 이전 생성본이 아래 기준을 충족하지 못했다. "
            "우선순위 순서대로 반드시 보완하라:\n" + "\n".join(lines))


# legal 미검증 HOLD 전용 sentinel(프롬프트 버전과 구분) — legal이 채워지면 이 HOLD는 무시되어 자동 해제.
_LEGAL_HOLD_VERSION = "legal_unverified"


def _load_legal_basis() -> dict:
    """계산기 slug→registry 엔트리(legal_basis.draft.yaml + registry_auto.yaml merge, 큐레이션 우선).
    registry_loader에 위임(단일 소스). §1: App Factory 자동엔트리도 여기서 함께 보임."""
    from .registry_loader import load_registry
    return load_registry()


def _legal_unverified(lb) -> bool:
    """needs_human_legal 선언 + 실제 legal(law/article/authority)이 전부 비어있음 = 진짜 미검증.
    플래그 단독이 아니라 '실제 데이터 존재'를 게이트로 삼아 견고(사람이 플래그 갱신을 깜빡해도,
    검증된 데이터가 있으면 정상 취급 / 데이터가 없으면 플래그와 무관하게 미검증으로 차단).
    → 기존 7종은 legal이 채워져 있어 False(회귀 없음), App Factory 자동엔트리(legal 전부 null)는 True."""
    if not isinstance(lb, dict):
        return False
    return bool(lb.get("needs_human_legal")) and not (lb.get("law") or lb.get("article") or lb.get("authority"))


def _legal_undetermined_block() -> str:
    """legal 미확정 계산기용 writer 지침(작업지시서 E §4). 특정 조항 인용을 원천 금지해
    환각(검증 안 된 조항 인용) 벡터를 차단 + 강한 면책 문구 강제."""
    return (
        "\n[법적 근거 미확정 — 아래를 반드시 지킨다]\n"
        "이 계산기의 법적 근거는 아직 확정되지 않았습니다. 다음을 반드시 지킵니다:\n"
        "1. 특정 법령명이나 조항 번호를 절대 언급하지 않습니다(확인되지 않은 조항을 "
        "인용하면 심각한 오류가 됩니다).\n"
        "2. 대신 일반적인 정보와 계산 방식의 취지만 서술합니다.\n"
        "3. 다음 면책 문구를 주의사항에 반드시 포함합니다: \"본 계산기의 법적 근거는 아직 "
        "확정되지 않았습니다. 일반 참고용으로만 활용하시고, 정확한 기준은 관할기관에 "
        "문의하시기 바랍니다.\""
    )


def _ssot_suffix(calc: dict) -> str:
    """STEP 28-24: content_ssot 기반 최신 법정수치 블록(law_ssot.get_ssot_prompt_block 재사용).
    slug에 content_ssot가 없으면 빈 문자열 — 기존 _legal_basis_block() 출력에 영향 없음."""
    from .law_ssot import get_ssot_prompt_block
    block = get_ssot_prompt_block(str(calc.get("slug", "")).strip())
    return f"\n\n{block}" if block else ""


def _legal_basis_block(calc: dict) -> str:
    """계산기 slug의 검증된 법적 근거를 'AI가 지어내지 말고 그대로 인용'하도록 주입.
    AI_STYLE_BLOCKLIST(문체 금지, _style_block)와는 별개 목록(조항 금지=lb['forbidden_articles']).
    null-safe: 값이 없는 필드는 줄 자체를 생략(빈칸/None 누출 방지). 미검증 계산기는 §4 블록으로 대체.
    STEP 28-24: 법령 인용 가드레일 뒤에 content_ssot 기반 최신 법정수치(_ssot_suffix)를 덧붙인다."""
    lb = _load_legal_basis().get(str(calc.get("slug", "")).strip())
    if not lb:
        return ""
    # legal 미확정(needs_human_legal + 실제 legal 공백) → 환각방지 지침 블록으로 대체
    if _legal_unverified(lb):
        return _legal_undetermined_block() + _ssot_suffix(calc)
    parts = ["\n[법적 근거 — 아래 검증된 값을 그대로 정확히 인용한다. 스스로 다른 조항 번호를 "
             "만들어내지 않으며, 확실하지 않으면 법령명과 취지만 쓴다]"]
    if lb.get("law"):
        parts.append(f"- 법령: {lb['law']}")
    if lb.get("article"):
        parts.append(f"- 조항: {lb['article']}")
    if lb.get("related_articles"):
        parts.append(f"- 관련조항: {', '.join(str(x) for x in lb['related_articles'])}")
    if lb.get("authority"):
        parts.append(f"- 소관기관: {lb['authority']}")
    if lb.get("writer_note"):
        parts.append(f"- 작성 지침: {str(lb['writer_note']).strip()}")
    bl = lb.get("forbidden_articles") or []
    if bl:
        parts.append(f"- 다음 조항은 절대 인용하지 않는다: {', '.join(str(x) for x in bl)}")
    fp = lb.get("forbidden_phrases") or []
    if fp:
        parts.append(f"- 다음 확정형 표현은 쓰지 않는다(수급/지급 요건이 복합적이므로 "
                     f"'가능성이 있습니다'/'심사 결과에 따라 달라질 수 있습니다'로 표현): {', '.join(fp)}")
    # §3 표준 면책 문구(소관기관 자동 삽입) — authority 없으면 '관할기관'으로 폴백(None 누출 방지).
    authority = lb.get("authority") or "관할기관"
    parts.append(f"- 주의사항 섹션에 다음 취지의 면책 문구를 반드시 포함한다: "
                 f"\"정확한 세부 기준은 {authority} 등 관할기관에 확인하시기 바랍니다.\" "
                 f"(소관기관명이 복합 표기이면 자연스럽게 요약해서 문장에 녹인다.)")
    return "\n".join(parts) + _ssot_suffix(calc)


def _check_legal_current_before_save(body_html: str, slug: str, cid: str) -> list[dict]:
    """STEP 28-26: DB 저장 직전 SSOT 법정수치 검증(논블로킹 warning).
    STEP 28-20에서 generate_calculator()에 연결한 기존 게이트(check_g_legal_current)를
    그대로 재사용한다(신규 파서 없음). 실패해도 저장을 막지 않고 warning만 남긴다."""
    try:
        from .content_integrity import check_g_legal_current
        fails = check_g_legal_current(body_html, slug)
    except Exception as e:
        fails = [{"gate": "G-LEGAL-CURRENT", "grade": "error", "detail": f"게이트 실행 오류: {e}"}]
    if fails:
        LOG.warning("G-LEGAL-CURRENT 불일치 감지(저장은 계속 진행): cid=%s -> %s",
                    cid, [f.get("detail") for f in fails])
    return fails


def _resolve_context_block(calc: dict) -> str:
    """resolve()로 legal_master.deduction_rules/calculation_flow + registry.writer_context를 조회해
    writer 프롬프트에 '계산 근거 데이터'로 주입한다. 해당 데이터가 없는 계산기는 빈 문자열(no-op)
    → 다른 계산기에는 영향 없음. (Legal Platform v1.0 resolve와 writer를 잇는 최소 연결)"""
    try:
        from .registry_loader import resolve
        r = resolve(str(calc.get("slug", "")).strip()) or {}
    except Exception:
        return ""
    dr = r.get("deduction_rules") or {}
    cf = r.get("calculation_flow") or []
    wc = r.get("writer_context") or {}
    if not (dr or cf or wc):
        return ""
    parts = ["\n[계산 근거 데이터 — 아래 검증된 수치를 활용해 구체적으로 서술한다. 없는 숫자를 지어내지 말 것]"]
    for name, v in dr.items():
        detail = " · ".join(f"{k}={val}" for k, val in v.items()) if isinstance(v, dict) else str(v)
        parts.append(f"- {name}: {detail}")
    if cf:
        parts.append("계산 흐름: " + " → ".join(str(x) for x in cf))
    if wc.get("emphasize"):
        parts.append("강조 공제: " + ", ".join(str(x) for x in wc["emphasize"]))
    if wc.get("example_patterns"):
        parts.append("예시 패턴(서로 다른 조건 2개): " + " / ".join(str(x) for x in wc["example_patterns"]))
    if wc.get("calculation_story"):
        parts.append("핵심 스토리: " + ", ".join(str(x) for x in wc["calculation_story"]))
    return "\n".join(parts)


def _write_article(cfg: dict, calc: dict, keyword: str, seo: dict, faq: list,
                   failed_rules=None, intent: str = None) -> tuple:
    provider, model = make_provider(cfg, "writer")
    # calculator 엔진은 항상 고정 7-H2 템플릿 사용 — intent 분기 없음
    # (eligibility/documents/howto 템플릿은 V2 블로그 엔진용으로 content/blog/ 에 예약됨)
    system = (_load_prompt() + _style_block(cfg) + _legal_basis_block(calc)
              + _resolve_context_block(calc) + _rewrite_block(failed_rules))
    user = (
        f"계산기명: {calc.get('name')}\n"
        f"타겟 키워드(글 주제): {keyword}\n"
        f"SEO 제목: {seo.get('seo_title')}\n"
        f"메타설명: {seo.get('seo_description')}\n"
        f"계산 공식: {calc.get('formula','')}\n"
        f"FAQ: {json.dumps(faq, ensure_ascii=False)}"
        # CTA/위젯은 시스템이 본문 뒤에 자동 삽입하므로 AI 본문에 CTA를 요구하지 않는다(중복 방지).
    )
    text, tokens = provider.chat(system, user, model, max_tokens=4500)
    try:
        BudgetTracker(cfg).record(model, tokens)
    except Exception as _e:
        LOG.warning("토큰 비용 기록/조회 실패: %s", _e)
    
    # 본문에서 첫 번째 <h1> 제거 (워드프레스 제목과 중복 방지)
    body = cleaner.parse_html_body(text)
    body = cleaner.strip_prompt_artifacts(body)
    body = re.sub(r'<h1>.*?</h1>', '', body, count=1, flags=re.IGNORECASE | re.DOTALL)

    return body, tokens


def write_article_for_rewrite(cfg: dict, calc: dict, keyword: str, seo: dict, faq: list,
                               failed_rules=None, intent: str = None) -> tuple:
    """rewrite_pipeline이 사용하는 외부 진입점. _write_article에 위임."""
    return _write_article(cfg, calc, keyword, seo, faq, failed_rules, intent)


def run_calculator_once(cfg: dict, max_count: int = None, only_cid: str = None, allow_duplicate: bool = False, skip_quality: bool = False, intent: str = None) -> dict:
    """활성 계산기 키워드로 SEO 글을 생산/발행. max_count 미지정 시 DAILY_POST_COUNT.
    only_cid 지정 시 그 계산기 후보만 대상(재평가 재도전 등 특정 계산기만 재생성용).
    allow_duplicate: QA 전용. 중복 판정 건너뜀(새 Draft 생성용)."""
    start = time.time()
    budget = BudgetTracker(cfg)
    target = int(max_count if max_count is not None else cfg.get("DAILY_POST_COUNT", 1) or 1)

    bs = budget.check_budget()
    if bs["daily_exceeded"] or bs["monthly_exceeded"]:
        LOG.warning("예산 초과 — 계산기 파이프라인 중단")
        # 발행 0건 조기종료 — 운영자 인지(Sprint 1 §2). 실패해도 흐름 무영향.
        try:
            tops.notify_level(cfg, "WARNING", "예산 초과 — 계산기 파이프라인 중단",
                              f"일예산 초과={bs['daily_exceeded']} / 월예산 초과={bs['monthly_exceeded']}",
                              event="budget")
        except Exception as _e:
            LOG.warning("예산초과 알림 실패(무시): %s", _e)
        return {"produced": 0, "reason": "budget"}

    # 1) 키워드 수집 (Calculator Collector)
    items = get_collector("calculator").collect(cfg, site=None)
    if not items:
        LOG.info("활성 계산기 없음 — 종료 (App Factory/시드로 등록 필요)")
        return {"produced": 0, "reason": "no_calculators"}

    # 특정 계산기만 대상(only_cid) — 재평가 재도전 등에서 1개 계산기만 재생성할 때.
    if only_cid:
        items = [it for it in items if str(it.get("calculator_id", "")) == str(only_cid)]
        LOG.info("[대상한정] 계산기 cid=%s 키워드 %d개만 처리", only_cid, len(items))
        if not items:
            return {"produced": 0, "reason": "only_cid_no_keywords"}

    # 2) 점수화/정렬 (기본 휴리스틱 — 비용 0, cfg.CALCULATOR_AI_SCORE=true면 AI)
    use_ai = bool(cfg.get("CALCULATOR_AI_SCORE", False))
    ranked = score_keywords(cfg, items, use_ai=use_ai)
    LOG.info("계산기 키워드 %d개 수집/정렬 (상위 점수 %s)", len(ranked),
             ranked[0].get("score") if ranked else "-")

    # 중복 방지용 기존 제목
    repo = CalculatorRepository(get_db_adapter(cfg))
    art_repo = ArticleRepository(get_db_adapter(cfg))
    # 기사 스냅샷 1회 로드(sheet read 절감) — 후보당 count/has_quality_hold를 이 스냅샷으로 판정.
    # 실행 중 새로 저장한 행은 아래에서 snapshot에 append(같은 run 내 중복/재평가 정확도 유지).
    try:
        snapshot = list(art_repo.get_all())
    except Exception:
        snapshot = []
    # 계산기 단위 중복 방지 — 동일 계산기의 기존 발행 제목만 비교(cross-calculator 비교 불필요:
    # 계산기명이 제목에 포함되므로 계산기 간 제목 충돌 가능성 극히 낮음).
    # 같은 run 내 새 제목도 아래 루프에서 calc별로 추가되어 intra-run dedup도 유지.
    existing_by_calc: dict[str, set] = {}
    
    # QA 모드(allow_duplicate=True)라면 중복 판정을 건너뛴다.
    if not allow_duplicate:
        for _r in snapshot:
            if _r.get("상태값") == "발행완료":
                _c = str(_r.get("calculator_id", "") or "")
                _t = _r.get("최종추천제목", "") or ""
                if _c and _t:
                    existing_by_calc.setdefault(_c, set()).add(_t)
    else:
        LOG.info("[QA MODE] 중복 판정(Duplicate Filter)을 건너뜁니다.")

    stats = {"produced": 0, "processed": 0, "failed": 0, "dup": 0,
             "quality_hold": 0, "hold_skip": 0, "published": None}
    rcfg = cfg.get("QUALITY_RETRY", {}) or {}
    # §5 legal 미검증 차단 스위치(기본 true). needs_human_legal + 실제 legal 공백 계산기를
    # GPT 호출 전 품질보류. legal-HOLD는 아래 sentinel 버전으로 기록해, 프롬프트 버전 기반
    # 재평가 게이트(has_quality_hold(sig))와 충돌하지 않도록 분리 → legal이 채워지면 자동 해제.
    block_unverified = bool((cfg.get("QUALITY_GATE") or {}).get("BLOCK_UNVERIFIED_LEGAL", True))
    max_candidates = int(rcfg.get("MAX_CANDIDATES_PER_RUN", 5) or 5)
    reeval = bool((cfg.get("QUALITY_HOLD") or {}).get("REEVALUATE_ON_PROMPT_VERSION_CHANGE", True))

    # intent 파라미터 우선순위: 전달받은 인자 > 설정 파일
    intent = intent or cfg.get("intent") 

    attempted = 0   # 실제 생성까지 간 후보 수(AI 비용 기준 상한)
    for it in ranked:
        if stats["produced"] >= target:
            break
        if attempted >= max_candidates:
            LOG.info("[품질] 후보 시도 상한(%d) 도달 — 이번 실행 후보 순회 중단", max_candidates)
            break
        keyword = it.get("keyword") or it.get("title", "")
        calc = repo.get_by_id(it.get("calculator_id", "")) or {"name": keyword}
        stats["processed"] += 1
        try:
            # 계산기당 발행 상한(설정값) — 상태 판단은 Repository(count_active_articles)에 위임.
            # 파이프라인은 개수만 비교하고 상태값 문자열을 직접 다루지 않는다.
            cid = it.get("calculator_id", "")
            # 품질 재평가 서명(계산기별). legal_basis/게이트/프롬프트 변경 시 값이 바뀌어
            # 옛 HOLD가 자동으로 재도전 대상이 된다.
            sig = _quality_signature(cfg, calc)
            max_per = int(cfg.get("MAX_ARTICLES_PER_CALCULATOR", 1) or 1)
            if cid and art_repo.count_active_articles(cid, rows=snapshot) >= max_per:
                stats["dup"] += 1
                continue
            # HOLD 재평가 게이트: 품질보류 이력은 count_active_articles에서 제외되므로
            # 여기서 품질 서명(sig)으로 재도전 여부를 결정(상태 판단은 Repository 헬퍼에 위임).
            if cid:
                if reeval:
                    # 현재 서명 + 같은 키워드로 이미 HOLD된 건 → 재시도 무의미(스킵).
                    # 다른 키워드는 통과(키워드 단위 hold_skip). 서명 변경 시도 통과 → 재도전.
                    if art_repo.has_quality_hold(cid, prompt_version=sig, rows=snapshot, keyword=keyword):
                        stats["hold_skip"] += 1
                        LOG.info("[HOLD스킵] %s (cid=%s)", keyword, cid)
                        continue
                else:
                    # 재평가 off → 같은 키워드 HOLD 이력 있으면 영구 제외(다른 키워드는 허용).
                    if art_repo.has_quality_hold(cid, rows=snapshot, keyword=keyword):
                        stats["hold_skip"] += 1
                        LOG.info("[HOLD스킵] %s (cid=%s)", keyword, cid)
                        continue
            # §5 legal 미검증 차단 게이트 — GPT(generate_seo) 호출 이전에 즉시 품질보류.
            #   trigger: BLOCK_UNVERIFIED_LEGAL=true AND needs_human_legal+실제 legal 공백.
            #   idempotent: 이미 legal-HOLD 이력(sentinel) 있으면 재기록 없이 스킵.
            #   해제: 사람이 legal_basis.draft.yaml에 legal 채우면 _legal_unverified=False → 이 게이트 통과.
            if block_unverified and cid:
                _lb = _load_legal_basis().get(str(calc.get("slug", "")).strip())
                if _lb and _legal_unverified(_lb):
                    if art_repo.has_quality_hold(cid, prompt_version=_LEGAL_HOLD_VERSION, rows=snapshot):
                        stats["hold_skip"] += 1
                        LOG.info("[HOLD스킵] %s (cid=%s)", keyword, cid)
                        continue
                    LOG.warning("[품질] legal 미검증(needs_human_legal, legal 공백) — GPT 호출 전 품질보류: %s",
                                calc.get("slug", cid))
                    # 발행 0건(legal 미검증 차단) — 운영자 인지(Sprint 1 §2)
                    try:
                        tops.notify_level(cfg, "WARNING",
                            f"legal 미검증 발행 보류: {calc.get('name', keyword)}",
                            f"slug={calc.get('slug', cid)} · needs_human_legal이나 법령/조항/기관 값이 비어 "
                            f"발행 차단(품질보류). legal_basis.draft.yaml 입력 시 자동 해제.",
                            event="quality_critical_hold")
                    except Exception as _e:
                        LOG.warning("legal HOLD 알림 실패(무시): %s", _e)
                    _aid = art_repo.save({
                        "정책명": keyword, "최종추천제목": calc.get("name", keyword),
                        "발행일시": datetime.now().isoformat(),
                        "상태값": "품질보류", "site_id": it.get("site_id", ""), "calculator_id": cid,
                        "quality_status": "LEGAL_UNVERIFIED",
                        "quality_prompt_version": _LEGAL_HOLD_VERSION,
                        "quality_reviewed_at": datetime.now().isoformat(),
                    })
                    try:
                        art_repo.append_history(_aid, "quality_hold",
                                                {"reason": "legal_unverified", "needs_human_legal": True,
                                                 "prompt_version": _LEGAL_HOLD_VERSION})
                    except Exception as _e:
                        LOG.warning("history(legal_unverified) 기록 실패(무시): %s", _e)
                    snapshot.append({"calculator_id": cid, "상태값": "품질보류",
                                     "quality_prompt_version": _LEGAL_HOLD_VERSION})
                    stats["quality_hold"] += 1
                    continue
            seo = generate_seo(cfg, calc.get("name", keyword), keyword, intent=intent)
            if seo.get("seo_title") in existing_by_calc.get(cid, set()):
                stats["dup"] += 1
                continue
            attempted += 1   # 모든 스킵 게이트 통과 → 실제 생성 진입(후보 상한 카운트)
            # FAQ: 계산기에 저장된 것 우선, 없으면 생성
            faq = []
            if calc.get("faq"):
                try:
                    faq = json.loads(calc["faq"]) if isinstance(calc["faq"], str) else calc["faq"]
                except Exception:
                    faq = []
            if not faq:
                faq = generate_faq(cfg, calc.get("name", keyword))

            # 계산기 위젯(결정론) — 재시도와 무관하므로 1회만 계산.
            # 블로그 본문과 중복되는 섹션(본문/FAQ/관련계산기/광고/PWA)은 위젯에서 숨김.
            from .app_generator import generate_calculator, render_inline_calculator
            widget_cfg = dict(cfg)
            widget_cfg.update({"SHOW_ARTICLE": False, "SHOW_FAQ": False, "SHOW_RELATED": False,
                               "SHOW_ADSENSE": False, "SHOW_CPA": False, "SHOW_PWA": False})
            widget = render_inline_calculator(generate_calculator(calc, widget_cfg))
            # 관련링크 후보(결정론) — 1회만 조회
            try:
                from .internal_link_engine import (generate_related_calculators,
                                                   generate_related_articles, inject_internal_links)
                rel_calc = generate_related_calculators(cfg, cid, 3)
                rel_art = generate_related_articles(cfg, keyword, 3)
            except Exception as _e:
                LOG.warning("내부링크 후보 조회 실패(무시): %s", _e)
                rel_calc, rel_art = [], []
                inject_internal_links = lambda h, *a: h
            # Adaptive G5용: inject_internal_links가 실제로 렌더할 유효 후보 수 (URL 보유 항목만)
            _link_pool_size = (
                sum(1 for c in rel_calc if c.get("url")) +
                sum(1 for a in rel_art if a.get("title") and a.get("url"))
            )

            def _assemble(_body):
                fh = f"{_body}\n<hr/>\n<h2>계산기 사용하기</h2>\n<p>{CTA_TEXT}</p>\n{widget}"
                try:
                    return inject_internal_links(fh, rel_calc, rel_art)
                except Exception as _e2:
                    LOG.warning("내부링크 주입 실패(무시): %s", _e2)
                    return fh

            # 본문 생성 → 조립 → 품질검수(Gate→Score). REWRITE면 writer 전체재생성 재시도.
            from .publish_quality import check_publish_quality
            LOG.info("_write_article intent=%s 호출", intent)
            body_html, _ = _write_article(cfg, calc, keyword, seo, faq, intent=intent)
            body_html = content_quality.improve_content(body_html)
            final_html = _assemble(body_html)
            
            # has_verified: 계산기에 formula가 있으면 verified 예시 있다고 간주(G4/G-NEW2 분기용)
            _has_verified = bool((calc or {}).get("formula"))
            if skip_quality:
                LOG.info("[QA MODE] 품질 검수(Quality Gate)를 건너뜁니다.")
                qc = {"result": "PASS", "score": 100, "html": final_html}
            else:
                qc = check_publish_quality(cfg, body_html, final_html, calc,
                                           link_pool_size=_link_pool_size,
                                           intent=intent, has_verified=_has_verified)

            max_total = int(rcfg.get("MAX_TOTAL_RETRY", 3) or 3)     # 총 재시도 하드상한(무한루프 방지)
            crit_limit = int(rcfg.get("CRITICAL_RETRY_LIMIT", 2) or 2)  # Critical 연속실패 임계
            q_retries, consec_critical, critical_exhausted = 0, 0, False
            while qc.get("result") == "REWRITE" and q_retries < max_total:
                q_retries += 1
                consec_critical = (consec_critical + 1) if qc.get("severity") == "critical" else 0
                if consec_critical >= crit_limit:
                    critical_exhausted = True
                    LOG.warning("[품질] Critical 연속 %d회(임계 %d) 반복 실패: %s",
                                consec_critical, crit_limit, keyword)
                LOG.info("[품질] REWRITE 전체재생성 %d/%d: %s (severity=%s)",
                         q_retries, max_total, keyword, qc.get("severity"))
                # Rewrite Contract 주입: 직전 검수의 failed_rules를 우선순위 순으로 writer에 전달
                body_html, _ = _write_article(cfg, calc, keyword, seo, faq,
                                              failed_rules=qc.get("failed_rules"), intent=intent)
                body_html = content_quality.improve_content(body_html)
                final_html = _assemble(body_html)
                qc = check_publish_quality(cfg, body_html, final_html, calc,
                                           link_pool_size=_link_pool_size,
                                           intent=intent, has_verified=_has_verified)

            final_html = qc.get("html") or final_html   # G6 CTA중복 코드수정 반영본
            q_fields = {
                "quality_score": ("" if qc.get("score") is None else qc.get("score")),
                "quality_status": qc.get("result", ""),
                "quality_failed_rules": json.dumps(qc.get("failed_rules") or [], ensure_ascii=False),
                "quality_review_model": qc.get("quality_review_model") or "",
                "quality_reviewed_at": datetime.now().isoformat(),
                "quality_prompt_version": sig,
            }

            # 한도 초과에도 REWRITE → 발행하지 않고 품질 HOLD("품질보류", 자동 재도전 대상)
            if qc.get("result") == "REWRITE":
                crit_gates = [r.get("gate", "") for r in (qc.get("failed_rules") or [])
                              if r.get("grade") == "critical"]
                LOG.warning("[품질] 재시도 한도(%d) 초과에도 REWRITE — 미발행/품질보류: %s (critical=%s)",
                            max_total, keyword, crit_gates or "-")
                article_id = art_repo.save({
                    "정책명": keyword, "최종추천제목": seo.get("seo_title"),
                    "메타설명": seo.get("seo_description"),
                    "태그": ", ".join(seo.get("seo_keywords", []) or []),
                    "발행일시": datetime.now().isoformat(),
                    "원본출처": calc.get("published_url", ""),
                    "상태값": "품질보류", "site_id": it.get("site_id", ""), "calculator_id": cid,
                    **q_fields,
                })
                try:
                    art_repo.append_history(article_id, "quality_hold",
                                            {"quality_status": "REWRITE", "retries": q_retries,
                                             "severity": qc.get("severity", ""),
                                             "critical_gates": crit_gates,
                                             "prompt_version": sig})
                except Exception as _e:
                    LOG.warning("history(quality_hold) 기록 실패(무시): %s", _e)
                # Critical 반복실패 HOLD → 운영 알림(기존: critical_exhausted일 때만 발송)
                _notify_critical_hold(cfg, calc, crit_gates, critical_exhausted)
                # 비-Critical(Major/Score 미달) 재시도 한도 초과 HOLD도 조용히 넘기지 않는다(Sprint 1 §2).
                # critical_exhausted면 위에서 이미 발송했으므로 중복 방지 위해 else로만.
                if not critical_exhausted:
                    try:
                        tops.notify_level(cfg, "WARNING",
                            f"품질 미달 발행 보류(재시도 한도 초과): {calc.get('name', keyword)}",
                            f"severity={qc.get('severity','')} · retries={q_retries}/{max_total} · "
                            f"failed_gates={[r.get('gate','') for r in (qc.get('failed_rules') or [])] or '-'}",
                            event="quality_critical_hold")
                    except Exception as _e:
                        LOG.warning("품질 HOLD(WARNING) 알림 실패(무시): %s", _e)
                existing_by_calc.setdefault(cid, set()).add(seo.get("seo_title"))
                # 같은 run 내 후속 후보 판정을 위해 스냅샷에 반영(품질보류 + 프롬프트버전 + 키워드)
                # 정책명(keyword) 포함 — 키워드 단위 hold_skip이 동일-run에서도 정확히 작동하도록.
                snapshot.append({"calculator_id": cid, "상태값": "품질보류",
                                 "quality_prompt_version": sig, "정책명": keyword,
                                 "최종추천제목": seo.get("seo_title", "")})
                stats["quality_hold"] += 1
                continue

            # PASS/WARN → 콘텐츠 완성. Calculator = 웹앱 전용(WordPress/Image 미호출).
            # 실제 웹앱 표시 콘텐츠는 calculators.article_content(app_generator가 렌더)에 저장.
            # body_html(순수 AI 본문)만 저장 — final_html은 WP 삽입용 위젯(<script>/SM_CONFIG 포함)이
            # 통째로 붙어있어 웹앱 페이지에 그대로 넣으면 위젯 스크립트 중첩으로 article이 숨겨짐.
            # STEP 28-26: DB 저장 직전 SSOT 법정수치 검증(논블로킹 warning — 저장은 계속 진행).
            _check_legal_current_before_save(body_html, calc.get("slug", ""), cid)
            # STEP 28-52: 콘텐츠 SSOT 추적 필드(content_hash/content_ssot_hash/
            # legal_validated_* 등) 계산 — 기존 게이트를 내부에서 재사용하는 공통 helper.
            try:
                from .content_integrity import build_content_tracking_fields
                _tracking_fields = build_content_tracking_fields(
                    body_html, calc.get("slug", ""), "pipeline_auto")
            except Exception as _te:
                LOG.warning("콘텐츠 추적 필드 계산 실패(저장은 계속 진행): cid=%s -> %s", cid, _te)
                _tracking_fields = {}
            repo.update_generated(cid, {
                "article_content": body_html,
                "seo_title": seo.get("seo_title"),
                "seo_description": seo.get("seo_description"),
                **_tracking_fields,
            })
            article_id = art_repo.save({
                "정책명": keyword,
                "최종추천제목": seo.get("seo_title"),
                "메타설명": seo.get("seo_description"),
                "태그": ", ".join(seo.get("seo_keywords", []) or []),
                "발행일시": datetime.now().isoformat(),
                "원본출처": calc.get("published_url", ""),
                "상태값": "발행완료",
                "site_id": it.get("site_id", ""),
                "calculator_id": cid,
                **q_fields,
            })
            # history "publish" 이벤트 기록(감사 추적 — WP 없이 콘텐츠 완성 시점 기록. 실패해도 무시)
            try:
                art_repo.append_history(article_id, "publish", {})
            except Exception as _e:
                LOG.warning("history(publish) 기록 실패(무시): %s", _e)
            # 재평가로 되살아나 콘텐츠 완성됨 → 같은 계산기의 옛 품질보류 행을 '재처리완료'로 정리
            # (삭제 안 함, 상태만 변경 + history — 감사 추적)
            if cid:
                try:
                    _nres = art_repo.resolve_holds_for_calculator(
                        cid, new_signature=sig, published_post_id="", exclude_id=article_id)
                    if _nres:
                        LOG.info("[REEVALUATE] 콘텐츠 완성 → 옛 품질보류 %d건 재처리완료(resolved): cid=%s",
                                 _nres, cid)
                except Exception as _e:
                    LOG.warning("품질보류 정리 실패(무시): %s", _e)
            existing_by_calc.setdefault(cid, set()).add(seo.get("seo_title"))
            # 같은 run 내 후속 후보의 count_active_articles 판정을 위해 스냅샷에 반영
            snapshot.append({"calculator_id": cid,
                             "상태값": "발행완료",
                             "최종추천제목": seo.get("seo_title", ""),
                             "quality_prompt_version": sig})
            stats["produced"] += 1
            LOG.info("계산기 글 생산: %s", seo.get("seo_title"))
            # 슬롯 표시용 메타(반환값 enrich만). 스케줄러는 max_count=1 단건.
            stats["published"] = {
                "keyword": keyword, "title": seo.get("seo_title", ""),
                "status": "completed",
            }
        except Exception as e:
            stats["failed"] += 1
            LOG.error("계산기 글 생성 오류(%s): %s", keyword, e, exc_info=True)
            tops.notify(cfg, f"[ERROR] 계산기 글 오류: {e}")

    # 실행 종료 사유 3구분(§5): 아무것도 발행 안 된 이유를 사람이 바로 알 수 있게.
    if stats["produced"] > 0:
        reason = "정상완료"          # 이번 실행에서 PASS/WARN 발행 있음
    elif attempted > 0:
        reason = "모든후보HOLD"      # 시도했으나 전부 REWRITE 한도초과로 HOLD
    else:
        reason = "후보소진"          # 시도할 신규 후보 없음(전부 발행됨/재평가 대상 아닌 HOLD)
    stats["reason"] = reason
    stats["attempted"] = attempted

    elapsed = round(time.time() - start, 1)
    LOG.info("✅ 계산기 파이프라인 종료[%s]: 목표 %d / 생산 %d / 시도 %d / 처리 %d / "
             "중복 %d / HOLD스킵 %d / 품질보류 %d / 실패 %d / %s초",
             reason, target, stats["produced"],
             attempted, stats["processed"], stats["dup"], stats["hold_skip"], stats["quality_hold"],
             stats["failed"], elapsed)
    return stats


def reevaluate_holds(cfg: dict, apply: bool = False, only_slug: str = None) -> dict:
    """품질보류(HOLD) 재평가 — 운영 도구(수동 트리거용).

    현재 품질 서명(_quality_signature)과 각 REWRITE HOLD에 저장된 서명을 비교해
    '재도전 대상(released)'과 '유지(blocked)'를 집계하고 [REEVALUATE] 로그를 남긴다.
    실제 해제는 서명 불일치로 자동 처리되므로(다음 파이프라인 실행에서 재도전), 이 함수는
    기본이 '리포트(dry-run)'다. apply=True면 즉시 run_calculator_once를 1회 실행해 재생성한다.
    only_slug 지정 시 그 계산기만 리포트/재생성 대상으로 한정(1건만 검증할 때).
    legal 미검증 HOLD(sentinel)는 legal_basis 입력이 필요하므로 별도 legal_pending으로 분리 보고.

    반환: {holds, released:[...], blocked:[...], legal_pending:[...], applied:bool, produced:int}
    """
    db = get_db_adapter(cfg)
    arepo = ArticleRepository(db)
    crepo = CalculatorRepository(db)
    rows = arepo.get_all()
    holds = [r for r in rows if str(r.get("상태값", "")).strip() == "품질보류"]

    max_per = int(cfg.get("MAX_ARTICLES_PER_CALCULATOR", 1) or 1)
    released, blocked, legal_pending, already_published = [], [], [], []
    for r in holds:
        cid = str(r.get("calculator_id", "") or "")
        saved = str(r.get("quality_prompt_version", "") or "")
        calc = crepo.get_by_id(cid) or {}
        if only_slug and str(calc.get("slug", "")) != str(only_slug):
            continue   # 대상 계산기 한정
        # legal 미검증 sentinel HOLD는 서명 재평가 대상이 아님(legal 입력 시 게이트가 자동 통과)
        if saved == _LEGAL_HOLD_VERSION or str(r.get("quality_status", "")) == "LEGAL_UNVERIFIED":
            legal_pending.append({"cid": cid, "slug": calc.get("slug", ""),
                                  "name": calc.get("name", r.get("최종추천제목", ""))})
            continue
        cur = _quality_signature(cfg, calc)
        item = {"cid": cid, "name": calc.get("name", r.get("최종추천제목", "")),
                "old": saved, "new": cur, "hold_id": str(r.get("ID", "") or "")}
        if saved == cur:
            blocked.append(item)                                  # 서명 동일 → 유지
        elif arepo.count_active_articles(cid, rows=rows) >= max_per:
            already_published.append(item)                        # 이미 발행됨 → 잔존 HOLD(정리 대상)
        else:
            released.append(item)                                 # 서명 변경 + 미발행 → 재도전

    # [REEVALUATE] 로그(요청 형식)
    LOG.info("[REEVALUATE] 품질보류 재평가 — 총 %d건 (재도전 %d / 유지 %d / 이미발행 %d / legal미검증 %d)",
             len(holds), len(released), len(blocked), len(already_published), len(legal_pending))
    for it in released:
        LOG.info("[REEVALUATE]   released(서명변경→재도전): %s (cid=%s) %s→%s",
                 it["name"], it["cid"], it["old"], it["new"])
    for it in already_published:
        LOG.info("[REEVALUATE]   already_published(이미 발행됨→정리 대상): %s (cid=%s)",
                 it["name"], it["cid"])
    for it in blocked:
        LOG.info("[REEVALUATE]   blocked(서명동일→유지): %s (cid=%s) %s",
                 it["name"], it["cid"], it["old"])
    for it in legal_pending:
        LOG.info("[REEVALUATE]   legal미검증(legal_basis 입력 필요): %s (slug=%s)",
                 it["name"], it["slug"])

    applied, produced, resolved = False, 0, 0
    if apply:
        # 1) 이미 발행된 계산기의 잔존 품질보류 정리(삭제 안 함, 재처리완료 + history)
        done = set()
        for it in already_published:
            if it["cid"] in done:
                continue
            resolved += arepo.resolve_holds_for_calculator(
                it["cid"], new_signature=it["new"], reason="already_published_on_reeval")
            done.add(it["cid"])
        if resolved:
            LOG.info("[REEVALUATE] --apply: 이미 발행된 잔존 품질보류 %d건 → 재처리완료(resolved)", resolved)
        # 2) 재도전 대상 재생성(only_slug면 그 계산기만)
        if released:
            target_cid = released[0]["cid"] if only_slug else None
            LOG.info("[REEVALUATE] --apply: 재도전 대상 %d건 → 즉시 재생성 실행%s",
                     len(released), f" (cid={target_cid} 한정)" if target_cid else "")
            stats = run_calculator_once(cfg, only_cid=target_cid) or {}
            produced = int(stats.get("produced", 0))
        applied = True

    return {"holds": len(holds), "released": released, "blocked": blocked,
            "already_published": already_published, "legal_pending": legal_pending,
            "applied": applied, "produced": produced, "resolved": resolved}
