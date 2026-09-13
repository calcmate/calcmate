# -*- coding: utf-8 -*-
"""tests/test_sqlite_first_adapter.py — IRP-23

adapters/db/sqlite_first_adapter.py::SQLiteFirstAdapter의 SQLite-원본/Sheets-백업
동작을 mock/fake Sheets adapter로 검증한다(실제 Google Sheets API 호출 없음 —
credentials.json/네트워크 의존 없이 순수 로직만 검증).

enqueue_sync()/_notify_sheet_failure()는 실제 프로젝트 파일(data/sync/pending_sync.json)
/Telegram을 건드리므로 monkeypatch로 스파이 처리해 부작용을 차단한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from adapters.db import sqlite_first_adapter as sfa
from adapters.db.sqlite_first_adapter import SQLiteFirstAdapter
from adapters.db.content_splitter import split_content, MAX_CHARS


class FakeSheetsAdapter:
    """SheetsAdapter의 public 메서드만 흉내내는 인메모리 fake. 네트워크 호출 없음."""

    _ID_COL = {"app_templates": "template_id", "app_templates_html_parts": "part_id"}

    def __init__(self, fail=False):
        self.fail = fail
        self.tables: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def _idc(self, table):
        return self._ID_COL.get(table, "id")

    def get_all(self, table):
        self.calls.append(("get_all", table))
        return [dict(r) for r in self.tables.get(table, {}).values()]

    def get_where(self, table, filters):
        self.calls.append(("get_where", table))
        rows = [dict(r) for r in self.tables.get(table, {}).values()]
        for k, v in filters.items():
            rows = [r for r in rows if str(r.get(k, "")) == str(v)]
        return rows

    def insert(self, table, row):
        self.calls.append(("insert", table))
        if self.fail:
            raise RuntimeError("simulated sheets insert failure")
        idc = self._idc(table)
        self.tables.setdefault(table, {})[row.get(idc)] = dict(row)
        return str(row.get(idc, ""))

    def update(self, table, row_id, data):
        self.calls.append(("update", table))
        if self.fail:
            raise RuntimeError("simulated sheets update failure")
        idc = self._idc(table)
        store = self.tables.setdefault(table, {})
        if row_id in store:
            store[row_id].update(data)
        else:
            store[row_id] = {**data, idc: row_id}

    def delete(self, table, row_id):
        self.calls.append(("delete", table))
        if self.fail:
            raise RuntimeError("simulated sheets delete failure")
        self.tables.setdefault(table, {}).pop(row_id, None)

    def invalidate_cache(self, table=None):
        pass


@pytest.fixture(autouse=True)
def _no_real_side_effects(monkeypatch):
    """enqueue_sync/_notify_sheet_failure이 실제 data/sync/pending_sync.json이나
    Telegram을 건드리지 않도록 스파이로 교체한다(이 테스트 파일 범위 밖 부작용 차단)."""
    calls = {"enqueue": [], "notify": []}
    monkeypatch.setattr(sfa, "enqueue_sync", lambda *a, **k: calls["enqueue"].append((a, k)))
    monkeypatch.setattr(sfa, "_notify_sheet_failure", lambda *a, **k: calls["notify"].append((a, k)))
    return calls


def _make_adapter(tmp_path, sheets_fail=False):
    cfg = {"DB_ADAPTER": "dual", "SQLITE_PATH": "test_irp23.db", "_root": str(tmp_path)}
    adapter = SQLiteFirstAdapter(cfg)
    adapter._sheets = FakeSheetsAdapter(fail=sheets_fail)
    return adapter


# ── A. SQLite 성공 + Sheets 성공 → SUCCESS ─────────────────────────
def test_a_insert_success_both_stores(tmp_path):
    adapter = _make_adapter(tmp_path)
    row = {"template_id": "tpl_a", "html_template": "<html>ok</html>", "status": "active"}
    row_id = adapter.insert("app_templates", row)
    assert row_id == "tpl_a"
    assert adapter._sqlite.get_where("app_templates", {"template_id": "tpl_a"})[0]["html_template"] == "<html>ok</html>"
    assert adapter._sheets.tables["app_templates"]["tpl_a"]["html_template"] == "<html>ok</html>"


# ── B. SQLite 성공 + Sheets 실패 → 운영 성공, backup pending 기록 ───
def test_b_insert_sqlite_success_sheets_fail_still_operational_success(tmp_path, _no_real_side_effects):
    adapter = _make_adapter(tmp_path, sheets_fail=True)
    row = {"template_id": "tpl_b", "html_template": "<html>ok</html>", "status": "active"}
    row_id = adapter.insert("app_templates", row)   # 예외 없이 성공해야 함
    assert row_id == "tpl_b"
    assert adapter._sqlite.get_where("app_templates", {"template_id": "tpl_b"})[0]["html_template"] == "<html>ok</html>"
    assert len(_no_real_side_effects["enqueue"]) == 1   # pending 기록은 남음(스파이로 확인, 실제 파일 미접촉)
    # SQLite 쪽에 sync_status=sync_pending 마킹 시도(기존 dual_adapter 패턴 재사용)
    row_after = adapter._sqlite.get_where("app_templates", {"template_id": "tpl_b"})[0]
    assert row_after.get("sync_status") == "sync_pending"


# ── C. SQLite 실패 → ERROR, Sheets write 없음 ──────────────────────
def test_c_insert_sqlite_failure_no_sheets_write(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)

    def _boom(table, row):
        raise RuntimeError("simulated sqlite failure")
    monkeypatch.setattr(adapter._sqlite, "insert", _boom)

    with pytest.raises(RuntimeError):
        adapter.insert("app_templates", {"template_id": "tpl_c", "html_template": "x"})
    assert adapter._sheets.calls == []   # Sheets는 전혀 호출되지 않아야 함


def test_c2_update_sqlite_failure_no_sheets_write(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    adapter.insert("app_templates", {"template_id": "tpl_c2", "html_template": "x"})
    adapter._sheets.calls.clear()

    def _boom(table, row_id, data):
        raise RuntimeError("simulated sqlite update failure")
    monkeypatch.setattr(adapter._sqlite, "update", _boom)

    with pytest.raises(RuntimeError):
        adapter.update("app_templates", "tpl_c2", {"html_template": "y"})
    assert adapter._sheets.calls == []


# ── D. 50K 이하 → 단일 Sheets cell ─────────────────────────────────
def test_d_under_50k_uses_single_cell(tmp_path):
    adapter = _make_adapter(tmp_path)
    content = "a" * 1000
    adapter.insert("app_templates", {"template_id": "tpl_d", "html_template": content})
    stored = adapter._sheets.tables["app_templates"]["tpl_d"]["html_template"]
    assert stored == content
    assert not sfa._is_placeholder(stored)
    assert adapter._sheets.tables.get(sfa.PARTS_TABLE, {}) == {}


# ── E. 50K 초과 → parts 저장, 각 part ≤50K, 재조립==원문 ───────────
def test_e_over_50k_splits_into_parts_and_reassembles(tmp_path):
    adapter = _make_adapter(tmp_path)
    content = "가" * 120000   # 50K 초과
    adapter.insert("app_templates", {"template_id": "tpl_e", "html_template": content})

    stored = adapter._sheets.tables["app_templates"]["tpl_e"]["html_template"]
    assert sfa._is_placeholder(stored)

    part_rows = adapter._sheets.get_where(sfa.PARTS_TABLE, {"template_id": "tpl_e"})
    assert len(part_rows) == 3   # 120000 / 50000 = 3 parts(50000+50000+20000)
    assert all(len(p["content"]) <= MAX_CHARS for p in part_rows)

    from adapters.db.content_splitter import reassemble
    parts = [{"part_no": int(p["part_no"]), "content": p["content"],
              "content_hash": p["content_hash"], "full_content_hash": p["full_content_hash"],
              "total_parts": int(p["total_parts"])} for p in part_rows]
    assert reassemble(parts) == content

    # SQLite에는 항상 전체 원문 그대로(분할 없음)
    sqlite_row = adapter._sqlite.get_where("app_templates", {"template_id": "tpl_e"})[0]
    assert sqlite_row["html_template"] == content


# ── F. 동일 full_content_hash → 불필요한 parts 재작성 없음 ─────────
def test_f_idempotent_same_content_skips_rewrite(tmp_path):
    adapter = _make_adapter(tmp_path)
    content = "나" * 120000
    adapter.insert("app_templates", {"template_id": "tpl_f", "html_template": content})

    part_rows_before = adapter._sheets.get_where(sfa.PARTS_TABLE, {"template_id": "tpl_f"})
    call_count_before = len([c for c in adapter._sheets.calls if c[1] == sfa.PARTS_TABLE])

    adapter._sheets.calls.clear()
    adapter.update("app_templates", "tpl_f", {"html_template": content})   # 동일 콘텐츠 재저장

    parts_calls_after = [c for c in adapter._sheets.calls if c[1] == sfa.PARTS_TABLE]
    # get_where(조회)는 idempotent 판단을 위해 호출되지만 insert/delete(재작성)는 없어야 함
    assert not any(c[0] in ("insert", "delete") for c in parts_calls_after)
    part_rows_after = adapter._sheets.get_where(sfa.PARTS_TABLE, {"template_id": "tpl_f"})
    assert part_rows_after == part_rows_before


# ── G. hash 변경 → 기존 parts 전체 교체 ────────────────────────────
def test_g_content_change_replaces_all_parts(tmp_path):
    adapter = _make_adapter(tmp_path)
    content_v1 = "다" * 120000
    adapter.insert("app_templates", {"template_id": "tpl_g", "html_template": content_v1})
    old_hashes = {p["content_hash"] for p in adapter._sheets.get_where(sfa.PARTS_TABLE, {"template_id": "tpl_g"})}

    content_v2 = "라" * 130000   # 다른 콘텐츠, 다른 total_parts(3개 그대로지만 내용 다름)
    adapter.update("app_templates", "tpl_g", {"html_template": content_v2})

    new_rows = adapter._sheets.get_where(sfa.PARTS_TABLE, {"template_id": "tpl_g"})
    new_hashes = {p["content_hash"] for p in new_rows}
    assert new_hashes != old_hashes

    from adapters.db.content_splitter import reassemble
    parts = [{"part_no": int(p["part_no"]), "content": p["content"],
              "content_hash": p["content_hash"], "full_content_hash": p["full_content_hash"],
              "total_parts": int(p["total_parts"])} for p in new_rows]
    assert reassemble(parts) == content_v2


# ── H. SQLite READ → Sheets READ가 호출되지 않음 ───────────────────
def test_h_normal_read_never_touches_sheets(tmp_path):
    adapter = _make_adapter(tmp_path)
    adapter.insert("app_templates", {"template_id": "tpl_h", "html_template": "hello"})
    adapter._sheets.calls.clear()   # insert 백업 호출 기록 제거 후 READ만 측정

    rows = adapter.get_where("app_templates", {"template_id": "tpl_h"})
    assert rows[0]["html_template"] == "hello"
    all_rows = adapter.get_all("app_templates")
    assert any(r["template_id"] == "tpl_h" for r in all_rows)

    assert adapter._sheets.calls == []   # 정상 운영에서는 Sheets READ가 전혀 호출되지 않아야 함


# ── 예외 경로: SQLite 자체가 예외를 던지면 Sheets 복구 읽기 허용 ────
def test_i_sqlite_read_exception_falls_back_to_sheets(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path)
    adapter.insert("app_templates", {"template_id": "tpl_i", "html_template": "backup-source"})

    def _boom(table):
        raise RuntimeError("simulated sqlite corruption")
    monkeypatch.setattr(adapter._sqlite, "get_all", _boom)

    rows = adapter.get_all("app_templates")
    assert any(r.get("html_template") == "backup-source" for r in rows)   # Sheets에서 복구됨


# ── 기존 TemplateRepository API 호환성 ─────────────────────────────
def test_j_template_repository_compat(tmp_path):
    from repositories.template_repository import TemplateRepository
    adapter = _make_adapter(tmp_path)
    repo = TemplateRepository(adapter)
    tpl_id = repo.save({"html_template": "<html>compat</html>", "template_type": "t"})
    fetched = repo.get_by_id(tpl_id)
    assert fetched["html_template"] == "<html>compat</html>"
    repo.update(tpl_id, {"html_template": "<html>updated</html>"})
    assert repo.get_by_id(tpl_id)["html_template"] == "<html>updated</html>"
