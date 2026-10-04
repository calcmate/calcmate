# -*- coding: utf-8 -*-
"""tests/test_calculator_3way_sync_telegram.py

STEP38: run_calculator_3way_sync_and_log()의 Telegram sync_mismatch 연결
회귀 테스트. 실제 Telegram Bot API는 절대 호출하지 않는다 —
modules.telegram_ops.notify_level을 mock으로 대체한다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.sync_log_calculator_repository import SyncLogCalculatorRepository
from modules.calculator_3way_sync import run_calculator_3way_sync_and_log


class _StubRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기", status="active",
          category="labor", review_score="80", review_status="AUTO_APPROVED",
          review_attempts="0", reviewed_at="2026-01-01T00:00:00"):
    return {"id": id, "slug": slug, "name": name, "status": status, "category": category,
            "review_score": review_score, "review_status": review_status,
            "review_attempts": review_attempts, "reviewed_at": reviewed_at}


def _log_repo(tmp_path) -> SyncLogCalculatorRepository:
    cfg = {"SQLITE_PATH": "test_telegram_sync_log.db", "_root": str(tmp_path)}
    return SyncLogCalculatorRepository(SQLiteAdapter(cfg))


# ── 1/2. PASS(전부 INFO) → Telegram 미호출 ───────────────────────────

@patch("modules.telegram_ops.notify_level")
def test_pass_all_info_does_not_call_telegram(mock_notify, tmp_path):
    rows = [_calc(id=f"calc_{i}", slug=f"slug-{i}") for i in range(5)]
    sheets_rows = [dict(r) for r in rows]
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo(rows), sheets_repo=_StubRepo(sheets_rows),
        log_repo=_log_repo(tmp_path))

    assert out["result"] == "PASS"
    assert out["telegram_result"] == "skipped"
    mock_notify.assert_not_called()


# ── 3. WARN → WARNING 레벨 호출 ──────────────────────────────────────

@patch("modules.telegram_ops.notify_level")
def test_warn_calls_notify_level_warning(mock_notify, tmp_path):
    sqlite_row = _calc(reviewed_at="2026-01-01T00:00:00.055444")
    sheets_row = _calc(reviewed_at="2026-01-01 00:00:00")
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=_log_repo(tmp_path))

    assert out["result"] == "WARN"
    assert out["telegram_result"] == "sent"
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "WARNING"
    assert kwargs.get("event") == "sync_mismatch"


# ── 4. FAIL → ERROR 레벨 호출 ─────────────────────────────────────────

@patch("modules.telegram_ops.notify_level")
def test_fail_calls_notify_level_error(mock_notify, tmp_path):
    sqlite_row = _calc(status="active")
    sheets_row = _calc(status="draft")
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=_log_repo(tmp_path))

    assert out["result"] == "FAIL"
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "ERROR"


# ── 5. CRITICAL → CRITICAL 레벨 호출 ──────────────────────────────────

@patch("modules.telegram_ops.notify_level")
def test_critical_calls_notify_level_critical(mock_notify, tmp_path):
    sqlite_row = _calc(id="calc_only_sqlite")
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([]),
        log_repo=_log_repo(tmp_path))

    assert out["result"] == "CRITICAL"
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "CRITICAL"


# ── 6/7. 메시지에 run_id / calculator_id / slug / reason 포함 ────────

@patch("modules.telegram_ops.notify_level")
def test_message_contains_run_id_calc_id_slug_reason(mock_notify, tmp_path):
    sqlite_row = _calc(id="calc_20260805121653_0065", slug="severance-pay",
                       reviewed_at="2026-08-07T11:50:10.055444")
    sheets_row = _calc(id="calc_20260805121653_0065", slug="severance-pay",
                       reviewed_at="2026-08-07 11:50:10")
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=_log_repo(tmp_path))

    args, kwargs = mock_notify.call_args
    detail = args[3] if len(args) > 3 else kwargs.get("detail", "")
    full_text = " ".join(str(a) for a in args) + " " + str(kwargs)
    assert out["run_id"] in full_text
    assert "calc_20260805121653_0065" in full_text
    assert "severance-pay" in full_text
    assert "reviewed_at_mismatch" in full_text


# ── 8. content/HTML/시크릿/원본 timestamp 값 미포함 ───────────────────

@patch("modules.telegram_ops.notify_level")
def test_message_excludes_raw_timestamps_and_html(mock_notify, tmp_path):
    sqlite_row = _calc(reviewed_at="2026-08-07T11:50:10.055444")
    sheets_row = _calc(reviewed_at="2026-08-07 11:50:10")
    run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=_log_repo(tmp_path))

    args, kwargs = mock_notify.call_args
    full_text = " ".join(str(a) for a in args) + " " + str(kwargs)
    # 원본 timestamp 값(before/after)은 절대 포함되면 안 됨 — 정규화된 reason만.
    assert "2026-08-07T11:50:10.055444" not in full_text
    assert "2026-08-07 11:50:10" not in full_text
    assert "<html" not in full_text.lower()
    assert "<script" not in full_text.lower()


# ── 9. Telegram 예외 발생 → drift 결과 유지 ──────────────────────────

@patch("modules.telegram_ops.notify_level", side_effect=RuntimeError("telegram down"))
def test_telegram_exception_does_not_change_drift_result(mock_notify, tmp_path):
    sqlite_row = _calc(status="active")
    sheets_row = _calc(status="draft")
    out = run_calculator_3way_sync_and_log(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]),
        log_repo=_log_repo(tmp_path))

    assert out["result"] == "FAIL"          # drift 판정은 그대로
    assert out["log_result"] == "saved"     # DB 로그 저장도 영향 없음
    assert out["telegram_result"] == "failed"
    assert out["telegram_error"] is not None
