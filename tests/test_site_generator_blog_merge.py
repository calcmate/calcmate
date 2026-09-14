# -*- coding: utf-8 -*-
"""tests/test_site_generator_blog_merge.py

modules/site_generator.py의 GOLDEN_10 + blog_articles 병합 로직 검증(STEP186).
실제 프로젝트 DB(data/blog_auto.db)는 전혀 건드리지 않는다 — adapters.db.factory
.get_db_adapter를 monkeypatch해 tmp_path 위의 임시 SQLite로 완전히 격리한다.
"""
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
import modules.site_generator as sg
from content.blog import GOLDEN_10


def _seed_extra_row(tmp_path, wp_post_id, slug, title="제목", desc="설명", wp_status="publish"):
    adapter = SQLiteAdapter({"SQLITE_PATH": "test_merge.db", "_root": str(tmp_path)})
    adapter.insert("blog_articles", {
        "article_id": f"blog_extra_{wp_post_id}", "slug": slug, "title": title,
        "content": "<p>본문</p>", "calculator_id": None, "intent": "howto",
        "content_source": "wordpress_auto", "status": "publish",
        "wp_post_id": str(wp_post_id), "wp_status": wp_status,
        "wp_permalink": f"https://blog.genon.app/{slug}/",
        "canonical_url": f"https://calcmate.kr/blog/{slug}/",
        "seo_title": None, "meta_description": desc,
        "published_at": "2026-09-14T00:00:00", "created_at": "2026-09-14T00:00:00",
        "updated_at": "2026-09-14T00:00:00", "last_synced_at": "2026-09-14T00:00:00",
        "sync_status": "synced", "sync_error": None,
    })
    return str(tmp_path / "test_merge.db")


def _patched_db_adapter(tmp_path):
    def fake_get_db_adapter(_cfg):
        return SQLiteAdapter({"SQLITE_PATH": "test_merge.db", "_root": str(tmp_path)})
    return mock.patch("adapters.db.factory.get_db_adapter", side_effect=fake_get_db_adapter)


def test_extra_published_blog_articles_excludes_golden10_slugs(tmp_path):
    golden_slug = GOLDEN_10[0].slug
    _seed_extra_row(tmp_path, 9001, golden_slug)  # GOLDEN_10과 겹치는 slug는 절대 extra로 안 나옴
    _seed_extra_row(tmp_path, 9002, "genuinely-new-slug")

    with _patched_db_adapter(tmp_path):
        extras = sg._extra_published_blog_articles({})

    slugs = {e["slug"] for e in extras}
    assert golden_slug not in slugs
    assert "genuinely-new-slug" in slugs


def test_extra_published_blog_articles_excludes_non_publish(tmp_path):
    _seed_extra_row(tmp_path, 9003, "draft-slug", wp_status="draft")
    with _patched_db_adapter(tmp_path):
        extras = sg._extra_published_blog_articles({})
    assert "draft-slug" not in {e["slug"] for e in extras}


def test_generate_index_preserves_golden10_cards_and_order(tmp_path):
    _seed_extra_row(tmp_path, 9004, "new-guide-x", title="새 글 X", desc="새 글 설명")
    with _patched_db_adapter(tmp_path):
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    # 기존 10개 카드 마커가 그대로, 원래 순서 그대로 존재
    positions = []
    for gc in GOLDEN_10:
        marker = f'href="https://calcmate.kr/blog/{gc.slug}/" aria-label="{gc.title}"'
        assert marker in html, f"GOLDEN_10 카드 손상: {gc.slug}"
        positions.append(html.index(marker))
    assert positions == sorted(positions)

    # 신규 글 카드도 추가로 존재
    assert "/blog/new-guide-x/" in html
    assert "새 글 X" in html


def test_generate_index_without_extra_rows_matches_golden10_only_behavior(tmp_path):
    """extra row가 하나도 없으면(=신규 없음) 기존 동작과 완전히 동일해야 한다."""
    SQLiteAdapter({"SQLITE_PATH": "test_merge_empty.db", "_root": str(tmp_path)})

    def fake_get_db_adapter(_cfg):
        return SQLiteAdapter({"SQLITE_PATH": "test_merge_empty.db", "_root": str(tmp_path)})

    with mock.patch("adapters.db.factory.get_db_adapter", side_effect=fake_get_db_adapter):
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    for gc in GOLDEN_10:
        assert f'href="https://calcmate.kr/blog/{gc.slug}/"' in html


def test_generate_sitemap_merges_without_duplicates(tmp_path):
    _seed_extra_row(tmp_path, 9005, "sitemap-new-guide")
    with _patched_db_adapter(tmp_path):
        xml = sg.generate_sitemap({"SITE_URL": "https://calcmate.kr"})

    urls = re.findall(r"<loc>(.*?)</loc>", xml)
    assert len(urls) == len(set(urls))  # 중복 URL 없음
    assert any(u.endswith("/blog/sitemap-new-guide/") for u in urls)
    for gc in GOLDEN_10:
        assert any(u.endswith(f"/blog/{gc.slug}/") for u in urls)


def test_extra_published_blog_articles_returns_empty_on_db_error():
    """DB 접근이 실패해도(어댑터 미구성 등) 메인 페이지 생성 자체가 죽지 않도록
    빈 리스트를 반환해야 한다."""
    def failing_get_db_adapter(_cfg):
        raise RuntimeError("db unavailable")

    with mock.patch("adapters.db.factory.get_db_adapter", side_effect=failing_get_db_adapter):
        extras = sg._extra_published_blog_articles({})
    assert extras == []
