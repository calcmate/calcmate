# -*- coding: utf-8 -*-
"""tests/test_calculator_site_sync_record.py

STEP51: modules/calculator_site_sync.run_calculator_site_sync_and_log()의
sync_runs/sync_log_calculator_entries 저장 + Telegram 연결 회귀 테스트.

STEP50에서 확인된 구조적 공백(SQLite↔_site 축이 record/Telegram에 연결되어
있지 않음)을 메우는 신규 코드에 대한 테스트다. 기존 SQLite↔Sheets 쪽
(modules/calculator_3way_sync.py, tests/test_calculator_3way_sync_record.py 등)은
이 파일에서 전혀 건드리지 않는다 — 완전히 별개의 target("calculators_site")과
완전히 별개의 함수(run_calculator_site_sync_and_log)로 격리돼 있다.

Production `_site`/DB/Sheets/Telegram은 전혀 건드리지 않는다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.sync_log_calculator_repository import SyncLogCalculatorRepository
from repositories.sync_log_repository import SyncLogRepository
from modules.calculator_site_sync import (
    compare_calculators_sqlite_vs_site,
    run_calculator_site_sync_and_log,
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


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기",
          input_schema='{"avg_wage": "number"}', output_schema='{"result": "number"}'):
    return {"id": id, "slug": slug, "name": name,
            "input_schema": input_schema, "output_schema": output_schema}


def _write_site_page(site_dir: Path, slug: str, sm_config: dict):
    import json
    page_dir = site_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    body = f"window.SM_CONFIG = {json.dumps(sm_config, ensure_ascii=False)};"
    html = f"<html><head></head><body><script>{body}</script></body></html>"
    (page_dir / "index.html").write_text(html, encoding="utf-8")


def _log_repo(tmp_path) -> SyncLogCalculatorRepository:
    cfg = {"SQLITE_PATH": "test_site_sync_log.db", "_root": str(tmp_path)}
    return SyncLogCalculatorRepository(SQLiteAdapter(cfg))


def _matching_sm_config(slug="test-calc", name="테스트 계산기", input_type="number"):
    return {
        "name": name, "slug": slug,
        "inputs": [{"name": "avg_wage", "label": "x", "type": input_type, "unit": ""}],
        "outputs": [{"key": "result", "label": "y", "unit": ""}],
    }


# ── A. SQLite↔_site INFO 결과가 record adapter로 전달되는지 ──────────────

def test_a_info_result_is_saved_to_record(tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc()
    _write_site_page(site_dir, "test-calc", _matching_sm_config())
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["result"] == "PASS"
    assert out["log_result"] == "saved"
    assert out["run_id"] is not None
    assert out["run_id"].startswith("sync_calculators_site_")

    run_row = log_repo.get_run(out["run_id"])
    assert run_row["target"] == "calculators_site"
    assert run_row["result"] == "PASS"

    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert len(entries) == 1
    assert entries[0]["severity"] == "INFO"


# ── B. normalization으로 INFO가 된 항목에 metadata가 남는지 ─────────────

def test_b_normalized_match_leaves_trace_in_reasons(tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc(input_schema='{"avg_wage": "integer"}')  # SQLite=integer
    _write_site_page(site_dir, "test-calc", _matching_sm_config(input_type="number"))  # _site=number
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["severity"][SEVERITY_INFO] == 1  # 정규화로 INFO
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "INFO"
    assert "normalized:integer_to_number" in entries[0]["reasons"]


def test_b2_numeric_select_normalized_match_leaves_trace(tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc(input_schema='{"avg_wage": "select:1=a,2=b"}')
    _write_site_page(site_dir, "test-calc", _matching_sm_config(input_type="number"))
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert "normalized:numeric_select_to_number" in entries[0]["reasons"]


# ── C. 원래부터 동일한 number↔number에는 metadata가 없는지 ──────────────

def test_c_originally_matching_has_no_normalization_trace(tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc(input_schema='{"avg_wage": "number"}')
    _write_site_page(site_dir, "test-calc", _matching_sm_config(input_type="number"))
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["reasons"] == "no_change"
    assert "normalized:" not in entries[0]["reasons"]


# ── D. non-numeric select mismatch는 FAIL로 유지되는지(record까지) ──────

def test_d_non_numeric_select_stays_fail_through_record(tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc(input_schema='{"avg_wage": "select:a=x,b=y"}')
    _write_site_page(site_dir, "test-calc", _matching_sm_config(input_type="number"))
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["result"] == "FAIL"
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "FAIL"
    assert "inputs_mismatch" in entries[0]["reasons"]
    assert "normalized:" not in entries[0]["reasons"]  # number로 승격되지 않았으므로 흔적 없음


# ── E. CRITICAL 3건 유형(missing _site)이 record를 거쳐도 CRITICAL 유지 ──

def test_e_missing_site_page_stays_critical_through_record(tmp_path):
    site_dir = tmp_path / "_site"
    site_dir.mkdir(parents=True, exist_ok=True)
    calc = _calc(slug="no-such-page")
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["result"] == "CRITICAL"
    entries = log_repo.get_calculator_entries_by_run(out["run_id"])
    assert entries[0]["severity"] == "CRITICAL"
    assert entries[0]["reasons"] == "index_html_missing"


# ── F. SQLite↔Sheets 축과 완전히 분리(같은 DB에 공존해도 서로 영향 없음) ──

def test_f_site_axis_and_sheets_axis_runs_coexist(tmp_path):
    """calculator_3way_sync.py(Sheets 축)를 이 파일에서 직접 호출하진 않지만,
    같은 sync_runs 테이블에 target만 다르게 공존 가능한지 확인한다(스키마 공유
    가능성 검증 — STEP51 §2 결정 사항의 실증)."""
    site_dir = tmp_path / "_site"
    calc = _calc()
    _write_site_page(site_dir, "test-calc", _matching_sm_config())
    log_repo = _log_repo(tmp_path)

    site_out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    # 동일 SyncLogCalculatorRepository로 target="calculators"(Sheets 축 관례)의
    # run을 하나 더 얹어도 충돌 없이 공존하는지 확인.
    sheets_like_run_id = "sync_calculators_99999999999999_zzzz"
    log_repo.create_run({
        "run_id": sheets_like_run_id, "target": "calculators",
        "started_at": "t0", "finished_at": "t1", "duration_ms": 1,
        "result": "PASS", "total_count": 1, "info_count": 1,
        "warn_count": 0, "fail_count": 0, "critical_count": 0,
    })

    assert log_repo.get_run(site_out["run_id"])["target"] == "calculators_site"
    assert log_repo.get_run(sheets_like_run_id)["target"] == "calculators"
    assert site_out["run_id"] != sheets_like_run_id


# ── G. Telegram(mock) — INFO/PASS 미전송, WARN/FAIL/CRITICAL 전송 ────────

@patch("modules.telegram_ops.notify_level")
def test_g1_pass_does_not_call_telegram(mock_notify, tmp_path):
    site_dir = tmp_path / "_site"
    calc = _calc()
    _write_site_page(site_dir, "test-calc", _matching_sm_config())
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["result"] == "PASS"
    assert out["telegram_result"] == "skipped"
    mock_notify.assert_not_called()


@patch("modules.telegram_ops.notify_level")
def test_g2_critical_calls_telegram_with_correct_target_label(mock_notify, tmp_path):
    site_dir = tmp_path / "_site"
    site_dir.mkdir(parents=True, exist_ok=True)
    calc = _calc(slug="no-such-page")
    log_repo = _log_repo(tmp_path)

    out = run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert out["result"] == "CRITICAL"
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    detail = args[3] if len(args) > 3 else kwargs.get("detail", "")
    assert level == "CRITICAL"
    assert kwargs.get("event") == "sync_mismatch"
    assert "calculators_site" in detail  # target이 Sheets 축과 혼동되지 않게 명시됨


# ── H. 원본 SQLite schema/_site input은 변경되지 않는지(record까지 포함) ──

def test_h_original_schema_and_site_files_untouched_through_record(tmp_path):
    site_dir = tmp_path / "_site"
    original_input_schema = '{"avg_wage": "integer"}'
    calc = _calc(input_schema=original_input_schema)
    _write_site_page(site_dir, "test-calc", _matching_sm_config())
    log_repo = _log_repo(tmp_path)

    index_path = site_dir / "test-calc" / "index.html"
    before_html = index_path.read_text(encoding="utf-8")

    run_calculator_site_sync_and_log(
        {}, sqlite_repo=_StubRepo([calc]), site_dir=site_dir, log_repo=log_repo)

    assert calc["input_schema"] == original_input_schema  # dict 필드 그대로
    assert index_path.read_text(encoding="utf-8") == before_html  # 파일 무변경
