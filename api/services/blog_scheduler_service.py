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
    # run_once()가 이 cfg로 WP에 쓰므로 production WordPress를 명시한다
    # (target 없는 load_config()는 로컬 WORDPRESS_URL=salarymate.test를 가리킨다).
    cfg = dict(load_config(wp_target="production"))
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


def create_oneoff_reservation(scheduled_at: str, mode: str, topic_id: str | None = None) -> dict:
    """1회성 예약 1건을 추가한다(CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01).

    scheduler_engine.add_oneoff_reservation()에 그대로 위임하는 thin wrapper다 —
    timezone/mode 검증, lock, 중복 방지(duplicate), reservation schema는 전부 그
    함수 책임이며 여기서 재구현하지 않는다. dashboard.py의 "1회성 예약 추가" 버튼과
    동일한 _blog_cfg()(scheduler_line="blog")를 사용해 FastAPI Worker가 실제로
    소비하는 data/schedule/blog/oneoff_schedule.json에 그대로 저장되도록 한다.

    scheduled_at은 ISO 8601 문자열이어야 하며 timezone 오프셋을 포함해야 한다
    (naive면 add_oneoff_reservation()이 ValueError를 낸다 — 그대로 전달).

    CALCMATE-DIRECT-RESERVATION-IMPLEMENT-01: topic_id가 주어지면 예약 생성 전에
    Topic이 존재하고 status=="approved"인지 확인하고(아니면 ValueError — 기존
    add_oneoff_reservation()의 예외 계약과 동일하게 router가 그대로 VALIDATION_ERROR로
    매핑하므로 router는 수정하지 않음), 예약이 실제로 새로 생성된 경우(duplicate가
    아닌 경우)에만 Topic을 approved→scheduled로 전이하고 oneoff_reservation_id를
    연결한다. topic_id=None이면 이 블록 전체를 실행하지 않아 Golden10 계약을
    그대로 보존한다. add_oneoff_reservation() 자체와 transition_status()/
    update_topic()은 수정하지 않고 기존 함수를 그대로 재사용한다 — 전이 실패 시
    별도 rollback을 수행하지 않는다(reservation은 pending, Topic은 approved로
    남아 Worker가 나중에 기존 fail-closed 경로로 자연스럽게 처리한다)."""
    from datetime import datetime as _dt
    try:
        scheduled_dt = _dt.fromisoformat(scheduled_at)
    except (TypeError, ValueError) as e:
        raise ValueError(f"scheduled_at 형식이 올바르지 않습니다(ISO 8601 필요): {e}")

    cfg = _blog_cfg()

    if topic_id is not None:
        from modules import topic_pool
        topic = topic_pool.get_topic(cfg, topic_id)
        if topic is None:
            raise ValueError(f"topic_id={topic_id!r}를 찾을 수 없습니다")
        if topic.get("status") != "approved":
            raise ValueError(
                f"topic_id={topic_id!r}는 approved 상태가 아닙니다(현재: {topic.get('status')!r})"
            )

    entry = scheduler_engine.add_oneoff_reservation(cfg, scheduled_dt, mode, topic_id=topic_id)

    if topic_id is not None and not entry.get("duplicate"):
        from modules import topic_pool
        topic_pool.transition_status(
            cfg, topic_id, "scheduled",
            actor="direct_reservation", reason="oneoff_reservation_created",
        )
        topic_pool.update_topic(cfg, topic_id, oneoff_reservation_id=entry["id"])

    return entry


def run_once(mode: str = None) -> dict:
    """기존 lock을 사용해 Scheduler loop와의 동시 실행을 방지한 뒤,
     실행 함수를 max_count=1로 정확히 1회 호출한다.

     mode 파라미터가 주어지면 one-off 실행 경로(resolve_blog_oneoff_publish_fn)를 사용해
     BLOG_SCHEDULE.enabled와 무관하게 실행한다. mode가 없으면 기존 recurring 경로
     (resolve_blog_publish_fn)를 사용하며 BLOG_SCHEDULE.enabled 체크를 적용한다."""
    cfg = _blog_cfg()

    if mode is not None:
        mode = str(mode or "draft").strip().lower()
        if mode not in ("draft", "publish"):
            raise ValueError(f"허용되지 않는 mode: {mode!r} (허용값: draft, publish)")
        from main import resolve_blog_oneoff_publish_fn
        run_once_fn = resolve_blog_oneoff_publish_fn(cfg, mode)
    else:
        if not cfg.get("BLOG_SCHEDULE", {}).get("enabled", False):
            raise BlogSchedulerDisabled("BLOG_SCHEDULE.enabled=false")
        from main import resolve_blog_publish_fn
        run_once_fn = resolve_blog_publish_fn(cfg)

    if not scheduler_engine._acquire_lock(cfg):
        raise BlogSchedulerBusy("다른 Blog Scheduler 실행이 진행 중입니다(lock 보유 중)")
    try:
        return run_once_fn(cfg, max_count=1, driver_id="fastapi_manual_run_once")
    finally:
        scheduler_engine._release_lock(cfg)
