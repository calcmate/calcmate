# -*- coding: utf-8 -*-
"""
repositories/sync_log_calculator_repository.py — SyncLogCalculatorRepository (STEP37)

Calculator SQLite↔Sheets drift 판정 결과 전용 로그 Repository.

기존 SyncLogRepository(sync_runs/sync_log_entries)는 무수정으로 둔다.
sync_runs는 target 중립적인 공용 테이블이라 그대로 재사용하지만(target=
"calculators"로 삽입), sync_log_entries는 article_id/wp_post_id가 NOT NULL +
UNIQUE(run_id, article_id)로 Blog 전용 스키마에 결합돼 있어(STEP36 §2/§3에서
실제 DDL로 확인) Calculator가 그대로 쓸 수 없다. 그래서 Calculator 세부 항목은
신규 테이블 sync_log_calculator_entries에 저장한다 — "article_id"/"wp_post_id"
같은 Blog 전용 컬럼을 억지로 쓰지 않기 위함이다.

책임은 로그 적재와 최소 조회로 한정한다. compare_calculators_sqlite_vs_sheets()의
판정 로직에는 관여하지 않는다(호출부가 판정 결과를 받아 이 Repository로 저장할 뿐).
"""
import sqlite3

from adapters.db.base import AbstractDBAdapter

# 로그에 저장 금지 필드 — 실수로라도 SQLite/Sheets 원본 행 전체나 본문성 데이터가
# 통째로 담긴 dict를 저장하지 않도록 명시적으로 체크한다(sync_log_repository.py의
# _FORBIDDEN_ENTRY_FIELDS와 동일한 원칙, Calculator 쪽 필드명에 맞게 조정).
_FORBIDDEN_ENTRY_FIELDS = {"content", "html", "article_content",
                           "sqlite_row", "sheets_row", "before", "after",
                           "raw_sqlite_value", "raw_sheets_value", "changed_fields"}

# sync_log_entries(Blog)와 동일한 제약 스타일(PK/NOT NULL/UNIQUE, FK 없음 —
# 프로젝트 전체에 FOREIGN KEY를 쓰는 테이블이 하나도 없음을 STEP37 §1에서 확인,
# PRAGMA foreign_keys도 기본 비활성이라 일관성 있게 FK를 추가하지 않는다).
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sync_log_calculator_entries (
    entry_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    calculator_id   TEXT NOT NULL,
    slug            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    reasons         TEXT NOT NULL,
    error_type      TEXT,
    error_message   TEXT,
    checked_at      TEXT NOT NULL,
    PRIMARY KEY(entry_id),
    UNIQUE(run_id, calculator_id)
)
"""


def ensure_schema(sqlite_adapter) -> None:
    """sync_log_calculator_entries가 없으면 제약조건을 갖춘 정식 스키마로
    생성한다(idempotent — 이미 있으면 아무 것도 하지 않는다).

    SQLiteAdapter.insert()가 쓰는 범용 자동-DDL(_ensure_table())은 테이블이
    없을 때 전체 TEXT·제약조건 없이 생성하므로, 그 경로로는
    UNIQUE(run_id, calculator_id)/PRIMARY KEY가 생기지 않는다(기존
    sync_runs/sync_log_entries도 처음엔 이와 동일하게 명시적 DDL로 생성됐다).
    그래서 insert 이전에 반드시 이 함수로 스키마를 먼저 확정한다.
    """
    conn = sqlite3.connect(str(sqlite_adapter._path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


class SyncLogCalculatorRepository:
    RUNS_TABLE = "sync_runs"
    ENTRIES_TABLE = "sync_log_calculator_entries"

    def __init__(self, db: AbstractDBAdapter):
        self._db = db
        if hasattr(db, "_path"):
            ensure_schema(db)

    def create_run(self, run: dict) -> str:
        """sync_runs에 1건 삽입. 기존 SyncLogRepository.insert_run()과 동일한
        스키마·규칙(테이블을 공유하므로 로직도 그대로 맞춘다)."""
        required = {"run_id", "target", "started_at", "finished_at", "duration_ms",
                    "result", "total_count", "info_count", "warn_count",
                    "fail_count", "critical_count"}
        missing = required - set(run.keys())
        if missing:
            raise ValueError(f"create_run()에 필수 필드 누락: {missing}")
        row = dict(run)
        # SQLiteAdapter.insert()가 str(v or "")로 직렬화하므로 정수 0(예:
        # fail_count=0)이 falsy로 빈 문자열이 되지 않도록 미리 문자열화한다
        # (sync_log_repository.py의 insert_run()과 동일 원칙, STEP20 그대로).
        for k in ("duration_ms", "total_count", "info_count", "warn_count",
                  "fail_count", "critical_count"):
            if k in row and row[k] is not None:
                row[k] = str(row[k])
        return self._db.insert(self.RUNS_TABLE, row)

    def insert_calculator_entry(self, entry: dict) -> str:
        """sync_log_calculator_entries에 1건 삽입. content/HTML 등 대용량·민감
        필드는 절대 허용하지 않는다."""
        forbidden_present = _FORBIDDEN_ENTRY_FIELDS & set(entry.keys())
        if forbidden_present:
            raise ValueError(f"insert_calculator_entry()에 금지 필드가 포함됨(본문 누출 방지): "
                             f"{forbidden_present}")
        required = {"entry_id", "run_id", "calculator_id", "slug",
                    "severity", "reasons", "checked_at"}
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"insert_calculator_entry()에 필수 필드 누락: {missing}")
        return self._db.insert(self.ENTRIES_TABLE, dict(entry))

    def get_run(self, run_id: str) -> dict | None:
        rows = self._db.get_where(self.RUNS_TABLE, {"run_id": run_id})
        return rows[0] if rows else None

    def get_calculator_entries_by_run(self, run_id: str) -> list[dict]:
        return self._db.get_where(self.ENTRIES_TABLE, {"run_id": run_id})
