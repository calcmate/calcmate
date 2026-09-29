"""
repositories/article_repository.py — ArticleRepository
마스터_DB CRUD. 기존 db_manager / sheet_sync 대체.
"""
import json
import uuid
from datetime import datetime
from adapters.db.base import AbstractDBAdapter

VALID_STATUSES = {
    "대기", "진행중", "작성중", "이미지오류", "작성오류",
    "발행완료", "발행실패", "복구대기", "보류", "만료", "재처리대기",
    "수정됨", "휴지통", "품질보류", "재처리완료",
    "리라이트중",  # P2-3: rewrite 선점 상태. 발행완료 → 리라이트중 → 발행완료(성공/실패 모두 복원).
}

# 유효 발행 카운트에서 제외할 비활성 상태(삭제/휴지통/품질보류 등). 상태 종류가 늘어나면
# 이 집합만 수정하면 되도록 Repository 계층에 둔다(파이프라인/엔진은 개수만 사용).
# "품질보류": 자동 품질검수 HOLD(발행 안 됨) — 발행됨으로 카운트하지 않아 재도전 여지를 둔다.
# "재처리완료": 재평가로 재생성·발행되어 해소된 옛 HOLD 행(감사 이력 보존용, 발행 카운트 제외).
INACTIVE_ARTICLE_STATUSES = {"삭제됨", "휴지통", "발행취소", "품질보류", "재처리완료"}


class ArticleRepository:
    TABLE = "articles"

    def __init__(self, db: AbstractDBAdapter):
        self._db = db

    def get_all(self) -> list[dict]:
        return self._db.get_all(self.TABLE)

    def get_pending(self) -> list[dict]:
        rows = self._db.get_where(self.TABLE, {"상태값": "대기"})
        rows.sort(key=lambda r: float(r.get("우선발행점수") or 0), reverse=True)
        return rows

    def get_top_pending(self) -> dict | None:
        rows = self.get_pending()
        return rows[0] if rows else None

    def get_recent_published_titles(self, n: int = 30) -> list[str]:
        rows = self._db.get_all(self.TABLE)
        published = [r for r in rows if r.get("상태값") == "발행완료"]
        published.sort(key=lambda r: r.get("발행일시") or "", reverse=True)
        return [r.get("최종추천제목", "") for r in published[:n]]

    def count_active_articles(self, calculator_id, rows=None) -> int:
        """해당 계산기로 발행된 글 중 비활성('삭제됨' 등)을 제외한 유효 발행 건수.
        상태값 문자열 판단은 이 Repository 내부(INACTIVE_ARTICLE_STATUSES)에만 둔다 —
        파이프라인은 이 개수를 MAX_ARTICLES_PER_CALCULATOR와 비교만 한다.
        rows 전달 시 그 스냅샷을 필터(sheet read 절감). None이면 기존대로 get_where."""
        cid = str(calculator_id or "").strip()
        if not cid:
            return 0
        if rows is None:
            src = self._db.get_where(self.TABLE, {"calculator_id": cid})
        else:
            src = [r for r in rows if str(r.get("calculator_id", "")).strip() == cid]
        return sum(1 for r in src
                   if str(r.get("상태값", "")).strip() not in INACTIVE_ARTICLE_STATUSES)

    def has_quality_hold(self, calculator_id, prompt_version=None, rows=None, keyword=None) -> bool:
        """해당 계산기에 자동 품질검수 HOLD("품질보류") 이력이 있는지.
        상태값 문자열 판단은 이 Repository 내부에만 둔다(파이프라인은 True/False만 사용).
        prompt_version 지정 시: 그 버전으로 HOLD된 건이 하나라도 있으면 True
        (프롬프트가 그대로면 재도전 불필요). None이면 HOLD 이력 존재 여부만.
        keyword 지정 시: 그 키워드(정책명)로 HOLD된 건만 판정 대상(키워드 단위 hold_skip).
        None이면 계산기 단위(모든 키워드)로 판정 — legal 미검증 게이트 등 계산기 전체 차단용.
        rows 전달 시 그 스냅샷을 필터(sheet read 절감). None이면 기존대로 get_where."""
        cid = str(calculator_id or "").strip()
        if not cid:
            return False
        if rows is None:
            src = self._db.get_where(self.TABLE, {"calculator_id": cid})
        else:
            src = [r for r in rows if str(r.get("calculator_id", "")).strip() == cid]
        holds = [r for r in src if str(r.get("상태값", "")).strip() == "품질보류"]
        if keyword is not None:
            kw = str(keyword).strip()
            holds = [r for r in holds if str(r.get("정책명", "")).strip() == kw]
        if prompt_version is None:
            return bool(holds)
        return any(str(r.get("quality_prompt_version", "")).strip() == str(prompt_version) for r in holds)

    def resolve_holds_for_calculator(self, calculator_id, new_signature: str = "",
                                     published_post_id: str = "", exclude_id: str = "",
                                     reason: str = "quality_signature_changed") -> int:
        """해당 계산기의 '품질보류' 행을 '재처리완료'로 정리(재생성 발행 성공/재평가 후).

        삭제하지 않고 상태만 변경 + history("quality_hold_released") 기록 → 감사 추적 가능.
        exclude_id(방금 발행한 새 행)는 건너뛴다. 반환: 정리된 행 수.
        상태값 문자열 판단은 이 Repository 내부에만 둔다(파이프라인은 개수만 사용)."""
        cid = str(calculator_id or "").strip()
        if not cid:
            return 0
        n = 0
        for r in self._db.get_where(self.TABLE, {"calculator_id": cid}):
            if str(r.get("상태값", "")).strip() != "품질보류":
                continue
            rid = str(r.get("ID", "") or "")
            if not rid or rid == str(exclude_id):
                continue
            self.update_status(rid, "재처리완료",
                               {"quality_resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            try:
                self.append_history(rid, "quality_hold_released",
                                    {"reason": reason, "new_signature": new_signature,
                                     "published_post_id": str(published_post_id)})
            except Exception:
                pass
            n += 1
        return n

    def get_by_id(self, article_id: str) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"ID": article_id})
        return rows[0] if rows else None

    def save(self, article: dict) -> str:
        if not article.get("ID"):
            article["ID"] = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]
        article.setdefault("상태값", "대기")
        article.setdefault("최종수정일", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        # STEP32: quality_score=0이 SQLiteAdapter/SheetsAdapter의 str(v or "")에 의해
        # 빈 문자열로 소실되는 것을 막기 위해, 여기서만 미리 문자열화한다(STEP31에서 확인된
        # 잠재 위험 경로 — calculator_pipeline.py의 REWRITE HOLD 저장). None은 기존 그대로
        # 어댑터에 넘겨 기존 "빈 값" 처리 동작을 유지한다(전역 adapter는 건드리지 않음).
        if "quality_score" in article and article["quality_score"] is not None:
            article["quality_score"] = str(article["quality_score"])
        return self._db.insert(self.TABLE, article)

    def update_status(self, article_id: str, status: str, extra: dict = None):
        if status not in VALID_STATUSES:
            raise ValueError(f"유효하지 않은 상태값: {status}")
        data = {"상태값": status, "최종수정일": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        if extra:
            data.update(extra)
        # STEP32: save()와 동일한 원칙 — rewrite_pipeline.py가 이 경유로 quality_score를
        # 저장하므로 동일하게 보호한다.
        if "quality_score" in data and data["quality_score"] is not None:
            data["quality_score"] = str(data["quality_score"])
        self._db.update(self.TABLE, article_id, data)

    def upsert_by_policy_name(self, policy_name: str, source_url: str, score: float,
                               site_id: str = "") -> str:
        rows = self._db.get_where(self.TABLE, {"정책명": policy_name})
        if rows:
            return str(rows[0].get("ID", ""))
        return self.save({
            "정책명": policy_name,
            "원본출처": source_url,
            "우선발행점수": score,
            "site_id": site_id,
        })

    def append_history(self, article_id, event, extra=None):
        """기존 history(JSON 문자열)를 읽어 이벤트 1건 append 후 update_status의
        extra로 저장. article이 없거나 history가 비어있으면 빈 배열에서 시작."""
        row = self.get_by_id(article_id)
        hist = []
        try:
            hist = json.loads(row.get("history") or "[]") if row else []
        except Exception:
            hist = []
        entry = {"event": event, "at": datetime.now().isoformat()}
        if extra:
            entry.update(extra)
        hist.append(entry)
        # 상태값 검증(VALID_STATUSES)을 타지 않도록 update_status 대신 저수준 update 사용.
        # 상태값은 그대로 두고 history 필드만 갱신 → "검수대기" 등 어떤 상태에서도 안전.
        return self._db.update(self.TABLE, article_id,
                               {"history": json.dumps(hist, ensure_ascii=False)})

    def increment_fail(self, article_id: str) -> int:
        row = self.get_by_id(article_id)
        if not row:
            return 0
        log = row.get("상태변경로그", "")
        fail_count = log.count("FAIL:") + 1
        self._db.update(self.TABLE, article_id, {
            "상태변경로그": log + f" | FAIL:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "상태값": "재처리대기" if fail_count >= 3 else "발행실패",
        })
        return fail_count
