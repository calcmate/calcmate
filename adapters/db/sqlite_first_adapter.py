# -*- coding: utf-8 -*-
"""
adapters/db/sqlite_first_adapter.py — app_templates 전용 SQLite-원본/Sheets-백업 Adapter

IRP-22 설계(SQLite=운영 원본, Google Sheets=백업/관리)를 IRP-23에서 구현한다.
AbstractDBAdapter와 동일한 public method signature를 구현하므로 TemplateRepository는
이 adapter를 받아도 코드를 바꿀 필요가 없다(순수 위임 구조).

⚠️ 이 adapter는 app_templates 테이블 전용으로 설계됐다. "calculators"/"sites"/
"articles" 등 다른 테이블 구조는 이 파일이 전혀 건드리지 않는다(factory.py에서
get_db_adapter()의 전역 동작도 그대로 유지된다 — 이 adapter는 별도 경로로만 쓰인다).

정책 요약:
  READ  : 정상 운영에서는 SQLite만 읽는다(Sheets READ 호출 없음).
          SQLite 조회 자체가 예외를 던지는 극단적 상황(DB 파일 손상 등)에서만
          Sheets에서 복구 읽기를 시도한다("데이터가 없음"과 "SQLite 장애"를
          구분할 수 없으므로, 단순히 결과가 빈 리스트인 경우는 복구 대상이 아니다 —
          정상적인 "해당 없음"으로 취급한다).
  WRITE : SQLite 저장 성공 = 운영 성공. SQLite 실패는 즉시 실패(Sheets에 먼저
          쓰거나 Sheets 성공을 운영 성공으로 인정하지 않는다).
          SQLite 성공 후 Sheets 백업을 시도한다 — 실패해도 운영 결과는 SUCCESS이며,
          기존 dual_adapter의 재시도 큐(enqueue_sync)에 상태만 기록한다(자동 소비자가
          없다는 사실은 기존과 동일 — 있는 것처럼 보고하지 않는다).
  50K   : html_template이 50,000자 이하면 기존처럼 app_templates 단일 셀에 저장한다.
          초과하면 app_templates_html_parts에 분할 저장하고, app_templates.html_template
          에는 관리자가 알아볼 수 있는 placeholder만 남긴다(운영 데이터 자체는 항상
          SQLite에 전체 원문 그대로 저장되므로 placeholder는 Sheets 백업 표시 전용).
"""
import logging

from .base import AbstractDBAdapter
from .sqlite_adapter import SQLiteAdapter
from .sheets_adapter import SheetsAdapter, _notify_sheet_failure
from .dual_adapter import enqueue_sync
from .content_splitter import split_content, reassemble, verify_integrity, IntegrityError, MAX_CHARS

LOG = logging.getLogger("sqlite_first_adapter")

PARTS_TABLE = "app_templates_html_parts"
SPLIT_FIELD = "html_template"


def _placeholder(template_id: str, total_parts: int) -> str:
    return f"[SPLIT:template_id={template_id},total_parts={total_parts}]"


def _is_placeholder(value: str) -> bool:
    return isinstance(value, str) and value.startswith("[SPLIT:template_id=")


def _part_id(template_id: str, part_no) -> str:
    return f"{template_id}::{part_no}"


class SQLiteFirstAdapter(AbstractDBAdapter):
    """app_templates 전용. SQLite=1차(운영 원본), Sheets=2차(백업)."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._sqlite = SQLiteAdapter(cfg)
        self._sheets = SheetsAdapter(cfg)

    # ── READ: SQLite 우선, 예외 시에만 Sheets 복구 ────────────────────
    def get_all(self, table: str) -> list[dict]:
        try:
            return self._sqlite.get_all(table)
        except Exception as e:
            LOG.warning("[sqlite_first] SQLite get_all 예외 — Sheets 복구 시도: %s", e)
            return self._recover_all_from_sheets(table)

    def get_where(self, table: str, filters: dict) -> list[dict]:
        try:
            return self._sqlite.get_where(table, filters)
        except Exception as e:
            LOG.warning("[sqlite_first] SQLite get_where 예외 — Sheets 복구 시도: %s", e)
            rows = self._recover_all_from_sheets(table)
            for col, val in filters.items():
                rows = [r for r in rows if str(r.get(col, "")) == str(val)]
            return rows

    def _recover_all_from_sheets(self, table: str) -> list[dict]:
        rows = self._sheets.get_all(table)
        if table != "app_templates":
            return rows
        return [self._reassemble_row_if_split(r) for r in rows]

    def _reassemble_row_if_split(self, row: dict) -> dict:
        """Sheets 행의 html_template이 split placeholder면 parts에서 원문을 복원한다."""
        html = row.get(SPLIT_FIELD, "")
        if not _is_placeholder(html):
            return row
        template_id = row.get("template_id", "")
        part_rows = self._sheets.get_where(PARTS_TABLE, {"template_id": template_id})
        if not part_rows:
            LOG.error("[sqlite_first] split placeholder이나 parts가 없음: template_id=%s", template_id)
            return row
        parts = [
            {
                "part_no": int(p["part_no"]),
                "content": p.get("content", ""),
                "content_hash": p.get("content_hash", ""),
                "full_content_hash": p.get("full_content_hash", ""),
                "total_parts": int(p.get("total_parts", 0)),
            }
            for p in part_rows
        ]
        try:
            verify_integrity(parts)
        except IntegrityError as e:
            LOG.error("[sqlite_first] parts 무결성 검증 실패(template_id=%s): %s", template_id, e)
            return row
        restored = dict(row)
        restored[SPLIT_FIELD] = reassemble(parts)
        return restored

    # ── WRITE: SQLite 성공 = 운영 성공. 성공 후에만 Sheets 백업 시도 ──
    def insert(self, table: str, row: dict) -> str:
        row_id = self._sqlite.insert(table, row)   # 실패 시 여기서 즉시 예외 전파(Sheets 쓰기 없음)
        self._backup_insert_to_sheets(table, row)
        return row_id

    def update(self, table: str, row_id: str, data: dict):
        self._sqlite.update(table, row_id, data)   # 실패 시 여기서 즉시 예외 전파(Sheets 쓰기 없음)
        self._backup_update_to_sheets(table, row_id, data)

    def delete(self, table: str, row_id: str):
        self._sqlite.delete(table, row_id)         # 실패 시 여기서 즉시 예외 전파
        try:
            self._sheets.delete(table, row_id)
            if table == "app_templates":
                self._delete_parts(row_id)
        except Exception as e:
            LOG.warning("[sqlite_first] Sheets delete 백업 실패(무시, 운영은 SQLite 기준 성공): %s", e)
            enqueue_sync("delete", table, {}, row_id, str(e))

    def read_test(self) -> bool:
        return self._sqlite.read_test()

    def invalidate_cache(self, table: str = None):
        if hasattr(self._sheets, "invalidate_cache"):
            self._sheets.invalidate_cache(table)

    # ── Sheets 백업 구현 ──────────────────────────────────────────
    def _backup_insert_to_sheets(self, table: str, row: dict):
        if table != "app_templates" or SPLIT_FIELD not in row:
            self._try_sheets(lambda: self._sheets.insert(table, row), "insert", table, row, row.get("template_id", ""))
            return
        content = row.get(SPLIT_FIELD) or ""
        template_id = row.get("template_id", "")
        row_for_sheets = dict(row)
        if len(content) > MAX_CHARS:
            parts = split_content(content)
            row_for_sheets[SPLIT_FIELD] = _placeholder(template_id, parts[0]["total_parts"])

            def _do():
                self._sheets.insert(table, row_for_sheets)
                self._write_parts_to_sheets(template_id, content, parts)
            self._try_sheets(_do, "insert", table, row, template_id)
        else:
            self._try_sheets(lambda: self._sheets.insert(table, row_for_sheets), "insert", table, row, template_id)

    def _backup_update_to_sheets(self, table: str, row_id: str, data: dict):
        if table != "app_templates" or SPLIT_FIELD not in data:
            self._try_sheets(lambda: self._sheets.update(table, row_id, data), "update", table, data, row_id)
            return
        content = data.get(SPLIT_FIELD) or ""
        data_for_sheets = dict(data)
        if len(content) > MAX_CHARS:
            parts = split_content(content)
            data_for_sheets[SPLIT_FIELD] = _placeholder(row_id, parts[0]["total_parts"])

            def _do():
                self._sheets.update(table, row_id, data_for_sheets)
                self._write_parts_to_sheets(row_id, content, parts)
            self._try_sheets(_do, "update", table, data, row_id)
        else:
            def _do():
                self._sheets.update(table, row_id, data_for_sheets)
                self._delete_parts(row_id)   # 이전 버전이 분할돼 있었을 수 있으므로 잔여 parts 정리
            self._try_sheets(_do, "update", table, data, row_id)

    def _try_sheets(self, fn, op: str, table: str, payload: dict, row_id: str):
        try:
            fn()
        except Exception as e:
            LOG.error("[sqlite_first] Sheets 백업 실패(운영 데이터는 SQLite 기준 SUCCESS 유지): %s", e)
            enqueue_sync(op, table, payload, row_id, str(e),
                         direction="sqlite_to_sheets", source_adapter="SQLiteFirstAdapter")
            _notify_sheet_failure(self._cfg, f"app_templates Sheets 백업 실패({op}, template_id={row_id}): {e}")
            try:
                self._sqlite.update(table, row_id, {"sync_status": "sync_pending"})
            except Exception:
                pass

    def _write_parts_to_sheets(self, template_id: str, content: str, parts: list[dict] = None):
        """parts 전체 교체 + idempotent 처리 + 무결성 재검증."""
        parts = parts or split_content(content)
        new_full_hash = parts[0]["full_content_hash"]

        existing = self._sheets.get_where(PARTS_TABLE, {"template_id": template_id})
        if existing:
            existing_hashes = {p.get("full_content_hash", "") for p in existing}
            existing_total = {str(p.get("total_parts", "")) for p in existing}
            if (existing_hashes == {new_full_hash} and existing_total == {str(len(parts))}
                    and len(existing) == len(parts)):
                return   # 동일 콘텐츠 — 불필요한 재작성 생략(idempotent)

        self._delete_parts(template_id)

        from datetime import datetime
        now = datetime.now().isoformat()
        for p in parts:
            self._sheets.insert(PARTS_TABLE, {
                "part_id": _part_id(template_id, p["part_no"]),
                "template_id": template_id,
                "part_no": str(p["part_no"]),
                "content": p["content"],
                "content_hash": p["content_hash"],
                "full_content_hash": p["full_content_hash"],
                "total_parts": str(p["total_parts"]),
                "created_at": now,
                "updated_at": now,
            })

        # 무결성 재검증: 방금 쓴 parts를 다시 읽어 재조립/hash 확인
        written = self._sheets.get_where(PARTS_TABLE, {"template_id": template_id})
        readback = [
            {
                "part_no": int(p["part_no"]),
                "content": p.get("content", ""),
                "content_hash": p.get("content_hash", ""),
                "full_content_hash": p.get("full_content_hash", ""),
                "total_parts": int(p.get("total_parts", 0)),
            }
            for p in written
        ]
        verify_integrity(readback)   # 실패 시 IntegrityError 전파 — 호출부(_try_sheets)가 pending 처리

    def _delete_parts(self, template_id: str):
        existing = self._sheets.get_where(PARTS_TABLE, {"template_id": template_id})
        for p in existing:
            self._sheets.delete(PARTS_TABLE, p.get("part_id", _part_id(template_id, p.get("part_no", ""))))
