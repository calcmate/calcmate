"""
adapters/db/sheets_adapter.py — Google Sheets 구현체 (현재 기본값)

성능/쿼터 개선(인터페이스 무변경, 내부 구현만):
  1) 워크시트 핸들 캐싱(self._ws_cache): gspread의 worksheet(tab)는 호출마다
     fetch_sheet_metadata() API를 유발 → 같은 탭 핸들을 인스턴스에 캐싱해 재사용.
  2) get_all() 짧은 TTL 캐시(기본 8초, cfg SHEETS_CACHE_TTL): 같은 실행 안에서
     get_where→get_all이 반복 호출돼도 시트 read를 1회로 접는다. 쓰기(insert/update/
     delete)는 해당 탭 캐시를 자동 무효화. 최신성이 중요한 곳은 get_all(force_refresh=True)
     또는 invalidate_cache()로 강제 새로고침.
  3) 429(rate limit)/일시장애(5xx) 발생 시 exponential backoff 재시도(최대 3회).
"""
import time
import logging
import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from requests.exceptions import ConnectionError as _ReqConnError, ChunkedEncodingError as _ChunkErr, Timeout as _ReqTimeout
from google.oauth2.service_account import Credentials
from pathlib import Path
from datetime import datetime
from .base import AbstractDBAdapter

LOG = logging.getLogger("sheets_adapter")


def _notify_sheet_failure(cfg: dict, detail: str) -> None:
    """시트 작업이 재시도 소진 후 실패했을 때 운영자에게 Telegram 알림(best-effort).
    저수준 어댑터라 telegram_ops를 lazy import + 실패 무시(알림이 본 흐름을 막지 않음)."""
    try:
        from modules import telegram_ops
        telegram_ops.notify_level(
            cfg or {}, "ERROR", "Google Sheets 작업 실패 — 운영자 확인 필요",
            f"{detail}\n(재시도 소진. rollback/상태 반영이 누락됐을 수 있음)", event="error")
    except Exception:
        pass


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 테이블명 → Sheets 탭명 매핑
_TAB = {
    "sites":              "sites",
    "articles":           "마스터_DB",
    "logs":               "운영로그",
    "calculators":        "calculators",
    "app_templates":      "app_templates",
    "app_factory_queue":  "app_factory_queue",
    "app_factory_logs":   "app_factory_logs",
    # IRP-23: app_templates.html_template 50,000자 초과 백업용(SQLiteFirstAdapter 전용).
    "app_templates_html_parts": "app_templates_html_parts",
}

# 테이블별 id 컬럼명
_ID_COL = {
    "sites":             "site_id",
    "articles":          "ID",
    "calculators":       "id",
    "app_templates":     "template_id",
    "app_factory_queue": "job_id",
    "app_factory_logs":  "log_id",
    # 복합키(template_id+part_no)를 단일 문자열("template_id::part_no")로 합성해 사용한다.
    "app_templates_html_parts": "part_id",
}

_DEFAULT_CACHE_TTL = 8          # get_all TTL(초). cfg SHEETS_CACHE_TTL로 override(0이면 비활성).
_MAX_RETRIES = 3               # 429/5xx backoff 최대 재시도 횟수
_RETRY_STATUS = (429, 500, 502, 503)  # 재시도 대상 HTTP 상태(rate limit + 일시 장애)


class SheetsAdapter(AbstractDBAdapter):
    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._gc = None
        self._sh = None
        self._ws_cache: dict = {}        # 탭명 → worksheet 핸들(메타데이터 재요청 방지)
        self._get_all_cache: dict = {}   # 탭명 → (expires_at(monotonic), rows)
        try:
            self._cache_ttl = float(cfg.get("SHEETS_CACHE_TTL", _DEFAULT_CACHE_TTL))
        except (TypeError, ValueError):
            self._cache_ttl = _DEFAULT_CACHE_TTL

    # ── 재시도 래퍼 ────────────────────────────────────────────
    def _with_retry(self, fn, *args, **kwargs):
        """gspread API 호출 래퍼. 429(rate limit)/5xx 및 네트워크 오류(연결 끊김/타임아웃)
        시 exponential backoff 재시도(최대 _MAX_RETRIES회). 최종 실패 시 ERROR 로그 +
        Telegram 알림(best-effort) 후 전파 → rollback 등 시트 쓰기의 견고성 확보.
        그 외 APIError(권한/미존재 등)·WorksheetNotFound는 즉시 전파."""
        delay = 1.0
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except APIError as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status not in _RETRY_STATUS or attempt >= _MAX_RETRIES:
                    if status in _RETRY_STATUS:
                        _notify_sheet_failure(self._cfg, f"HTTP {status} (재시도 {_MAX_RETRIES}회 소진)")
                    raise
                LOG.warning("Sheets API %s — %d/%d 재시도 (%.1fs 대기)",
                            status, attempt, _MAX_RETRIES, delay)
                time.sleep(delay)
                delay *= 2
            except (_ReqConnError, _ChunkErr, _ReqTimeout) as e:
                # RemoteDisconnected 등 네트워크 오류 — 재시도 대상(기존엔 미처리라 rollback 실패했음)
                if attempt >= _MAX_RETRIES:
                    LOG.error("Sheets 작업 실패(네트워크, %d회 재시도 소진): %s", _MAX_RETRIES, e)
                    _notify_sheet_failure(self._cfg, f"네트워크 오류: {str(e)[:120]}")
                    raise
                LOG.warning("Sheets 네트워크 오류 — %d/%d 재시도 (%.1fs 대기): %s",
                            attempt, _MAX_RETRIES, delay, str(e)[:80])
                time.sleep(delay)
                delay *= 2

    def _connect(self):
        if self._gc:
            return
        root = Path(self._cfg.get("_root", "."))
        cred_path = root / self._cfg.get("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
        creds = Credentials.from_service_account_file(str(cred_path), scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._sh = self._with_retry(self._gc.open_by_key, self._cfg["GOOGLE_SHEET_ID"])

    def _ws(self, table: str):
        """워크시트 핸들 반환(캐싱). 같은 탭은 metadata 재요청 없이 재사용."""
        self._connect()
        tab = _TAB.get(table, table)
        cached = self._ws_cache.get(tab)
        if cached is not None:
            return cached
        try:
            ws = self._with_retry(self._sh.worksheet, tab)
        except WorksheetNotFound:
            ws = self._with_retry(self._sh.add_worksheet, tab, rows=1000, cols=50)
        self._ws_cache[tab] = ws
        return ws

    # ── 캐시 무효화 ────────────────────────────────────────────
    def invalidate_cache(self, table: str = None):
        """get_all TTL 캐시 무효화. table=None이면 전체.
        Content Sync 등 최신성이 중요한 호출부에서 강제 새로고침용."""
        if table is None:
            self._get_all_cache.clear()
        else:
            self._get_all_cache.pop(_TAB.get(table, table), None)

    def _invalidate(self, table: str):
        self._get_all_cache.pop(_TAB.get(table, table), None)

    # ── CRUD ──────────────────────────────────────────────────
    def get_all(self, table: str, force_refresh: bool = False) -> list[dict]:
        """전체 행 반환. TTL(기본 8초) 내 반복 호출은 캐시 재사용.
        force_refresh=True면 캐시 무시하고 시트에서 새로 읽는다.
        반환값은 방어적 복사(호출부에서 행을 수정해도 캐시 오염 없음)."""
        tab = _TAB.get(table, table)
        now = time.monotonic()
        if not force_refresh and self._cache_ttl > 0:
            hit = self._get_all_cache.get(tab)
            if hit and hit[0] > now:
                return [dict(r) for r in hit[1]]
        ws = self._ws(table)
        rows = self._with_retry(ws.get_all_records, head=1)
        if self._cache_ttl > 0:
            self._get_all_cache[tab] = (now + self._cache_ttl, rows)
        return [dict(r) for r in rows]

    def get_where(self, table: str, filters: dict) -> list[dict]:
        rows = self.get_all(table)
        for col, val in filters.items():
            rows = [r for r in rows if str(r.get(col, "")) == str(val)]
        return rows

    def insert(self, table: str, row: dict) -> str:
        ws = self._ws(table)
        headers = self._with_retry(ws.row_values, 1)
        if not headers:
            headers = list(row.keys())
            self._with_retry(ws.update, "A1", [headers])
        values = [str(row.get(h, "") or "") for h in headers]
        self._with_retry(ws.append_row, values, value_input_option="USER_ENTERED")
        self._invalidate(table)   # 새 행 추가 → 다음 read는 최신 반영
        id_col = _ID_COL.get(table, "id")
        return str(row.get(id_col, ""))

    def update(self, table: str, row_id: str, data: dict):
        ws = self._ws(table)
        all_vals = self._with_retry(ws.get_all_values)
        if not all_vals:
            return
        headers = all_vals[0]
        # 신규 컬럼은 헤더에 자동 추가(기존 컬럼/데이터 불변)
        missing = [c for c in data.keys() if c not in headers]
        if missing:
            headers = headers + missing
            self._with_retry(ws.update, "A1", [headers])
        id_col = _ID_COL.get(table, "id")
        id_idx = headers.index(id_col) if id_col in headers else 0
        for i, row in enumerate(all_vals[1:], start=2):
            if str(row[id_idx]) == str(row_id):
                for col, val in data.items():
                    if col in headers:
                        self._with_retry(ws.update_cell, i, headers.index(col) + 1, str(val or ""))
                if "updated_at" in headers:
                    self._with_retry(ws.update_cell, i, headers.index("updated_at") + 1,
                                     datetime.now().isoformat())
                self._invalidate(table)   # 셀 갱신 → 캐시 무효화
                return
        self._invalidate(table)   # 헤더가 바뀌었을 수 있으므로(신규 컬럼) 무효화

    def delete(self, table: str, row_id: str):
        ws = self._ws(table)
        all_vals = self._with_retry(ws.get_all_values)
        if not all_vals:
            return
        headers = all_vals[0]
        id_col = _ID_COL.get(table, "id")
        id_idx = headers.index(id_col) if id_col in headers else 0
        for i, row in enumerate(all_vals[1:], start=2):
            if str(row[id_idx]) == str(row_id):
                self._with_retry(ws.delete_rows, i)
                self._invalidate(table)   # 행 삭제 → 캐시 무효화
                return

    def read_test(self) -> bool:
        try:
            self._connect()
            self._with_retry(self._sh.worksheets)
            return True
        except Exception:
            return False
