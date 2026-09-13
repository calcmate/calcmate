"""
adapters/db/dual_adapter.py — Sheets(primary) + SQLite(secondary) 동시 쓰기

쓰기 전략:
  두 스토리지를 독립적으로 시도한다.
  - Sheets OK, SQLite 실패 → SQLite 재시도 큐(data/sync/pending_sync.json) 적재, Sheets 데이터 보존
  - SQLite OK, Sheets 실패 → SQLite 행에 sync_status='sync_pending' 마킹, 데이터 유실 없음
  - 둘 다 실패 → RuntimeError 전파(호출자가 처리)
읽기: Sheets 우선(최신성 보장). Sheets 다운 시 SQLite fallback.
config.yaml:  DB_ADAPTER: dual
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from .base import AbstractDBAdapter

LOG = logging.getLogger("dual_adapter")

_SYNC_QUEUE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sync" / "pending_sync.json"


# ── 동기화 재시도 큐 ────────────────────────────────────────────

def _load_queue() -> list:
    if _SYNC_QUEUE_PATH.exists():
        try:
            return json.loads(_SYNC_QUEUE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_queue(items: list):
    _SYNC_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SYNC_QUEUE_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def enqueue_sync(op: str, table: str, row: dict, row_id: str = "", error: str = "",
                 direction: str = None, source_adapter: str = None,
                 delete_targets: dict = None) -> str:
    """재시도 큐에 1건 적재한다(STEP59: direction/source_adapter/delete_targets/
    retry_count/last_attempt_at 추가 — STEP58에서 설계한 최소 스키마).

    direction/source_adapter/delete_targets는 여기서 추론하지 않는다 — 호출부가
    명시적으로 전달해야 한다(잘못된 방향을 자동 추론해 넣는 것을 방지, STEP58 §4).
    호출부가 이 값들을 넘기지 않으면 None으로 남아 retry_pending_sync()가
    "legacy/unsupported" 항목으로 안전하게 처리를 거부한다(STEP59 §13)."""
    items = _load_queue()
    qid = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]
    items.append({
        "id": qid,
        "op": op,            # insert | update | delete
        "table": table,
        "row": row,
        "row_id": row_id,
        "direction": direction,             # "sheets_to_sqlite" | "sqlite_to_sheets" | None
        "source_adapter": source_adapter,   # "DualAdapter" | "SQLiteFirstAdapter" | None
        "delete_targets": delete_targets,   # {"sqlite": bool, "sheets": bool} (op=="delete"만) | None
        "retry_count": 0,
        "status": "pending",
        "error": str(error)[:300],
        "created_at": datetime.now().isoformat(),
        "last_attempt_at": None,
    })
    _save_queue(items)
    LOG.warning("[dual] 동기화 재시도 큐 적재: %s %s %s (error: %s)", op, table, row_id, str(error)[:80])
    return qid


def list_pending_sync() -> list:
    return [i for i in _load_queue() if i.get("status") == "pending"]


def list_all_sync(status: str = None) -> list:
    """STEP61: Dashboard가 private _load_queue()를 직접 쓰지 않도록 하는 최소
    공개 조회 API. status=None이면 전체, 지정하면 해당 status만 반환한다.
    list_pending_sync()는 그대로 유지(변경/삭제하지 않음) — 이 함수는 순수
    조회 전용 추가이며 큐 스키마/retry 로직은 전혀 건드리지 않는다."""
    items = _load_queue()
    if status is None:
        return items
    return [i for i in items if i.get("status") == status]


def remove_sync(qid: str):
    _save_queue([i for i in _load_queue() if i.get("id") != qid])


# ── STEP59: 격리된 단일-항목 재시도 엔진 ────────────────────────────
# 이 함수를 1회 호출하면 지정된 queue item 1개만 정확히 1회 재시도한다.
# 내부에 while/for 자동 반복이 없다 — 다음 재시도는 항상 별도의 명시적 호출
# (미래의 Dashboard 수동 복구 버튼 등)이 있어야 발생한다(STEP58 §12/§13 원칙).
_MAX_RETRY = 3  # SheetsAdapter._MAX_RETRIES와 동일하게 맞춤(STEP58 §5 근거)


def _row_exists(sqlite_adapter, table: str, row_id: str) -> bool:
    """대상 adapter(SQLiteAdapter)와 동일한 id 컬럼 매핑을 사용해 존재 여부만 확인한다
    (STEP59 §7 — 임의 추론 금지, sqlite_adapter._ID_COL을 그대로 재사용)."""
    if not row_id:
        return False
    from .sqlite_adapter import _ID_COL
    id_col = _ID_COL.get(table, "id")
    return bool(sqlite_adapter.get_where(table, {id_col: row_id}))


def _retry_dual_adapter_write(cfg: dict, item: dict) -> tuple[bool, str]:
    """DualAdapter가 SQLite(secondary)에 쓰지 못했던 insert/update만 SQLite에
    재시도한다. Sheets는 이미 성공했으므로 건드리지 않는다."""
    from .sqlite_adapter import SQLiteAdapter
    sqlite = SQLiteAdapter(cfg)
    op = item["op"]
    table = item["table"]
    row_id = item.get("row_id") or ""
    try:
        if op == "insert":
            # STEP59 §7: 중복 INSERT 방지 — 이미 있으면 성공 처리만 하고 다시 넣지 않는다.
            if row_id and _row_exists(sqlite, table, row_id):
                return True, "already present in SQLite(중복 INSERT 방지)"
            sqlite.insert(table, dict(item.get("row") or {}))
            return True, "SQLite insert retried"
        elif op == "update":
            # STEP59 §8: 대상이 사라졌으면 실패로 처리(값을 추측해 만들어내지 않음).
            if row_id and not _row_exists(sqlite, table, row_id):
                return False, f"target row_id={row_id!r} not found in SQLite(update 대상 소멸)"
            sqlite.update(table, row_id, dict(item.get("row") or {}))
            return True, "SQLite update retried"
        return False, f"unsupported op for DualAdapter retry: {op!r}"
    except Exception as e:
        return False, str(e)[:300]


def _retry_sqlite_first_adapter_write(cfg: dict, item: dict) -> tuple[bool, str]:
    """SQLiteFirstAdapter가 Sheets에 쓰지 못했던 insert/update를 재시도한다.

    STEP58 §4/STEP59 §6 결론 유지: raw SheetsAdapter.insert()/update()를 직접
    호출하지 않는다 — app_templates가 50,000자를 넘으면 placeholder+분할 저장이
    필요하므로, 반드시 SQLiteFirstAdapter의 상위 메서드
    (_backup_insert_to_sheets/_backup_update_to_sheets)를 그대로 재사용한다.

    알려진 제약: 이 상위 메서드는 실패 시 자체적으로 enqueue_sync()를 다시
    호출한다(_try_sheets() 구조, 원본 재설계 아님). 재시도가 또 실패하면 새
    큐 항목이 하나 더 생기므로, 그 신규 항목은 즉시 제거하고 원본 항목의
    retry_count만 증가시켜 동일 실패를 두 항목으로 이중 추적하지 않는다."""
    from .sqlite_first_adapter import SQLiteFirstAdapter
    adapter = SQLiteFirstAdapter(cfg)
    op = item["op"]
    table = item["table"]
    row_id = item.get("row_id") or ""
    row = dict(item.get("row") or {})

    queue_before_ids = {i.get("id") for i in _load_queue()}
    try:
        if op == "insert":
            adapter._backup_insert_to_sheets(table, row)
        elif op == "update":
            adapter._backup_update_to_sheets(table, row_id, row)
        else:
            return False, f"unsupported op for SQLiteFirstAdapter retry: {op!r}"
    except Exception as e:
        return False, str(e)[:300]

    queue_after = _load_queue()
    new_ids = [i["id"] for i in queue_after if i.get("id") not in queue_before_ids]
    if new_ids:
        for nid in new_ids:
            remove_sync(nid)
        return False, "SQLiteFirstAdapter backup retry failed(내부 재큐 항목 정리됨)"
    return True, "Sheets backup retried via SQLiteFirstAdapter"


def _retry_delete(cfg: dict, item: dict) -> tuple[bool, str]:
    """delete_targets에 명시된 저장소만 정확히 재시도한다(STEP59 §9).
    대상이 이미 없는 삭제는 각 adapter의 delete()가 예외 없이 통과시키므로
    멱등적으로 안전하다."""
    targets = item.get("delete_targets") or {}
    table = item["table"]
    row_id = item.get("row_id") or ""
    errors = []
    if targets.get("sqlite"):
        from .sqlite_adapter import SQLiteAdapter
        try:
            SQLiteAdapter(cfg).delete(table, row_id)
        except Exception as e:
            errors.append(f"sqlite: {e}")
    if targets.get("sheets"):
        from .sheets_adapter import SheetsAdapter
        try:
            SheetsAdapter(cfg).delete(table, row_id)
        except Exception as e:
            errors.append(f"sheets: {e}")
    if errors:
        return False, "; ".join(errors)
    retried = ",".join(k for k, v in targets.items() if v) or "(no target)"
    return True, f"delete retried for: {retried}"


def retry_pending_sync(qid: str, cfg: dict) -> dict:
    """pending_sync 큐 항목 1개를 정확히 1회만 재시도한다. 자동 반복 없음 —
    이 함수를 호출한 쪽(향후 Dashboard 등)이 다음 재시도 여부를 결정한다.

    반환: {"result": "success"|"failed"|"unsupported"|"not_found"|"duplicate",
           "detail": str}
    성공 시 remove_sync()로 큐에서 제거한다. 실패 시 retry_count만 증가시키고
    3회 이상이면 status="failed_permanent"로 전환한다(Telegram 등 추가 액션
    없음 — STEP59 범위 밖).
    """
    items = _load_queue()
    idx = next((i for i, it in enumerate(items) if it.get("id") == qid), None)
    if idx is None:
        return {"result": "not_found", "detail": f"queue item {qid!r}를 찾을 수 없음"}

    item = items[idx]

    if item.get("status") == "processing":
        return {"result": "duplicate", "detail": "이미 처리 중인 항목(중복 실행 방지)"}
    if item.get("status") == "failed_permanent":
        return {"result": "unsupported", "detail": "이미 failed_permanent 상태(수동 조사 필요)"}

    op = item.get("op")
    direction = item.get("direction")
    source_adapter = item.get("source_adapter")

    # STEP59 §13: 신규 필드가 없는 legacy 항목은 방향을 추론하지 않고 안전하게 거부한다.
    if op == "delete":
        if item.get("delete_targets") is None:
            return {"result": "unsupported",
                    "detail": "legacy delete 항목(delete_targets 없음) — 수동 확인 필요"}
    else:
        if direction is None or source_adapter is None:
            return {"result": "unsupported",
                    "detail": "legacy 항목(direction/source_adapter 없음) — 수동 확인 필요"}

    item["status"] = "processing"
    item["last_attempt_at"] = datetime.now().isoformat()
    items[idx] = item
    _save_queue(items)

    try:
        if op == "delete":
            ok, detail = _retry_delete(cfg, item)
        elif source_adapter == "DualAdapter":
            ok, detail = _retry_dual_adapter_write(cfg, item)
        elif source_adapter == "SQLiteFirstAdapter":
            ok, detail = _retry_sqlite_first_adapter_write(cfg, item)
        else:
            ok, detail = False, f"unknown source_adapter: {source_adapter!r}"
    except Exception as e:
        ok, detail = False, str(e)[:300]

    items = _load_queue()
    idx = next((i for i, it in enumerate(items) if it.get("id") == qid), None)
    if idx is None:
        return {"result": "success" if ok else "failed", "detail": detail}

    if ok:
        remove_sync(qid)
        return {"result": "success", "detail": detail}

    item = items[idx]
    item["retry_count"] = int(item.get("retry_count") or 0) + 1
    item["error"] = str(detail)[:300]
    item["status"] = "failed_permanent" if item["retry_count"] >= _MAX_RETRY else "pending"
    items[idx] = item
    _save_queue(items)
    return {"result": "failed", "detail": detail}


def resume_failed_sync(qid: str) -> dict:
    """STEP64 A안: failed_permanent 항목을 재시도 가능한 pending 상태로 되돌린다.

    이 함수는 "재시도 실행"이 아니라 "재시도 가능 상태로의 복귀"만 담당한다 —
    실제 SQLite/Sheets 호출은 전혀 하지 않으며, 다음 실제 재시도는 여전히
    retry_pending_sync()가 담당한다(processing 가드도 그쪽에서 그대로 재사용).

    반환: {"result": "success"|"not_found"|"unsupported", "detail": str}
    id/op/table/row/row_id/direction/source_adapter/delete_targets/error/
    created_at/last_attempt_at은 전부 그대로 유지하고, retry_count만 0으로
    초기화하고 status만 "pending"으로 바꾼다 — 그 외 필드는 손대지 않는다.
    """
    items = _load_queue()
    idx = next((i for i, it in enumerate(items) if it.get("id") == qid), None)
    if idx is None:
        return {"result": "not_found", "detail": f"queue item {qid!r}를 찾을 수 없음"}

    item = items[idx]

    if item.get("status") != "failed_permanent":
        return {"result": "unsupported",
                "detail": f"failed_permanent 상태가 아님(현재 status={item.get('status')!r})"}

    # STEP59 §13과 동일한 legacy 방어 — direction/source_adapter를 자동 추정하지 않는다.
    if item.get("op") == "delete":
        if item.get("delete_targets") is None:
            return {"result": "unsupported",
                    "detail": "legacy delete 항목(delete_targets 없음) — 재개 불가"}
    else:
        if item.get("direction") is None or item.get("source_adapter") is None:
            return {"result": "unsupported",
                    "detail": "legacy 항목(direction/source_adapter 없음) — 재개 불가"}

    item["retry_count"] = 0
    item["status"] = "pending"
    items[idx] = item
    _save_queue(items)
    return {"result": "success", "detail": "pending 상태로 복귀(retry_count=0)"}


class DualAdapter(AbstractDBAdapter):
    """Primary: SheetsAdapter / Secondary: SQLiteAdapter."""

    def __init__(self, cfg: dict):
        from .sheets_adapter import SheetsAdapter
        from .sqlite_adapter import SQLiteAdapter
        self._primary = SheetsAdapter(cfg)
        self._secondary = SQLiteAdapter(cfg)

    # ── 읽기: Sheets 우선, 실패 시 SQLite fallback ────────────────
    def get_all(self, table: str, **kwargs) -> list[dict]:
        try:
            return self._primary.get_all(table, **kwargs)
        except Exception as e:
            LOG.warning("[dual] Sheets get_all 실패, SQLite fallback: %s", e)
            return self._secondary.get_all(table)

    def get_where(self, table: str, filters: dict) -> list[dict]:
        try:
            return self._primary.get_where(table, filters)
        except Exception as e:
            LOG.warning("[dual] Sheets get_where 실패, SQLite fallback: %s", e)
            return self._secondary.get_where(table, filters)

    # ── 쓰기: 독립 시도, 개별 실패 핸들링 ──────────────────────────
    def insert(self, table: str, row: dict) -> str:
        sheets_ok, local_ok = False, False
        sheets_id = ""

        try:
            sheets_id = self._primary.insert(table, row)
            sheets_ok = True
        except Exception as e:
            LOG.error("[dual] Sheets insert 실패: %s", e)
            # Sheets 실패 → local에 sync_pending 마킹
            try:
                self._secondary.insert(table, {**row, "sync_status": "sync_pending"})
                local_ok = True
                LOG.info("[dual] Sheets 실패 → 로컬 sync_pending 저장됨 (데이터 유실 없음)")
            except Exception as le:
                LOG.error("[dual] 로컬 fallback도 실패: %s", le)

        if sheets_ok:
            try:
                self._secondary.insert(table, {**row, "sync_status": "synced"})
                local_ok = True
            except Exception as le:
                LOG.warning("[dual] 로컬 insert 실패, 재시도 큐 적재: %s", le)
                enqueue_sync("insert", table, row, sheets_id, str(le),
                             direction="sheets_to_sqlite", source_adapter="DualAdapter")

        if not sheets_ok and not local_ok:
            raise RuntimeError(f"DualAdapter: both storages failed for insert({table})")

        return sheets_id or str(row.get("id", ""))

    def update(self, table: str, row_id: str, data: dict):
        sheets_ok = False
        try:
            self._primary.update(table, row_id, data)
            sheets_ok = True
        except Exception as e:
            LOG.error("[dual] Sheets update 실패: %s", e)
            try:
                self._secondary.update(table, row_id, {**data, "sync_status": "sync_pending"})
                LOG.info("[dual] Sheets 실패 → 로컬 sync_pending 갱신됨")
                return
            except Exception as le:
                raise RuntimeError(f"DualAdapter: both storages failed for update({table},{row_id})") from le

        if sheets_ok:
            try:
                self._secondary.update(table, row_id, data)
            except Exception as le:
                LOG.warning("[dual] 로컬 update 실패, 재시도 큐 적재: %s", le)
                enqueue_sync("update", table, data, row_id, str(le),
                             direction="sheets_to_sqlite", source_adapter="DualAdapter")

    def delete(self, table: str, row_id: str):
        # STEP56: insert()/update()와 동일하게 "양쪽 다 실패"만 RuntimeError로 승격한다.
        # 편측 실패(로그만 남기고 계속 진행)는 기존 동작 그대로 유지 — 여기서 바뀌는
        # 것은 "둘 다 실패했는데도 예외 없이 조용히 성공 취급되던 것"뿐이다.
        # 실제 production 호출부(modules/app_factory.py::delete_app(), calc_repo.delete()
        # 경유)가 이미 try/except로 예외를 정상 처리하고 있음을 STEP56에서 확인했다.
        sheets_ok, local_ok = False, False
        try:
            self._primary.delete(table, row_id)
            sheets_ok = True
        except Exception as e:
            LOG.error("[dual] Sheets delete 실패: %s", e)
        try:
            self._secondary.delete(table, row_id)
            local_ok = True
        except Exception as le:
            LOG.warning("[dual] 로컬 delete 실패: %s", le)
            enqueue_sync("delete", table, {}, row_id, str(le),
                         delete_targets={"sqlite": True, "sheets": not sheets_ok})

        if not sheets_ok and not local_ok:
            raise RuntimeError(f"DualAdapter: both storages failed for delete({table},{row_id})")

    def read_test(self) -> bool:
        return self._primary.read_test()

    def invalidate_cache(self, table: str = None):
        if hasattr(self._primary, "invalidate_cache"):
            self._primary.invalidate_cache(table)
