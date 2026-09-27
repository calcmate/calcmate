# -*- coding: utf-8 -*-
"""
modules/publishing_planner.py — Publishing Planner
(CALCMATE-AUTO-CONTENT-PUBLISHING-POLICY-IMPLEMENT-01)

PUBLISHING-POLICY-PLANNER-READONLY-AUDIT-01에서 확정한 계약을 구현한다.

책임 경계(감사 STEP11/16 결론 그대로):
    Publishing Policy 읽기(modules/publishing_policy.py, 재사용)
      -> 현재 pending reservation 확인(modules/scheduler.py::load_oneoff, 재사용)
      -> 사용 가능한 요일/range 계산(이 모듈의 신규 로직)
      -> approved Topic 선택(modules/topic_pool.py::list_topics, 재사용)
      -> slot 생성(이 모듈의 신규 로직)
      -> 예약 생성(modules/scheduler.py::add_oneoff_reservation, 재사용 — GAP3에서
         이미 추가된 topic_id= 파라미터를 그대로 사용, scheduler.py 무수정)
      -> Topic에 reservation id 기록 + approved -> scheduled
         (modules/topic_pool.py::update_topic/transition_status, 재사용)

이 모듈은 WordPress를 직접 호출하지 않는다(발행은 기존 One-off Scheduler ->
modules/topic_publish_adapter.py 경로를 그대로 사용). FINAL DUP CHECK는 예약
"낭비 방지" 목적으로 예약 생성 직전에 1회 수행하며(_check_wp_duplicate 재사용),
실제 발행 직전의 race-protection 목적 FINAL DUP CHECK(topic_publish_adapter.py)는
이 모듈이 대체하지 않는다 — 감사 STEP17 결론대로 두 위치 모두 유지한다.

Scheduler의 기존 lock/dedup/atomic-write/topic_id 전달 로직은 이 모듈에서
전혀 수정하지 않으며, run_planner_once() 자체는 여전히 무한 loop를 갖지
않는다 — 1회 호출 = 1회 실행(감사 STEP15/19 결론 그대로 무변경).

CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-EXECUTION-DECOUPLING-B-IMPLEMENT-01:
run_planner_once() 위에 재사용 가능한 자동 polling loop(run_planner_loop())를
추가한다. 이 loop는 AUTO_PUBLISHING.enabled 여부만 매 tick 확인해
run_planner_once()를 호출할지 결정할 뿐, scheduling/priority/pending cap/
duplicate check/Topic 상태 변경 등 어떤 로직도 다시 구현하지 않는다(그 책임은
전부 run_planner_once()에 있음, A 단계와 동일한 "얇은 wrapper" 원칙). Dashboard
thread 기동/수동 실행 버튼은 이 STEP의 범위가 아니다(다음 C 단계).
"""
import time
from datetime import datetime, timedelta

from modules import publishing_policy
from modules import scheduler
from modules import topic_pool
from modules.logger import get_logger

LOG = get_logger()

KST = scheduler.KST
_LOOKAHEAD_DAYS = 14
_MAX_RETRY_PER_RANGE = 20


def _default_dup_check_fn(cfg, slug):
    # SINGLE-OWNER-HARDENING S2: 기존 draft까지 보는 Topic 전용 helper 재사용.
    from modules.topic_publish_adapter import check_topic_wp_duplicate
    return check_topic_wp_duplicate(cfg, slug)


def _resolve_mode(cfg: dict) -> str:
    """draft/publish 모드는 이 STEP의 Publishing Policy SSOT에 포함되지 않는다
    (감사 대상 스키마에 명시적으로 없음). 기존 BLOG_SCHEDULE.mode(신규 키 추가
    없음, 이미 존재하는 설정 재사용)를 그대로 따르며, 없거나 잘못된 값이면
    안전한 기본값 "draft"로 처리한다."""
    mode = str((cfg.get("BLOG_SCHEDULE") or {}).get("mode") or "draft").strip().lower()
    return mode if mode in scheduler.ONEOFF_MODES else "draft"


def _topic_dates_used(pending_entries: list, target_date, tz=KST) -> int:
    """target_date(해당 timezone 기준)에 이미 배정된(topic_id가 있는) pending
    예약 수를 센다 — 요일별 count 예산을 "이 날짜에 이미 몇 건이나 배정됐는지"로
    추적하는 근사치다(개별 time_range를 소모했는지 자체를 별도로 추적하는 필드가
    없으므로, 날짜 단위 총 개수를 요일 count의 상한으로 사용한다 — 이 모듈의
    설계 판단, PUBLISHING-POLICY-IMPLEMENT-01 STEP16 문서화)."""
    n = 0
    for e in pending_entries:
        if not e.get("topic_id"):
            continue
        try:
            dt = datetime.fromisoformat(e["scheduled_at"])
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        if dt.astimezone(tz).date() == target_date:
            n += 1
    return n


def find_next_available_slot(cfg: dict, policy: dict, now: datetime,
                              pending_entries: list, locally_claimed: set,
                              mode: str, rng=None):
    """정책/현재 pending 예약/이번 run에서 이미 배정된 slot을 감안해 다음으로
    사용 가능한 절대 datetime 1개를 반환한다. 찾지 못하면 None(호출자가
    "no_available_slot"으로 처리).

    _abs_time_key()가 naive datetime을 내부적으로 KST로 간주해 처리하므로
    (modules/scheduler.py의 기존 동작 그대로), 여기서 별도로 tzinfo를
    선처리하지 않는다."""
    pending_keys = {(scheduler._abs_time_key(datetime.fromisoformat(e["scheduled_at"])),
                      e.get("mode"))
                     for e in pending_entries}

    today = now.astimezone(KST).date()
    for day_offset in range(_LOOKAHEAD_DAYS):
        d = today + timedelta(days=day_offset)
        day_key = publishing_policy.weekday_key_for_date(d)
        day_policy = policy["weekdays"][day_key]
        count = day_policy["count"]
        if count == 0:
            continue

        used = _topic_dates_used(pending_entries, d) + \
            sum(1 for k in locally_claimed if k[1] == d.isoformat())
        if used >= count:
            continue

        for time_range in day_policy["time_ranges"]:
            for _attempt in range(_MAX_RETRY_PER_RANGE):
                hhmm = publishing_policy.generate_random_time_in_range(time_range, rng=rng)
                h, m = int(hhmm[:2]), int(hhmm[3:])
                candidate = datetime(d.year, d.month, d.day, h, m, tzinfo=KST)
                if candidate <= now:
                    break  # 이 range는 오늘 이미 지난 시간대 — 다음 range로
                abs_key = scheduler._abs_time_key(candidate)
                if (abs_key, mode) in pending_keys:
                    continue  # 재시도(다른 분으로 다시 랜덤)
                if (abs_key, d.isoformat()) in locally_claimed:
                    continue
                return candidate
        # 이 날짜의 모든 range가 과거이거나 충돌 — 다음 날짜로
    return None


def run_planner_once(cfg: dict, *, now: datetime = None, rng=None,
                      dup_check_fn=None) -> dict:
    """Publishing Planner 1회 실행. 자동 실행 루프와 Dashboard 수동 "[지금 실행]"
    양쪽에서 동일하게 재사용된다 — 이 함수 자체는 loop를 갖지 않는다.

    Publishing Policy가 유효하지 않으면(fail-closed) 예약을 전혀 만들지 않고
    reason="invalid_policy"로 즉시 반환한다.

    Returns:
        {"scheduled": int, "reason": str, "results": [dict]}
    """
    now = now or datetime.now(KST)
    dup_check_fn = dup_check_fn or _default_dup_check_fn

    try:
        policy = publishing_policy.load_policy(cfg)
    except ValueError as e:
        return {"scheduled": 0, "reason": f"invalid_policy: {e}", "results": []}

    mode = _resolve_mode(cfg)

    all_reservations = scheduler.load_oneoff(cfg)
    pending_entries = [e for e in all_reservations if e.get("status") == "pending"]

    capacity = policy["max_pending_reservations"] - len(pending_entries)
    if capacity <= 0:
        return {"scheduled": 0, "reason": "max_pending_reservations_reached", "results": []}

    candidates = topic_pool.list_topics(cfg, status="approved")
    if not candidates:
        return {"scheduled": 0, "reason": "no_approved_topics", "results": []}

    results = []
    scheduled_count = 0
    locally_claimed = set()  # {(abs_time_key, date_iso)} — 이번 run 내 신규 확정 slot

    for topic in candidates:
        topic_id = topic["topic_id"]
        if scheduled_count >= capacity:
            results.append({"topic_id": topic_id, "status": "SKIPPED",
                             "reason": "max_pending_reservations_reached"})
            continue

        slot_dt = find_next_available_slot(cfg, policy, now, pending_entries,
                                            locally_claimed, mode, rng=rng)
        if slot_dt is None:
            results.append({"topic_id": topic_id, "status": "SKIPPED",
                             "reason": "no_available_slot"})
            continue

        try:
            dup = dup_check_fn(cfg, topic["slug"])
        except Exception as e:
            results.append({"topic_id": topic_id, "status": "ERROR",
                             "reason": f"duplicate_check_error:{e}"[:300]})
            continue

        if not dup.get("confirmed"):
            topic_pool.record_failure(cfg, topic_id, "schedule_failed",
                                       dup.get("error") or "duplicate_check_failed")
            results.append({"topic_id": topic_id, "status": "SCHEDULE_FAILED",
                             "reason": "duplicate_check_failed"})
            continue
        if dup.get("exists"):
            topic_pool.record_failure(cfg, topic_id, "schedule_failed",
                                       "wp_duplicate_exists")
            results.append({"topic_id": topic_id, "status": "SCHEDULE_FAILED",
                             "reason": "wp_duplicate_exists"})
            continue

        entry = scheduler.add_oneoff_reservation(cfg, slot_dt, mode, topic_id=topic_id)
        if entry.get("duplicate"):
            results.append({"topic_id": topic_id, "status": "SKIPPED",
                             "reason": "slot_collision"})
            continue

        locally_claimed.add((scheduler._abs_time_key(slot_dt), slot_dt.date().isoformat()))

        try:
            topic_pool.update_topic(cfg, topic_id, oneoff_reservation_id=entry["id"])
            topic_pool.transition_status(cfg, topic_id, "scheduled",
                                          actor="publishing_planner",
                                          reason="oneoff_reservation_created")
        except Exception as e:
            results.append({"topic_id": topic_id, "status": "ERROR",
                             "reason": f"post_reservation_sync_error:{e}"[:300],
                             "reservation_id": entry["id"]})
            continue

        scheduled_count += 1
        results.append({"topic_id": topic_id, "status": "SCHEDULED",
                         "reservation_id": entry["id"], "scheduled_at": slot_dt.isoformat()})

    return {
        "scheduled": scheduled_count,
        "reason": "" if scheduled_count else "no_slot_scheduled",
        "results": results,
    }


def _auto_publishing_config_path(cfg: dict):
    """cfg가 로드된 config.yaml 경로를 재구성한다. modules/scheduler.py::
    _blog_schedule_config_path()/modules/content_sync.py::
    _content_sync_config_path()와 동일한 목적이며, 이 모듈이 이미 따르는
    "_root만 사용"(scheduler.py의 더 단순한 관례, _instance_id 없음)을
    그대로 따른다(scheduler.py 자체는 이번 STEP에서 수정하지 않으므로 그
    헬퍼를 import해서 재사용하지 않고, 동일한 경로 규칙만 이 모듈 안에 복제)."""
    from pathlib import Path
    root = Path(cfg.get("_root", "."))
    return root / "config" / "config.yaml"


def _auto_publishing_enabled_now(cfg: dict, fallback: bool) -> bool:
    """Planner 자동 loop tick마다 config.yaml의 AUTO_PUBLISHING.enabled만
    다시 읽는다(modules/content_sync.py::_content_sync_enabled_now()와 동일한
    "가벼운 최소 재로딩" 패턴 재사용 — CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-
    EXECUTION-DECOUPLING-B-IMPLEMENT-01).

    content_sync 원본과의 의도적인 차이(Test E 요구사항): 원본은 재로딩
    실패(파일 없음/파싱 오류) 시 기존에 알던 값(fallback)을 그대로 유지해
    "오동작(무한 실행 또는 무한 중단) 방지"를 우선했다. 이 함수는 반대로
    **재로딩 자체가 실패하면 무조건 False(자동 실행 안 함)로 fail-closed
    처리한다** — "AUTO_PUBLISHING 상태를 확정할 수 없으면 자동 Planner를
    실행하지 않는다"는 이번 STEP의 명시적 요구사항 때문이다. 파일이 정상
    읽히고 파싱도 되지만 AUTO_PUBLISHING 키/enabled 키가 없는 "정상적인
    누락" 상황에서만 fallback을 사용한다(이 부분은 content_sync와 동일)."""
    import yaml
    path = _auto_publishing_config_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return False  # fail-closed: 재로딩 실패 시 항상 OFF로 취급(content_sync와 다름, 의도적)
    ap = raw.get("AUTO_PUBLISHING", {}) or {}
    return bool(ap.get("enabled", fallback))


def run_planner_loop(cfg: dict, poll_seconds: int = 300, *, now: datetime = None,
                      rng=None, dup_check_fn=None) -> None:
    """AUTO_PUBLISHING.enabled 기반 Topic Planner 자동 polling loop.

    매 tick마다 AUTO_PUBLISHING.enabled를 config.yaml에서 다시 읽어(위
    _auto_publishing_enabled_now()) 확인하고, 켜져 있을 때만 정확히 1회
    run_planner_once(cfg, now=now, rng=rng, dup_check_fn=dup_check_fn)를
    호출한다. scheduling/priority/pending cap/duplicate check/Topic 상태
    변경 등 어떤 로직도 이 함수 안에서 다시 구현하지 않는다 — 전부
    run_planner_once()에 위임한다(계약 무변경).

    poll_seconds 기본값 300(5분): Blog/One-off/Calc-Webapp 스케줄러(30초)는
    "실제 발행 시각에 도달했는지"를 확인하는 실행기라 초 단위 정밀도가
    필요하지만, Planner는 예약을 미리(최대 14일 lookahead) 만들어두는
    생성기일 뿐이라 그 정밀도가 불필요하다. Content Sync(60초 poll, 실제
    작업은 하루 1회)보다도 더 느슨해도 되는 이유는, Content Sync는 "정확한
    실행 시각(03:00)"을 60초 이내 오차로 잡아야 하지만 Planner는 "새로
    approved된 topic이 언젠가 스케줄된다"는 정도의 지연만 허용하면 되기
    때문이다. 너무 짧으면(예: 30초) DB/파일을 불필요하게 반복 조회하고,
    너무 길면(예: 1시간+) 새로 승인된 topic이 오래 대기한다 — 5분은 이
    두 극단 사이의 절충값이다.

    예외 발생 시 loop 전체를 종료하지 않고 기존 scheduler.py 루프들과
    동일한 패턴(LOG.error + scheduler._alert_throttled, 새 알림 시스템
    신설 없음)으로 기록한 뒤 다음 tick을 계속한다."""
    LOG.info("Publishing Planner 자동 루프 시작 (poll=%ds)", poll_seconds)
    while True:
        try:
            enabled = _auto_publishing_enabled_now(
                cfg, bool((cfg.get("AUTO_PUBLISHING") or {}).get("enabled", False)))
            if enabled:
                result = run_planner_once(cfg, now=now, rng=rng, dup_check_fn=dup_check_fn)
                LOG.info("Publishing Planner 실행: scheduled=%s reason=%s",
                         result.get("scheduled"), result.get("reason"))
            else:
                LOG.debug("AUTO_PUBLISHING.enabled=off — 이번 tick 건너뜀")
        except Exception as e:
            LOG.error("Publishing Planner 루프 오류: %s", e, exc_info=True)
            scheduler._alert_throttled(cfg, "publishing_planner_loop", "ERROR",
                                       "Publishing Planner 루프 예외", e)
        time.sleep(poll_seconds)
