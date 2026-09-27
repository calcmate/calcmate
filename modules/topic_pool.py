# -*- coding: utf-8 -*-
"""
modules/topic_pool.py — Topic Pool 핵심 storage/state layer
(CALCMATE-AUTO-CONTENT-TOPIC-IMPLEMENT-01)

CALCMATE-AUTO-CONTENT-TOPIC-IMPLEMENTATION-DESIGN-01의 확정 설계를 구현한다.
이 모듈은 Topic Pool의 저장(별도 DB table "topic_pool")·CRUD·상태 전이만
담당하며, 다음은 이 STEP의 범위 밖이다(별도 STEP에서 구현 예정):
  - Blog Generation 연결(TopicGenerationRequest)
  - AI Topic 생성
  - Publishing Planner(weekly slot 계산)
  - Dashboard UI
  - WordPress 호출

기존 시스템과의 관계(READ-ONLY 또는 완전 분리):
  - content/blog/__init__.py(Golden10)      — 이 모듈은 참조/수정하지 않는다.
  - modules/blog_scheduler_adapter.py       — 무관, 무수정.
  - modules/scheduler.py(recurring/one-off) — 무관, 무수정. Topic Pool은
    data/schedule/blog/oneoff_schedule.json과 완전히 별도의 저장소(DB table)를
    쓰며, "oneoff_reservation_id" 필드로만 참조 관계를 가진다(소유하지 않음).
  - modules/publisher.py                   — 무관, 무수정.

저장소: DB "topic_pool" 테이블(adapters/db/factory.py::get_topic_pool_storage_adapter()
경유). 기존 SQLiteAdapter._ensure_table()이 최초 insert() 시점에 테이블을 자동
생성하므로 별도 마이그레이션 스크립트가 필요 없다(adapters/db/sqlite_adapter.py의
_ID_COL에 "topic_pool": "topic_id" 항목만 추가됨 — 기존 테이블 매핑은 무변경).

상태 전이 설계 상 주의(구현자 판단 — 설계 문서 STEP6에 명시되지 않아 이 모듈이
보완한 부분):
  "approved -> generation_failed" 와 "approved -> schedule_failed"는 STEP6
  문서에 명시적으로 나열되어 있지 않았으나, 이 두 상태로 "들어가는" 경로가 이
  둘 외에는 존재하지 않아(각각 hold/approved로만 "나가는" 경로만 정의됨) 상태
  머신이 도달 불가능해지는 문제가 있었다. 콘텐츠 생성/예약 시도는 논리적으로
  "approved" 상태에서 이루어진다고 보고, 이 두 전이를 approved의 허용 대상에
  포함시켰다. record_failure()가 이 경로를 사용하며, 중간 상태(generation_failed/
  schedule_failed)는 DB의 status 컬럼에 별도로 persist되지 않고 status_history
  안에서만 기록된다(STEP12의 "중간 상태 미저장" 원칙을 그대로 지킴 — 최종
  status만 한 번의 update()로 저장).
"""
import json
import uuid
from datetime import datetime, timezone

from content.blog import validate_intent

TABLE = "topic_pool"

# ── 상태 상수(기존 프로젝트 convention — enum.Enum이 아닌 plain tuple 상수,
# modules/scheduler.py::STATUS/FAILURE_MODES, content/blog/__init__.py::
# VALID_INTENTS와 동일한 관례를 따른다) ──────────────────────────────────
TOPIC_STATUSES = (
    "candidate", "approved", "scheduled", "publishing", "published",
    "duplicate", "rejected", "hold",
    "generation_failed", "schedule_failed", "publish_failed",
)

_FAILURE_TYPES = ("generation_failed", "schedule_failed")
_MAX_FAILURE_BEFORE_HOLD = 3

# 자동/코드 판단으로 도달 가능한 전이(actor는 필요하되 manual=True 불필요)
_AUTO_ALLOWED_TRANSITIONS = {
    "candidate": {"approved", "duplicate", "rejected", "hold"},
    "approved": {"scheduled", "generation_failed", "schedule_failed"},
    "scheduled": {"publishing"},
    "publishing": {"published", "publish_failed"},
    "generation_failed": {"approved", "hold"},
    "schedule_failed": {"approved", "hold"},
}

# Dashboard의 명시적 수동 액션만으로 허용되는 재활성화 전이(transition_status의
# manual=True가 필요 — STEP6 "자동 전이로 처리하지 않는다" 요구사항)
#
# GAP4-IMPLEMENT-01(READONLY-AUDIT-02에서 발견된 HIGH GAP-4 보완): "publish_failed"가
# 이 표에 없어 수동으로도 재활성화할 수 없는 dead-end 상태였다. hold/duplicate/
# rejected와 동일한 패턴으로 "publish_failed -> candidate"만 추가한다("-> approved"는
# 추가하지 않음 — 재승인은 반드시 candidate를 거쳐 별도로 이루어져야 한다는 원칙).
#
# E2E-REALTEST-RECOVERY-GAP-01/IMPLEMENT-01에서 발견된 동일 계열의 GAP 보완:
# "scheduled"도 위와 같은 이유로 dead-end였다 — 예약(oneoff reservation)이
# 예약 생성 경로 오류/삭제 등으로 사라지면 Topic이 "scheduled"에 고립되고
# 되돌아올 방법이 없었다(오직 "publishing"으로만 나갈 수 있었음). 동일한
# 패턴으로 "scheduled -> candidate"만 추가한다. 이 전이 자체는 reservation
# reference(oneoff_reservation_id)를 자동으로 정리하지 않는다 — 상태 전이와
# reservation cleanup의 책임을 섞지 않기 위해서다(호출자가 필요 시 별도로
# update_topic(oneoff_reservation_id="")을 먼저/나중에 호출해야 한다).
#
# PUBLISHED-WP-RECONCILIATION-GAP-FOLLOWUP-DECISION-01: "published"도 동일한
# 이유로 dead-end였다 — WP에 게시된 뒤 그 WP post가 외부에서 trash/삭제되어도
# Topic은 영원히 "published"에 남아 되돌릴 방법이 없었다(GAP-AUDIT-01에서
# 실측 확인). 동일한 패턴으로 "published -> candidate"만 추가한다. 이 전이는
# 어떤 자동 호출부(scheduler/publisher/topic_publish_adapter)도 사용하지
# 않으며(3개 실제 자동 호출부 어디에도 "published"를 from_status로 하는
# transition_status() 호출이 없음을 확인함), modules/topic_wp_reconciliation.py의
# 조회 함수 역시 이 전이를 호출하지 않는다(조회는 상태를 바꾸지 않음) —
# Dashboard에서 사람이 MISMATCH를 확인한 뒤 별도로 transition_status(...,
# manual=True)를 호출해야만 발생한다.
_MANUAL_ONLY_TRANSITIONS = {
    "hold": {"candidate"},
    "duplicate": {"candidate"},
    "rejected": {"candidate"},
    "publish_failed": {"candidate"},
    "scheduled": {"candidate"},
    "published": {"candidate"},
}

# update_topic()으로는 절대 변경할 수 없는 필드(status 변경은 transition_status()/
# record_failure()만 사용 가능하게 강제 — STEP11 원칙)
_UPDATE_FORBIDDEN_FIELDS = {"status", "status_history", "topic_id", "created_at"}


# ── adapter ──────────────────────────────────────────────────────────

def _adapter(cfg: dict):
    from adapters.db.factory import get_topic_pool_storage_adapter
    return get_topic_pool_storage_adapter(cfg)


# ── status_history 직렬화/역직렬화 ──────────────────────────────────────

def _make_history_event(from_status: str | None, to_status: str, actor: str,
                         reason: str) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "from_status": from_status,
        "to_status": to_status,
        "reason": reason,
    }


def _load_status_history(row: dict) -> list:
    raw = row.get("status_history")
    if not raw:
        return []
    if isinstance(raw, list):
        return list(raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _serialize_status_history(history: list) -> str:
    return json.dumps(history, ensure_ascii=False)


def _compute_approved_at(status_history: list) -> str | None:
    """가장 최근의 "-> approved" 전이 timestamp를 status_history에서 파생한다.
    별도의 approved_at 컬럼을 두지 않는다(STEP9 원칙 — 중복 timestamp 저장 금지)."""
    approved_events = [e for e in status_history if e.get("to_status") == "approved"]
    if not approved_events:
        return None
    return max(approved_events, key=lambda e: e.get("timestamp", ""))["timestamp"]


def _enrich(row: dict) -> dict:
    """DB row(전부 TEXT)를 적절한 타입으로 정규화하고 approved_at을 파생시킨다."""
    out = dict(row)
    history = _load_status_history(row)
    out["status_history"] = history
    try:
        out["priority"] = int(row.get("priority") or 0)
    except (TypeError, ValueError):
        out["priority"] = 0
    try:
        out["failure_count"] = int(row.get("failure_count") or 0)
    except (TypeError, ValueError):
        out["failure_count"] = 0
    out["approved_at"] = _compute_approved_at(history)
    return out


# ── 전이 검증 ────────────────────────────────────────────────────────

def _validate_transition(from_status: str, to_status: str, *, manual: bool) -> None:
    if from_status not in TOPIC_STATUSES:
        raise ValueError(f"알 수 없는 현재 status: {from_status!r}")
    if to_status not in TOPIC_STATUSES:
        raise ValueError(f"허용되지 않는 status: {to_status!r}")

    auto_targets = _AUTO_ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status in auto_targets:
        return

    manual_targets = _MANUAL_ONLY_TRANSITIONS.get(from_status, frozenset())
    if to_status in manual_targets:
        if manual:
            return
        raise ValueError(
            f"{from_status!r} -> {to_status!r}는 수동 재활성화 전이입니다 "
            f"(transition_status(..., manual=True)로만 허용됩니다)"
        )

    raise ValueError(f"금지된 전이: {from_status!r} -> {to_status!r}")


# ── CRUD ─────────────────────────────────────────────────────────────

def create_topic(cfg: dict, *, slug: str, topic: str, intent: str,
                  title: str = "", description: str = "", category: str = "",
                  priority: int = 100, calculator_id: str | None = None,
                  actor: str = "system") -> dict:
    """Topic Pool에 신규 topic 1건을 생성한다. 초기 status="candidate".

    Golden10/calculators/blog_articles 테이블은 조회·수정하지 않는다(이번 STEP
    범위 밖). intent 검증은 기존 content.blog.validate_intent()를 그대로
    재사용한다(신규 검증 코드를 만들지 않음)."""
    if not str(slug or "").strip():
        raise ValueError("slug는 비어있을 수 없습니다")
    if not str(topic or "").strip():
        raise ValueError("topic은 비어있을 수 없습니다")
    if not validate_intent(intent):
        raise ValueError(f"허용되지 않는 intent: {intent!r}")

    now = datetime.now(timezone.utc).isoformat()
    topic_id = (
        f"topic_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_"
        f"{uuid.uuid4().hex[:6]}"
    )
    history = [_make_history_event(None, "candidate", actor, "created")]

    row = {
        "topic_id": topic_id,
        "calculator_id": calculator_id or "",
        "slug": slug,
        "topic": topic,
        "title": title,
        "description": description,
        "intent": intent,
        "category": category,
        "status": "candidate",
        "priority": str(int(priority)),
        "failure_count": "0",
        "last_failure_type": "",
        "last_error": "",
        "last_failed_at": "",
        "matched_content_id": "",
        "oneoff_reservation_id": "",
        "status_history": _serialize_status_history(history),
        "created_at": now,
        "updated_at": now,
    }
    _adapter(cfg).insert(TABLE, row)
    return get_topic(cfg, topic_id)


def get_topic(cfg: dict, topic_id: str) -> dict | None:
    rows = _adapter(cfg).get_where(TABLE, {"topic_id": topic_id})
    if not rows:
        return None
    return _enrich(rows[0])


def list_topics(cfg: dict, *, status: str | None = None) -> list[dict]:
    """priority ASC -> approved_at ASC(없으면 created_at으로 대체) -> topic_id ASC
    순으로 정렬해 반환한다(STEP10 원칙, 임의 변경 금지)."""
    rows = _adapter(cfg).get_all(TABLE)
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    enriched = [_enrich(r) for r in rows]
    enriched.sort(key=lambda t: (
        t["priority"],
        t["approved_at"] or t.get("created_at") or "",
        t.get("topic_id") or "",
    ))
    return enriched


def update_topic(cfg: dict, topic_id: str, **fields) -> dict:
    """status/status_history 이외의 일반 필드만 갱신한다. status 변경은
    transition_status()/record_failure()만 사용할 수 있다(STEP11 원칙)."""
    bad = _UPDATE_FORBIDDEN_FIELDS & set(fields.keys())
    if bad:
        raise ValueError(
            f"update_topic()으로 변경할 수 없는 필드: {sorted(bad)} — "
            f"status는 transition_status()/record_failure()만 사용하세요"
        )
    topic = get_topic(cfg, topic_id)
    if topic is None:
        raise ValueError(f"topic_id={topic_id!r}를 찾을 수 없습니다")

    data = dict(fields)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _adapter(cfg).update(TABLE, topic_id, data)
    return get_topic(cfg, topic_id)


def _save_topic_fields(cfg: dict, topic_id: str, data: dict) -> None:
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _adapter(cfg).update(TABLE, topic_id, data)


# ── 상태 전이 ────────────────────────────────────────────────────────

def transition_status(cfg: dict, topic_id: str, to_status: str, *,
                       actor: str, reason: str, manual: bool = False) -> dict:
    """topic 1건의 status를 전이시키고 status_history에 이벤트 1건을 append한다.
    허용되지 않는 전이는 ValueError를 던지며 어떤 필드도 저장하지 않는다."""
    if not str(actor or "").strip():
        raise ValueError("actor는 비어있을 수 없습니다")

    topic = get_topic(cfg, topic_id)
    if topic is None:
        raise ValueError(f"topic_id={topic_id!r}를 찾을 수 없습니다")

    from_status = topic["status"]
    _validate_transition(from_status, to_status, manual=manual)

    history = list(topic["status_history"])
    history.append(_make_history_event(from_status, to_status, actor, reason))

    _save_topic_fields(cfg, topic_id, {
        "status": to_status,
        "status_history": _serialize_status_history(history),
    })
    return get_topic(cfg, topic_id)


def record_failure(cfg: dict, topic_id: str, failure_type: str, error,
                    *, actor: str = "system") -> dict:
    """generation_failed/schedule_failed 발생을 기록하고, failure_count에 따라
    즉시 approved(<3) 또는 hold(>=3)로 전이시킨다.

    중간 상태(failure_type)는 status 컬럼에 별도로 persist되지 않고
    status_history에만 두 이벤트(from_status->failure_type, failure_type->최종
    상태)로 기록된다 — 단 한 번의 update()로 최종 상태와 함께 저장되어
    중간 상태가 별도로 저장되는 일이 없다(STEP12 원칙)."""
    if failure_type not in _FAILURE_TYPES:
        raise ValueError(
            f"허용되지 않는 failure_type: {failure_type!r} (허용값: {_FAILURE_TYPES})"
        )

    topic = get_topic(cfg, topic_id)
    if topic is None:
        raise ValueError(f"topic_id={topic_id!r}를 찾을 수 없습니다")

    from_status = topic["status"]
    _validate_transition(from_status, failure_type, manual=False)

    new_failure_count = int(topic.get("failure_count") or 0) + 1
    to_status = "approved" if new_failure_count < _MAX_FAILURE_BEFORE_HOLD else "hold"
    _validate_transition(failure_type, to_status, manual=False)

    now = datetime.now(timezone.utc).isoformat()
    history = list(topic["status_history"])
    history.append(_make_history_event(from_status, failure_type, actor,
                                        f"{failure_type} 발생"))
    history.append(_make_history_event(
        failure_type, to_status, actor,
        f"failure_count={new_failure_count} "
        f"({'<' if to_status == 'approved' else '>='} {_MAX_FAILURE_BEFORE_HOLD} -> {to_status})"
    ))

    _save_topic_fields(cfg, topic_id, {
        "status": to_status,
        "status_history": _serialize_status_history(history),
        "failure_count": str(new_failure_count),
        "last_failure_type": failure_type,
        "last_error": str(error)[:500],
        "last_failed_at": now,
    })
    return get_topic(cfg, topic_id)
