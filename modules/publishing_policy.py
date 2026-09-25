# -*- coding: utf-8 -*-
"""
modules/publishing_policy.py — Publishing Policy 계약
(CALCMATE-AUTO-CONTENT-PUBLISHING-POLICY-IMPLEMENT-01)

PUBLISHING-POLICY-PLANNER-READONLY-AUDIT-01에서 확정한 최신 SSOT를 구현한다.

    PUBLISHING_POLICY:
      timezone: "Asia/Seoul"
      weekdays:
        mon: {count: N, time_ranges: [{start, end}, ...]}   # len(time_ranges) == count 필수
        ...
      max_pending_reservations: 10

이 모듈은 순수 정책 계약(로드/검증/랜덤 시각 생성)만 담당한다. Topic Pool/
One-off Scheduler/실제 예약 생성은 modules/publishing_planner.py의 책임이며,
이 모듈은 그 어떤 DB/파일/네트워크에도 접근하지 않는다(config dict만 입력).

핵심 원칙(임의 보정 금지 — fail-closed):
  - count와 time_ranges 개수가 다르면 무조건 오류(0으로 자동 채우거나 잘라내지
    않음).
  - 이번 버전은 timezone="Asia/Seoul" 외 값을 전부 거부한다 — 기존
    modules/scheduler.py 전체가 ZoneInfo("Asia/Seoul")을 하드코딩 가정하므로
    다른 timezone을 "허용"해도 실제로 지원되지 않는다(READONLY-AUDIT-01
    Section 3/7 결론).
"""
import random
from datetime import time as dt_time

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ALLOWED_TIMEZONE = "Asia/Seoul"

_WEEKDAY_ENTRY_KEYS = {"count", "time_ranges"}
_TIME_RANGE_KEYS = {"start", "end"}
_POLICY_TOP_KEYS = {"timezone", "weekdays", "max_pending_reservations"}

DEFAULT_POLICY = {
    "timezone": "Asia/Seoul",
    "weekdays": {
        "mon": {"count": 1, "time_ranges": [{"start": "09:00", "end": "18:00"}]},
        "tue": {"count": 0, "time_ranges": []},
        "wed": {"count": 1, "time_ranges": [{"start": "09:00", "end": "18:00"}]},
        "thu": {"count": 0, "time_ranges": []},
        "fri": {"count": 1, "time_ranges": [{"start": "09:00", "end": "18:00"}]},
        "sat": {"count": 0, "time_ranges": []},
        "sun": {"count": 0, "time_ranges": []},
    },
    "max_pending_reservations": 10,
}


def _parse_hhmm(value) -> int | None:
    """"HH:MM" -> 0~1439 분. 형식/범위 오류 시 None."""
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    h_str, m_str = parts
    if not (h_str.isdigit() and m_str.isdigit()):
        return None
    if len(h_str) != 2 or len(m_str) != 2:
        return None
    h, m = int(h_str), int(m_str)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def _is_plain_int(value) -> bool:
    """bool은 int의 서브클래스이므로 True/False가 count로 통과하지 않도록 구분."""
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_time_range(rng, prefix: str) -> list:
    errors = []
    if not isinstance(rng, dict):
        return [f"{prefix}: time_range는 dict여야 합니다 (got {type(rng).__name__})"]
    extra = set(rng.keys()) - _TIME_RANGE_KEYS
    if extra:
        errors.append(f"{prefix}: 알 수 없는 키 {sorted(extra)}")
    missing = _TIME_RANGE_KEYS - set(rng.keys())
    if missing:
        errors.append(f"{prefix}: 누락된 키 {sorted(missing)}")
        return errors  # start/end 없이는 더 이상 검증 불가

    start_min = _parse_hhmm(rng.get("start"))
    end_min = _parse_hhmm(rng.get("end"))
    if start_min is None:
        errors.append(f"{prefix}: start 형식/범위 오류 — {rng.get('start')!r} "
                       f"(HH:MM, 00~23:00~59 이어야 함)")
    if end_min is None:
        errors.append(f"{prefix}: end 형식/범위 오류 — {rng.get('end')!r} "
                       f"(HH:MM, 00~23:00~59 이어야 함)")
    if start_min is not None and end_min is not None and start_min > end_min:
        errors.append(f"{prefix}: start({rng['start']}) > end({rng['end']}) — "
                       f"자정 넘김 범위는 허용하지 않습니다")
    return errors


def _validate_weekday_entry(entry, day_key: str) -> list:
    errors = []
    prefix = f"weekdays.{day_key}"
    if not isinstance(entry, dict):
        return [f"{prefix}: dict여야 합니다 (got {type(entry).__name__})"]

    extra = set(entry.keys()) - _WEEKDAY_ENTRY_KEYS
    if extra:
        errors.append(f"{prefix}: 알 수 없는 키 {sorted(extra)}")
    missing = _WEEKDAY_ENTRY_KEYS - set(entry.keys())
    if missing:
        errors.append(f"{prefix}: 누락된 키 {sorted(missing)}")
        return errors

    count = entry.get("count")
    if not _is_plain_int(count) or count < 0:
        errors.append(f"{prefix}.count: 0 이상의 정수여야 합니다 (got {count!r})")
        count = None  # 이후 개수 비교는 건너뜀

    time_ranges = entry.get("time_ranges")
    if not isinstance(time_ranges, list):
        errors.append(f"{prefix}.time_ranges: list여야 합니다 (got {type(time_ranges).__name__})")
        return errors

    for i, rng in enumerate(time_ranges):
        errors.extend(_validate_time_range(rng, f"{prefix}.time_ranges[{i}]"))

    if count is not None and len(time_ranges) != count:
        errors.append(
            f"{prefix}: count({count})와 time_ranges 개수({len(time_ranges)})가 "
            f"일치하지 않습니다 — count=0이면 time_ranges=[]여야 하고, count=N이면 "
            f"정확히 N개의 time_range가 필요합니다"
        )
    return errors


def validate_policy(policy) -> list:
    """Publishing Policy 전체 검증 — 오류 메시지 리스트 반환(빈 리스트면 정상).
    어떤 값도 임의로 보정하지 않는다(fail-closed)."""
    errors = []
    if not isinstance(policy, dict):
        return [f"policy는 dict여야 합니다 (got {type(policy).__name__})"]

    extra = set(policy.keys()) - _POLICY_TOP_KEYS
    if extra:
        errors.append(f"알 수 없는 최상위 키: {sorted(extra)}")
    missing = _POLICY_TOP_KEYS - set(policy.keys())
    if missing:
        errors.append(f"누락된 최상위 키: {sorted(missing)}")
        return errors

    if policy.get("timezone") != ALLOWED_TIMEZONE:
        errors.append(
            f"timezone: {ALLOWED_TIMEZONE!r} 외 값은 허용되지 않습니다 "
            f"(got {policy.get('timezone')!r}) — 기존 코드 전체가 Asia/Seoul을 "
            f"가정하므로 실제로 다른 timezone을 지원하지 않습니다"
        )

    weekdays = policy.get("weekdays")
    if not isinstance(weekdays, dict):
        errors.append(f"weekdays: dict여야 합니다 (got {type(weekdays).__name__})")
    else:
        extra_days = set(weekdays.keys()) - set(WEEKDAYS)
        if extra_days:
            errors.append(f"weekdays: 알 수 없는 요일 키 {sorted(extra_days)}")
        missing_days = set(WEEKDAYS) - set(weekdays.keys())
        if missing_days:
            errors.append(f"weekdays: 누락된 요일 키 {sorted(missing_days)}")
        for day in WEEKDAYS:
            if day in weekdays:
                errors.extend(_validate_weekday_entry(weekdays[day], day))

    max_pending = policy.get("max_pending_reservations")
    if not _is_plain_int(max_pending) or max_pending <= 0:
        errors.append(
            f"max_pending_reservations: 1 이상의 정수여야 합니다 (got {max_pending!r})"
        )

    return errors


def load_policy(cfg: dict) -> dict:
    """cfg["PUBLISHING_POLICY"]를 검증 후 반환한다. 키 자체가 없으면
    DEFAULT_POLICY를 사용한다(단, DEFAULT_POLICY도 동일하게 validate_policy()를
    통과해야 하며 실제로 통과한다 — 자기 자신도 검증 대상).

    잘못된 정책은 어떤 값도 보정하지 않고 ValueError를 raise한다(fail-closed —
    Planner가 이 예외를 받으면 예약을 전혀 만들지 않아야 한다)."""
    policy = cfg.get("PUBLISHING_POLICY")
    if policy is None:
        policy = DEFAULT_POLICY
    errors = validate_policy(policy)
    if errors:
        raise ValueError(f"PUBLISHING_POLICY 검증 실패: {errors}")
    return policy


def generate_random_time_in_range(time_range: dict, rng=None) -> str:
    """time_range={"start":"HH:MM","end":"HH:MM"} 내에서 분 단위 랜덤 "HH:MM"을
    반환한다(초 단위 랜덤 없음, 양 끝 포함).

    rng: random 모듈 또는 random.Random 인스턴스(.randint(a,b) 제공). 기본값은
    표준 random 모듈(운영 시 실제 랜덤) — 테스트는 random.Random(seed)를
    주입해 결정적으로 재현한다."""
    rng = rng if rng is not None else random
    start_min = _parse_hhmm(time_range["start"])
    end_min = _parse_hhmm(time_range["end"])
    if start_min is None or end_min is None or start_min > end_min:
        raise ValueError(f"유효하지 않은 time_range: {time_range!r}")
    chosen = rng.randint(start_min, end_min)
    return f"{chosen // 60:02d}:{chosen % 60:02d}"


def weekday_key_for_date(d) -> str:
    """datetime.date/datetime -> "mon".."sun" (월요일=0 기준)."""
    return WEEKDAYS[d.weekday()]


def candidate_times_for_date(policy: dict, d, rng=None) -> list:
    """해당 날짜의 요일 정책에 따라 time_ranges 각각에서 독립적으로 정확히
    1개씩 랜덤 "HH:MM"을 생성해 리스트로 반환한다(count==0이면 빈 리스트).
    반환 리스트의 길이는 항상 해당 요일의 count와 같다(load_policy()를 거친
    정책이라면 count==len(time_ranges)가 이미 보장됨)."""
    day_key = weekday_key_for_date(d)
    entry = policy["weekdays"][day_key]
    return [generate_random_time_in_range(rng_range, rng=rng)
            for rng_range in entry["time_ranges"]]
