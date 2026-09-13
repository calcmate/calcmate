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
  - Dashboard의 결과-분기 코드(dashboard.py 실제 소스, 수정 없이 그대로)가
    mocked retry_pending_sync()의 반환값에 따라 의도한 st.* 위젯을 호출하는지
를 명시적으로 커버한다.

이 파일은 dashboard.py를 import하거나 실행하지 않는다. 대신 "🔁 동기화 복구"
탭의 실제 소스 텍스트를 파일에서 그대로 읽어(수정 없이) exec()로 격리
실행한다 — st 모듈과 adapters.db.dual_adapter의 3개 함수만 mock으로 주입한다.
이렇게 하면 dashboard.py 코드를 1바이트도 바꾸지 않고 실제 분기 로직을
검증할 수 있다(STEP61에서 확인된 대로, dashboard.py 전체를 실행하면 실제
config.yaml 기반 스케줄러 스레드가 기동될 위험이 있어 회피한다).

최우선 보호 조건: 이 파일의 모든 테스트는 tmp_path/monkeypatch로
_SYNC_QUEUE_PATH를 격리한다. 실제 data/sync/pending_sync.json은 이 파일
실행 전후로 완전히 동일해야 한다(마지막 테스트에서 SHA256 재확인).
"""
import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
_DASHBOARD_SRC = (Path(__file__).resolve().parent.parent / "dashboard.py").read_text(encoding="utf-8")


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


# ── 8/9. Dashboard UI 결과 분기 검증(dashboard.py 소스를 수정 없이 격리 실행) ──

def _tab_source() -> str:
    marker = 'elif tab == "🔁 동기화 복구":'
    idx = _DASHBOARD_SRC.index(marker)
    return _DASHBOARD_SRC[idx:].replace('elif tab ==', 'if tab ==', 1)


def _run_tab_with_mocks(pending_items, processing_items, failed_items,
                         retry_return, clicked_key, resume_return=None,
                         checkbox_checked=True, resume_clicked_key=None):
    """dashboard.py의 "🔁 동기화 복구" 탭 소스를 1바이트도 바꾸지 않고 그대로
    읽어 exec()로 격리 실행한다. st와 adapters.db.dual_adapter의 4개 함수만
    mock으로 주입 — dashboard.py 파일 자체는 이 테스트에서 전혀 수정하지 않는다.

    st.button은 실제 Streamlit처럼 disabled=True면 클릭 여부와 무관하게
    항상 False를 반환하도록 흉내낸다(재개 확인 버튼의 checkbox-gate 검증용)."""
    mock_st = MagicMock()
    mock_st.expander.return_value.__exit__.return_value = False  # 예외 삼키지 않음
    mock_st.checkbox.return_value = checkbox_checked

    def _button(*args, **kwargs):
        if kwargs.get("disabled"):
            return False
        key = kwargs.get("key")
        return key == clicked_key or key == resume_clicked_key
    mock_st.button.side_effect = _button

    import adapters.db.dual_adapter as dam
    orig = (dam.list_pending_sync, dam.list_all_sync, dam.retry_pending_sync, dam.resume_failed_sync)
    dam.list_pending_sync = lambda: pending_items
    dam.list_all_sync = lambda status=None: {
        "processing": processing_items, "failed_permanent": failed_items,
    }.get(status, pending_items + processing_items + failed_items)
    dam.retry_pending_sync = lambda qid, cfg: retry_return
    dam.resume_failed_sync = lambda qid: resume_return
    try:
        namespace = {"st": mock_st, "cfg": {}, "tab": "🔁 동기화 복구"}
        exec(compile(_tab_source(), "<dashboard_sync_recovery_tab>", "exec"), namespace)
    finally:
        (dam.list_pending_sync, dam.list_all_sync,
         dam.retry_pending_sync, dam.resume_failed_sync) = orig
    return mock_st


_FAKE_ITEM = {
    "id": "qid1", "op": "update", "table": "calculators", "row_id": "r1",
    "direction": "sheets_to_sqlite", "source_adapter": "DualAdapter",
    "retry_count": 0, "status": "pending", "error": "e",
    "created_at": "t0", "last_attempt_at": None, "delete_targets": None,
}


@pytest.mark.parametrize("result_value,expect_widget", [
    ({"result": "success", "detail": "ok-success"}, "success"),
    ({"result": "failed", "detail": "ok-failed"}, "error"),
    ({"result": "not_found", "detail": "ok-not-found"}, "warning"),
    ({"result": "duplicate", "detail": "ok-duplicate"}, "warning"),
    ({"result": "unsupported", "detail": "ok-unsupported"}, "warning"),
])
def test_09_ui_branch_calls_expected_widget_per_result(result_value, expect_widget):
    mock_st = _run_tab_with_mocks(
        pending_items=[dict(_FAKE_ITEM)], processing_items=[], failed_items=[],
        retry_return=result_value, clicked_key="retry_qid1")

    widget = getattr(mock_st, expect_widget)
    widget.assert_called_once_with(result_value["detail"])
    mock_st.rerun.assert_called_once()
    for other in ("success", "error", "warning"):
        if other != expect_widget:
            getattr(mock_st, other).assert_not_called()


def test_08_processing_item_renders_without_retry_button_call(monkeypatch):
    """processing 항목만 있을 때는 st.button이 '🔁 Retry'로 호출되지 않아야 한다
    (버튼 자체가 렌더링되지 않음 — key가 어떤 retry_* 로도 클릭되지 않게 강제)."""
    proc_item = dict(_FAKE_ITEM, id="qidproc", status="processing")
    mock_st = _run_tab_with_mocks(
        pending_items=[], processing_items=[proc_item], failed_items=[],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key="retry_qidproc")  # 눌렸다고 가정해도 버튼 자체가 없어야 함
    button_keys = [kw.get("key") for _, kw in mock_st.button.call_args_list]
    assert "retry_qidproc" not in button_keys
    mock_st.success.assert_not_called()
    mock_st.error.assert_not_called()


def test_08b_failed_permanent_item_renders_without_retry_button_call():
    fp_item = dict(_FAKE_ITEM, id="qidfp", status="failed_permanent", retry_count=3)
    mock_st = _run_tab_with_mocks(
        pending_items=[], processing_items=[], failed_items=[fp_item],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key="retry_qidfp")
    button_keys = [kw.get("key") for _, kw in mock_st.button.call_args_list]
    assert "retry_qidfp" not in button_keys


def test_08c_legacy_item_renders_without_retry_button_call():
    legacy_item = dict(_FAKE_ITEM, id="qidlegacy", direction=None, source_adapter=None)
    mock_st = _run_tab_with_mocks(
        pending_items=[legacy_item], processing_items=[], failed_items=[],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key="retry_qidlegacy")
    button_keys = [kw.get("key") for _, kw in mock_st.button.call_args_list]
    assert "retry_qidlegacy" not in button_keys


# ── 10. Dashboard 재개(resume) UX 검증(STEP65) ──────────────────────

_FP_ITEM = dict(_FAKE_ITEM, id="fpqid1", status="failed_permanent", retry_count=3)


def test_10a_resume_confirm_button_disabled_when_checkbox_unchecked():
    """checkbox 미체크 시 '재개 확인' 버튼은 disabled=True로 렌더링되어,
    클릭을 시도해도(key 일치) 실제로는 눌리지 않는다(resume_failed_sync 미호출)."""
    mock_st = _run_tab_with_mocks(
        pending_items=[], processing_items=[], failed_items=[dict(_FP_ITEM)],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key=None, resume_return={"result": "success", "detail": "should-not-fire"},
        checkbox_checked=False, resume_clicked_key="confirm_resume_fpqid1")

    # button()이 disabled=True로 호출됐는지 확인(실제 UI가 비활성 상태로 렌더링됨)
    disabled_calls = [kw for _, kw in mock_st.button.call_args_list
                       if kw.get("key") == "confirm_resume_fpqid1"]
    assert disabled_calls and disabled_calls[0].get("disabled") is True
    mock_st.success.assert_not_called()
    mock_st.warning.assert_not_called()


def test_10b_resume_confirm_button_enabled_when_checkbox_checked_and_success():
    mock_st = _run_tab_with_mocks(
        pending_items=[], processing_items=[], failed_items=[dict(_FP_ITEM)],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key=None, resume_return={"result": "success", "detail": "resumed-ok"},
        checkbox_checked=True, resume_clicked_key="confirm_resume_fpqid1")

    disabled_calls = [kw for _, kw in mock_st.button.call_args_list
                       if kw.get("key") == "confirm_resume_fpqid1"]
    assert disabled_calls and disabled_calls[0].get("disabled") is False
    mock_st.success.assert_called_once_with("resumed-ok")
    mock_st.rerun.assert_called_once()


def test_10c_resume_unsupported_result_uses_st_warning():
    mock_st = _run_tab_with_mocks(
        pending_items=[], processing_items=[], failed_items=[dict(_FP_ITEM)],
        retry_return={"result": "success", "detail": "unused"},
        clicked_key=None, resume_return={"result": "unsupported", "detail": "cannot-resume"},
        checkbox_checked=True, resume_clicked_key="confirm_resume_fpqid1")

    mock_st.warning.assert_called_once_with("cannot-resume")
    mock_st.rerun.assert_called_once()
    mock_st.success.assert_not_called()


# ── Isolation(최우선 보호 조건) ────────────────────────────────────

def test_99_real_production_queue_file_untouched():
    after = hashlib.sha256(_REAL_QUEUE_PATH.read_bytes()).hexdigest()
    assert after == _REAL_QUEUE_HASH_BEFORE
