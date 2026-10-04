# -*- coding: utf-8 -*-
"""tests/test_sync_log_calculator_repository.py

STEP37: SyncLogCalculatorRepository(sync_runs 공용 재사용 + 신규
sync_log_calculator_entries) 회귀 테스트. Production DB는 전혀 건드리지
않는다 — tmp_path에 격리된 SQLiteAdapter만 사용한다.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.sync_log_calculator_repository import SyncLogCalculatorRepository
from repositories.sync_log_repository import SyncLogRepository, generate_run_id, generate_entry_id


def _repo(tmp_path) -> SyncLogCalculatorRepository:
    cfg = {"SQLITE_PATH": "test_calc_sync_log.db", "_root": str(tmp_path)}
    return SyncLogCalculatorRepository(SQLiteAdapter(cfg))


def _run_payload(run_id, **overrides):
    base = {
        "run_id": run_id, "target": "calculators",
        "started_at": "2026-09-12T00:00:00", "finished_at": "2026-09-12T00:00:01",
        "duration_ms": 1000, "result": "PASS",
        "total_count": 19, "info_count": 19, "warn_count": 0,
        "fail_count": 0, "critical_count": 0,
    }
    base.update(overrides)
    return base


def _entry_payload(run_id, calc_id, **overrides):
    base = {
        "entry_id": f"log_calculators_test_{calc_id}", "run_id": run_id,
        "calculator_id": calc_id, "slug": calc_id.replace("calc_", "slug-"),
        "severity": "INFO", "reasons": "no_change", "checked_at": "2026-09-12T00:00:01",
    }
    base.update(overrides)
    return base


# ── run insert ───────────────────────────────────────────────────────

def test_run_insert_and_get(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000000_aaaa"
    repo.create_run(_run_payload(run_id))

    row = repo.get_run(run_id)
    assert row is not None
    assert row["target"] == "calculators"
    assert row["result"] == "PASS"
    assert row["total_count"] == "19"  # falsy 직렬화 대응으로 문자열화되어 저장


def test_create_run_missing_field_raises(tmp_path):
    repo = _repo(tmp_path)
    payload = _run_payload("sync_calculators_x")
    del payload["fail_count"]
    with pytest.raises(ValueError):
        repo.create_run(payload)


# ── INFO / WARN entry insert ─────────────────────────────────────────

def test_info_entry_insert(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000001_bbbb"
    repo.create_run(_run_payload(run_id))
    repo.insert_calculator_entry(_entry_payload(run_id, "calc_1", severity="INFO", reasons="no_change"))

    entries = repo.get_calculator_entries_by_run(run_id)
    assert len(entries) == 1
    assert entries[0]["severity"] == "INFO"
    assert entries[0]["reasons"] == "no_change"


def test_warn_entry_insert(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000002_cccc"
    repo.create_run(_run_payload(run_id, warn_count=1))
    repo.insert_calculator_entry(_entry_payload(
        run_id, "calc_20260805121653_0065", slug="severance-pay",
        severity="WARN", reasons="reviewed_at_mismatch"))

    entries = repo.get_calculator_entries_by_run(run_id)
    assert entries[0]["severity"] == "WARN"
    assert entries[0]["reasons"] == "reviewed_at_mismatch"
    assert entries[0]["slug"] == "severance-pay"


# ── multiple entries ──────────────────────────────────────────────────

def test_multiple_calculator_entries_under_same_run(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000003_dddd"
    repo.create_run(_run_payload(run_id, total_count=3))
    for i in range(3):
        repo.insert_calculator_entry(_entry_payload(run_id, f"calc_{i}"))

    entries = repo.get_calculator_entries_by_run(run_id)
    assert len(entries) == 3


# ── duplicate (run_id, calculator_id) blocked ────────────────────────

def test_duplicate_run_id_calculator_id_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000004_eeee"
    repo.create_run(_run_payload(run_id))
    repo.insert_calculator_entry(_entry_payload(run_id, "calc_dup", entry_id="log_a"))
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_calculator_entry(_entry_payload(run_id, "calc_dup", entry_id="log_b"))


# ── missing required field blocked ───────────────────────────────────

def test_insert_calculator_entry_missing_field_raises(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000005_ffff"
    repo.create_run(_run_payload(run_id))
    payload = _entry_payload(run_id, "calc_x")
    del payload["slug"]
    with pytest.raises(ValueError):
        repo.insert_calculator_entry(payload)


def test_insert_calculator_entry_rejects_forbidden_fields(tmp_path):
    repo = _repo(tmp_path)
    run_id = "sync_calculators_20260912000006_0000"
    repo.create_run(_run_payload(run_id))
    payload = _entry_payload(run_id, "calc_y")
    payload["content"] = "본문 유출 금지"
    with pytest.raises(ValueError):
        repo.insert_calculator_entry(payload)


# ── run_id 생성기: target 포함, 유일성 ───────────────────────────────

def test_generate_run_id_includes_target():
    run_id = generate_run_id("calculators")
    assert run_id.startswith("sync_calculators_")


def test_generate_entry_id_includes_target():
    entry_id = generate_entry_id("calculators")
    assert entry_id.startswith("log_calculators_")


def test_generate_run_id_is_unique_across_calls():
    ids = {generate_run_id("calculators") for _ in range(20)}
    assert len(ids) == 20


# ── 기존 Blog 로그 데이터와 충돌 없음(같은 테이블 공유) ───────────────

def test_calculator_and_blog_runs_coexist_without_collision(tmp_path):
    cfg = {"SQLITE_PATH": "test_shared_sync_runs.db", "_root": str(tmp_path)}
    adapter = SQLiteAdapter(cfg)
    blog_repo = SyncLogRepository(adapter)
    calc_repo = SyncLogCalculatorRepository(adapter)

    blog_run_id = "sync_20260912140906_a167"  # 기존 Blog 방식(target 미포함)
    calc_run_id = generate_run_id("calculators")

    blog_repo.insert_run({
        "run_id": blog_run_id, "target": "blog_articles",
        "started_at": "t0", "finished_at": "t1", "duration_ms": 100,
        "result": "PASS", "total_count": 10, "info_count": 10,
        "warn_count": 0, "fail_count": 0, "critical_count": 0,
    })
    calc_repo.create_run(_run_payload(calc_run_id))

    assert blog_repo.get_run(blog_run_id) is not None
    assert calc_repo.get_run(calc_run_id) is not None
    assert blog_run_id != calc_run_id
