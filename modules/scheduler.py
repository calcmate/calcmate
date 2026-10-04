# -*- coding: utf-8 -*-
"""
modules/scheduler.py — 글별 발행 시간 슬롯 스케줄러 (v12 신규)

운영자가 DAILY_POST_COUNT 만큼 슬롯(시작~종료 시간 범위)을 지정하면,
당일 시작 시 각 슬롯 범위 내 랜덤 시각을 1회 생성하여 하루 동안 고정한다.
현재 시각이 예약 시각에 도달하면 해당 글 1건만 발행한다.

영속: data/schedule/today_schedule.json (프로그램 재시작 후에도 유지)
이력: data/schedule/history.jsonl  (예약/실제/지연/결과 — 운영로그 확장)

config.yaml 의 PUBLISH_SCHEDULE 로 슬롯을 설정한다(대시보드에서 편집):
    PUBLISH_SCHEDULE:
      enabled: true
      failure_mode: retry_in_slot   # none | retry_in_slot | next_slot
      weekday:
        - {start: "07:00", end: "08:00"}
        - {start: "12:00", end: "13:00"}
      weekend:
        - {start: "09:00", end: "10:00"}
슬롯 미설정 시 DAILY_POST_COUNT 만큼 09~21시 사이로 균등 자동 생성.
"""
import json
import os
import random
import tempfile
import time
import uuid
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .logger import get_logger

LOG = get_logger()

KST = ZoneInfo("Asia/Seoul")

FAILURE_MODES = ("none", "retry_in_slot", "next_slot")
STATUSES = ("pending", "running", "completed", "failed", "retry")

# 재시도해도 결과가 안 바뀌는 미생산 사유(신규 후보 없음/예산 등) → 슬롯 내 재시도 무의미.
# 이런 사유는 즉시 failed 처리해 retry_in_slot 폭주(분당 재시도)를 막는다.
# (일시적 오류/예외는 여기 없음 → 기존 retry_in_slot 유지)
NON_RETRYABLE_REASONS = ("no_calculators", "후보소진", "모든후보HOLD", "no_items")

# Lock ownership token storage (for both recurring and oneoff locks)
_LOCK_OWNER_TOKENS: dict[str, dict] = {}

# owner token의 process_start_time 비교 허용 오차(초). PID 재사용 판정은
# "현재 그 PID를 가진 프로세스가 token 기록 프로세스보다 나중에 생성됨"일 때만 한다.
_PROCESS_START_TOLERANCE = 1.0

# Windows 프로세스 조회 상수 (ctypes kernel32 — Windows에서 signal 0 kill은
# CTRL_C_EVENT 전송이므로 liveness 확인에 kill 계열 호출을 사용하지 않는다)
_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_ERROR_INVALID_PARAMETER = 87
_WIN_STILL_ACTIVE = 259
_WIN_EPOCH_AS_FILETIME = 116444736000000000


def _win_kernel32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _win_creation_time(k32, handle) -> float | None:
    """프로세스 handle의 생성 시각(epoch 초). 실패 시 None."""
    import ctypes
    from ctypes import wintypes
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                               ctypes.byref(kernel), ctypes.byref(user)):
        return None
    ft = (created.dwHighDateTime << 32) | created.dwLowDateTime
    if ft <= 0:
        return None
    return (ft - _WIN_EPOCH_AS_FILETIME) / 1e7


def _win_query_process(pid: int) -> tuple[str, float | None]:
    """Windows에서 신호/이벤트 전송 없이 프로세스 상태를 조회한다.
    반환: ("alive"|"dead"|"unknown", 생성 시각 또는 None)."""
    import ctypes
    from ctypes import wintypes
    k32 = _win_kernel32()
    handle = k32.OpenProcess(_WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        if ctypes.get_last_error() == _WIN_ERROR_INVALID_PARAMETER:
            return "dead", None        # 해당 PID 프로세스 없음
        return "unknown", None         # 접근 거부 등 → 판단 불가
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return "unknown", None
        if code.value != _WIN_STILL_ACTIVE:
            return "dead", None        # 종료됐으나 handle만 남은 프로세스
        return "alive", _win_creation_time(k32, handle)
    finally:
        k32.CloseHandle(handle)


def _posix_query_process(pid: int) -> tuple[str, float | None]:
    """POSIX: 신호 없이 /proc로만 확인한다. /proc가 없으면 판단 불가(unknown → 탈취 금지)."""
    proc = Path("/proc")
    if not proc.is_dir():
        return "unknown", None
    return ("alive" if (proc / str(pid)).exists() else "dead"), None


def _query_process(pid) -> tuple[str, float | None]:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return "unknown", None
    try:
        if os.name == "nt":
            return _win_query_process(pid)
        return _posix_query_process(pid)
    except Exception:
        return "unknown", None


def _compute_process_start_time() -> float | None:
    """현재 프로세스의 실제 생성 시각(epoch 초). Windows는 GetProcessTimes, 그 외/실패 시 None."""
    if os.name != "nt":
        return None
    try:
        k32 = _win_kernel32()
        return _win_creation_time(k32, k32.GetCurrentProcess())
    except Exception:
        return None


# Process start time for PID reuse protection (실제 프로세스 생성 시각; 조회 불가 시 None)
_PROCESS_START_TIME: float | None = _compute_process_start_time()


def _get_process_start_time() -> float | None:
    """Return the process start time for PID reuse protection."""
    return _PROCESS_START_TIME


def _build_owner_token() -> dict:
    """Build owner identity token with PID, process start time, UUID, and timestamp."""
    return {
        "pid": os.getpid(),
        "process_start_time": _PROCESS_START_TIME,
        "token": uuid.uuid4().hex,
        "created_at": datetime.now(KST).isoformat(),
    }


def _serialize_token(token: dict) -> str:
    """Serialize owner token to string for lock file storage."""
    return json.dumps(token, separators=(",", ":"), ensure_ascii=False)


def _deserialize_token(content: str) -> dict | None:
    """Deserialize owner token from lock file content."""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "pid" in data and "token" in data:
            return data
    except Exception:
        pass
    return None


def _is_valid_owner_token(owner) -> bool:
    """stale recovery 허용 대상인 정상 owner token인지 확인한다(_build_owner_token schema).
    pid: 양의 int / process_start_time: 양수 또는 None(조회 불가 기록) /
    token: 비어 있지 않은 str / created_at: 비어 있지 않은 str."""
    if not isinstance(owner, dict):
        return False
    pid = owner.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    start = owner.get("process_start_time", 0)
    if start is not None and (isinstance(start, bool) or not isinstance(start, (int, float)) or start <= 0):
        return False
    for key in ("token", "created_at"):
        value = owner.get(key)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def _is_process_alive(pid: int, process_start_time) -> bool:
    """owner 프로세스가 살아 있을 수 있으면 True(보수적). False는 다음 경우에만 반환한다.
    - 해당 PID 프로세스가 확실히 없음(종료)
    - PID는 살아 있으나 token 기록 프로세스보다 나중에 생성됨(PID 재사용 확정)
    상태/생성 시각을 확인할 수 없으면 True(탈취 금지)."""
    state, created = _query_process(pid)
    if state == "dead":
        return False
    if state != "alive":
        return True
    if isinstance(process_start_time, bool) or not isinstance(process_start_time, (int, float)) \
            or process_start_time <= 0 or created is None:
        return True
    # owner 프로세스는 token의 process_start_time 이전(또는 동시)에 생성됐어야 한다.
    return created <= process_start_time + _PROCESS_START_TOLERANCE


def _create_lock_file(p: Path, tokens: dict):
    """O_CREAT|O_EXCL로 lock 생성 후 owner token 기록. 성공 시 token dict, 실패 시 None."""
    token = _build_owner_token()
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except Exception:
        return None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_serialize_token(token))
    except Exception:
        # 방금 O_EXCL로 만든 자기 파일만 정리한다
        try:
            p.unlink()
        except Exception:
            pass
        return None
    tokens[str(p)] = token
    return token


def _remove_stale_lock(p: Path, evaluated: str) -> bool:
    """stale 판정한 lock을 제거한다. 판정과 제거 사이에 다른 프로세스가 lock을
    교체했을 수 있으므로 unlink 대신 고유 tombstone으로 rename한 뒤, 옮겨진 내용이
    판정한 내용과 같을 때만 삭제한다. 다르면 os.link로 원래 이름에 복원하고(대상이 있으면
    실패 → 덮어쓰지 않음) False. 복원 실패 시 tombstone은 보존한다."""
    tomb = p.with_name(f"{p.name}.stale-{uuid.uuid4().hex}")
    try:
        os.rename(str(p), str(tomb))
    except FileNotFoundError:
        return True                    # 이미 다른 프로세스가 정리함 → O_EXCL 경쟁으로 진행
    except Exception:
        return False
    try:
        moved = tomb.read_text(encoding="utf-8")
    except Exception:
        moved = None
    if moved == evaluated:
        try:
            tomb.unlink()
        except Exception:
            pass
        return True
    # 다른 owner의 새 lock을 옮긴 경우 → 복원. os.rename은 POSIX에서 기존 대상을 덮어쓰므로
    # 사용하지 않고, 대상이 있으면 FileExistsError로 실패하는 os.link 후 tombstone만 제거한다.
    try:
        os.link(str(tomb), str(p))
    except Exception:
        LOG.warning("Lock restore failed after stale race (tombstone kept): %s", tomb.name)
        return False
    try:
        os.unlink(str(tomb))
    except Exception:
        LOG.warning("Lock restored but tombstone cleanup failed: %s", tomb.name)
    return False


def _recover_stale_lock(p: Path, stale_seconds: int) -> bool:
    """lock이 없거나 안전하게 제거되면 True. 살아 있는 owner·판단 불가·읽기 실패 시 False."""
    try:
        if not p.exists():
            return True
        if time.time() - p.stat().st_mtime <= stale_seconds:
            return False
        content = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except Exception:
        return False                   # token 읽기 실패 → 삭제하지 않는다
    owner = _deserialize_token(content)
    if not _is_valid_owner_token(owner):
        # malformed/empty/구버전 형식 → owner 확인 불가 → stale이어도 자동 삭제하지 않는다
        LOG.warning("Stale lock kept: owner token unverifiable (manual check required): %s", p.name)
        return False
    if _is_process_alive(owner["pid"], owner.get("process_start_time")):
        LOG.debug("Lock held by alive process (pid=%s) - not stealing", owner["pid"])
        return False
    # owner 종료 또는 PID 재사용 확정 → stale 정책대로 제거
    return _remove_stale_lock(p, content)


def _release_owned_lock(p: Path, tokens: dict, token: dict = None) -> bool:
    """이 프로세스가 획득한 token과 lock 파일 내용이 일치할 때만 삭제한다.
    내 token이 없으면 삭제하지 않는다(lock 파일 자신의 token으로 대체하지 않음)."""
    lock_key = str(p)
    stored = tokens.get(lock_key)
    token = token or stored
    if not isinstance(token, dict):
        return False
    is_stored = token == stored
    try:
        current = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        if is_stored:
            tokens.pop(lock_key, None)
        return False
    except Exception:
        return False
    if _serialize_token(token) != current:
        LOG.warning("Lock release skipped: token mismatch (other owner): %s", p.name)
        if is_stored:
            tokens.pop(lock_key, None)
        return False
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        return False
    tokens.pop(lock_key, None)
    return True

def _is_non_retryable_reason(reason) -> bool:
    r = str(reason or "").strip()
    return r.startswith("budget") or r in NON_RETRYABLE_REASONS

# 루프 예외 알림 스팸 방지용 스로틀(태그별 마지막 발송 시각). poll(기본 30s)마다
# 같은 예외가 반복돼도 min_interval 이내엔 재발송하지 않는다.
_last_alert_ts: dict = {}

def _alert_throttled(cfg: dict, tag: str, level: str, title: str, detail="",
                     event: str = "error", min_interval: int = 1800) -> None:
    """telegram_ops.notify_level을 스로틀링해서 호출(알림 폭주 방지). 실패해도 무시."""
    now = time.time()
    if now - _last_alert_ts.get(tag, 0) < min_interval:
        return
    _last_alert_ts[tag] = now
    try:
        from . import telegram_ops
        telegram_ops.notify_level(cfg, level, title, detail, event=event)
    except Exception:
        pass


def _notify_slot_result(cfg: dict, entry: dict, reason: str) -> None:
    """슬롯 레벨 실패 알림 — HOLD/후보소진 전용. 실패해도 스케줄러 흐름 무영향.
    성공은 calculator_pipeline.py의 publish_success가 담당하므로 여기선 침묵."""
    slot = entry.get("scheduled_time", "-")
    no = entry.get("post_no", "?")
    try:
        from . import telegram_ops
        if reason == "모든후보HOLD":
            telegram_ops.notify_level(cfg, "WARNING",
                f"글{no} 슬롯 품질보류 ({slot})",
                "모든 후보가 품질 재시도 한도 초과로 발행 보류됨 — 프롬프트 개선 시 자동 재도전",
                event="quality_critical_hold")
        elif reason == "후보소진":
            telegram_ops.notify_level(cfg, "WARNING",
                f"글{no} 슬롯 후보소진 ({slot})",
                "발행 가능한 신규 후보 없음 — 계산기 전부 발행됨 또는 HOLD 상태",
                event="quality_critical_hold")
    except Exception:
        pass


# ── 경로 ──────────────────────────────────────────────────────────
def _schedule_dir(cfg: dict) -> Path:
    root = Path(cfg.get("_root", "."))
    line = cfg.get("scheduler_line", "")
    if line == "blog":
        d = root / "data" / "schedule" / "blog"
    elif line == "calc_webapp":
        d = root / "data" / "schedule" / "calc_webapp"
    else:
        d = root / "data" / "schedule"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _schedule_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "today_schedule.json"

def _history_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "history.jsonl"

def _lock_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "scheduler.lock"


# ── 시간 유틸 ─────────────────────────────────────────────────────
def _to_min(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)

def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5   # 5=토, 6=일


# ── 슬롯 설정 ─────────────────────────────────────────────────────
def default_slots(count: int) -> list:
    """09:00~21:00 사이를 count개 1시간 슬롯으로 균등 분할."""
    count = max(1, int(count or 1))
    start_min, end_min = 9 * 60, 21 * 60
    span = end_min - start_min
    step = span // count
    slots = []
    for i in range(count):
        s = start_min + i * step
        e = min(s + min(step, 60), end_min)
        if e <= s:
            e = s + 30
        slots.append({"start": _to_hhmm(s), "end": _to_hhmm(e)})
    return slots

def get_slots_for(cfg: dict, d: date = None) -> tuple:
    """(day_type, slots) 반환.

    Blog 라인: PUBLISHING_POLICY.weekdays가 있으면 그 날의 실제 요일(mon..sun)
    key로 count/time_ranges를 조회해 슬롯을 계산한다(CALCMATE-WEEKDAY-SEMANTIC-
    FIX-01) — 해당 요일의 count가 0이면 그날은 슬롯을 만들지 않는다(사용자가
    선택하지 않은 요일 = 실행 안 함). PUBLISHING_POLICY.weekdays가 없거나 형식이
    유효하지 않으면 기존 BLOG_SCHEDULE.publish_slots/weekday_only로 그대로
    폴백한다(하위호환, 기존 동작 무변경). Publishing Planner(one-off 예약 생성,
    modules/publishing_planner.py)와 API/schema는 이 변경과 무관하게 그대로다.
    Calculator 라인(기본): PUBLISH_SCHEDULE 우선, 없으면 자동 생성.
    """
    d = d or date.today()
    day_type = "weekend" if _is_weekend(d) else "weekday"

    if cfg.get("scheduler_line") == "blog":
        pp = cfg.get("PUBLISHING_POLICY")
        if isinstance(pp, dict):
            weekdays = pp.get("weekdays")
            if isinstance(weekdays, dict) and weekdays:
                try:
                    from .publishing_policy import weekday_key_for_date
                    entry = weekdays.get(weekday_key_for_date(d))
                    if isinstance(entry, dict):
                        count = int(entry.get("count", 0) or 0)
                        if count <= 0:
                            return day_type, []  # 이 요일은 선택되지 않음
                        ranges = entry.get("time_ranges")
                        if isinstance(ranges, list) and ranges:
                            slots = [{"start": r["start"], "end": r["end"]} for r in ranges
                                     if isinstance(r, dict) and "start" in r and "end" in r]
                            if slots:
                                return day_type, slots
                        # count>0인데 유효한 time_ranges가 없으면 기존 자동 생성으로 대체
                        return day_type, default_slots(count)
                except Exception:
                    pass  # 형식 이상 시 아래 기존 BLOG_SCHEDULE 폴백으로 진행

        # 폴백: PUBLISHING_POLICY.weekdays가 없거나 사용 불가 → 기존 방식 그대로
        bs = cfg.get("BLOG_SCHEDULE", {}) or {}
        slots = bs.get("publish_slots") or []
        weekday_only = bs.get("weekday_only", False)
        if weekday_only and day_type == "weekend":
            slots = []  # weekday_only=True且周末 → 슬롯 없음
        if not slots:
            count = int(cfg.get("DAILY_POST_COUNT", 1) or 1)
            slots = default_slots(count)
        return day_type, slots

    # Calculator 라인(기존 동작)
    ps = cfg.get("PUBLISH_SCHEDULE", {}) or {}
    slots = ps.get(day_type) or []
    if not slots:
        count = int(cfg.get("DAILY_POST_COUNT", 1) or 1)
        slots = default_slots(count)
    return day_type, slots

def failure_mode(cfg: dict) -> str:
    # Blog 라인: BLOG_SCHEDULE.failure_mode 우선 (미설정 시 기본값 사용)
    if cfg.get("scheduler_line") == "blog":
        bs = cfg.get("BLOG_SCHEDULE", {}) or {}
        fm = bs.get("failure_mode", "retry_in_slot")
        return fm if fm in FAILURE_MODES else "retry_in_slot"
    # Calculator 라인(기존 동작)
    ps = cfg.get("PUBLISH_SCHEDULE", {}) or {}
    fm = ps.get("failure_mode", "retry_in_slot")
    return fm if fm in FAILURE_MODES else "retry_in_slot"


# ── 검증 ──────────────────────────────────────────────────────────
def validate_slots(slots: list, expected_count: int = None) -> list:
    """슬롯 설정 검증. 오류 메시지 리스트 반환(빈 리스트면 정상)."""
    errors = []
    if not slots:
        return ["슬롯이 비어 있습니다."]
    if expected_count is not None and len(slots) != expected_count:
        errors.append(f"슬롯 수({len(slots)})가 DAILY_POST_COUNT({expected_count})와 다릅니다.")
    ranges = []
    for i, s in enumerate(slots, 1):
        st, en = s.get("start", ""), s.get("end", "")
        try:
            sm, em = _to_min(st), _to_min(en)
        except Exception:
            errors.append(f"글{i}: 시간 형식 오류 (HH:MM) — start={st!r}, end={en!r}")
            continue
        if not (0 <= sm < 24 * 60 and 0 <= em <= 24 * 60):
            errors.append(f"글{i}: 시간 범위 초과 — {st}~{en}")
        if sm >= em:
            errors.append(f"글{i}: 시작시간이 종료시간 이상입니다 — {st} >= {en}")
        ranges.append((sm, em, i))
    # 슬롯 중복(겹침) 경고
    ranges.sort()
    for a, b in zip(ranges, ranges[1:]):
        if a[1] > b[0]:
            errors.append(f"슬롯 겹침 경고: 글{a[2]}({_to_hhmm(a[0])}~{_to_hhmm(a[1])}) ↔ "
                          f"글{b[2]}({_to_hhmm(b[0])}~{_to_hhmm(b[1])})")
    return errors


# ── 스케줄 생성/저장/로드 ─────────────────────────────────────────
def _rand_time_in(start: str, end: str, taken: set) -> str:
    """[start, end) 내 랜덤 HH:MM, 이미 사용된 시각과 중복 방지."""
    sm, em = _to_min(start), _to_min(end)
    if em <= sm:
        em = sm + 1
    for _ in range(50):
        t = random.randint(sm, max(sm, em - 1))
        if t not in taken:
            taken.add(t)
            return _to_hhmm(t)
    taken.add(sm)
    return _to_hhmm(sm)

def available_slots(now: datetime, slot_candidates: list) -> list:
    """now 이후에 실행 가능한 슬롯만 반환. 하루 시작/수동 재생성/내일 일정 미리 생성 등
    모든 '슬롯 생성' 경로에서 재사용(get_due_posts 등 실행 경로는 건드리지 않는다).
      - 완전 과거 슬롯(종료 ≤ now): 제외
      - 진행 중 슬롯(시작 ≤ now < 종료): 시작을 now 직후로 당겨 과거 시각 생성 방지
      - 미래 슬롯: 그대로
    now=None(오늘이 아닌 날짜=내일 일정 미리 생성 등)이면 필터하지 않고 전체 반환."""
    if now is None:
        return list(slot_candidates)
    now_min = now.hour * 60 + now.minute
    out = []
    for s in slot_candidates:
        try:
            sm, em = _to_min(s.get("start", "")), _to_min(s.get("end", ""))
        except Exception:
            out.append(s)
            continue
        if em <= now_min:
            continue   # 완전 과거 슬롯 → 생성하지 않음
        start = s.get("start") if sm > now_min else _to_hhmm(min(now_min + 1, em - 1))
        out.append({**s, "start": start})
    return out


def generate_today_schedule(cfg: dict, d: date = None) -> dict:
    """오늘(또는 지정일) 스케줄 생성 후 저장.

    재생성 시 병합 규칙(오늘 날짜 한정):
      - completed / failed / running 항목은 절대 삭제하지 않고 유지(실행 이력 보존).
      - pending / retry 항목만 재생성 대상 — 새 슬롯 설정으로 교체.
      - 병합 기준: scheduled_time. 보존 시각과 동일 시각의 신규 슬롯은 생성 금지(중복 방지).
      - 날짜가 다른 경우(내일 미리 생성 등)에는 보존 없이 새로 생성.
    """
    d = d or date.today()
    day_type, slots = get_slots_for(cfg, d)
    # 오늘 일정 재생성 시 이미 지난 시각 슬롯은 만들지 않는다(available_slots).
    # 미래 날짜(내일 일정 미리 생성 등)는 필터하지 않음(now=None).
    now = datetime.now() if d == date.today() else None
    slots = available_slots(now, slots)

    # ── 기존 실행 이력 보존(오늘 재생성 시에만) ──────────────────────
    # 날짜가 다르면(내일 미리 생성 / 날짜 변경 직후) 보존 없이 새로 생성.
    preserved = []
    if now is not None:
        existing = load_schedule(cfg)
        if existing and existing.get("date") == d.isoformat():
            preserved = [e for e in existing.get("schedule", [])
                         if str(e.get("status", "")).strip() in ("completed", "failed", "running")]

    # 보존 항목의 scheduled_time(분)을 taken 초기값으로 설정 → 신규 슬롯이 같은 시각 생성 금지
    taken = set()
    for e in preserved:
        t = e.get("scheduled_time", "")
        if t and ":" in str(t):
            try:
                taken.add(_to_min(t))
            except Exception:
                pass

    # ── 신규 pending 슬롯 생성 ────────────────────────────────────────
    new_entries = []
    for slot in slots:
        st, en = slot.get("start", "09:00"), slot.get("end", "10:00")
        try:
            sched_time = _rand_time_in(st, en, taken)
        except Exception:
            sched_time = st
        new_entries.append({
            "post_no": 0,          # 병합 후 재부여
            "slot_start": st,
            "slot_end": en,
            "scheduled_time": sched_time,
            "status": "pending",
            "actual_time": "",
            "delay_min": "",
            "result": "",
            "attempts": 0,
        })

    # ── 병합: 보존 + 신규 → 시각 순 정렬 → post_no 재부여 ───────────
    merged = sorted(preserved + new_entries, key=lambda e: e.get("scheduled_time", ""))
    for i, e in enumerate(merged, 1):
        e["post_no"] = i

    sched = {
        "date": d.isoformat(),
        "day_type": day_type,
        "failure_mode": failure_mode(cfg),
        "schedule": merged,
    }
    save_schedule(cfg, sched)
    LOG.info("오늘(%s, %s) 발행 일정 생성: %d건 (보존 %d + 신규 %d)",
             d.isoformat(), day_type, len(merged), len(preserved), len(new_entries))
    return sched

def load_schedule(cfg: dict) -> dict | None:
    p = _schedule_path(cfg)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        LOG.warning("today_schedule.json 로드 실패: %s", e)
        return None

def save_schedule(cfg: dict, sched: dict):
    with open(_schedule_path(cfg), "w", encoding="utf-8") as f:
        json.dump(sched, f, ensure_ascii=False, indent=2)

def ensure_today_schedule(cfg: dict) -> dict:
    """오늘 일정이 없거나 날짜가 바뀌었으면 새로 생성(다음날 자동 생성)."""
    sched = load_schedule(cfg)
    today = date.today().isoformat()
    if sched is None or sched.get("date") != today:
        sched = generate_today_schedule(cfg)
    return sched

def reset_today(cfg: dict):
    """오늘 일정 초기화(삭제)."""
    _schedule_path(cfg).unlink(missing_ok=True)
    LOG.info("오늘 일정 초기화 완료")


# ── 실행 ──────────────────────────────────────────────────────────
def get_due_posts(sched: dict, now: datetime = None) -> list:
    """현재 시각 이상이고 아직 실행 대기(pending/retry)인 글 목록."""
    now = now or datetime.now()
    now_min = now.hour * 60 + now.minute
    due = []
    for e in sched.get("schedule", []):
        if e.get("status") in ("pending", "retry"):
            try:
                if _to_min(e["scheduled_time"]) <= now_min:
                    due.append(e)
            except Exception:
                continue
    return due

def _append_history(cfg: dict, sched: dict, entry: dict):
    rec = {
        "date": sched.get("date"),
        "post_no": entry.get("post_no"),
        "scheduled_time": entry.get("scheduled_time"),
        "actual_time": entry.get("actual_time"),
        "delay_min": entry.get("delay_min"),
        "status": entry.get("status"),
        "result": entry.get("result"),
        "attempts": entry.get("attempts"),
    }
    try:
        with open(_history_path(cfg), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        LOG.warning("스케줄 이력 기록 실패: %s", e)

def _apply_failure_mode(cfg: dict, sched: dict, entry: dict):
    """실패 시 모드별 후처리."""
    mode = sched.get("failure_mode", "retry_in_slot")
    now_min = datetime.now().hour * 60 + datetime.now().minute
    if mode == "none":
        entry["status"] = "failed"
        LOG.info("글%s 실패 — 재시도 안함(mode=none)", entry["post_no"])
    elif mode == "retry_in_slot":
        end_min = _to_min(entry["slot_end"])
        if now_min < end_min - 1:
            new_t = _rand_time_in(_to_hhmm(now_min + 1), entry["slot_end"], set())
            entry["scheduled_time"] = new_t
            entry["status"] = "retry"
            LOG.info("글%s 실패 — 슬롯 내 재예약 %s", entry["post_no"], new_t)
        else:
            entry["status"] = "failed"
            LOG.info("글%s 실패 — 슬롯 시간 소진, 재시도 불가", entry["post_no"])
    elif mode == "next_slot":
        # 다음 빈(pending/retry) 슬롯 시각으로 이동
        later = [e for e in sched["schedule"]
                 if e["post_no"] != entry["post_no"]
                 and e["status"] in ("pending", "retry")
                 and _to_min(e["scheduled_time"]) > now_min]
        if later:
            target = min(later, key=lambda e: _to_min(e["scheduled_time"]))
            entry["scheduled_time"] = target["scheduled_time"]
            entry["status"] = "retry"
            LOG.info("글%s 실패 — 다음 슬롯(%s)으로 이동", entry["post_no"], target["scheduled_time"])
        else:
            entry["status"] = "failed"
            LOG.info("글%s 실패 — 다음 빈 슬롯 없음", entry["post_no"])

def execute_due_post(cfg: dict, sched: dict, entry: dict, run_once_fn) -> str:
    """예약 도래한 글 1건 실행. run_once_fn(cfg, max_count=1) 사용."""
    now = datetime.now()
    entry["status"] = "running"
    entry["attempts"] = int(entry.get("attempts", 0)) + 1
    entry["actual_time"] = now.strftime("%H:%M")
    try:
        delay = (now.hour * 60 + now.minute) - _to_min(entry["scheduled_time"])
        entry["delay_min"] = max(0, delay)
    except Exception:
        entry["delay_min"] = ""
    save_schedule(cfg, sched)
    LOG.info("▶ 글%s 발행 실행 (예약 %s / 실제 %s)",
             entry["post_no"], entry["scheduled_time"], entry["actual_time"])
    try:
        stats = run_once_fn(cfg, max_count=1) or {}
        produced = stats.get("produced", 0) if isinstance(stats, dict) else 0
        if produced >= 1:
            entry["status"] = "completed"
            entry["result"] = "성공"
            # 슬롯에 발행 결과 메타 저장(대시보드 표시용). 예약/발행/스케줄 알고리즘은 불변 — 결과 기록만.
            meta = stats.get("published") or {}
            if meta:
                entry["keyword"] = meta.get("keyword", "")
                entry["title"] = meta.get("title", "")
                entry["wp_post_id"] = meta.get("wp_post_id", "")
                entry["wp_url"] = meta.get("wp_url", "")
            entry["completed_at"] = entry.get("actual_time", "")
            LOG.info("✅ 글%s 발행 완료", entry["post_no"])
        else:
            reason = stats.get("reason", "")
            entry["result"] = f"미생산({reason})"
            # 재시도 무의미 사유(신규 후보 없음/예산 등)는 즉시 실패 — 슬롯 내 재시도 폭주 방지.
            if _is_non_retryable_reason(reason):
                entry["status"] = "failed"
                LOG.info("글%s 미생산(%s) — 재시도 무의미, 즉시 실패(폭주 방지)",
                         entry["post_no"], reason)
                _notify_slot_result(cfg, entry, reason)
            else:
                _apply_failure_mode(cfg, sched, entry)
    except Exception as e:
        # 일시적 오류/예외는 재시도 의미 있음 → 기존 retry_in_slot 유지
        entry["result"] = f"오류:{str(e)[:80]}"
        LOG.error("글%s 실행 오류: %s", entry["post_no"], e, exc_info=True)
        _apply_failure_mode(cfg, sched, entry)
    save_schedule(cfg, sched)
    _append_history(cfg, sched, entry)
    return entry["status"]


def summarize(sched: dict) -> dict:
    """오늘 일정 요약(빠른 KPI용)."""
    items = (sched or {}).get("schedule", [])
    from collections import Counter
    c = Counter(e.get("status") for e in items)
    nxt = None
    pend = sorted([e for e in items if e.get("status") in ("pending", "retry")],
                  key=lambda x: x.get("scheduled_time", ""))
    if pend:
        nxt = pend[0].get("scheduled_time")
    return {
        "total": len(items),
        "completed": c.get("completed", 0),
        "pending": c.get("pending", 0) + c.get("retry", 0),
        "failed": c.get("failed", 0),
        "running": c.get("running", 0),
        "next": nxt,
    }


def immediate_publish(cfg: dict, run_once_fn, mode: str = "pull") -> tuple:
    """예약시간 무시하고 즉시 1건 발행.

    mode="pull": 다음 대기 슬롯 1개를 당겨서 소모(기본).
    mode="add" : 슬롯 소모 없이 추가 발행(오늘 일정에 '즉시' 항목 추가).
    반환: (ok, message)
    """
    sched = ensure_today_schedule(cfg)
    now = datetime.now()
    if not _acquire_lock(cfg):
        return False, "다른 발행이 진행 중입니다(lock). 잠시 후 다시 시도하세요."
    try:
        try:
            stats = run_once_fn(cfg, max_count=1) or {}
        except Exception as e:
            LOG.error("즉시 발행 실행 오류: %s", e, exc_info=True)
            return False, f"즉시 발행 실패: {e}"
        produced = stats.get("produced", 0) if isinstance(stats, dict) else 0
        result = "성공" if produced >= 1 else f"미생산({stats.get('reason','')})"

        target = None
        if mode == "pull":
            pend = sorted([e for e in sched["schedule"] if e.get("status") in ("pending", "retry")],
                          key=lambda x: _to_min(x["scheduled_time"]) if ":" in str(x.get("scheduled_time","")) else 9999)
            target = pend[0] if pend else None

        if target is not None:   # 당겨쓰기
            target["status"] = "completed" if produced >= 1 else "failed"
            target["actual_time"] = now.strftime("%H:%M")
            target["result"] = f"즉시({result})"
            target["attempts"] = int(target.get("attempts", 0)) + 1
            # 슬롯 표시용 발행 메타(스케줄러 슬롯과 동일 표시). 발행/예약 로직 불변 — 결과 기록만.
            _meta = stats.get("published") or {} if isinstance(stats, dict) else {}
            if _meta:
                target["keyword"] = _meta.get("keyword", "")
                target["title"] = _meta.get("title", "")
                target["wp_post_id"] = _meta.get("wp_post_id", "")
                target["wp_url"] = _meta.get("wp_url", "")
            target["completed_at"] = target["actual_time"]
            target["delay_min"] = 0
            _append_history(cfg, sched, {**target, "scheduled_time": "즉시실행"})
        else:                    # 추가 발행
            post_no = max([e.get("post_no", 0) for e in sched["schedule"]] or [0]) + 1
            entry = {
                "post_no": post_no, "slot_start": "-", "slot_end": "-",
                "scheduled_time": "즉시실행",
                "status": "completed" if produced >= 1 else "failed",
                "actual_time": now.strftime("%H:%M"), "delay_min": 0,
                "result": result, "attempts": 1,
            }
            sched["schedule"].append(entry)
            _append_history(cfg, sched, entry)
        save_schedule(cfg, sched)
        LOG.info("즉시 발행(%s): %s", mode, result)
        return (produced >= 1), f"즉시 발행 {result}"
    finally:
        _release_lock(cfg)


def run_scheduler_loop(cfg: dict, run_once_fn, poll_seconds: int = 30):
    """슬롯 스케줄러 메인 루프. 수동 실행과의 동시 실행 방지를 위해 lock 사용."""
    LOG.info("슬롯 발행 스케줄러 시작 (poll=%ds)", poll_seconds)
    while True:
        try:
            # 비용 관리: 80% 경고 / 100% 자동 일시정지(익일 자동 재개)
            try:
                from . import cost_manager
                cost_manager.check_budget_alerts(cfg)
                if cost_manager.is_paused(cfg):
                    LOG.warning("[cost] 일 예산 한도 — 발행 일시정지(익일 재개). 이번 주기 건너뜀")
                    time.sleep(poll_seconds)
                    continue
            except Exception as _e:
                LOG.warning("cost_manager 점검 실패(무시): %s", _e)
            sched = ensure_today_schedule(cfg)
            for entry in get_due_posts(sched):
                if _acquire_lock(cfg):
                    try:
                        execute_due_post(cfg, sched, entry, run_once_fn)
                    finally:
                        _release_lock(cfg)
                else:
                    LOG.info("다른 실행이 진행 중(lock) — 이번 주기 건너뜀")
                    break
            remaining = [e for e in sched["schedule"] if e["status"] in ("pending", "retry")]
            if not remaining:
                LOG.info("오늘 일정 모두 처리됨 — 다음 날 자동 생성 대기")
        except Exception as e:
            LOG.error("스케줄러 루프 오류: %s", e, exc_info=True)
            # 루프 예외 — 운영자 즉시 인지(Sprint 1 §1-3). 스팸 방지 스로틀.
            _alert_throttled(cfg, "scheduler_loop", "ERROR", "발행 스케줄러 루프 예외", e)
        time.sleep(poll_seconds)


# ── 수동 실행 충돌 방지용 파일 락 (CALCMATE-LOCK-HARDENING-01) ──
# O_CREAT|O_EXCL로 원자적 생성, owner token(PID+process_start+UUID+timestamp) 기록
# stale recovery 시 owner process liveness 확인 후 탈취 방지
# release 시 token 검증으로 다른 owner의 lock 보호
def _acquire_lock(cfg: dict, stale_seconds: int = 1800) -> bool:
    p = _lock_path(cfg)
    try:
        if not _recover_stale_lock(p, stale_seconds):
            return False
        return _create_lock_file(p, _LOCK_OWNER_TOKENS) is not None
    except Exception:
        return False


def _release_lock(cfg: dict) -> bool:
    return _release_owned_lock(_lock_path(cfg), _LOCK_OWNER_TOKENS)


# ══════════════════════════════════════════════════════════════════
# ── 1회성(one-off) 예약 실행 구조(CALCMATE-ONEOFF-SCHEDULE-STRUCTURE-02) ──
#
# 위 recurring publish_slots(매일 반복 시간대) 구조와는 완전히 분리된 별도
# 경로다 — 기존 today_schedule.json / _schedule_path / _lock_path / get_due_posts
# / execute_due_post / run_scheduler_loop는 이 섹션에서 단 한 줄도 참조·수정하지
# 않는다. 저장 파일도 별도(oneoff_schedule.json), lock 파일도 별도
# (oneoff_scheduler.lock)를 사용해 자원을 공유하지 않는다.
#
# 하나의 예약(reservation) = {id, scheduled_at(ISO, tz-aware), mode(draft|publish),
# status(pending|completed|failed), created_at, executed_at, result}.
# 요일별/개수별/반복 설정은 이 구조에 존재하지 않는다(의도적으로 미구현).
# ══════════════════════════════════════════════════════════════════

ONEOFF_MODES = ("draft", "publish")
ONEOFF_STATUSES = ("pending", "completed", "failed")


def _oneoff_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "oneoff_schedule.json"


def load_oneoff(cfg: dict) -> list:
    """1회성 예약 전체 목록을 로드한다. 파일이 없거나 손상됐으면 빈 리스트를
    반환해 호출부가 죽지 않도록 한다(기존 load_schedule()과 동일한 방어 패턴)."""
    p = _oneoff_path(cfg)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("reservations", []) if isinstance(data, dict) else []
    except Exception as e:
        LOG.warning("oneoff_schedule.json 로드 실패: %s", e)
        return []


def save_oneoff(cfg: dict, reservations: list):
    """oneoff_schedule.json을 원자적으로 쓴다(CALCMATE-ONEOFF-SCHEDULE-SAFETY-FIX-01).

    같은 디렉터리에 임시 파일을 쓰고 flush+fsync한 뒤 os.replace()로 교체한다.
    os.replace()는 POSIX/Windows 모두에서 원자적이므로, 쓰기 도중 프로세스가
    비정상 종료돼도 기존 oneoff_schedule.json은 손상되지 않고 그대로 남는다
    (부분쓰기로 잘린 파일이 남는 경우가 없음).

    기존 recurring save_schedule()의 저장 방식은 이번 STEP에서 변경하지
    않는다 — oneoff 저장 함수만 개선한다."""
    path = _oneoff_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".oneoff_schedule_", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump({"reservations": reservations}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _abs_time_key(dt: datetime) -> str:
    """timezone-aware datetime을 절대시각 비교용 키로 정규화한다(UTC ISO).
    naive datetime은 KST로 간주해 부착한 뒤 변환한다(기존 get_due_oneoff()와
    동일한 관례)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(timezone.utc).isoformat()


def add_oneoff_reservation(cfg: dict, scheduled_at: datetime, mode: str,
                            lock_retries: int = 5, lock_retry_interval: float = 0.5,
                            topic_id: str | None = None) -> dict:
    """1회성 WP 예약 1건을 추가하고 저장된(또는 기존) entry를 반환한다
    (CALCMATE-ONEOFF-SCHEDULE-SAFETY-FIX-01).

    scheduled_at은 반드시 timezone-aware datetime이어야 한다(naive 금지).
    mode는 "draft"|"publish"만 허용한다.

    topic_id: CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01 — 선택적(additive)
    keyword-only 성격의 인자(기본값 None). None이면 entry에 "topic_id" 키 자체를
    넣지 않아 기존(레거시) entry와 완전히 동일한 shape을 유지한다(기존 호출부는
    한 글자도 바꾸지 않아도 이전과 동일하게 동작). 값이 주어지면 entry에
    "topic_id"를 그대로 저장한다 — 이 함수는 topic_id의 존재 여부를 검증하지
    않는다(GAP3-READONLY-DESIGN-AUDIT-01 STEP15: 실제 Topic 존재 검증은 실행
    시점에 Topic 전용 실행 함수가 fail-closed로 수행).

    중복 방지: 동일 scheduled_at(절대시각 기준) + mode 조합의 "pending" 예약이
    이미 있으면 새로 추가하지 않고 그 기존 entry를 그대로 반환한다(entry에
    "duplicate": True가 추가되어 호출자가 구분할 수 있다). completed/failed
    예약은 이 중복 검사에서 제외된다(같은 시각·모드라도 재예약 가능). 이번
    STEP에서는 dedup key에 topic_id를 포함하지 않는다(GAP3-READONLY-DESIGN-
    AUDIT-01에서 이미 식별된 "다른 topic이 같은 시각/mode를 예약하면 오탐
    중복 처리된다"는 문제는 Publishing Planner가 슬롯을 유일하게 배정하도록
    설계하는 후속 단계에서 재검토하기로 명시적으로 보류함 — 이번 STEP은
    dedup 정책을 임의로 바꾸지 않는다).
    성공적으로 새로 추가된 경우 "duplicate": False가 포함된 entry를 반환한다
    (반환값은 항상 entry-shape이므로 기존 호출부(entry["id"] 등 접근)는
    그대로 호환된다).

    Race condition 제거: execute_due_oneoff()가 사용하는 oneoff_scheduler.lock을
    이 함수도 사용해 "최신 JSON 재로드 → 중복 확인 → 추가 → 저장"을 lock 보유
    상태에서 원자적으로 수행한다. lock은 non-blocking 파일 존재 검사이므로
    재귀적으로 다시 잡는 경로가 없어 deadlock 위험이 없다(이 함수는
    execute_due_oneoff()/run_oneoff_scheduler_loop() 내부에서 호출되지 않음 —
    완전히 별도의 호출 경로). lock이 계속 사용 중이면 짧게 재시도 후 실패를
    RuntimeError로 알린다(실행 중인 WP 발행이 오래 걸릴 수 있으므로 무한 대기
    대신 명확한 실패를 반환)."""
    if scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at은 timezone-aware datetime이어야 합니다(naive 금지)")
    mode = str(mode or "").strip().lower()
    if mode not in ONEOFF_MODES:
        raise ValueError(f"허용되지 않는 mode: {mode!r} (허용값: {ONEOFF_MODES})")

    acquired = False
    for _ in range(max(1, lock_retries)):
        if _acquire_oneoff_lock(cfg):
            acquired = True
            break
        time.sleep(lock_retry_interval)
    if not acquired:
        raise RuntimeError(
            "1회성 예약 lock 획득 실패 — 다른 1회성 예약 작업(추가 또는 실행)이 "
            "진행 중입니다. 잠시 후 다시 시도하세요."
        )

    try:
        reservations = load_oneoff(cfg)  # lock 보유 중 최신 상태 재로드

        target_key = _abs_time_key(scheduled_at)
        for e in reservations:
            if e.get("status") != "pending" or e.get("mode") != mode:
                continue
            try:
                existing_key = _abs_time_key(datetime.fromisoformat(e["scheduled_at"]))
            except Exception:
                continue
            if existing_key == target_key:
                dup = dict(e)
                dup["duplicate"] = True
                return dup

        entry = {
            "id": f"oneoff_{datetime.now(KST).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "scheduled_at": scheduled_at.isoformat(),
            "mode": mode,
            "status": "pending",
            "created_at": datetime.now(KST).isoformat(),
            "executed_at": None,
            "result": None,
            "duplicate": False,
        }
        if topic_id is not None:
            entry["topic_id"] = topic_id
        reservations.append(entry)
        save_oneoff(cfg, reservations)
        return entry
    finally:
        _release_oneoff_lock(cfg)


def get_due_oneoff(cfg: dict, now: datetime = None) -> list:
    """status=pending이고 scheduled_at <= now인 1회성 예약 목록을 반환한다.

    now는 반드시 timezone-aware여야 한다(naive 금지 — F번 검증 항목).
    completed/failed로 전환된 예약은 status가 더 이상 "pending"이 아니므로
    이 함수가 두 번 다시 선택하지 않는다(E번 검증 항목 — 재실행 방지)."""
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware datetime이어야 합니다(naive 금지)")

    due = []
    for e in load_oneoff(cfg):
        if e.get("status") != "pending":
            continue
        try:
            sched_dt = datetime.fromisoformat(e["scheduled_at"])
        except Exception:
            continue
        if sched_dt.tzinfo is None:
            sched_dt = sched_dt.replace(tzinfo=KST)
        if sched_dt <= now:
            due.append(e)
    return due


def mark_oneoff_result(cfg: dict, reservation_id: str, status: str, result: dict = None):
    """1회성 예약 1건의 실행 결과를 기록한다. status는 "completed"|"failed"만
    허용 — 기록 이후 get_due_oneoff()가 이 예약을 다시 반환하지 않는다."""
    if status not in ("completed", "failed"):
        raise ValueError(f"허용되지 않는 status: {status!r}")
    reservations = load_oneoff(cfg)
    for e in reservations:
        if e.get("id") == reservation_id:
            # SINGLE-OWNER-HARDENING M3: 이미 completed/failed로 확정된 예약을
            # 뒤늦은(stale) 실행자가 덮어쓰지 못하게 한다 — pending일 때만 기록.
            if e.get("status") != "pending":
                LOG.warning("1회성 예약 결과 기록 생략(이미 %s): id=%s",
                            e.get("status"), reservation_id)
                return False
            e["status"] = status
            e["executed_at"] = datetime.now(KST).isoformat()
            e["result"] = result
            break
    save_oneoff(cfg, reservations)
    return True


def execute_due_oneoff(cfg: dict, entry: dict, resolve_fn) -> str:
    """1회성 예약 1건을 실행한다.

    resolve_fn(mode, topic_id) -> run_once_fn 형태의 콜러블이어야 한다(main.py의
    resolve_blog_oneoff_publish_fn과 짝을 이룸) — 이 모듈은 blog_scheduler_adapter/
    publisher/topic_pool을 직접 import하지 않는다(기존 execute_due_post와 동일하게
    실행 함수 자체는 항상 호출부가 주입, 이 함수는 Topic Pool 상태를 직접 변경하지
    않는다 — GAP3-READONLY-DESIGN-AUDIT-01 STEP9/11 결론).

    topic_id 인자(CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01): entry에
    "topic_id"가 없는(레거시) reservation은 entry.get("topic_id")가 None을
    반환하므로 resolve_fn(mode, None)이 호출되며, 이는 기존 resolve_fn(mode)
    단일 인자 호출과 동일하게 취급되어야 한다(resolve_fn 구현체 쪽 책임 —
    이 함수 자체는 항상 두 인자를 전달할 뿐 분기하지 않는다).

    실행 직후 즉시 completed/failed로 전환해 같은 tick 또는 다음 tick에서
    재실행되지 않도록 한다."""
    try:
        run_once_fn = resolve_fn(entry.get("mode", "draft"), entry.get("topic_id"))
        stats = run_once_fn(cfg, max_count=1) or {}
        produced = stats.get("produced", 0) if isinstance(stats, dict) else 0
        if produced >= 1:
            mark_oneoff_result(cfg, entry["id"], "completed", stats)
            LOG.info("1회성 예약 완료: id=%s mode=%s", entry["id"], entry.get("mode"))
            return "completed"
        mark_oneoff_result(cfg, entry["id"], "failed", stats)
        LOG.info("1회성 예약 미생산: id=%s mode=%s", entry["id"], entry.get("mode"))
        return "failed"
    except Exception as e:
        mark_oneoff_result(cfg, entry["id"], "failed", {"error": str(e)[:300]})
        LOG.error("1회성 예약 실행 오류: id=%s error=%s", entry["id"], e, exc_info=True)
        return "failed"


def _oneoff_lock_path(cfg: dict) -> Path:
    return _schedule_dir(cfg) / "oneoff_scheduler.lock"


# 이 프로세스가 획득한 oneoff lock의 owner token(lock 경로별). token 인자 없이
# 호출하는 기존 _release_oneoff_lock(cfg) 호출부 호환용.
_ONEOFF_LOCK_TOKENS: dict = {}


def _acquire_oneoff_lock(cfg: dict, stale_seconds: int = 1800):
    """기존 _acquire_lock()과 동일한 패턴이나 완전히 별도 파일을 사용한다 —
    recurring 루프의 scheduler.lock과 절대 공유하지 않는다.

    LOCK-HARDENING: O_CREAT|O_EXCL로 원자적 생성하고 owner token(PID+process_start+UUID+timestamp)을
    JSON으로 기록한다. 성공 시 token dict 반환, 실패 시 False.
    stale recovery 시 owner process liveness 확인 후 탈취 방지(token 읽기 실패 시 삭제하지 않음)."""
    p = _oneoff_lock_path(cfg)
    try:
        if not _recover_stale_lock(p, stale_seconds):
            return False
        token = _create_lock_file(p, _ONEOFF_LOCK_TOKENS)
    except Exception:
        return False
    return token if token is not None else False


def _release_oneoff_lock(cfg: dict, token: dict = None) -> bool:
    """자신이 획득한 lock(token 일치)만 삭제한다 — 다른 owner의 lock은 지우지 않는다."""
    return _release_owned_lock(_oneoff_lock_path(cfg), _ONEOFF_LOCK_TOKENS, token)


def _blog_schedule_config_path(cfg: dict) -> Path:
    """cfg가 로드된 config.yaml 경로를 재구성한다(modules/content_sync.py::
    _content_sync_config_path()와 동일한 목적이나, scheduler.py는 _instance_id
    개념을 쓰지 않으므로(이 파일 다른 곳의 관례 그대로, 예: line 92
    `Path(cfg.get("_root", "."))`) 그 부분은 추가하지 않는다)."""
    root = Path(cfg.get("_root", "."))
    return root / "config" / "config.yaml"


def _blog_schedule_enabled_now(cfg: dict, fallback: bool) -> bool:
    """1회성 예약 루프 tick마다 config.yaml의 BLOG_SCHEDULE.enabled만 다시
    읽는다(modules/content_sync.py::_content_sync_enabled_now()와 동일한
    "가벼운 최소 재로딩" 패턴 재사용 — CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-
    EXECUTION-DECOUPLING-A-IMPLEMENT-01).

    run_oneoff_scheduler_loop()는 스레드 시작 시점에 캡처된 cfg를 그대로 들고
    있으므로(기존 관례, 재시작 필요 — dashboard.py 다른 스레드들과 동일), 이
    함수 없이는 실행 중 BLOG_SCHEDULE.enabled를 off로 바꿔도 반영되지 않는다.
    이 함수는 그 값만 매 tick 다시 확인해, topic_id가 없는(Golden10 계열)
    due 예약을 건너뛸지 판단하는 데만 쓰인다 — topic_id가 있는(Topic Pool)
    예약의 실행 여부에는 영향을 주지 않는다.

    secrets 병합/스키마 검증 등 load_config()의 나머지 처리는 건드리지 않는다.
    파일을 못 읽거나 파싱에 실패하면 기존에 알던 값(fallback, 스레드 시작
    시점의 cfg 값)을 그대로 유지한다(재로딩 실패로 오동작하지 않도록)."""
    import yaml
    path = _blog_schedule_config_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        bs = raw.get("BLOG_SCHEDULE", {}) or {}
        return bool(bs.get("enabled", fallback))
    except Exception:
        return fallback


def run_oneoff_scheduler_loop(cfg: dict, resolve_fn, poll_seconds: int = 30):
    """1회성 예약 전용 루프. 기존 run_scheduler_loop()(recurring publish_slots)와
    완전히 분리된 별도 루프이며, 그 함수의 동작에는 어떤 영향도 주지 않는다.

    매 tick마다 due 상태인 예약을 순서대로(생성 순) 최대 1건씩 lock을 잡고
    실행한다. 이 함수를 실제로 기동(스레드 시작)하는 것은 이번 STEP의 범위가
    아니다 — dashboard.py 쪽 기동 조건은 별도로 연결하되, 이 함수 자체는
    루프 로직만 제공한다.

    Golden10/Topic 실행 gate 분리(CALCMATE-AUTO-CONTENT-AUTO-PUBLISHING-
    EXECUTION-DECOUPLING-A-IMPLEMENT-01): dashboard.py가 이 루프를
    "BLOG_SCHEDULE.enabled OR AUTO_PUBLISHING.enabled"로 기동하게 되면,
    AUTO_PUBLISHING만 켜진 상태에서도 이 루프가 돌게 된다. 이 경우
    topic_id가 없는(Golden10 계열) due 예약까지 실행되면 "BLOG_SCHEDULE.enabled
    가 꺼져 있으면 예약이 실행되지 않는다"는 기존 약속이 깨진다. 따라서 이
    루프 자신이 매 tick `_blog_schedule_enabled_now()`로 최신 값을 확인해,
    topic_id가 없는 예약은 BLOG_SCHEDULE.enabled가 켜져 있을 때만 실행하고,
    꺼져 있으면 **실행하지 않고 그대로 pending으로 남긴다**(실패 처리 금지 —
    completed/failed 전환도, retry count 증가도 없음. mark_oneoff_result()를
    호출하지 않고 단순히 이번 tick에서 건너뛴다). topic_id가 있는(Topic Pool)
    예약은 이 gate의 영향을 받지 않고 항상 정상 처리된다."""
    LOG.info("1회성 예약 스케줄러 시작 (poll=%ds)", poll_seconds)
    non_owner_logged = False
    while True:
        # SINGLE-OWNER-HARDENING M1: production owner(load_config(wp_target=
        # "production")가 붙이는 명시적 표식)만 예약을 소비한다. 그 외(Streamlit,
        # standalone Task, local 미리보기)는 lock/상태/WP를 건드리지 않고 대기만 한다.
        if cfg.get("_wp_target") != "production":
            if not non_owner_logged:
                LOG.warning("1회성 예약 소비 안 함: production owner 아님(_wp_target=%r)",
                            cfg.get("_wp_target"))
                non_owner_logged = True
            time.sleep(poll_seconds)
            continue
        try:
            blog_enabled_now = _blog_schedule_enabled_now(
                cfg, cfg.get("BLOG_SCHEDULE", {}).get("enabled", False))
            for entry in get_due_oneoff(cfg):
                if entry.get("topic_id") is None and not blog_enabled_now:
                    LOG.info("Golden10 예약 skip(BLOG_SCHEDULE.enabled=off): id=%s",
                             entry.get("id"))
                    continue
                token = _acquire_oneoff_lock(cfg)
                if token:
                    try:
                        # SINGLE-OWNER-HARDENING M3: lock 획득 후 최신 상태 재확인 —
                        # 여전히 pending이고 due인 경우에만 실행한다.
                        fresh = next((e for e in get_due_oneoff(cfg)
                                      if e.get("id") == entry.get("id")), None)
                        if fresh is None:
                            LOG.info("1회성 예약 skip(이미 처리됨/더 이상 due 아님): id=%s",
                                     entry.get("id"))
                            continue
                        execute_due_oneoff(cfg, fresh, resolve_fn)
                    finally:
                        _release_oneoff_lock(cfg, token)
                else:
                    LOG.info("다른 1회성 실행이 진행 중(lock) — 이번 주기 건너뜀")
                    break
        except Exception as e:
            LOG.error("1회성 예약 스케줄러 루프 오류: %s", e, exc_info=True)
            _alert_throttled(cfg, "oneoff_scheduler_loop", "ERROR",
                             "1회성 예약 스케줄러 루프 예외", e)
        time.sleep(poll_seconds)
