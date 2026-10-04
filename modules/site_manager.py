"""
modules/site_manager.py — SiteRepository 브릿지
main.py 등 기존 호출부가 수정 없이 동작하도록 유지.
"""
from adapters.db.factory import get_db_adapter
from repositories.site_repository import SiteRepository


class SiteManager:
    def __init__(self, cfg: dict):
        db = get_db_adapter(cfg)
        self._repo = SiteRepository(db, cfg)

    def get_active_sites(self) -> list[dict]:
        return self._repo.get_active_sites()

    def get_all_sites(self) -> list[dict]:
        """전체 site(상태 무관, 저장소 순서 그대로) — site_wizard.list_sites()와 동일한 조회."""
        return self._repo.get_all()

    def get_by_id(self, site_id: str) -> dict | None:
        return self._repo.get_by_id(site_id)

    def get_wp_config(self, site_id: str) -> dict:
        return self._repo.get_wp_config(site_id)

    def get_ai_config(self, site_id: str) -> dict:
        return self._repo.get_ai_config(site_id)

    def register_site(self, site: dict) -> str:
        return self._repo.save(site)

    def update_status(self, site_id: str, status: str):
        self._repo.update_status(site_id, status)
