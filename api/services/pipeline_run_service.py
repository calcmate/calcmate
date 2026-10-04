"""api/services/pipeline_run_service.py — Dashboard Quick Action
「▶ 파이프라인 실행(전량)」 수동 실행 서비스.

STEP S12: dashboard.py의 "▶ 파이프라인 실행(전량)" 버튼(dashboard.py:472-473,
"🔧 고급 실행(수동)" expander 안)과 동일한 실행 의미를 재현한다.
main.py의 run_once(cfg)(max_count 미지정 → cfg.get("DAILY_POST_COUNT", 1))를
그대로 호출하며, 파이프라인 본체(collect→clean→strategy→SEO→write→edit→
image→publish→DB/log 11단계)를 새로 만들거나 수정하지 않는다.

중요: 이 함수는 기존 Blog Scheduler(api/services/blog_scheduler_service.py,
GET/POST /api/scheduler/blog/*)와는 **다른 함수**를 호출한다. Blog Scheduler는
main.resolve_blog_publish_fn(cfg)가 반환하는 modules.blog_scheduler_adapter의
run_blog_once/run_blog_once_wp를 쓰지만(articles DB에 기록하지 않는 경량 버전),
이 Quick Action은 main.py의 원본 run_once(cfg)를 그대로 쓴다(articles DB에
기록하는 무거운 버전) — 이름이 비슷해도 실행 경로가 다르므로 절대 서로
대체하지 않는다.

중복 실행 방지: main.run_once()에는 락이 없다. modules/scheduler.py의 기존
파일 lock(_acquire_lock/_release_lock)을 "blog" scheduler_line으로 재사용한다
— 이는 blog-scheduler-loop 스레드 및 기존 /api/scheduler/blog/run-once와
동일한 lock 파일(data/schedule/blog/scheduler.lock)이다. 함수 자체는 다르지만
둘 다 같은 blog 도메인 자원(articles DB/WordPress)에 쓰기 때문에, 이 lock을
공유해 서로 겹쳐 실행되지 않도록 막는다 — 새 in-memory lock을 만들지 않는다.
"""
from modules.config_loader import load_config
import modules.scheduler as scheduler_engine
import main as PIPE


class PipelineRunBusy(Exception):
    """다른 파이프라인 실행(Blog Scheduler 또는 다른 수동 실행)이 이미 lock을 보유 중."""


def _cfg() -> dict:
    cfg = dict(load_config())
    cfg["scheduler_line"] = "blog"
    return cfg


def run_once() -> dict:
    """반환: main.py의 run_once(cfg)의 결과 dict 그대로(가공하지 않음) —
    {"produced", "processed", "dup", "failed", "no_wp", "reason"}.
    lock 획득 실패 시 PipelineRunBusy를 던진다(라우터에서 명확한 실패 응답으로
    변환)."""
    cfg = _cfg()
    if not scheduler_engine._acquire_lock(cfg):
        raise PipelineRunBusy(
            "다른 파이프라인 실행이 진행 중입니다(Blog Scheduler 또는 다른 실행). 잠시 후 재시도하세요.")
    try:
        return PIPE.run_once(cfg)
    finally:
        scheduler_engine._release_lock(cfg)


def run_one() -> dict:
    """CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02: dashboard.py "📝 글 생성(1건)"
    (PIPE.run_once(cfg, max_count=1), "🔧 고급 실행(수동)" expander 안) 이관.
    run_once()와 같은 cfg(WP 대상 미지정 = dashboard.py load_cfg()와 동일)와 같은
    blog lock을 쓰고, max_count=1만 다르다 — DAILY_POST_COUNT를 쓰지 않는다.
    BLOG_SCHEDULE.enabled와 무관하다(Blog Scheduler의 "지금 실행"과 다른 기능).
    반환값/예외는 run_once()와 동일."""
    cfg = _cfg()
    if not scheduler_engine._acquire_lock(cfg):
        raise PipelineRunBusy(
            "다른 파이프라인 실행이 진행 중입니다(Blog Scheduler 또는 다른 실행). 잠시 후 재시도하세요.")
    try:
        return PIPE.run_once(cfg, max_count=1)
    finally:
        scheduler_engine._release_lock(cfg)
