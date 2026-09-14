# -*- coding: utf-8 -*-
"""tests/test_wp_blog_sync.py

modules/wp_blog_sync.py 검증(STEP186). 네트워크 호출 없음(WP GET은 전부 fake dict),
실제 프로젝트 DB(data/blog_auto.db)는 전혀 건드리지 않는다 — 모든 DB 접근은
tmp_path 위의 임시 SQLite 파일을 사용한다.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.blog_article_repository import BlogArticleRepository, CONTENT_UPDATE_FIELDS
from modules.wp_blog_sync import (
    detect_new_and_modified,
    build_new_article_row,
    insert_new_articles_transactional,
    _validate_row,
)


GOLDEN10_SLUGS = {"severance-pay", "weekly-holiday-allowance"}


def _existing_row(wp_post_id="502", slug="severance-pay", last_synced_at="2026-09-12T13:01:56"):
    return {
        "article_id": "blog_existing_001", "slug": slug, "wp_post_id": wp_post_id,
        "last_synced_at": last_synced_at, "updated_at": last_synced_at,
    }


def _wp_post(post_id=999999, slug="new-post", status="publish",
             modified_gmt="2026-09-14T00:00:00"):
    return {
        "id": post_id, "slug": slug, "status": status,
        "title": "제목", "excerpt": "<p>요약</p>", "link": f"https://blog.genon.app/{slug}/",
        "date": "2026-09-14T09:00:00", "date_gmt": "2026-09-14T00:00:00",
        "modified": "2026-09-14T09:00:00", "modified_gmt": modified_gmt,
    }


# ── A. 신규 감지 ────────────────────────────────────────────────────────
def test_a_new_post_detected():
    existing = [_existing_row()]
    posts = [_wp_post(post_id=991001, slug="brand-new-post")]
    result = detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert len(result["new"]) == 1
    assert result["new"][0]["slug"] == "brand-new-post"
    assert result["skipped_golden10"] == []
    assert result["modified"] == []


def test_b_multiple_new_posts_detected():
    existing = [_existing_row()]
    posts = [
        _wp_post(post_id=991001, slug="new-a"),
        _wp_post(post_id=991002, slug="new-b"),
        _wp_post(post_id=991003, slug="new-c"),
    ]
    result = detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert {p["slug"] for p in result["new"]} == {"new-a", "new-b", "new-c"}


def test_c_existing_wp_post_id_not_treated_as_new():
    """이미 blog_articles에 있는 wp_post_id는 재처리해도 신규로 잡히지 않는다(중복 방지)."""
    existing = [_existing_row(wp_post_id="502", slug="severance-pay")]
    posts = [_wp_post(post_id=502, slug="severance-pay")]
    result = detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert result["new"] == []


def test_e_draft_status_not_detected_as_new():
    existing = [_existing_row()]
    posts = [_wp_post(post_id=991004, slug="draft-post", status="draft")]
    result = detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert result["new"] == []


def test_f_golden10_slug_never_treated_as_new_even_if_unknown_wp_post_id():
    """GOLDEN_10 slug는 blog_articles에 매칭되는 row가 없어도(예: wp_post_id 불일치)
    절대 신규 INSERT 후보가 되지 않는다 — skipped_golden10으로만 분류된다."""
    existing = [_existing_row(wp_post_id="502", slug="severance-pay")]
    posts = [_wp_post(post_id=999999, slug="severance-pay")]  # 다른 wp_post_id, 같은 golden10 slug
    result = detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert result["new"] == []
    assert len(result["skipped_golden10"]) == 1


def test_g_modified_detection_uses_utc_aware_comparison():
    """WP modified_gmt(UTC)가 blog_articles.last_synced_at(naive KST 해석) 보다
    실제로 더 최근일 때만 modified로 분류한다."""
    # last_synced_at(KST) 2026-09-12T13:01:56 == UTC 2026-09-12T04:01:56
    existing = [_existing_row(wp_post_id="502", slug="severance-pay",
                               last_synced_at="2026-09-12T13:01:56")]
    posts_newer = [_wp_post(post_id=502, slug="severance-pay", modified_gmt="2026-09-13T21:20:26")]
    result_newer = detect_new_and_modified(posts_newer, existing, GOLDEN10_SLUGS)
    assert len(result_newer["modified"]) == 1

    posts_older = [_wp_post(post_id=502, slug="severance-pay", modified_gmt="2026-09-10T00:00:00")]
    result_older = detect_new_and_modified(posts_older, existing, GOLDEN10_SLUGS)
    assert result_older["modified"] == []


def test_modified_detection_does_not_write_anything():
    """detect_new_and_modified는 순수 함수 — modified로 분류돼도 실제 UPDATE는
    이 함수도, run_wp_blog_sync_once도 이번 STEP 범위에서 수행하지 않는다(참고용)."""
    existing = [_existing_row(wp_post_id="502", slug="severance-pay",
                               last_synced_at="2026-09-01T00:00:00")]
    before = dict(existing[0])
    posts = [_wp_post(post_id=502, slug="severance-pay", modified_gmt="2026-09-14T00:00:00")]
    detect_new_and_modified(posts, existing, GOLDEN10_SLUGS)
    assert existing[0] == before  # 입력 dict 자체가 변형되지 않음


# ── B. row 조립/검증 ────────────────────────────────────────────────────
def test_build_new_article_row_has_all_required_fields():
    post = _wp_post(post_id=991005, slug="row-build-test")
    wp_full = {"title": "제목", "content": "<p>본문</p>", "excerpt": "<p>요약문</p>",
               "link": "https://blog.genon.app/row-build-test/", "date": "2026-09-14T00:00:00"}
    row = build_new_article_row(post, wp_full)
    assert _validate_row(row) is None
    assert row["calculator_id"] is None
    assert row["intent"] == "howto"
    assert row["content_source"] == "wordpress_auto"
    assert row["meta_description"] == "요약문"  # HTML 태그 제거됨
    assert row["canonical_url"] == "https://calcmate.kr/blog/row-build-test/"


def test_build_new_article_row_empty_excerpt_falls_back_to_none():
    post = _wp_post(post_id=991006, slug="empty-excerpt-test")
    wp_full = {"title": "제목", "content": "<p>본문</p>", "excerpt": "",
               "link": "https://blog.genon.app/x/", "date": "2026-09-14T00:00:00"}
    row = build_new_article_row(post, wp_full)
    assert row["meta_description"] is None
    assert _validate_row(row) is None  # meta_description은 nullable이라 유효


def test_validate_row_catches_missing_required_field():
    row = build_new_article_row(_wp_post(post_id=991007, slug="x"),
                                 {"title": "", "content": "y", "excerpt": "", "link": "l", "date": "d"})
    assert _validate_row(row) == "required_field_empty:title"


# ── C. transaction/rollback ─────────────────────────────────────────────
def _make_test_db(tmp_path) -> str:
    """blog_articles 테이블이 있는 임시 SQLite 파일 생성(실제 스키마와 동일한 컬럼)."""
    db_path = str(tmp_path / "test_wp_blog_sync.db")
    adapter = SQLiteAdapter({"SQLITE_PATH": "test_wp_blog_sync.db", "_root": str(tmp_path)})
    seed_row = build_new_article_row(
        _wp_post(post_id=1, slug="seed"),
        {"title": "seed", "content": "seed", "excerpt": "seed", "link": "https://x/seed/", "date": "2026-01-01"},
    )
    adapter.insert("blog_articles", seed_row)
    return db_path


def test_transactional_insert_multiple_success(tmp_path):
    db_path = _make_test_db(tmp_path)
    rows = [
        build_new_article_row(_wp_post(post_id=2001, slug="tx-a"),
                               {"title": "A", "content": "a", "excerpt": "a", "link": "https://x/a/", "date": "d"}),
        build_new_article_row(_wp_post(post_id=2002, slug="tx-b"),
                               {"title": "B", "content": "b", "excerpt": "b", "link": "https://x/b/", "date": "d"}),
        build_new_article_row(_wp_post(post_id=2003, slug="tx-c"),
                               {"title": "C", "content": "c", "excerpt": "c", "link": "https://x/c/", "date": "d"}),
    ]
    result = insert_new_articles_transactional(db_path, rows)
    assert result["success"] is True
    assert result["inserted"] == 3

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM blog_articles").fetchone()[0]
    conn.close()
    assert count == 1 + 3  # seed 1건 + 신규 3건


def test_transactional_insert_rollback_on_invalid_row(tmp_path):
    """3건 중 마지막(C)이 필수 필드 누락으로 무효화되면, 앞의 2건(A/B)이 개별적으로는
    유효했더라도 전부 rollback되어 DB에 하나도 반영되지 않아야 한다(전체 성공/전체 롤백).

    SQLiteAdapter._ensure_table()은 컬럼을 전부 TEXT로만 선언하고 PK/UNIQUE 제약을
    코드로 강제하지 않는다(실제 운영 DB의 UNIQUE 제약은 과거 별도 마이그레이션으로
    생성된 것으로, 이 어댑터가 신규로 만드는 스키마에는 없다) — 따라서 이 테스트는
    스키마 제약이 아니라 insert_new_articles_transactional 자체의 _validate_row 검증이
    실패를 유발하고 rollback으로 이어지는지를 확인한다."""
    db_path = _make_test_db(tmp_path)
    rows = [
        build_new_article_row(_wp_post(post_id=3001, slug="rb-a"),
                               {"title": "A", "content": "a", "excerpt": "a", "link": "https://x/a/", "date": "d"}),
        build_new_article_row(_wp_post(post_id=3002, slug="rb-b"),
                               {"title": "B", "content": "b", "excerpt": "b", "link": "https://x/b/", "date": "d"}),
        build_new_article_row(_wp_post(post_id=3003, slug="rb-c"),
                               {"title": "", "content": "c", "excerpt": "c", "link": "https://x/c/", "date": "d"}),  # title 누락 → 무효
    ]
    result = insert_new_articles_transactional(db_path, rows)
    assert result["success"] is False
    assert result["inserted"] == 0

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM blog_articles").fetchone()[0]
    rb_a = conn.execute("SELECT COUNT(*) FROM blog_articles WHERE slug='rb-a'").fetchone()[0]
    rb_b = conn.execute("SELECT COUNT(*) FROM blog_articles WHERE slug='rb-b'").fetchone()[0]
    conn.close()
    assert count == 1          # seed만 남아있어야 함(rb-a/rb-b도 롤백됨)
    assert rb_a == 0
    assert rb_b == 0


def test_transactional_insert_empty_list_is_noop(tmp_path):
    db_path = _make_test_db(tmp_path)
    result = insert_new_articles_transactional(db_path, [])
    assert result == {"success": True, "inserted": 0}


# ── D. update_content_fields — 필드 제한 ────────────────────────────────
def test_update_content_fields_allowed_field(tmp_path):
    adapter = SQLiteAdapter({"SQLITE_PATH": "t.db", "_root": str(tmp_path)})
    row = build_new_article_row(_wp_post(post_id=4001, slug="upd-test"),
                                 {"title": "old", "content": "old", "excerpt": "old",
                                  "link": "https://x/upd/", "date": "d"})
    adapter.insert("blog_articles", row)
    repo = BlogArticleRepository(adapter)

    repo.update_content_fields(row["article_id"], title="new title")
    updated = repo.get_by_article_id(row["article_id"])
    assert updated["title"] == "new title"
    assert updated["slug"] == "upd-test"  # 다른 필드는 불변


def test_update_content_fields_rejects_disallowed_field(tmp_path):
    adapter = SQLiteAdapter({"SQLITE_PATH": "t.db", "_root": str(tmp_path)})
    row = build_new_article_row(_wp_post(post_id=4002, slug="upd-test2"),
                                 {"title": "old", "content": "old", "excerpt": "old",
                                  "link": "https://x/upd2/", "date": "d"})
    adapter.insert("blog_articles", row)
    repo = BlogArticleRepository(adapter)

    try:
        repo.update_content_fields(row["article_id"], slug="changed-slug")
        assert False, "slug 변경은 거부되어야 한다"
    except ValueError:
        pass


def test_update_content_fields_field_set_matches_spec():
    assert CONTENT_UPDATE_FIELDS == {
        "title", "content", "meta_description", "wp_status", "wp_permalink",
        "published_at", "last_synced_at", "sync_status", "sync_error",
    }
    # 신원/계약성 필드는 절대 포함되지 않아야 한다
    for forbidden in ("slug", "calculator_id", "intent", "content_source", "wp_post_id", "created_at", "article_id"):
        assert forbidden not in CONTENT_UPDATE_FIELDS


# ── E. calculators 테이블 비관여(구조 검증) ─────────────────────────────
def test_wp_blog_sync_module_never_accesses_article_content_or_calculators_table():
    """설계 원칙을 설명하는 docstring/주석 안의 문자열 언급은 허용하되(의도적 경계 설명),
    실제 dict 키 접근("article_content") / SQL 테이블명("calculators")으로는 등장하지
    않아야 한다."""
    import modules.wp_blog_sync as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert '"article_content"' not in src
    assert "'article_content'" not in src
    assert 'FROM "calculators"' not in src
    assert '"calculators"' not in src


def test_wp_blog_sync_uses_get_only_methods():
    import modules.wp_blog_sync as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ('method="POST"', 'method="PUT"', 'method="PATCH"', 'method="DELETE"'):
        assert forbidden not in src
