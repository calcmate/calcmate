"""api/services/blog_scheduler_service.py — Blog Scheduler 조회/실행 서비스 (STEP 18-E).

기존 엔진(modules.scheduler, main.resolve_blog_publish_fn, modules.blog_scheduler_adapter)을
그대로 호출한다. 스케줄링/락 로직을 새로 구현하지 않고 기존 modules.scheduler의
_acquire_lock()/_release_lock()을 그대로 재사용해 Scheduler loop(dashboard.py에서
기동되는 blog-scheduler-loop 스레드 포함)와의 동시 실행을 방지한다.
"""
import json

from modules.config_loader import load_config
import modules.scheduler as scheduler_engine
from main import resolve_blog_publish_fn


class BlogSchedulerDisabled(Exception):
    """BLOG_SCHEDULE.enabled=false 상태에서 run-once를 시도한 경우."""


class BlogSchedulerBusy(Exception):
    """다른 실행(Scheduler loop 또는 다른 run-once)이 이미 lock을 보유 중인 경우."""


def _blog_cfg() -> dict:
    """기존 config를 로드하고 blog 라인 전용으로 scheduler_line만 표시한다.
    modules/scheduler.py는 cfg["scheduler_line"]=="blog"일 때 data/schedule/blog/*를
    사용한다 — 이 표시 방식 자체가 기존 엔진의 라인 격리 메커니즘이다."""
    cfg = dict(load_config())
    cfg["scheduler_line"] = "blog"
    return cfg


def get_today_schedule() -> dict:
    cfg = _blog_cfg()
    sched = scheduler_engine.load_schedule(cfg)
    return sched or {}


def get_history(limit: int = 20) -> list:
    cfg = _blog_cfg()
    path = scheduler_engine._history_path(cfg)
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def get_oneoff_reservations() -> list:
    """1회성(one-off) 예약 목록을 그대로 반환한다(CALCMATE-DASHBOARD-ONEOFF-
    SCHEDULER-VIEW-IMPLEMENT-01). scheduler_engine.load_oneoff()가 반환하는
    reservation dict(각 항목의 id/scheduled_at/mode/status/created_at/
    executed_at/result/duplicate, Topic Pool 계열은 추가로 topic_id)를 그대로
    전달한다 — 값을 가공하거나 의미를 바꾸지 않는다(get_today_schedule()과
    동일한 얇은 wrapper 원칙). topic_id가 없는(Golden10 계열) 예약도 그대로
    포함된다(load_oneoff() 자체가 두 계열을 구분하지 않고 전부 반환)."""
    cfg = _blog_cfg()
    reservations = scheduler_engine.load_oneoff(cfg)
    return reservations or []


def run_once() -> dict:
    """기존 lock을 사용해 Scheduler loop와의 동시 실행을 방지한 뒤,
    main.resolve_blog_publish_fn(cfg)가 반환하는 실제 엔진 함수를 max_count=1로
    정확히 1회 호출한다. mode에 따라 draft(격리 출력만)/publish(WordPress 발행)로
    분기되는 것은 기존 엔진의 동작 그대로다 — 이 함수는 그 분기 로직을 재구현하지 않는다."""
    cfg = _blog_cfg()
    if not cfg.get("BLOG_SCHEDULE", {}).get("enabled", False):
        raise BlogSchedulerDisabled("BLOG_SCHEDULE.enabled=false")

    if not scheduler_engine._acquire_lock(cfg):
        raise BlogSchedulerBusy("다른 Blog Scheduler 실행이 진행 중입니다(lock 보유 중)")
    try:
        run_once_fn = resolve_blog_publish_fn(cfg)
        return run_once_fn(cfg, max_count=1, driver_id="fastapi_manual_run_once")
    finally:
        scheduler_engine._release_lock(cfg)
