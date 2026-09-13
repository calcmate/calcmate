# -*- coding: utf-8 -*-
"""tests/test_blog_article_repository.py

BlogArticleRepository + run_blog_articles_sync_once() 검증.
SQLiteAdapter를 tmp_path에 물려 사용 — 실제 프로젝트 DB(data/blog_auto.db),
Google Sheets, WordPress는 전혀 건드리지 않는다(네트워크 호출 없음, wp_get_fn은 전부 fake).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.article_repository import ArticleRepository
from repositories.blog_article_repository import BlogArticleRepository
from modules.blog_articles_sync import run_blog_articles_sync_once, SEVERITY_INFO, SEVERITY_WARN, SEVERITY_FAIL, SEVERITY_CRITICAL


def _adapter(tmp_path) -> SQLiteAdapter:
    cfg = {"SQLITE_PATH": "test_blog_articles.db", "_root": str(tmp_path)}
    return SQLiteAdapter(cfg)


def _sample_row(n=1, **overrides):
    row = {
        "article_id": f"blog_test_{n:03d}",
        "slug": f"slug-{n}",
        "title": f"제목 {n}",
        "content": f"본문 {n}",
        "calculator_id": f"calc_{n}",
        "intent": "calculator",
        "content_source": "wordpress_migrated",
        "status": "publish",
        "wp_post_id": str(500 + n),
        "wp_status": "publish",
        "wp_permalink": f"https://blog.genon.app/slug-{n}/",
        "canonical_url": f"https://calcmate.kr/blog/slug-{n}/",
        "seo_title": None,
        "meta_description": None,
        "published_at": "2026-09-07T00:00:00",
        "created_at": "2026-09-12T00:00:00",
        "updated_at": "2026-09-09T00:00:00",
        "last_synced_at": "2026-09-12T00:00:00",
        "sync_status": "synced",
        "sync_error": None,
    }
    row.update(overrides)
    return row


def _seed(tmp_path, n=10):
    adapter = _adapter(tmp_path)
    for i in range(1, n + 1):
        adapter.insert("blog_articles", _sample_row(i))
    return adapter


# ── A. BlogArticleRepository가 TABLE="blog_articles"를 사용하는지 ──────
def test_a_blog_article_repository_table_is_blog_articles():
    assert BlogArticleRepository.TABLE == "blog_articles"


# ── B. 기존 ArticleRepository가 TABLE="articles"를 계속 사용하는지(회귀) ──
def test_b_article_repository_table_still_articles():
    assert ArticleRepository.TABLE == "articles"


# ── C. get_by_wp_post_id()가 정확한 건을 조회하는지 ───────────────────
def test_c_get_by_wp_post_id_and_slug_and_article_id(tmp_path):
    adapter = _seed(tmp_path, n=10)
    repo = BlogArticleRepository(adapter)

    assert len(repo.list_all()) == 10

    row = repo.get_by_wp_post_id("505")
    assert row is not None
    assert row["slug"] == "slug-5"

    row2 = repo.get_by_slug("slug-3")
    assert row2["wp_post_id"] == "503"

    row3 = repo.get_by_article_id("blog_test_007")
    assert row3["wp_post_id"] == "507"

    assert repo.get_by_wp_post_id("999999") is None


# ── D. WP 응답 vs SQLite 비교 분류 ────────────────────────────────────
def test_d_classify_same_is_info(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert len(results) == 1
    assert results[0]["severity"] == SEVERITY_INFO


def test_d_classify_modified_changed_is_warn(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": "2099-01-01T00:00:00",
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_WARN
    assert "modified_changed" in results[0]["reasons"]


def test_d_classify_title_changed_is_warn(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": "완전히 바뀐 제목", "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_WARN
    assert "title_changed" in results[0]["reasons"]


def test_d_classify_content_changed_is_warn(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": "완전히 바뀐 본문",
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_WARN
    assert "content_changed" in results[0]["reasons"]


def test_d_classify_slug_changed_is_fail(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "changed-slug",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_FAIL
    assert "slug_changed" in results[0]["reasons"]


def test_d_classify_status_changed_is_fail(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": "trash", "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_FAIL
    assert any("status_changed" in r for r in results[0]["reasons"])


def test_d_classify_404_is_critical(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        return {"success": False, "http_status": 404, "error": "not found", "wp_post_id": post_id}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_CRITICAL
    assert "wp_post_not_found_404" in results[0]["reasons"]


def test_d_classify_post_id_mismatch_is_critical(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": 999999, "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_CRITICAL
    assert any("wp_post_id_mismatch" in r for r in results[0]["reasons"])


# ── E. 변경 감지 함수가 SQLite 값을 변경하지 않는지 ────────────────────
def test_e_sync_does_not_mutate_sqlite(tmp_path):
    adapter = _seed(tmp_path, n=10)
    repo = BlogArticleRepository(adapter)
    before = repo.list_all()

    def fake_wp_get(post_id, **kwargs):
        # 일부러 전부 다른 값을 주어도 SQLite가 바뀌지 않아야 한다.
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "다른slug",
                "status": "trash", "date": "1999-01-01", "modified": "1999-01-01",
                "link": "https://example.com/other/", "title": "다른 제목", "content": "다른 본문",
                "excerpt": "다른 요약"}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert len(results) == 10

    after = repo.list_all()
    assert before == after   # 완전히 동일해야 함(단 하나도 변경되지 않음)


# ── F. WP POST/PATCH/DELETE를 호출하지 않는지(구조 검증) ──────────────
def test_f_wp_readonly_client_has_no_write_methods():
    import modules.wp_readonly_client as client
    src = Path(client.__file__).read_text(encoding="utf-8")
    assert "urllib.request.Request" in src
    # method="GET" 명시, POST/PUT/PATCH/DELETE 문자열이 실제 요청 메서드로 쓰이지 않음
    assert 'method="GET"' in src
    for forbidden in ['method="POST"', 'method="PUT"', 'method="PATCH"', 'method="DELETE"']:
        assert forbidden not in src


def test_f_sync_never_calls_adapter_write_methods(tmp_path):
    adapter = _seed(tmp_path, n=3)

    write_calls = []
    orig_insert, orig_update, orig_delete = adapter.insert, adapter.update, adapter.delete
    adapter.insert = lambda *a, **k: write_calls.append(("insert", a, k)) or orig_insert(*a, **k)
    adapter.update = lambda *a, **k: write_calls.append(("update", a, k)) or orig_update(*a, **k)
    adapter.delete = lambda *a, **k: write_calls.append(("delete", a, k)) or orig_delete(*a, **k)

    repo = BlogArticleRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "changed",
                "status": "trash", "date": "x", "modified": "x", "link": "x",
                "title": "x", "content": "x", "excerpt": "x"}

    run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert write_calls == []   # insert/update/delete 전부 호출되지 않아야 함


# ── STEP16: 한글 slug 오탐 회귀 테스트 ────────────────────────────────
# WP REST가 한글 slug를 URL-encoded로 반환해도(SQLite엔 디코딩된 값 저장),
# slug_changed로 오판(FAIL)하지 않고 INFO로 판정해야 한다.

def test_step16_case_a_ascii_slug_matches_as_info(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.insert("blog_articles", _sample_row(1, slug="severance-pay",
                                                 wp_permalink="https://blog.genon.app/severance-pay/"))
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "severance-pay",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_INFO
    assert "slug_changed" not in results[0]["reasons"]


def test_step16_case_b_korean_slug_urlencoded_matches_as_info(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.insert("blog_articles", _sample_row(
        9, slug="육아휴직_급여_계산기",
        wp_permalink="https://blog.genon.app/%ec%9c%a1%ec%95%84%ed%9c%b4%ec%a7%81_%ea%b8%89%ec%97%ac_%ea%b3%84%ec%82%b0%ea%b8%b0/",
    ))
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_009")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id),
                "slug": "%ec%9c%a1%ec%95%84%ed%9c%b4%ec%a7%81_%ea%b8%89%ec%97%ac_%ea%b3%84%ec%82%b0%ea%b8%b0",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_INFO
    assert "slug_changed" not in results[0]["reasons"]


def test_step16_yearend_korean_slug_urlencoded_matches_as_info(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.insert("blog_articles", _sample_row(
        10, slug="연말정산_환급액_계산기",
        wp_permalink="https://blog.genon.app/%ec%97%b0%eb%a7%90%ec%a0%95%ec%82%b0_%ed%99%98%ea%b8%89%ec%95%a1_%ea%b3%84%ec%82%b0%ea%b8%b0/",
    ))
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_010")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id),
                "slug": "%ec%97%b0%eb%a7%90%ec%a0%95%ec%82%b0_%ed%99%98%ea%b8%89%ec%95%a1_%ea%b3%84%ec%82%b0%ea%b8%b0",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_INFO
    assert "slug_changed" not in results[0]["reasons"]


def test_step16_slug_still_detected_when_actually_different(tmp_path):
    """오탐 수정이 진짜 slug 변경 감지 기능 자체를 죽이지 않았는지 확인(회귀 방지)."""
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "actually-different-slug",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_FAIL
    assert "slug_changed" in results[0]["reasons"]


# ── STEP18: excerpt ↔ meta_description 비교 제거(정책 B) 회귀 테스트 ──
# meta_description=NULL인 상태에서 WP excerpt가 존재해도(둘이 달라도) INFO여야 한다.

def test_step18_case1_null_meta_description_with_wp_excerpt_is_info(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.insert("blog_articles", _sample_row(1, meta_description=None))
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")
    assert row["meta_description"] in (None, "", "None")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": "WP에만 존재하는 실제 요약문(GOLDEN_10 description 유래)"}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_INFO
    assert "excerpt_changed" not in results[0]["reasons"]


def test_step18_case2_title_changed_still_warn(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": "바뀐 제목", "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_WARN
    assert "title_changed" in results[0]["reasons"]


def test_step18_case3_content_changed_still_warn(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": "바뀐 본문",
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_WARN
    assert "content_changed" in results[0]["reasons"]


def test_step18_case4_slug_changed_still_fail(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": "다른-slug",
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_FAIL
    assert "slug_changed" in results[0]["reasons"]


def test_step18_case5_status_changed_still_fail(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": row["slug"],
                "status": "draft", "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_FAIL
    assert any("status_changed" in r for r in results[0]["reasons"])


def test_step18_case6_id_mismatch_still_critical(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)
    row = repo.get_by_article_id("blog_test_001")

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": 424242, "slug": row["slug"],
                "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                "excerpt": row["meta_description"] or ""}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_CRITICAL


def test_step18_case6b_get_failure_still_critical(tmp_path):
    adapter = _seed(tmp_path, n=1)
    repo = BlogArticleRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        return {"success": False, "http_status": None, "error": "connection error", "wp_post_id": post_id}

    results = run_blog_articles_sync_once({}, repo=repo, wp_get_fn=fake_wp_get)
    assert results[0]["severity"] == SEVERITY_CRITICAL


def test_step18_case7_korean_slugs_with_null_meta_description_are_info(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.insert("blog_articles", _sample_row(
        9, slug="육아휴직_급여_계산기", meta_description=None,
        wp_permalink="https://blog.genon.app/%ec%9c%a1%ec%95%84%ed%9c%b4%ec%a7%81_%ea%b8%89%ec%97%ac_%ea%b3%84%ec%82%b0%ea%b8%b0/",
    ))
    adapter.insert("blog_articles", _sample_row(
        10, slug="연말정산_환급액_계산기", meta_description=None,
        wp_permalink="https://blog.genon.app/%ec%97%b0%eb%a7%90%ec%a0%95%ec%82%b0_%ed%99%98%ea%b8%89%ec%95%a1_%ea%b3%84%ec%82%b0%ea%b8%b0/",
    ))
    repo = BlogArticleRepository(adapter)

    def make_fake(slug_encoded, row):
        def fake_wp_get(post_id, **kwargs):
            return {"success": True, "http_status": 200, "id": int(post_id), "slug": slug_encoded,
                    "status": row["wp_status"], "date": row["published_at"], "modified": row["last_synced_at"],
                    "link": row["wp_permalink"], "title": row["title"], "content": row["content"],
                    "excerpt": "GOLDEN_10에서 유래한 실제 WP 요약문"}
        return fake_wp_get

    row9 = repo.get_by_article_id("blog_test_009")
    results9 = run_blog_articles_sync_once(
        {}, repo=repo,
        wp_get_fn=make_fake("%ec%9c%a1%ec%95%84%ed%9c%b4%ec%a7%81_%ea%b8%89%ec%97%ac_%ea%b3%84%ec%82%b0%ea%b8%b0", row9))
    r9 = [r for r in results9 if r["article_id"] == "blog_test_009"][0]
    assert r9["severity"] == SEVERITY_INFO

    row10 = repo.get_by_article_id("blog_test_010")
    results10 = run_blog_articles_sync_once(
        {}, repo=repo,
        wp_get_fn=make_fake("%ec%97%b0%eb%a7%90%ec%a0%95%ec%82%b0_%ed%99%98%ea%b8%89%ec%95%a1_%ea%b3%84%ec%82%b0%ea%b8%b0", row10))
    r10 = [r for r in results10 if r["article_id"] == "blog_test_010"][0]
    assert r10["severity"] == SEVERITY_INFO
