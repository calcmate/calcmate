# -*- coding: utf-8 -*-
"""tests/test_calculator_3way_sync.py

STEP35: modules/calculator_3way_sync.compare_calculators_sqlite_vs_sheets() 회귀 테스트.

Production SQLite/Sheets는 전혀 접근하지 않는다 — get_all()만 구현한 스텁
Repository를 주입해 완전히 격리된 상태에서 비교 로직만 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_3way_sync import (
    compare_calculators_sqlite_vs_sheets,
    _normalize,
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


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기", status="active",
          category="labor", review_score="80", review_status="AUTO_APPROVED",
          review_attempts="0", reviewed_at="2026-01-01T00:00:00"):
    return {"id": id, "slug": slug, "name": name, "status": status, "category": category,
            "review_score": review_score, "review_status": review_status,
            "review_attempts": review_attempts, "reviewed_at": reviewed_at}


# ── _normalize() 단위 테스트 ────────────────────────────────────────

def test_normalize_none_and_empty_string_are_equal():
    assert _normalize(None) == _normalize("")


def test_normalize_zero_variants_are_equal():
    assert _normalize(0) == _normalize("0") == _normalize(0.0) == _normalize(False)


def test_normalize_positive_number_variants_are_equal():
    assert _normalize(80) == _normalize("80") == _normalize(80.0)


def test_normalize_does_not_mutate_plain_strings():
    assert _normalize("AUTO_APPROVED") == "AUTO_APPROVED"


# ── 1. 완전 일치 ────────────────────────────────────────────────────

def test_1_full_match_is_info():
    row = _calc()
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([row]), sheets_repo=_StubRepo([dict(row)]))
    assert result["total"] == 1
    assert result["matched"] == 1
    assert result["mismatched"] == 0
    assert result["severity"][SEVERITY_INFO] == 1
    assert result["changed_fields"] == []


# ── 2. "80" vs 80 → INFO ────────────────────────────────────────────

def test_2_string_vs_int_score_is_info():
    sqlite_row = _calc(review_score="80")
    sheets_row = _calc(review_score=80)
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_INFO] == 1
    assert result["mismatched"] == 0


# ── 3. None vs "" → INFO(빈 값 동일 취급 정책) ───────────────────────

def test_3_none_vs_empty_string_is_info():
    sqlite_row = _calc(reviewed_at=None)
    sheets_row = _calc(reviewed_at="")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_INFO] == 1


# ── 4. 실제 title(name) 변경 → FAIL ──────────────────────────────────

def test_4_title_changed_is_fail():
    sqlite_row = _calc(name="원래 제목")
    sheets_row = _calc(name="바뀐 제목")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_FAIL] == 1
    entry = result["results"][0]
    assert entry["severity"] == SEVERITY_FAIL
    assert any(c["field"] == "name" for c in entry["changed_fields"])


# ── 5. 실제 status 변경 → FAIL ───────────────────────────────────────

def test_5_status_changed_is_fail():
    sqlite_row = _calc(status="active")
    sheets_row = _calc(status="draft")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_FAIL] == 1


# ── 6/7. review_score / review_attempts "0" vs 0 → INFO ─────────────

def test_6_review_score_zero_string_vs_int_is_info():
    sqlite_row = _calc(review_score="0")
    sheets_row = _calc(review_score=0)
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_INFO] == 1


def test_7_review_attempts_zero_string_vs_int_is_info():
    sqlite_row = _calc(review_attempts="0")
    sheets_row = _calc(review_attempts=0)
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_INFO] == 1


# ── 8/9. calculator_id 한쪽에만 존재 → CRITICAL(WARN 아님) ───────────

def test_8_missing_in_sheets_is_critical():
    sqlite_row = _calc(id="calc_only_sqlite")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([]))
    assert result["severity"][SEVERITY_CRITICAL] == 1
    assert result["severity"][SEVERITY_WARN] == 0
    assert result["missing_in_sheets"] == ["calc_only_sqlite"]


def test_9_missing_in_sqlite_is_critical():
    sheets_row = _calc(id="calc_only_sheets")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_CRITICAL] == 1
    assert result["missing_in_sqlite"] == ["calc_only_sheets"]


# ── 10. 중복 calculator_id → CRITICAL ───────────────────────────────

def test_10_duplicate_id_in_sqlite_is_critical():
    dup1 = _calc(id="calc_dup")
    dup2 = _calc(id="calc_dup", name="다른이름")
    sheets_row = _calc(id="calc_dup")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([dup1, dup2]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_CRITICAL] == 1
    assert any("duplicate_id_in_sqlite" in r for r in result["results"][0]["reasons"])


# ── 11. 저장소 접근 실패 → CRITICAL ──────────────────────────────────

def test_11a_sheets_access_failure_is_critical():
    sqlite_row = _calc()
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_FailingRepo())
    assert result["severity"][SEVERITY_CRITICAL] == 1
    assert result["total"] == 0
    assert "sheets_access_failed" in result["reasons"][0]


def test_11b_sqlite_access_failure_is_critical():
    sheets_row = _calc()
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_FailingRepo(), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_CRITICAL] == 1
    assert "sqlite_access_failed" in result["reasons"][0]


# ── 12. 여러 필드 동시 변경 → 전부 검출 ──────────────────────────────

def test_12_multiple_fields_changed_all_detected():
    sqlite_row = _calc(name="원래", status="active", category="labor")
    sheets_row = _calc(name="변경됨", status="draft", category="tax")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    entry = result["results"][0]
    assert entry["severity"] == SEVERITY_FAIL
    changed = {c["field"] for c in entry["changed_fields"]}
    assert changed == {"name", "status", "category"}


# ── 13. 정상 데이터 19건 전체 비교 → mismatch 0 ──────────────────────

def test_13_all_19_rows_zero_mismatch():
    rows = [_calc(id=f"calc_{i}", slug=f"slug-{i}") for i in range(19)]
    sheets_rows = [dict(r) for r in rows]
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo(rows), sheets_repo=_StubRepo(sheets_rows))
    assert result["total"] == 19
    assert result["matched"] == 19
    assert result["mismatched"] == 0
    assert result["severity"][SEVERITY_CRITICAL] == 0
    assert result["severity"][SEVERITY_FAIL] == 0
    assert result["severity"][SEVERITY_WARN] == 0


# ── 추가: reviewed_at만 다른 경우 → WARN(비핵심 필드만 차이) ─────────

def test_reviewed_at_only_difference_is_warn():
    sqlite_row = _calc(reviewed_at="2026-01-01T00:00:00")
    sheets_row = _calc(reviewed_at="2026-01-02T00:00:00")
    result = compare_calculators_sqlite_vs_sheets(
        {}, sqlite_repo=_StubRepo([sqlite_row]), sheets_repo=_StubRepo([sheets_row]))
    assert result["severity"][SEVERITY_WARN] == 1
    assert result["severity"][SEVERITY_FAIL] == 0
