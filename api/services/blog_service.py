"""api/services/blog_service.py — 실제 운영 Blog(calcmate.kr) 조회 서비스 (STEP 171).

STEP 166~170에서 확인된 사실을 반영한다: 실제 공개 Blog("calcmate.kr/blog/*")는
Cloudflare Worker를 통해 WordPress(blog.genon.app)를 origin으로 사용하며, 과거
정적 스냅샷(data/workspace/_site/blog/*)은 더 이상 실서비스 경로가 아니어서
제거되었다(STEP 170).

이 서비스는 이제 WordPress 발행 상태를 추적하는 SQLite MAIN의 blog_articles
테이블을 조회한다 — 새 DB 연결 방식을 만들지 않고 기존
repositories.blog_article_repository.BlogArticleRepository를 그대로 재사용한다.
DB write는 하지 않는다(list_all()은 순수 조회).
"""
from adapters.db.factory import get_db_adapter
from modules.config_loader import load_config
from repositories.blog_article_repository import BlogArticleRepository


def list_blog_posts() -> dict:
    """blog_articles를 읽기 전용으로 조회해 실제 운영(WordPress) Blog 목록을 만든다."""
    cfg = load_config()
    rows = BlogArticleRepository(get_db_adapter(cfg)).list_all()

    posts = [
        {
            "slug": row.get("slug", ""),
            "title": row.get("title", ""),
            "public_url": row.get("canonical_url") or row.get("wp_permalink") or "",
            "file_exists": row.get("wp_status") == "publish",
        }
        for row in sorted(rows, key=lambda r: r.get("slug", ""))
    ]

    return {"total": len(posts), "posts": posts}
