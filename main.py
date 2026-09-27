"""
main.py — 블로그자동화 v11.6 메인 오케스트레이터
12단계 무인 파이프라인 + 체크포인트 복구 + 비용 보호 + DLQ
"""
import sys, os, json, argparse, time, uuid
from datetime import datetime
from pathlib import Path

# 경로 설정
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from modules.config_loader import load_config, ConfigError
from modules.logger import get_logger, BudgetTracker
from modules import telegram_ops
import modules.rss_collector as rss_collector       # 하위 호환 유지
from modules.collector.factory import get_collector
from modules.site_manager import SiteManager
import modules.cleaner as cleaner
import modules.duplicate_checker as dup_checker
import modules.history_loader as history_loader
import modules.strategist as strategist
import modules.planner as planner
import modules.writer as writer
import modules.editor as editor
import modules.image_generator as image_generator
import modules.publisher as publisher
import modules.sheet_sync as sheet_sync
import modules.backup_manager as backup_manager
from modules.utils import health_monitor as health_check

LOG = get_logger("pipeline")
DLQ_DIR = BASE / "data" / "dlq"
DLQ_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="블로그자동화 v11.6")
    p.add_argument("--dry-run", action="store_true", help="설정 검증만 수행, 실제 API 호출 없음")
    p.add_argument("--once", action="store_true", help="파이프라인 1회만 실행(단발)")
    p.add_argument("--instance", default=None, help="멀티 인스턴스 ID (config/instances/{id}/config.yaml 로드)")
    p.add_argument("--strategy-room", action="store_true", help="전략회의실 즉시 실행")
    p.add_argument("--calculator-id", default=None, help="특정 계산기(ID)만 파이프라인 실행")
    p.add_argument("--intent", default=None, help="특정 Intent(예: eligibility)만 실행")
    p.add_argument("--allow-duplicate-draft", action="store_true", help="QA 모드에서 중복 Draft 생성 허용")
    p.add_argument("--skip-quality-gate", action="store_true", help="QA 모드에서 품질 게이트 우회")
    p.add_argument("--seed-calculators", action="store_true", help="CalcMate 초기 계산기/템플릿 시드 등록")
    p.add_argument("--reevaluate-hold", action="store_true",
                   help="품질보류 재평가 리포트(서명 변경으로 재도전 대상 집계). --apply로 즉시 재생성")
    p.add_argument("--apply", action="store_true",
                   help="--reevaluate-hold와 함께: 재도전 대상이 있으면 즉시 재생성 1회 실행")
    p.add_argument("--only-slug", default=None,
                   help="--reevaluate-hold와 함께: 특정 계산기(slug)만 재평가/재생성 대상으로 한정")
    p.add_argument("--detect-revisions", action="store_true",
                   help="법령 변경 감지(Detect Only): 공식 소스 hash 비교 → 변경 시 Telegram. 자동 수정 없음")
    p.add_argument("--rewrite", action="store_true",
                   help="P2-3 자동 리라이트: RMS/time-based 후보 수집 후 content+excerpt 갱신. "
                        "title/permalink 변경 없음. --dry-run 으로 후보 확인만 가능. 스케줄러 자동 연결 없음")
    return p.parse_args()

# ─────────────────────────────────────────────────────────────
def resolve_blog_publish_fn(cfg: dict):
    """Blog Line의 스케줄러 실행 함수 반환.
    BLOG_SCHEDULE.mode에 따라:
      - draft: isolated output만 생성 (DB/WP 미연결)
      - publish: 기존 publisher.py로 WordPress 발행
    """
    from modules.blog_scheduler_adapter import run_blog_once, run_blog_once_wp
    mode = str(cfg.get("BLOG_SCHEDULE", {}).get("mode", "draft")).strip().lower()
    if mode == "publish":
        return run_blog_once_wp
    return run_blog_once


def resolve_blog_oneoff_publish_fn(cfg: dict, mode: str, topic_id: str = None):
    """1회성(one-off) WP 예약 전용 실행 함수 반환(CALCMATE-ONEOFF-SCHEDULE-STRUCTURE-02).

    resolve_blog_publish_fn()(recurring publish_slots, "draft"=WP 미호출)과는
    완전히 별도의 경로다 — 이 함수는 draft/publish 둘 다 반드시 실제
    run_blog_once_wp()를 통해 WordPress에 게시하며 status만 다르게 전달한다.
      - draft   → run_blog_once_wp(..., status="draft")  (WP 비공개 초안)
      - publish → run_blog_once_wp(..., status="publish") (WP 공개 발행)

    publisher.py의 기존 status 처리(draft/publish 둘 다 지원)를 그대로
    재사용하며, 새로운 WP 발행 경로는 만들지 않는다. resolve_blog_publish_fn()
    자체는 이 함수 추가로 단 한 줄도 바뀌지 않는다.

    topic_id(CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01, additive):
    None이면(기본값) 위 설명대로 기존 Golden10 경로(run_blog_once_wp)를 그대로
    반환한다 — 이 분기는 재작성 없이 완전히 보존된다. topic_id가 주어지면
    명시적으로 Topic 전용 실행 함수(modules/topic_publish_adapter.run_topic_once_wp)
    로만 분기한다 — 잘못된/존재하지 않는 topic_id라도 Golden10으로 새어나가는
    fallback 경로는 존재하지 않는다(GAP3-READONLY-DESIGN-AUDIT-01 STEP7/9 결론.
    존재 검증 자체는 run_topic_once_wp 내부에서 fail-closed로 수행)."""
    from functools import partial
    mode = str(mode or "draft").strip().lower()
    if mode not in ("draft", "publish"):
        raise ValueError(f"허용되지 않는 mode: {mode!r} (허용값: draft, publish)")

    if topic_id is None:
        from modules.blog_scheduler_adapter import run_blog_once_wp
        return partial(run_blog_once_wp, status=mode)

    from modules.topic_publish_adapter import run_topic_once_wp
    return partial(run_topic_once_wp, topic_id=topic_id, status=mode)

# ─────────────────────────────────────────────────────────────
def run_once(cfg: dict, dry_run: bool = False, max_count: int = None) -> dict:
    """수집 후 DAILY_POST_COUNT(또는 max_count)만큼 글을 '생산'한다.

    - 각 항목은 _process_one()에서 독립 처리(한 건 실패가 전체를 멈추지 않음)
    - 중복/실패 건은 건너뛰고 다음 항목 시도
    - 목표 개수 도달 시 종료
    - 매 항목 전 예산 재확인 → 초과 시 즉시 중단
    - 처리 통계를 로그에 기록하고 dict로 반환

    max_count: 스케줄러가 1건씩 실행할 때 사용(미지정 시 DAILY_POST_COUNT).
    """
    start_time = time.time()
    budget = BudgetTracker(cfg)
    target = int(max_count if max_count is not None else cfg.get("DAILY_POST_COUNT", 1) or 1)

    # ── 예산 선차단 ────────────────────────────────────────────
    bs = budget.check_budget()
    if bs["daily_exceeded"]:
        LOG.warning("일 예산 초과 — 오늘 파이프라인 중단")
        telegram_ops.notify(cfg, f"⛔ BUDGET_LIMIT_DAILY: 일 예산 ${bs['daily_limit']} 초과")
        return {"produced": 0, "reason": "budget_daily"}
    if bs["monthly_exceeded"]:
        LOG.warning("월 예산 초과 — 이번 달 파이프라인 중단")
        telegram_ops.notify(cfg, f"⛔ BUDGET_LIMIT_MONTHLY: 월 예산 ${bs['monthly_limit']} 초과")
        return {"produced": 0, "reason": "budget_monthly"}

    # ── STEP 1: 수집 ──────────────────────────────────────────
    LOG.info("STEP 1: 수집 시작")
    if dry_run:
        LOG.info("[dry-run] STEP 1 완료")
        return {"produced": 0, "reason": "dry_run"}

    site_mgr = SiteManager(cfg)
    active_sites = site_mgr.get_active_sites()
    items = []
    if active_sites:
        for site in active_sites:
            collector = get_collector(site.get("site_type", "policy"))
            collected = collector.collect(cfg, site=site)
            items.extend(collected)
            LOG.info(f"사이트 '{site.get('site_name')}' ({site.get('site_type')}): {len(collected)}건")
    else:
        LOG.info("등록된 사이트 없음 — 기본 RSS 수집 fallback")
        items = rss_collector.collect(cfg)

    if not items:
        LOG.info("수집된 항목 없음 — 종료")
        return {"produced": 0, "reason": "no_items"}
    LOG.info(f"STEP 1 완료: 총 {len(items)}건 수집 / 목표 {target}건 생산")

    # 공통 컨텍스트 (한 번만 로드)
    existing_titles = sheet_sync.get_recent_titles(cfg, 30)
    recent_titles   = history_loader.load_recent_titles(cfg, 30)

    stats = {"produced": 0, "processed": 0, "dup": 0, "failed": 0, "no_wp": 0, "reason": "ok"}
    for idx, item in enumerate(items, 1):
        if stats["produced"] >= target:
            break
        # 매 항목 전 예산 재확인 (즉시 중단)
        bs = budget.check_budget()
        if bs["daily_exceeded"] or bs["monthly_exceeded"]:
            LOG.warning("처리 중 예산 초과 감지 — 남은 항목 중단 (생산 %d/%d)",
                        stats["produced"], target)
            telegram_ops.notify(cfg, "⛔ BUDGET_LIMIT: 처리 중 예산 초과 — 중단")
            stats["reason"] = "budget_midrun"
            break
        stats["processed"] += 1
        LOG.info("──[%d/%d] 항목 처리 (생산 %d/%d)──", idx, len(items),
                 stats["produced"], target)
        status = _process_one(item, cfg, budget, site_mgr, existing_titles, recent_titles)
        if status in ("published", "skipped_no_wp"):
            stats["produced"] += 1
            if status == "skipped_no_wp":
                stats["no_wp"] += 1
        elif status == "dup":
            stats["dup"] += 1
        else:
            stats["failed"] += 1

    elapsed = round(time.time() - start_time, 1)
    LOG.info("✅ 실행 종료: 목표 %d / 생산 %d (발행 %d, WP대기 %d) / 처리 %d / 중복 %d / 실패 %d / %s초",
             target, stats["produced"], stats["produced"] - stats["no_wp"], stats["no_wp"],
             stats["processed"], stats["dup"], stats["failed"], elapsed)
    return stats


def _process_one(item: dict, cfg: dict, budget, site_mgr,
                 existing_titles: list, recent_titles: list) -> str:
    """단일 항목 STEP 2~12. 반환: 'published'|'skipped_no_wp'|'dup'|'failed'.

    비용은 단계별 실제 모델로 기록(_accrue→flush)하며, 실패해도 그때까지의
    토큰 비용을 기록한다(task: 비용 정확도).
    """
    costs: dict = {}   # model -> tokens (단계별 정확 기록용)
    def _accrue(model, tokens):
        if tokens:
            costs[model] = costs.get(model, 0) + int(tokens)

    post_id = ""
    log_entry = {
        "로그ID": str(uuid.uuid4())[:8],
        "실행일시": datetime.now().isoformat(),
        "마스터ID": "", "대상 정책명": "", "가동 결과": "오류",
        "실패 모듈명": "", "오류 원인 내용": "", "발행 URL (성공 시)": "",
        "총 소요시간(초)": "", "사용 토큰 합계": "",
    }
    t0 = time.time()
    try:
        # ── STEP 2: 표준화 ──
        clean = cleaner.clean_rss_item(item, cfg)
        _accrue(cfg.get("MODEL_CLEANER"), clean.pop("_tokens", 0))
        clean["source_type"] = item.get("source_type", "policy")
        clean["site_id"] = item.get("site_id", "")
        LOG.info("STEP 2 완료: %s", clean.get("clean_policy_name"))

        # ── STEP 3: 1차 유사도 ──
        doc_for_check = f"{clean.get('clean_policy_name')} {clean.get('clean_summary','')}"
        is_dup, sim = dup_checker.check_duplicate(doc_for_check, existing_titles, cfg)
        if is_dup:
            LOG.info("STEP 3 차단: 유사도=%.3f → 보류", sim)
            sheet_sync.append_row(cfg, {
                "상태값": "보류", "정책명": clean.get("clean_policy_name"),
                "유사문서 위험도": sim, "발행일시": datetime.now().isoformat(),
            })
            _flush_costs(budget, costs)
            return "dup"
        LOG.info("STEP 3 통과: 유사도=%.3f", sim)

        # ── 사이트 AI 프로필 ──
        site_id  = clean.get("site_id", "")
        site_cfg = site_mgr.get_by_id(site_id) if site_id else None
        if site_cfg:
            LOG.info("사이트 AI 프로필 — research=%s writing=%s review=%s",
                     site_cfg.get("research_ai"), site_cfg.get("writing_ai"),
                     site_cfg.get("review_ai"))

        # ── STEP 5: M0 전략 ──
        strategy = strategist.design_strategy(clean, 70.0, recent_titles, cfg, site_cfg=site_cfg)
        _accrue(cfg.get("MODEL_ORCHESTRATOR"), strategy.pop("_tokens", 0))
        LOG.info("STEP 5 완료: final_score=%s", strategy.get("final_score"))

        # ── STEP 6: M1 SEO ──
        seo = planner.plan_seo(clean, strategy, recent_titles, cfg, site_cfg=site_cfg)
        _accrue(cfg.get("MODEL_PLANNER"), seo.pop("_tokens", 0))
        is_dup2, sim2 = dup_checker.check_duplicate(seo.get("seo_title", ""), existing_titles, cfg)
        if is_dup2:
            LOG.info("STEP 6 SEO 제목 유사도 차단: %.3f → 보류", sim2)
            _flush_costs(budget, costs)
            return "dup"
        LOG.info("STEP 6 완료: %s", seo.get("seo_title"))

        # ── STEP 7: M3 Writer ──
        draft_html, tok7 = writer.write_draft(clean, seo, strategy, [None, None, None],
                                              cfg, site_cfg=site_cfg)
        _accrue(cfg.get("MODEL_WRITER"), tok7)
        LOG.info("STEP 7 완료")

        # ── STEP 8: M4 Review ──
        edited_raw, tok8 = editor.edit(draft_html, cfg, LOG, site_cfg=site_cfg)
        _accrue(cfg.get("MODEL_EDITOR"), tok8)
        LOG.info("STEP 8 완료")

        # ── STEP 9: 파싱 ──
        final_html = cleaner.parse_html_body(edited_raw)

        # ── STEP 10: 이미지 ──
        post_id = datetime.now().strftime("%Y%m%d%H%M%S")
        image_urls = image_generator.generate(post_id, seo, cfg)

        # ── STEP 11: 발행 (사이트별 WP override) ──
        pub_cfg = dict(cfg)
        if site_id:
            wp_override = site_mgr.get_wp_config(site_id)
            if wp_override.get("WORDPRESS_URL"):
                pub_cfg.update(wp_override)
                LOG.info("사이트 '%s' WP 설정 적용", site_id)
        pub_result = publisher.publish(post_id, seo, final_html, image_urls, pub_cfg)
        pub_status = pub_result.get("status", "published")
        pub_url = pub_result.get("wordpress", "")
        wp_post_id   = pub_result.get("wp_post_id", "")
        wp_permalink = pub_result.get("wp_permalink", "")
        wp_status    = pub_result.get("wp_status", "")
        published_at = pub_result.get("published_at", "")
        LOG.info("STEP 11 완료: %s", pub_status)

        # ── STEP 12: DB/로그 ──
        article_status = "발행완료" if pub_status == "published" else "검수대기"
        # sheet_sync.append_row(무ID)와 동작 동일(=repo.save)이나, 신규 행 ID를 확보해
        # wp 메타 저장 + history("publish") 기록에 사용하기 위해 repo를 직접 사용.
        from repositories.article_repository import ArticleRepository
        from adapters.db.factory import get_db_adapter
        _art_repo = ArticleRepository(get_db_adapter(cfg))
        article_id = _art_repo.save({
            "상태값": article_status,
            "정책명": clean.get("clean_policy_name"),
            "최종추천제목": seo.get("seo_title"),
            "메인 키워드": seo.get("main_keyword"),
            "메타설명": seo.get("meta_description"),
            "태그": ", ".join(seo.get("tags_list", [])),
            "발행 URL": pub_url,
            "발행일시": datetime.now().isoformat(),
            "원본출처": clean.get("source_url"),
            "wp_post_id": wp_post_id,
            "wp_permalink": wp_permalink,
            "wp_status": wp_status,
            "published_at": published_at,
        })
        # history "publish" 이벤트 기록(발행 흐름 무영향 — 실패해도 무시)
        try:
            _art_repo.append_history(article_id, "publish", {"wp_post_id": wp_post_id})
        except Exception as e:
            LOG.warning("history(publish) 기록 실패(무시): %s", e)
        _flush_costs(budget, costs)

        # 같은 실행 내 중복 방지 (메모리 갱신)
        if seo.get("seo_title"):
            existing_titles.append(seo.get("seo_title"))

        total_tokens = sum(costs.values())
        log_entry.update({
            "마스터ID": post_id,
            "대상 정책명": clean.get("clean_policy_name"),
            "가동 결과": "성공" if pub_status == "published" else "성공(WP대기)",
            "발행 URL (성공 시)": pub_url,
            "총 소요시간(초)": round(time.time() - t0, 1),
            "사용 토큰 합계": total_tokens,
        })
        sheet_sync.append_log(cfg, log_entry)
        LOG.info("항목 완료: %s (%s, %d토큰)",
                 clean.get("clean_policy_name"), pub_status, total_tokens)
        return "published" if pub_status == "published" else "skipped_no_wp"

    except Exception as e:
        # 실패해도 그때까지 쓴 토큰 비용은 기록
        _flush_costs(budget, costs)
        log_entry.update({
            "실패 모듈명": type(e).__name__,
            "오류 원인 내용": str(e)[:500],
            "마스터ID": post_id,
            "사용 토큰 합계": sum(costs.values()),
            "총 소요시간(초)": round(time.time() - t0, 1),
        })
        try:
            sheet_sync.append_log(cfg, log_entry)
        except Exception as log_err:
            LOG.warning("운영로그 기록 실패(원 오류 처리 중): %s", log_err)
        telegram_ops.notify(cfg, f"❌ 항목 처리 오류: {e}")
        LOG.error("항목 처리 오류: %s", e, exc_info=True)
        _check_dlq(post_id, cfg)
        return "failed"


def _flush_costs(budget, costs: dict):
    """단계별로 모은 (모델→토큰)을 실제 모델 단가로 기록."""
    for model, tokens in costs.items():
        if model and tokens:
            try:
                budget.record(model, tokens)
            except Exception as e:
                LOG.warning("비용 기록 실패(model=%s): %s", model, e)
    costs.clear()

def _check_dlq(post_id: str, cfg: dict):
    if not post_id:
        return
    dlq_file = DLQ_DIR / f"{post_id}.json"
    failures = []
    if dlq_file.exists():
        with open(dlq_file, encoding="utf-8") as f:
            failures = json.load(f)
    failures.append(datetime.now().isoformat())
    with open(dlq_file, "w", encoding="utf-8") as f:
        json.dump(failures, f)
    threshold = cfg.get("DLQ_THRESHOLD", 3)
    if len(failures) >= threshold:
        telegram_ops.notify(cfg, f"⚠️ DLQ_MOVED: ID={post_id} 발행실패 {len(failures)}회 → 재처리대기")
        LOG.warning(f"DLQ: {post_id} 재처리대기 이동")

# ─────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    # 설정 로드
    if args.instance:
        cfg_path = BASE / "config" / "instances" / args.instance / "config.yaml"
    else:
        cfg_path = BASE / "config" / "config.yaml"
    try:
        cfg = load_config(str(cfg_path))
    except ConfigError as e:
        print(f"[ConfigError] {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"[오류] config.yaml 파일을 찾을 수 없습니다: {cfg_path}")
        sys.exit(1)

    # 프로젝트 루트 주입 (backup/score_weights/secrets 경로 기준)
    cfg["_root"] = str(BASE)
    cfg["_instance_id"] = args.instance or "default"

    LOG.info(f"블로그자동화 v12 시작 | instance={args.instance or 'default'} | dry-run={args.dry_run}")

    # 헬스체크
    LOG.info("헬스체크 실행...")
    hc = health_check.run(cfg)
    if not health_check.critical_passed(hc):
        failed = [k for k, v in hc.items() if isinstance(v, dict) and v.get("status") == "FAIL" and v.get("level") == "CRITICAL"]
        LOG.error(f"헬스체크 CRITICAL 실패: {failed} → 중단")
        telegram_ops.notify(cfg, f"⛔ HEALTH_CHECK_FAILED: {failed}")
        sys.exit(1)
    LOG.info("헬스체크 통과")

    if args.dry_run and not args.rewrite:
        LOG.info("[dry-run] 설정 검증 완료. 실제 실행 없이 종료.")
        return

    if args.strategy_room:
        from modules.strategy_room import run_strategy_room
        LOG.info("전략회의실 즉시 실행")
        result = run_strategy_room({}, cfg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.seed_calculators:
        from modules.calculator_seed import seed_all
        LOG.info("CalcMate 초기 계산기/템플릿 시드 등록")
        print(json.dumps(seed_all(cfg), ensure_ascii=False))
        return

    if args.calculator_id:
        from modules.calculator_pipeline import run_calculator_once
        LOG.info("QA MODE: Target Calculator: %s | Intent: %s | Duplicate Draft: %s | Skip Quality Gate: %s", args.calculator_id, args.intent, args.allow_duplicate_draft, args.skip_quality_gate)
        
        # cfg에 intent 추가
        cfg["intent"] = args.intent
        
        res = run_calculator_once(cfg, only_cid=args.calculator_id, allow_duplicate=args.allow_duplicate_draft, skip_quality=args.skip_quality_gate)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if args.reevaluate_hold:
        from modules.calculator_pipeline import reevaluate_holds
        LOG.info("품질보류 재평가%s%s", " + 즉시 재생성(--apply)" if args.apply else "(리포트)",
                 f" [slug={args.only_slug}]" if args.only_slug else "")
        res = reevaluate_holds(cfg, apply=args.apply, only_slug=args.only_slug)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if args.detect_revisions:
        from modules.revision_detector import detect_revisions
        LOG.info("법령 변경 감지(Detect Only) 실행")
        res = detect_revisions(cfg)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    if args.rewrite:
        # P2-3 자동 리라이트 — CLI 명시적 실행 전용. 스케줄러 자동 연결 없음.
        # --dry-run: 후보 목록만 출력하고 실제 rewrite 미실행 (WP 갱신 없음).
        # --only-slug: 특정 계산기(slug)만 대상으로 한정.
        from modules.rewrite_pipeline import collect_rewrite_candidates, run_calculator_rewrite
        from repositories.article_repository import ArticleRepository
        from repositories.calculator_repository import CalculatorRepository
        from adapters.db.factory import get_db_adapter

        LOG.info("P2-3 리라이트 파이프라인 — dry-run=%s only-slug=%s",
                 args.dry_run, args.only_slug or "all")

        candidates = collect_rewrite_candidates(cfg)

        if args.only_slug:
            calc_repo = CalculatorRepository(get_db_adapter(cfg))
            target_calc = next(
                (c for c in calc_repo.get_all()
                 if str(c.get("slug", "")) == args.only_slug),
                None,
            )
            if target_calc:
                candidates = [c for c in candidates
                              if c["calculator_id"] == str(target_calc.get("id", ""))]
            else:
                LOG.warning("[rewrite] --only-slug %r 에 해당하는 계산기 없음", args.only_slug)
                candidates = []

        print(f"[rewrite] 후보 {len(candidates)}건")
        for i, c in enumerate(candidates):
            r = c["reason"]
            print(
                f"  [{i+1}] article_id={c['article_id']}\n"
                f"       calculator_id={c['calculator_id']} | slug={c.get('slug', '')}\n"
                f"       wp_post_id={c['wp_post_id']}\n"
                f"       trigger={r['type']} | source={r.get('source', '')} "
                f"| severity={r['severity']} | priority_rank={c['severity_rank']}\n"
                f"       detected_at={r.get('detected_at', '')} "
                f"| affected_fields={r.get('affected_fields', [])}\n"
                f"       [DRY-RUN: 실제 rewrite/WP 갱신 없음]"
            )

        if args.dry_run:
            print("[rewrite] --dry-run: 후보 확인 완료. 실제 rewrite/WordPress 갱신 없음.")
            return

        art_repo = ArticleRepository(get_db_adapter(cfg))
        calc_repo = CalculatorRepository(get_db_adapter(cfg))
        results = []
        for c in candidates:
            article_row = art_repo.get_by_id(c["article_id"])
            calc = calc_repo.get_by_id(c["calculator_id"])
            if not article_row or not calc:
                LOG.warning("[rewrite] 데이터 누락 SKIP: article_id=%s", c["article_id"])
                continue
            res = run_calculator_rewrite(cfg, article_row, calc, c["reason"])
            results.append(res)
            LOG.info("[rewrite] %s — article_id=%s", res["result"], c["article_id"])

        print(json.dumps({"candidates": len(candidates), "results": results},
                         ensure_ascii=False, indent=2))
        return

    # 단발 실행 (run_pipeline.bat 등 하위호환)
    if args.once:
        run_once(cfg)
        return

    # Calculator 자동 스케줄러는 제거됨(Calculator는 수동 실행/웹앱 전용).
    # Blog 예약 발행은 scripts/run_blog_scheduler.py 또는 Dashboard의 Blog Schedule 스레드로 실행한다.
    LOG.info("실행할 CLI 옵션이 지정되지 않음 — --once, --calculator-id 등을 사용하거나 Dashboard를 사용하세요.")
    return

if __name__ == "__main__":
    main()
