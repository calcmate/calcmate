# -*- coding: utf-8 -*-
"""tests/test_dual_adapter_delete.py

STEP56: adapters/db/dual_adapter.py::DualAdapter.delete()의 "양쪽 다 실패" 처리
회귀 테스트. insert()/update()는 이미 이 처리를 갖고 있었으나 delete()에만
없었던 것을 STEP56에서 보완했다 — 편측 실패(기존 log-only 동작)는 그대로
유지되는지도 함께 확인한다.

실제 Sheets/SQLite에는 전혀 접근하지 않는다 — DualAdapter._primary/_secondary를
간단한 stub으로 직접 주입한다(생성자를 거치지 않고 인스턴스 속성만 교체).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adapters.db.dual_adapter as dual_adapter_module
from adapters.db.dual_adapter import DualAdapter


@pytest.fixture(autouse=True)
def _isolate_sync_queue_file(tmp_path, monkeypatch):
    """secondary(SQLite) 실패 시 enqueue_sync()가 실제 data/sync/pending_sync.json에
    쓰지 않도록 모듈 상수를 tmp_path로 격리한다(이 fixture가 없으면 이 테스트
    파일이 실제 프로젝트 파일을 오염시킨다 — STEP56에서 실제로 재현되어 즉시
    git checkout으로 원복하고 이 fixture를 추가함)."""
    monkeypatch.setattr(dual_adapter_module, "_SYNC_QUEUE_PATH",
                        tmp_path / "pending_sync.json")


class _StubStorage:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.delete_calls = []

    def delete(self, table, row_id):
        self.delete_calls.append((table, row_id))
        if self.fail:
            raise RuntimeError("storage delete failed")


def _make_dual(primary_fail: bool, secondary_fail: bool) -> DualAdapter:
    dual = DualAdapter.__new__(DualAdapter)  # __init__은 실제 Sheets/SQLite 연결을 시도하므로 우회
    dual._primary = _StubStorage(fail=primary_fail)
    dual._secondary = _StubStorage(fail=secondary_fail)
    return dual


def test_both_succeed_no_exception():
    dual = _make_dual(primary_fail=False, secondary_fail=False)
    dual.delete("calculators", "calc_1")  # 예외 없이 정상 종료
    assert dual._primary.delete_calls == [("calculators", "calc_1")]
    assert dual._secondary.delete_calls == [("calculators", "calc_1")]


def test_sheets_fails_sqlite_succeeds_no_exception():
    """편측 실패는 기존과 동일하게 예외 없이 로그만 남기고 넘어간다(회귀 방지)."""
    dual = _make_dual(primary_fail=True, secondary_fail=False)
    dual.delete("calculators", "calc_1")  # 예외 발생하면 안 됨
    assert dual._secondary.delete_calls == [("calculators", "calc_1")]


def test_sqlite_fails_sheets_succeeds_no_exception():
    """편측 실패는 기존과 동일하게 예외 없이 로그(+재시도 큐 적재)만 남기고 넘어간다."""
    dual = _make_dual(primary_fail=False, secondary_fail=True)
    dual.delete("calculators", "calc_1")  # 예외 발생하면 안 됨
    assert dual._primary.delete_calls == [("calculators", "calc_1")]


def test_both_fail_raises_runtime_error():
    """STEP56 수정 대상 — 이전에는 예외 없이 조용히 반환됐다."""
    dual = _make_dual(primary_fail=True, secondary_fail=True)
    with pytest.raises(RuntimeError, match="both storages failed for delete"):
        dual.delete("calculators", "calc_1")


def test_both_fail_still_attempts_both_before_raising():
    """양쪽 다 시도는 하되(부분 정보 보존 목적) 최종적으로만 예외를 던지는지 확인."""
    dual = _make_dual(primary_fail=True, secondary_fail=True)
    with pytest.raises(RuntimeError):
        dual.delete("calculators", "calc_1")
    assert dual._primary.delete_calls == [("calculators", "calc_1")]
    assert dual._secondary.delete_calls == [("calculators", "calc_1")]
