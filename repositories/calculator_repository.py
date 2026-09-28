"""
repositories/calculator_repository.py — CalculatorRepository
"""
import uuid
from datetime import datetime
from adapters.db.base import AbstractDBAdapter


class DuplicateCalculatorIdError(Exception):
    """save() 호출 시 동일 id row가 DB에 이미 2건 이상 존재해 안전하게
    update로 라우팅할 수 없는 상태. 임의로 한쪽을 골라 덮어쓰거나 삭제하지
    않고 명시적으로 실패시킨다(중복 정리는 별도 절차로 선행되어야 함)."""


class CalculatorRepository:
    TABLE = "calculators"

    def __init__(self, db: AbstractDBAdapter):
        self._db = db

    def get_all(self) -> list[dict]:
        return self._db.get_all(self.TABLE)

    def get_active(self) -> list[dict]:
        return self._db.get_where(self.TABLE, {"status": "active"})

    def get_by_site(self, site_id: str) -> list[dict]:
        return self._db.get_where(self.TABLE, {"site_id": site_id})

    def get_by_id(self, calc_id: str) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"id": calc_id})
        return rows[0] if rows else None

    def is_active(self, calc_id: str) -> bool:
        """계산기가 활성 상태인지. 상태값 문자열 비교는 이 Repository 내부에만 둔다
        (엔진/파이프라인은 이 헬퍼로만 판단). 존재하지 않으면(하드삭제 등) False."""
        row = self.get_by_id(calc_id)
        return bool(row) and str(row.get("status", "")).strip().lower() == "active"

    def save(self, calc: dict) -> str:
        """id가 이미 지정돼 있고 그 id로 DB에 기존 row가 있으면 UPDATE로
        라우팅한다(기존엔 무조건 INSERT라 동일 id가 중복 생성됐음 — 이 STEP에서 수정).
        동일 id가 2건 이상(비정상 중복) 존재하면 어느 쪽을 update할지 임의로
        고르지 않고 DuplicateCalculatorIdError를 던져 안전하게 실패한다."""
        existing_id = calc.get("id")
        if existing_id:
            matches = self._db.get_where(self.TABLE, {"id": existing_id})
            if len(matches) > 1:
                raise DuplicateCalculatorIdError(
                    f"id={existing_id!r}가 이미 {len(matches)}건 중복 존재 — "
                    "save()가 임의로 하나를 골라 덮어쓰지 않도록 중단합니다. "
                    "중복을 먼저 정리한 뒤 다시 시도하세요."
                )
            if len(matches) == 1:
                data = {k: v for k, v in calc.items() if k != "id"}
                self.update(existing_id, data)
                return existing_id
        if not calc.get("id"):
            calc["id"] = "calc_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:4]
        calc.setdefault("status", "draft")
        calc.setdefault("version", "1.0.0")
        calc.setdefault("created_at", datetime.now().isoformat())
        calc.setdefault("updated_at", datetime.now().isoformat())
        return self._db.insert(self.TABLE, calc)

    # create(): save 의 명시적 별칭 (기본 status=active)
    def create(self, calc: dict) -> str:
        calc.setdefault("status", "active")
        return self.save(calc)

    def get_by_slug(self, slug: str) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"slug": slug})
        return rows[0] if rows else None

    def upsert_by_slug(self, calc: dict) -> str:
        """slug로 기존 행을 찾으면 '비어있는 필드만' 채워 보존 update,
        없으면 create. 기존 비어있지 않은 값(article_content 등)은 덮지 않는다.
        시드 멱등성 + 생성 콘텐츠 보존용."""
        slug = (calc.get("slug") or "").strip()
        existing = self.get_by_slug(slug) if slug else None
        if not existing:
            return self.create(calc)
        fill = {k: v for k, v in calc.items()
                if k != "id" and not str(existing.get(k, "")).strip()}
        if fill:
            self.update(existing.get("id", ""), fill)
        return existing.get("id", "")

    def update(self, calc_id: str, data: dict):
        data["updated_at"] = datetime.now().isoformat()
        self._db.update(self.TABLE, calc_id, data)

    def delete(self, calc_id: str):
        self._db.delete(self.TABLE, calc_id)

    def publish(self, calc_id: str, url: str):
        self.update(calc_id, {"status": "active", "published_url": url})

    def update_generated(self, calc_id: str, data: dict):
        """AI 자동생성 결과 저장(seo_title/seo_description/article_content/
        image_prompt_thumbnail/image_prompt_body 등) + generated_at 스탬프.
        기존 컬럼은 변경하지 않고 신규 컬럼만 추가(어댑터가 자동 생성)."""
        payload = dict(data or {})
        # STEP24: review_score=0이 SQLiteAdapter/SheetsAdapter의 str(v or "")에 의해
        # 빈 문자열로 소실되는 것을 막기 위해, 여기서만 미리 문자열화한다(STEP22/23에서
        # 확인된 저장 경로 — approve()/reject() → update_generated()). None은 기존 그대로
        # 어댑터에 넘겨 기존 "빈 값" 처리 동작을 유지한다(전역 adapter는 건드리지 않음).
        if "review_score" in payload and payload["review_score"] is not None:
            payload["review_score"] = str(payload["review_score"])
        # STEP27: review_attempts=0도 동일한 소실 위험이 있다(STEP26에서 severance-pay/
        # severance-pay-documents가 review_status=AUTO_APPROVED인데 review_attempts만
        # 빈 문자열로 남은 것을 실증 확인 — auto_review_and_fix()의 attempts=0이 그 원인).
        # review_score와 동일한 원칙으로 None만 기존 동작 유지, 그 외는 문자열화.
        if "review_attempts" in payload and payload["review_attempts"] is not None:
            payload["review_attempts"] = str(payload["review_attempts"])
        payload["generated_at"] = datetime.now().isoformat()
        self.update(calc_id, payload)