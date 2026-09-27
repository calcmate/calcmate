"""
repositories/sync_log_repository.py — SyncLogRepository

sync_runs / sync_log_entries 전용 Repository. articles/blog_articles와 완전히 독립적이며,
그 두 테이블은 절대 대상으로 하지 않는다(STEP19 설계 §13 그대로).

책임은 로그 적재와 최소 조회로 한정한다. run_blog_articles_sync_once()의 판정 로직에는
관여하지 않는다(호출부가 판정 결과를 받아 이 Repository로 저장할 뿐).
"""
import uuid
from datetime import datetime

from adapters.db.base import AbstractDBAdapter

# 로그에 저장 금지 필드(STEP20 §5) — 실수로라도 이 키들이 담긴 dict를 그대로 저장하지 않도록
# insert_entry()에서 명시적으로 체크한다.
_FORBIDDEN_ENTRY_FIELDS = {"content", "excerpt", "title_before", "title_after",
                           "content_before", "content_after", "html"}


# STEP37: target을 포함한 run_id/entry_id 생성기. blog_articles_sync.py의 기존
# 인라인 생성 로직("sync_"+시각+4hex, target 미포함)은 그대로 둔다 — 이미 저장된
# run_id를 마이그레이션하지 않고, 새로 생성되는 run만 이 규칙을 쓴다(STEP37 §3).
# target을 ID 문자열에 넣으면 서로 다른 target(blog_articles/calculators)의 run이
# 같은 초에 실행돼도 run_id가 겹칠 가능성이 사실상 사라진다(STEP36 §4에서 지적된
# "target 미포함으로 인한 교차 충돌 가능성"에 대한 최소 보강).
def generate_run_id(target: str) -> str:
    return f"sync_{target}_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]


def generate_entry_id(target: str) -> str:
    return f"log_{target}_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]


class SyncLogRepository:
    RUNS_TABLE = "sync_runs"
    ENTRIES_TABLE = "sync_log_entries"

    def __init__(self, db: AbstractDBAdapter):
        self._db = db

    def insert_run(self, run: dict) -> str:
        """sync_runs 1건 삽입. run은 STEP19 §5 스키마의 11개 필드를 그대로 가져야 한다."""
        required = {"run_id", "target", "started_at", "finished_at", "duration_ms",
                    "result", "total_count", "info_count", "warn_count",
                    "fail_count", "critical_count"}
        missing = required - set(run.keys())
        if missing:
            raise ValueError(f"insert_run()에 필수 필드 누락: {missing}")
        # SQLiteAdapter.insert()가 값을 str(v or "")로 직렬화하므로, 정수 0이 그대로
        # 넘어가면 falsy로 취급되어 빈 문자열로 저장된다(기존 어댑터 동작, 이번 STEP에서
        # sqlite_adapter.py의 insert/update 자체는 건드리지 않는다). 미리 문자열로
        # 변환해 "0"(truthy 문자열)로 만들어 이 문제를 여기서만 우회한다.
        row = dict(run)
        for k in ("duration_ms", "total_count", "info_count", "warn_count",
                  "fail_count", "critical_count"):
            if k in row and row[k] is not None:
                row[k] = str(row[k])
        return self._db.insert(self.RUNS_TABLE, row)

    def insert_entry(self, entry: dict) -> str:
        """sync_log_entries 1건 삽입. 본문/발췌 등 대용량·민감 필드는 절대 허용하지 않는다."""
        forbidden_present = _FORBIDDEN_ENTRY_FIELDS & set(entry.keys())
        if forbidden_present:
            raise ValueError(f"insert_entry()에 금지 필드가 포함됨(본문 누출 방지): {forbidden_present}")
        required = {"entry_id", "run_id", "article_id", "wp_post_id", "slug",
                    "severity", "reasons", "checked_at"}
        missing = required - set(entry.keys())
        if missing:
            raise ValueError(f"insert_entry()에 필수 필드 누락: {missing}")
        return self._db.insert(self.ENTRIES_TABLE, dict(entry))

    def get_run(self, run_id: str) -> dict | None:
        rows = self._db.get_where(self.RUNS_TABLE, {"run_id": run_id})
        return rows[0] if rows else None

    def get_entries_by_run(self, run_id: str) -> list[dict]:
        return self._db.get_where(self.ENTRIES_TABLE, {"run_id": run_id})

    def list_runs(self) -> list[dict]:
        return self._db.get_all(self.RUNS_TABLE)
