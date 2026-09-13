# -*- coding: utf-8 -*-
"""tests/test_pending_sync_retry.py

STEP59: adapters/db/dual_adapter.py의 pending_sync 큐 스키마 확장
(direction/source_adapter/delete_targets/retry_count/status/last_attempt_at)과
격리된 단일-항목 재시도 함수 retry_pending_sync()에 대한 회귀 테스트.

최우선 보호 조건(STEP56 사고 재발 방지): 이 파일의 모든 테스트는 반드시
tmp_path/monkeypatch로 _SYNC_QUEUE_PATH를 격리한다. 실제
data/sync/pending_sync.json은 이 파일의 테스트 실행 전후로 완전히 동일해야
한다(마지막 테스트에서 SHA256 비교로 재확인한다).

실제 Google Sheets에는 전혀 접근하지 않는다 — SheetsAdapter의 개별 메서드만
monkeypatch로 대체한다(생성자 자체는 지연 연결이라 안전 — self._gc/self._sh는
실제 호출 전까지 None).
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adapters.db.dual_adapter as dual_adapter_module
from adapters.db.dual_adapter import (
    enqueue_sync,
    list_pending_sync,
    list_all_sync,
    retry_pending_sync,
    resume_failed_sync,
    _load_queue,
    _save_queue,
    _MAX_RETRY,
)
from adapters.db.sqlite_adapter import SQLiteAdapter
from adapters.db.sheets_adapter import SheetsAdapter


# 실제 production 큐 파일 — 이 파일의 모든 테스트 실행 전후 SHA256이 동일해야 한다.
_REAL_QUEUE_PATH = Path(__file__).resolve().parent.parent / "data" / "sync" / "pending_sync.json"
_REAL_QUEUE_HASH_BEFORE = hashlib.sha256(_REAL_QUEUE_PATH.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_sync_queue_file(tmp_path, monkeypatch):
    """모든 테스트에서 _SYNC_QUEUE_PATH를 tmp_path로 격리한다(STEP56 사고 재발 방지 —
    이 fixture 없이 enqueue_sync/retry_pending_sync를 호출하면 실제
    data/sync/pending_sync.json이 오염된다)."""
    monkeypatch.setattr(dual_adapter_module, "_SYNC_QUEUE_PATH", tmp_path / "pending_sync.json")


def _cfg(tmp_path, db_name: str = "test_pending_sync_retry.db") -> dict:
    return {"SQLITE_PATH": db_name, "_root": str(tmp_path)}


# ── 1. Schema ────────────────────────────────────────────────────────

def test_01_enqueue_sync_stores_full_schema(tmp_path):
    qid = enqueue_sync("insert", "calculators", {"id": "c1"}, "c1", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    item = _load_queue()[0]
    assert item["id"] == qid
    assert item["direction"] == "sheets_to_sqlite"
    assert item["source_adapter"] == "DualAdapter"
    assert item["delete_targets"] is None
    assert item["retry_count"] == 0
    assert item["status"] == "pending"
    assert item["last_attempt_at"] is None


def test_02_enqueue_sync_stores_delete_targets(tmp_path):
    enqueue_sync("delete", "calculators", {}, "c1", "boom",
                 delete_targets={"sqlite": True, "sheets": False})
    item = _load_queue()[0]
    assert item["delete_targets"] == {"sqlite": True, "sheets": False}
    assert item["direction"] is None
    assert item["source_adapter"] is None


def test_03_legacy_insert_item_without_new_fields_is_unsupported(tmp_path):
    """STEP59 §13: 신규 필드가 없는 legacy 항목은 방향을 추론하지 않고 거부한다."""
    _save_queue([{
        "id": "legacy_1", "op": "insert", "table": "calculators", "row": {"id": "c1"},
        "row_id": "c1", "error": "", "created_at": "t0", "status": "pending",
    }])
    result = retry_pending_sync("legacy_1", {})
    assert result["result"] == "unsupported"
    assert _load_queue()[0]["status"] == "pending"  # 원본 그대로 보존


def test_04_legacy_delete_item_without_delete_targets_is_unsupported(tmp_path):
    _save_queue([{
        "id": "legacy_del", "op": "delete", "table": "calculators", "row": {},
        "row_id": "c1", "error": "", "created_at": "t0", "status": "pending",
        "delete_targets": None,
    }])
    result = retry_pending_sync("legacy_del", {})
    assert result["result"] == "unsupported"


def test_05_retry_unknown_qid_returns_not_found(tmp_path):
    result = retry_pending_sync("no-such-id", {})
    assert result["result"] == "not_found"


# ── 2. Retry: DualAdapter (SQLite 쓰기 재시도) ──────────────────────

def test_06_dual_adapter_insert_retry_success(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("insert", "calculators", {"id": "c1", "name": "테스트"}, "c1", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    assert list_pending_sync() == []
    rows = SQLiteAdapter(cfg).get_where("calculators", {"id": "c1"})
    assert len(rows) == 1


def test_07_dual_adapter_insert_retry_duplicate_prevention(tmp_path):
    """이미 SQLite에 존재하는 행은 재삽입하지 않고 성공 처리만 한다(중복 INSERT 방지)."""
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "c1", "name": "이미있음"})
    qid = enqueue_sync("insert", "calculators", {"id": "c1", "name": "새값"}, "c1", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    rows = sqlite.get_where("calculators", {"id": "c1"})
    assert len(rows) == 1
    assert rows[0]["name"] == "이미있음"


def test_08_dual_adapter_update_retry_success(tmp_path):
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "c1", "name": "구버전"})
    qid = enqueue_sync("update", "calculators", {"name": "신버전"}, "c1", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    rows = sqlite.get_where("calculators", {"id": "c1"})
    assert rows[0]["name"] == "신버전"


def test_09_dual_adapter_update_retry_fails_when_target_missing(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("update", "calculators", {"name": "신버전"}, "nope", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "failed"
    item = _load_queue()[0]
    assert item["retry_count"] == 1
    assert item["status"] == "pending"


# ── 3. Retry: SQLiteFirstAdapter (Sheets 백업 재시도) ───────────────

def test_10_sqlite_first_adapter_insert_retry_success(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []
    monkeypatch.setattr(SheetsAdapter, "insert",
                         lambda self, table, row: calls.append((table, row)) or "ok")
    qid = enqueue_sync("insert", "app_templates",
                        {"template_id": "t1", "html_template": "short"}, "t1", "boom",
                        direction="sqlite_to_sheets", source_adapter="SQLiteFirstAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    assert list_pending_sync() == []
    assert calls


def test_11_sqlite_first_adapter_insert_retry_failure_cleans_duplicate_queue_entry(tmp_path, monkeypatch):
    """SQLiteFirstAdapter._backup_insert_to_sheets()는 실패 시 자체적으로
    enqueue_sync()를 또 호출한다 — retry_pending_sync()는 이 신규 중복 항목을
    감지해 제거하고, 원본 항목의 retry_count만 증가시켜야 한다(STEP59 설계)."""
    cfg = _cfg(tmp_path)

    def _boom(self, table, row):
        raise RuntimeError("sheets down again")

    monkeypatch.setattr(SheetsAdapter, "insert", _boom)
    monkeypatch.setattr("adapters.db.sqlite_first_adapter._notify_sheet_failure",
                         lambda cfg, msg: None)
    qid = enqueue_sync("insert", "app_templates",
                        {"template_id": "t1", "html_template": "short"}, "t1", "boom",
                        direction="sqlite_to_sheets", source_adapter="SQLiteFirstAdapter")
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "failed"
    items = _load_queue()
    assert len(items) == 1  # 신규 중복 항목이 제거되고 원본 1건만 남음
    assert items[0]["id"] == qid
    assert items[0]["retry_count"] == 1


# ── 4. Retry: DELETE (delete_targets 선택 재시도) ───────────────────

def test_12_retry_delete_sqlite_only(tmp_path):
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "c1", "name": "x"})
    qid = enqueue_sync("delete", "calculators", {}, "c1", "boom",
                        delete_targets={"sqlite": True, "sheets": False})
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    assert sqlite.get_where("calculators", {"id": "c1"}) == []


def test_13_retry_delete_sheets_only(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = []
    monkeypatch.setattr(SheetsAdapter, "delete",
                         lambda self, table, row_id: calls.append((table, row_id)))
    qid = enqueue_sync("delete", "calculators", {}, "c1", "boom",
                        delete_targets={"sqlite": False, "sheets": True})
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "success"
    assert calls == [("calculators", "c1")]


def test_14_retry_delete_both_targets_partial_failure(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "c1", "name": "x"})

    def _boom(self, table, row_id):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(SheetsAdapter, "delete", _boom)
    qid = enqueue_sync("delete", "calculators", {}, "c1", "boom",
                        delete_targets={"sqlite": True, "sheets": True})
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "failed"
    assert "sheets:" in result["detail"]
    assert sqlite.get_where("calculators", {"id": "c1"}) == []  # sqlite 삭제는 이미 반영(멱등)
    item = _load_queue()[0]
    assert item["retry_count"] == 1


# ── 5. Retry guard: retry_count / status lifecycle ──────────────────

def test_15_retry_count_reaches_max_becomes_failed_permanent(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("update", "calculators", {"name": "x"}, "nope", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    for _ in range(_MAX_RETRY):
        result = retry_pending_sync(qid, cfg)
        assert result["result"] == "failed"
    item = _load_queue()[0]
    assert item["retry_count"] == _MAX_RETRY
    assert item["status"] == "failed_permanent"


def test_16_retry_on_failed_permanent_item_is_rejected(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("update", "calculators", {"name": "x"}, "nope", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    for _ in range(_MAX_RETRY):
        retry_pending_sync(qid, cfg)
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "unsupported"


def test_17_processing_status_item_rejected_as_duplicate(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("update", "calculators", {"name": "x"}, "c1", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    items = _load_queue()
    items[0]["status"] = "processing"
    _save_queue(items)
    result = retry_pending_sync(qid, cfg)
    assert result["result"] == "duplicate"


def test_18_single_call_retries_exactly_once_no_internal_loop(tmp_path):
    """한 번 호출하면 정확히 1회만 재시도한다 — 내부에 while/for 자동 반복이 없다."""
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("update", "calculators", {"name": "x"}, "nope", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    retry_pending_sync(qid, cfg)
    item = _load_queue()[0]
    assert item["retry_count"] == 1


# ── 6. Queue lifecycle ───────────────────────────────────────────────

def test_19_success_removes_item_from_queue(tmp_path):
    cfg = _cfg(tmp_path)
    qid = enqueue_sync("insert", "calculators", {"id": "c9"}, "c9", "boom",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    retry_pending_sync(qid, cfg)
    assert _load_queue() == []


# ── 8. list_all_sync() (STEP61) ─────────────────────────────────────

def test_21_list_all_sync_none_returns_everything(tmp_path):
    enqueue_sync("insert", "calculators", {"id": "c1"}, "c1", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    enqueue_sync("insert", "calculators", {"id": "c2"}, "c2", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    assert len(list_all_sync()) == 2
    assert len(list_all_sync(None)) == 2


def test_22_list_all_sync_pending_only(tmp_path):
    enqueue_sync("insert", "calculators", {"id": "c1"}, "c1", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    items = _load_queue()
    items[0]["status"] = "processing"
    _save_queue(items)
    enqueue_sync("insert", "calculators", {"id": "c2"}, "c2", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    result = list_all_sync("pending")
    assert len(result) == 1
    assert result[0]["row_id"] == "c2"


def test_23_list_all_sync_processing_only(tmp_path):
    enqueue_sync("insert", "calculators", {"id": "c1"}, "c1", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    items = _load_queue()
    items[0]["status"] = "processing"
    _save_queue(items)
    result = list_all_sync("processing")
    assert len(result) == 1
    assert result[0]["row_id"] == "c1"


def test_24_list_all_sync_failed_permanent_only(tmp_path):
    qid = enqueue_sync("update", "calculators", {"name": "x"}, "nope", "e",
                        direction="sheets_to_sqlite", source_adapter="DualAdapter")
    for _ in range(_MAX_RETRY):
        retry_pending_sync(qid, {"SQLITE_PATH": "t.db", "_root": str(tmp_path)})
    result = list_all_sync("failed_permanent")
    assert len(result) == 1
    assert result[0]["id"] == qid
    assert result[0]["status"] == "failed_permanent"


def test_25_list_all_sync_empty_queue_returns_empty_list(tmp_path):
    assert list_all_sync() == []
    assert list_all_sync("pending") == []
    assert list_all_sync("failed_permanent") == []


def test_26_list_pending_sync_behavior_unchanged(tmp_path):
    """list_all_sync() 추가가 기존 list_pending_sync()의 동작을 바꾸지 않는지 확인."""
    enqueue_sync("insert", "calculators", {"id": "c1"}, "c1", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    items = _load_queue()
    items[0]["status"] = "failed_permanent"
    _save_queue(items)
    enqueue_sync("insert", "calculators", {"id": "c2"}, "c2", "e",
                 direction="sheets_to_sqlite", source_adapter="DualAdapter")
    assert len(list_pending_sync()) == 1
    assert list_pending_sync()[0]["row_id"] == "c2"
    assert len(list_all_sync()) == 2  # list_all_sync는 전체를 봄(대조군)


# ── 10. resume_failed_sync() (STEP65) ───────────────────────────────

def _fp_item(id="fp1", op="update", table="calculators", row_id="r1",
             direction="sheets_to_sqlite", source_adapter="DualAdapter",
             delete_targets=None, retry_count=3, error="last failure",
             created_at="2026-09-12T00:00:00", last_attempt_at="2026-09-12T00:05:00",
             row=None):
    return {
        "id": id, "op": op, "table": table, "row": row if row is not None else {"name": "x"},
        "row_id": row_id, "direction": direction, "source_adapter": source_adapter,
        "delete_targets": delete_targets, "retry_count": retry_count,
        "status": "failed_permanent", "error": error,
        "created_at": created_at, "last_attempt_at": last_attempt_at,
    }


def test_28_resume_failed_sync_resets_retry_count_and_status(tmp_path):
    item = _fp_item()
    _save_queue([dict(item)])
    result = resume_failed_sync("fp1")
    assert result["result"] == "success"
    after = _load_queue()[0]
    assert after["status"] == "pending"
    assert after["retry_count"] == 0
    assert after["id"] == "fp1"
    assert after["row"] == {"name": "x"}
    assert after["direction"] == "sheets_to_sqlite"
    assert after["source_adapter"] == "DualAdapter"
    assert after["delete_targets"] is None


def test_29_resume_failed_sync_preserves_error(tmp_path):
    item = _fp_item(error="original failure detail")
    _save_queue([dict(item)])
    resume_failed_sync("fp1")
    after = _load_queue()[0]
    assert after["error"] == "original failure detail"


def test_30_resume_failed_sync_preserves_timestamps_and_metadata(tmp_path):
    item = _fp_item(created_at="2026-01-01T00:00:00", last_attempt_at="2026-01-02T00:00:00")
    _save_queue([dict(item)])
    resume_failed_sync("fp1")
    after = _load_queue()[0]
    assert after["created_at"] == "2026-01-01T00:00:00"
    assert after["last_attempt_at"] == "2026-01-02T00:00:00"
    assert after["op"] == "update"
    assert after["table"] == "calculators"
    assert after["row_id"] == "r1"


def test_31_resume_on_pending_item_is_unsupported(tmp_path):
    item = dict(_fp_item(), status="pending", retry_count=1)
    _save_queue([item])
    result = resume_failed_sync("fp1")
    assert result["result"] == "unsupported"
    after = _load_queue()[0]
    assert after["status"] == "pending"
    assert after["retry_count"] == 1  # 불변


def test_32_resume_on_processing_item_is_unsupported(tmp_path):
    item = dict(_fp_item(), status="processing", retry_count=2)
    _save_queue([item])
    result = resume_failed_sync("fp1")
    assert result["result"] == "unsupported"
    after = _load_queue()[0]
    assert after["status"] == "processing"
    assert after["retry_count"] == 2


def test_33_resume_on_legacy_item_is_unsupported_and_not_auto_corrected(tmp_path):
    item = dict(_fp_item(), direction=None, source_adapter=None)
    _save_queue([item])
    result = resume_failed_sync("fp1")
    assert result["result"] == "unsupported"
    after = _load_queue()[0]
    assert after["status"] == "failed_permanent"  # 불변
    assert after["direction"] is None
    assert after["source_adapter"] is None


def test_34_resume_on_unknown_qid_returns_not_found(tmp_path):
    result = resume_failed_sync("no-such-id")
    assert result["result"] == "not_found"


def test_35_resumed_item_retries_normally_via_retry_pending_sync(tmp_path):
    """resume 이후 실제 재시도는 기존 retry_pending_sync()가 그대로 담당한다."""
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "r1", "name": "old"})
    item = _fp_item(row_id="r1", row={"name": "new"})
    _save_queue([dict(item)])

    resume_result = resume_failed_sync("fp1")
    assert resume_result["result"] == "success"

    retry_result = retry_pending_sync("fp1", cfg)
    assert retry_result["result"] == "success"
    assert list_all_sync() == []
    rows = sqlite.get_where("calculators", {"id": "r1"})
    assert rows[0]["name"] == "new"


def test_36_resume_itself_does_not_call_any_adapter(tmp_path, monkeypatch):
    """resume_failed_sync()는 상태 전환만 할 뿐, 실제 SQLite/Sheets를 호출하지 않는다."""
    calls = []
    monkeypatch.setattr(SQLiteAdapter, "insert", lambda self, t, r: calls.append("sqlite_insert"))
    monkeypatch.setattr(SQLiteAdapter, "update", lambda self, t, rid, d: calls.append("sqlite_update"))
    monkeypatch.setattr(SheetsAdapter, "insert", lambda self, t, r: calls.append("sheets_insert"))
    monkeypatch.setattr(SheetsAdapter, "update", lambda self, t, rid, d: calls.append("sheets_update"))

    item = _fp_item()
    _save_queue([dict(item)])
    result = resume_failed_sync("fp1")
    assert result["result"] == "success"
    assert calls == []  # 어떤 adapter도 호출되지 않음


# ── 9. Isolation(최우선 보호 조건) ────────────────────────────────────

def test_27_real_production_queue_file_untouched():
    """이 파일의 모든 테스트가 fixture로 격리되어 실행되므로, 모듈 import 시점에
    측정한 해시와 이 테스트 실행 시점의 해시가 완전히 동일해야 한다."""
    after = hashlib.sha256(_REAL_QUEUE_PATH.read_bytes()).hexdigest()
    assert after == _REAL_QUEUE_HASH_BEFORE
