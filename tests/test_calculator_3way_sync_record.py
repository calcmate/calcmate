# -*- coding: utf-8 -*-
"""tests/test_calculator_3way_sync_record.py

STEP37: modules/calculator_3way_sync.run_calculator_3way_sync_and_log() 회귀 테스트.

Production SQLite/Sheets는 전혀 접근하지 않는다. drift 판정 입력은 STEP35와
동일한 스텁 Repository로 격리하고, 로그 저장은 tmp_path SQLiteAdapter로
격리한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.sync_log_calculator_repository import SyncLogCalculatorRepository
from modules.calculator_3way_sync import (
    compare_calculators_sqlite_vs_sheets,
    run_calculator_3way_sync_and_log,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SEVERITY_FAIL,
    SEVERITY_CRITICAL,
)


class _StubRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


class _FailingRepo:
    def get_all(self):
        raise RuntimeError("boom")


class _FailingLogRepo:
    """create_run()에서 항상 실패하는 로그 Repository — 로그 저장 실패 격리 검증용."""
    def create_run(self, run):
        raise RuntimeError("log db down")

    def insert_calculator_entry(self, entry):
        raise RuntimeError("log db down")


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기", status="active",
          category="labor", review_score="80", review_status="AUTO_APPROVED",
          review_attempts="0", reviewed_at="2026-01-01T00:00:00"):
    return {"id": id, "slug": slug, "name": name, "status": status, "category": category,
            "review_score": review_score, "review_status": review_status,
            "review_attempts": review_attempts, "reviewed_at": reviewed_at}


def _log_repo(tmp_path) -> SyncLogCalculatorRepository:
    cfg = {"SQLITE_PATH": "test_wrapper_sync_log.db", "_root": str(tmp_path)}
    return SyncLogCalculatorRepository(SQLiteAdapter(cfg))


# ── all match → PASS ──────────────────────────────────────────────────

def test_all_match_result_is_pass_and_logs_all_entries(tmp_path):
    rows = [_calc(id=f"calc_{i}", slug=f"slug-{i}") for i in range(5)]
    sheets_rows = [dict(r) for r in rows]
    log_repo = _log_repo(tmp_path)

    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo(rows), sheets_repo=_StubRepo(sheets_rows), log_repo=log_repo)

    assert out["result"] == "PASS"
    assert out["log_result"] == "saved"
    assert out["run_id"] is not None

    run_row = log_repo.get_run(out["run_id"])
    assert run_row["result"] == "PASS"
    assert run_row["total_count"] == "5"

    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert len(entries) == 5
    assert all(e["severity"] == "INFO" for e in entries)


# ── WARN 1 → WARN ─────────────────────────────────────────────────────

def test_one_warn_makes_result_warn(tmp_path):
    sqlite_row = _calc(reviewed_at="2026-01-01T00:00:00.055444")
    sheets_row = _calc(reviewed_at="2026-01-01 00:00:00")
    log_repo = _log_repo(tmp_path)

    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=log_repo)

    assert out["result"] == "WARN"
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "WARN"
    assert entries[0]["reasons"] == "reviewed_at_mismatch"  # "_changed" -> "_mismatch" 변환 확인


# ── FAIL → FAIL ───────────────────────────────────────────────────────

def test_fail_makes_result_fail(tmp_path):
    sqlite_row = _calc(status="active")
    sheets_row = _calc(status="draft")
    log_repo = _log_repo(tmp_path)

    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=log_repo)

    assert out["result"] == "FAIL"
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "FAIL"
    assert entries[0]["reasons"] == "status_mismatch"


# ── CRITICAL → CRITICAL ───────────────────────────────────────────────

def test_missing_in_sheets_makes_result_critical(tmp_path):
    sqlite_row = _calc(id="calc_only_sqlite")
    log_repo = _log_repo(tmp_path)

    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([]),
        log_repo=log_repo)

    assert out["result"] == "CRITICAL"
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "CRITICAL"
    assert entries[0]["reasons"] == "missing_in_sheets"


# ── mixed severity → highest severity ────────────────────────────────

def test_mixed_severity_picks_highest(tmp_path):
    info_pair_sqlite = _calc(id="calc_info", slug="calc-info")
    info_pair_sheets = dict(info_pair_sqlite)

    warn_sqlite = _calc(id="calc_warn", slug="calc-warn", reviewed_at="2026-01-01T00:00:00.055444")
    warn_sheets = _calc(id="calc_warn", slug="calc-warn", reviewed_at="2026-01-01 00:00:00")

    fail_sqlite = _calc(id="calc_fail", slug="calc-fail", status="active")
    fail_sheets = _calc(id="calc_fail", slug="calc-fail", status="draft")

    critical_only_sqlite = _calc(id="calc_critical", slug="calc-critical")

    sqlite_rows = [info_pair_sqlite, warn_sqlite, fail_sqlite, critical_only_sqlite]
    sheets_rows = [info_pair_sheets, warn_sheets, fail_sheets]  # calc_critical 누락 -> CRITICAL

    log_repo = _log_repo(tmp_path)
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo(sqlite_rows), sheets_repo=_StubRepo(sheets_rows),
        log_repo=log_repo)

    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_WARN] == 1
    assert out["severity"][SEVERITY_FAIL] == 1
    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["result"] == "CRITICAL"  # CRITICAL > FAIL > WARN 우선순위


# ── 로그 저장 실패가 drift 판정 결과를 바꾸지 않는다 ──────────────────

def test_log_persistence_failure_does_not_change_drift_result():
    sqlite_row = _calc(status="active")
    sheets_row = _calc(status="draft")

    direct = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([dict(sheets_row)]))
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([dict(sheets_row)]),
        log_repo=_FailingLogRepo())

    # drift 판정 관련 키는 로그 저장 성공 여부와 무관하게 완전히 동일해야 한다.
    for key in ("total", "matched", "mismatched", "missing_in_sqlite",
                "missing_in_sheets", "changed_fields", "severity", "reasons", "results"):
        assert out[key] == direct[key]

    assert out["result"] == "FAIL"       # 판정 결과 자체는 정상 산출됨
    assert out["log_result"] == "failed"  # 로그 저장만 실패로 기록됨
    assert out["run_id"] is None
    assert out["log_error"] is not None
