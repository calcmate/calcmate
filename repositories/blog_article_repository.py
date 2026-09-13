"""
repositories/blog_article_repository.py — BlogArticleRepository

blog_articles 전용 Repository. articles(ArticleRepository)와 완전히 독립적이며,
articles 테이블은 절대 대상으로 하지 않는다.

update_sync_metadata()가 수정 가능한 필드는 다음으로 제한한다:
  wp_status / last_synced_at / sync_status / sync_error
그 외 필드(content/title/slug/calculator_id/intent/content_source/wp_post_id/
wp_permalink/canonical_url/seo_title/meta_description/published_at/created_at/
updated_at)는 이 Repository가 자동으로 덮어쓰지 않는다.
"""
from adapters.db.base import AbstractDBAdapter

SYNC_METADATA_FIELDS = {"wp_status", "last_synced_at", "sync_status", "sync_error"}


class BlogArticleRepository:
    TABLE = "blog_articles"

    def __init__(self, db: AbstractDBAdapter):
        self._db = db

    def list_all(self) -> list[dict]:
        return self._db.get_all(self.TABLE)

    def get_by_article_id(self, article_id: str) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"article_id": article_id})
        return rows[0] if rows else None

    def get_by_wp_post_id(self, wp_post_id) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"wp_post_id": str(wp_post_id)})
        return rows[0] if rows else None

    def get_by_slug(self, slug: str) -> dict | None:
        rows = self._db.get_where(self.TABLE, {"slug": slug})
        return rows[0] if rows else None

    def insert(self, row: dict) -> str:
        """신규 row 삽입. 이 Repository는 INSERT를 제공하지만 호출 여부는 상위 책임이다."""
        return self._db.insert(self.TABLE, row)

    def update_sync_metadata(self, article_id: str, wp_status: str = None,
                              sync_status: str = None, sync_error: str = None,
                              last_synced_at: str = None) -> None:
        """동기화 메타데이터만 갱신한다(content/title/slug 등 본문성 필드는 절대 건드리지 않음).

        SQLiteAdapter.update()가 'updated_at' 미지정 시 현재 시각으로 자동 채우므로,
        이 함수가 의도치 않게 updated_at을 변경하지 않도록 기존 값을 그대로 유지해 전달한다.
        """
        row = self.get_by_article_id(article_id)
        if row is None:
            raise ValueError(f"blog_articles에 article_id={article_id!r} 행이 없습니다.")

        data = {}
        if wp_status is not None:
            data["wp_status"] = wp_status
        if sync_status is not None:
            data["sync_status"] = sync_status
        if sync_error is not None:
            data["sync_error"] = sync_error
        if last_synced_at is not None:
            data["last_synced_at"] = last_synced_at

        unexpected = set(data.keys()) - SYNC_METADATA_FIELDS
        if unexpected:
            raise ValueError(f"update_sync_metadata()는 {SYNC_METADATA_FIELDS}만 허용합니다: {unexpected}")

        # updated_at은 이 함수의 갱신 대상이 아니므로 기존 값을 그대로 유지해 자동 변경을 막는다.
        data["updated_at"] = row.get("updated_at")

        self._db.update(self.TABLE, article_id, data)
