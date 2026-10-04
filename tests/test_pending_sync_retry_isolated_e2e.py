# -*- coding: utf-8 -*-
"""tests/test_pending_sync_retry_isolated_e2e.py

STEP62: "버튼 → Dashboard 분기 → retry_pending_sync() → queue 상태 변화 → 결과
표시"의 전체 실행 경로를, production 데이터와 완전히 분리된 격리 환경에서
검증한다.

STEP59/61에서 이미 검증된 개별 동작(tests/test_pending_sync_retry.py,
tests/test_dashboard_sync_recovery_tab.py)과 달리, 이 파일은:
  - retry_count/status의 단계별(1회 호출당 정확히 1단계) 전이를 명시적으로 확인
  - failed_permanent/legacy 항목이 "완전히 불변"임을 dict 전체 비교로 확인
  - DELETE의 delete_targets가 실제로 SQLite/Sheets 중 지정된 쪽만 건드리는지
  - SQLiteFirstAdapter 재시도가 raw SheetsAdapter를 우회하지 않는지
를 명시적으로 커버한다.

Streamlit "🔁 동기화 복구" 탭의 결과-분기 UI 테스트는 Streamlit 제거
(CALCMATE-LEGACY-DASHBOARD-TESTS-CLEANUP)와 함께 제거되었다. 수동 재시도/재개는
FastAPI(/api/scheduler/content-sync/retry, /resume — tests/test_content_sync_manual.py)가
담당한다.

최우선 보호 조건: 이 파일의 모든 테스트는 tmp_path/monkeypatch로
_SYNC_QUEUE_PATH를 격리한다. 실제 data/sync/pending_sync.json은 이 파일
실행 전후로 완전히 동일해야 한다(마지막 테스트에서 SHA256 재확인).
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adapters.db.dual_adapter as dual_adapter_module
from adapters.db.dual_adapter import (
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
from adapters.db.sqlite_first_adapter import SQLiteFirstAdapter


_REAL_QUEUE_PATH = Path(__file__).resolve().parent.parent / "data" / "sync" / "pending_sync.json"
_REAL_QUEUE_HASH_BEFORE = hashlib.sha256(_REAL_QUEUE_PATH.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_sync_queue_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dual_adapter_module, "_SYNC_QUEUE_PATH", tmp_path / "pending_sync.json")


def _cfg(tmp_path, db_name: str = "test_e2e.db") -> dict:
    return {"SQLITE_PATH": db_name, "_root": str(tmp_path)}


def _make_item(id, op, table, row_id, status, retry_count=0, direction=None,
               source_adapter=None, delete_targets=None, error="test error",
               row=None) -> dict:
    """STEP2 spec의 필드 구성 그대로 raw dict item을 만든다(enqueue_sync()를
    거치지 않고 _save_queue()로 직접 적재 — 정확히 지정된 상태를 재현하기 위함)."""
    return {
        "id": id, "op": op, "table": table, "row": row or {}, "row_id": row_id,
        "direction": direction, "source_adapter": source_adapter,
        "delete_targets": delete_targets, "retry_count": retry_count,
        "status": status, "error": error,
        "created_at": "2026-09-12T00:00:00", "last_attempt_at": None,
    }


# ── 3. success retry: pending → processing(관찰) → 성공 → 제거 ─────────

def test_03_success_path_observed_processing_then_removed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sqlite = SQLiteAdapter(cfg)
    sqlite.insert("calculators", {"id": "test-row-001", "name": "old"})
    item = _make_item("test-update-001", "update", "calculators", "test-row-001",
                       "pending", direction="sheets_to_sqlite", source_adapter="DualAdapter",
                       row={"name": "new"})
    _save_queue([item])

    observed = []
    real_fn = dual_adapter_module._retry_dual_adapter_write

    def _spy(cfg_, item_):
        mid = next(i for i in _load_queue() if i["id"] == "test-update-001")
        observed.append(mid["status"])
        return real_fn(cfg_, item_)

    monkeypatch.setattr(dual_adapter_module, "_retry_dual_adapter_write", _spy)

    result = retry_pending_sync("test-update-001", cfg)

    assert observed == ["processing"], "실제 adapter 재시도가 호출되는 시점에 큐 상태가 processing이어야 한다"
    assert result["result"] == "success"
    assert list_all_sync() == []
    rows = sqlite.get_where("calculators", {"id": "test-row-001"})
    assert rows[0]["name"] == "new"


# ── 4. 실패 경로: retry_count 0→1→2→3 단계별 확인, 자동 반복 없음 ────────

def test_04_failure_path_progresses_one_step_per_call(tmp_path):
    cfg = _cfg(tmp_path)
    item = _make_item("test-update-fail-001", "update", "calculators", "nope",
                       "pending", direction="sheets_to_sqlite", source_adapter="DualAdapter",
                       row={"name": "x"})
    _save_queue([item])

    r1 = retry_pending_sync("test-update-fail-001", cfg)
    assert r1["result"] == "failed"
    it1 = list_all_sync()[0]
    assert it1["retry_count"] == 1 and it1["status"] == "pending"

    r2 = retry_pending_sync("test-update-fail-001", cfg)
    assert r2["result"] == "failed"
    it2 = list_all_sync()[0]
    assert it2["retry_count"] == 2 and it2["status"] == "pending"

    r3 = retry_pending_sync("test-update-fail-001", cfg)
    assert r3["result"] == "failed"
    it3 = list_all_sync()[0]
    assert it3["retry_count"] == 3 and it3["status"] == "failed_permanent"


def test_04b_single_call_invokes_underlying_retry_exactly_once(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    item = _make_item("t2", "update", "calculators", "nope", "pending",
                       direction="sheets_to_sqlite", source_adapter="DualAdapter", row={"name": "x"})
    _save_queue([item])
    call_count = {"n": 0}
    real_fn = dual_adapter_module._retry_dual_adapter_write

    def _counter(cfg_, item_):
        call_count["n"] += 1
        return real_fn(cfg_, item_)

    monkeypatch.setattr(dual_adapter_module, "_retry_dual_adapter_write", _counter)
    retry_pending_sync("t2", cfg)
    assert call_count["n"] == 1, "함수 1회 호출 = 내부 retry 시도 정확히 1회(자동 반복 없음)"


# ── 5. processing 보호 ───────────────────────────────────────────────

def test_05_processing_item_returns_duplicate_and_state_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    item = _make_item("t-proc", "update", "calculators", "r1", "processing",
                       direction="sheets_to_sqlite", source_adapter="DualAdapter")
    _save_queue([dict(item)])
    result = retry_pending_sync("t-proc", cfg)
    assert result["result"] == "duplicate"
    after = list_all_sync()[0]
    assert after["status"] == "processing"
    assert after["retry_count"] == 0


# ── 6. failed_permanent 보호(완전 불변 확인) ─────────────────────────

def test_06_failed_permanent_item_returns_unsupported_and_is_fully_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    item = _make_item("t-fp", "update", "calculators", "r1", "failed_permanent",
                       retry_count=3, direction="sheets_to_sqlite", source_adapter="DualAdapter",
                       error="original error")
    _save_queue([dict(item)])
    before = list_all_sync()[0]
    result = retry_pending_sync("t-fp", cfg)
    assert result["result"] == "unsupported"
    after = list_all_sync()[0]
    assert after == before  # retry_count/status/error 등 전 필드 불변


# ── 7. legacy 보호(자동 추정 없음) ────────────────────────────────────

def test_07_legacy_update_item_returns_unsupported_no_auto_inference(tmp_path):
    cfg = _cfg(tmp_path)
    item = _make_item("t-legacy", "update", "calculators", "r1", "pending",
                       direction=None, source_adapter=None)
    _save_queue([dict(item)])
    before = list_all_sync()[0]
    result = retry_pending_sync("t-legacy", cfg)
    assert result["result"] == "unsupported"
    after = list_all_sync()[0]
    assert after == before
    assert after["direction"] is None
    assert after["source_adapter"] is None


def test_07b_legacy_delete_item_delete_targets_not_auto_inferred(tmp_path):
    cfg = _cfg(tmp_path)
    item = _make_item("t-legacy-del", "delete", "calculators", "r1", "pending",
                       delete_targets=None)
    _save_queue([dict(item)])
    before = list_all_sync()[0]
    result = retry_pending_sync("t-legacy-del", cfg)
    assert result["result"] == "unsupported"
    after = list_all_sync()[0]
    assert after == before
    assert after["delete_targets"] is None


# ── 10. list_all_sync() 연동 검증(pending/processing/failed_permanent 분리) ──

def test_10_list_all_sync_separates_statuses_correctly(tmp_path):
    items = [
        _make_item("p1", "insert", "calculators", "r1", "pending",
                   direction="sheets_to_sqlite", source_adapter="DualAdapter"),
        _make_item("p2", "insert", "calculators", "r2", "processing",
                   direction="sheets_to_sqlite", source_adapter="DualAdapter"),
        _make_item("p3", "insert", "calculators", "r3", "failed_permanent",
                   retry_count=3, direction="sheets_to_sqlite", source_adapter="DualAdapter"),
    ]
    _save_queue(items)
    assert {i["id"] for i in list_all_sync()} == {"p1", "p2", "p3"}
    assert {i["id"] for i in list_all_sync("pending")} == {"p1"}
    assert {i["id"] for i in list_all_sync("processing")} == {"p2"}
    assert {i["id"] for i in list_all_sync("failed_permanent")} == {"p3"}
    assert {i["id"] for i in list_pending_sync()} == {"p1"}  # 기존 함수도 동일하게 분리 유지


# ── 11. DELETE retry: delete_targets에 지정된 쪽만 실행 ─────────────

def test_11_delete_retry_sqlite_only_does_not_touch_sheets(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sqlite_calls, sheets_calls = [], []
    monkeypatch.setattr(SQLiteAdapter, "delete", lambda self, t, r: sqlite_calls.append((t, r)))
    monkeypatch.setattr(SheetsAdapter, "delete", lambda self, t, r: sheets_calls.append((t, r)))
    item = _make_item("d1", "delete", "calculators", "r1", "pending",
                       delete_targets={"sqlite": True, "sheets": False})
    _save_queue([item])
    result = retry_pending_sync("d1", cfg)
    assert result["result"] == "success"
    assert sqlite_calls == [("calculators", "r1")]
    assert sheets_calls == []


def test_11b_delete_retry_sheets_only_does_not_touch_sqlite(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    sqlite_calls, sheets_calls = [], []
    monkeypatch.setattr(SQLiteAdapter, "delete", lambda self, t, r: sqlite_calls.append((t, r)))
    monkeypatch.setattr(SheetsAdapter, "delete", lambda self, t, r: sheets_calls.append((t, r)))
    item = _make_item("d2", "delete", "calculators", "r2", "pending",
                       delete_targets={"sqlite": False, "sheets": True})
    _save_queue([item])
    result = retry_pending_sync("d2", cfg)
    assert result["result"] == "success"
    assert sqlite_calls == []
    assert sheets_calls == [("calculators", "r2")]


# ── 12. SQLiteFirstAdapter 경로 보호(raw SheetsAdapter 우회 확인) ────

def test_12_sqlite_first_adapter_retry_uses_backup_method_not_raw_sheets_adapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    calls = {"backup_insert": 0, "raw_sheets_insert": 0}

    def _tracked_backup_insert(self, table, row):
        calls["backup_insert"] += 1

    def _tracked_raw_insert(self, table, row):
        calls["raw_sheets_insert"] += 1

    monkeypatch.setattr(SQLiteFirstAdapter, "_backup_insert_to_sheets", _tracked_backup_insert)
    monkeypatch.setattr(SheetsAdapter, "insert", _tracked_raw_insert)

    # 50,000자 초과 — STEP59의 split/placeholder 로직이 실제로 필요한 케이스
    item = _make_item("s1", "insert", "app_templates", "t1", "pending",
                       direction="sqlite_to_sheets", source_adapter="SQLiteFirstAdapter",
                       row={"template_id": "t1", "html_template": "x" * 60000})
    _save_queue([item])
    result = retry_pending_sync("s1", cfg)
    assert result["result"] == "success"
    assert calls["backup_insert"] == 1
    assert calls["raw_sheets_insert"] == 0, "retry 엔진이 SheetsAdapter를 직접 호출하면 안 됨(split 로직 우회 위험)"


# ── Isolation(최우선 보호 조건) ────────────────────────────────────

def test_99_real_production_queue_file_untouched():
    after = hashlib.sha256(_REAL_QUEUE_PATH.read_bytes()).hexdigest()
    assert after == _REAL_QUEUE_HASH_BEFORE
