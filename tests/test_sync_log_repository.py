# -*- coding: utf-8 -*-
"""tests/test_sync_log_repository.py

SyncLogRepository + run_blog_articles_sync_and_log() 검증.
SQLiteAdapter를 tmp_path에 물려 사용 — 실제 프로젝트 DB(data/blog_auto.db),
Google Sheets, WordPress는 전혀 건드리지 않는다(네트워크 호출 없음, wp_get_fn은 전부 fake).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from adapters.db.sqlite_adapter import SQLiteAdapter
from repositories.blog_article_repository import BlogArticleRepository
from repositories.sync_log_repository import SyncLogRepository
from modules.blog_articles_sync import (
    run_blog_articles_sync_and_log,
    SEVERITY_INFO, SEVERITY_WARN, SEVERITY_FAIL, SEVERITY_CRITICAL,
)


def _adapter(tmp_path) -> SQLiteAdapter:
    cfg = {"SQLITE_PATH": "test_sync_logs.db", "_root": str(tmp_path)}
    return SQLiteAdapter(cfg)


def _create_sync_log_tables(adapter: SQLiteAdapter):
    """실제 운영 스키마(제약 포함)를 tmp DB에 그대로 생성 — UNIQUE 제약 테스트를 위해
    SQLiteAdapter._ensure_table()의 컬럼-전체-TEXT 자동생성에 의존하지 않는다."""
    conn = sqlite3.connect(str(adapter._path))
    conn.execute("""
        CREATE TABLE sync_runs (
            run_id          TEXT NOT NULL,
            target          TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT NOT NULL,
            duration_ms     INTEGER,
            result          TEXT NOT NULL,
            total_count     INTEGER NOT NULL,
            info_count      INTEGER NOT NULL,
            warn_count      INTEGER NOT NULL,
            fail_count      INTEGER NOT NULL,
            critical_count  INTEGER NOT NULL,
            PRIMARY KEY(run_id)
        )
    """)
    conn.execute("""
        CREATE TABLE sync_log_entries (
            entry_id        TEXT NOT NULL,
            run_id          TEXT NOT NULL,
            article_id      TEXT NOT NULL,
            wp_post_id      TEXT NOT NULL,
            slug            TEXT NOT NULL,
            severity        TEXT NOT NULL,
            reasons         TEXT NOT NULL,
            error_type      TEXT,
            error_message   TEXT,
            checked_at      TEXT NOT NULL,
            PRIMARY KEY(entry_id),
            UNIQUE(run_id, article_id)
        )
    """)
    conn.commit()
    conn.close()


def _sample_blog_row(n=1, **overrides):
    row = {
        "article_id": f"blog_test_{n:03d}", "slug": f"slug-{n}", "title": f"제목 {n}",
        "content": f"본문 {n}", "calculator_id": f"calc_{n}", "intent": "calculator",
        "content_source": "wordpress_migrated", "status": "publish",
        "wp_post_id": str(500 + n), "wp_status": "publish",
        "wp_permalink": f"https://blog.genon.app/slug-{n}/",
        "canonical_url": f"https://calcmate.kr/blog/slug-{n}/",
        "seo_title": None, "meta_description": None,
        "published_at": "2026-09-07T00:00:00", "created_at": "2026-09-12T00:00:00",
        "updated_at": "2026-09-09T00:00:00", "last_synced_at": "2026-09-12T00:00:00",
        "sync_status": "synced", "sync_error": None,
    }
    row.update(overrides)
    return row


def _seed_blog_articles(adapter, n=10):
    for i in range(1, n + 1):
        adapter.insert("blog_articles", _sample_blog_row(i))


# ── A. Repository 테스트 ───────────────────────────────────────────────
def test_a_insert_run_and_entry(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    log_repo = SyncLogRepository(adapter)

    log_repo.insert_run({
        "run_id": "sync_test_001", "target": "blog_articles",
        "started_at": "t0", "finished_at": "t1", "duration_ms": 100,
        "result": "PASS", "total_count": 1, "info_count": 1,
        "warn_count": 0, "fail_count": 0, "critical_count": 0,
    })
    run = log_repo.get_run("sync_test_001")
    assert run is not None
    assert run["result"] == "PASS"

    log_repo.insert_entry({
        "entry_id": "log_test_001", "run_id": "sync_test_001",
        "article_id": "blog_test_001", "wp_post_id": "501", "slug": "slug-1",
        "severity": "INFO", "reasons": "no_change", "checked_at": "t1",
    })
    entries = log_repo.get_entries_by_run("sync_test_001")
    assert len(entries) == 1
    assert entries[0]["severity"] == "INFO"


def test_a_unique_run_id_article_id(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    log_repo = SyncLogRepository(adapter)
    log_repo.insert_run({
        "run_id": "sync_test_002", "target": "blog_articles",
        "started_at": "t0", "finished_at": "t1", "duration_ms": 1,
        "result": "PASS", "total_count": 1, "info_count": 1,
        "warn_count": 0, "fail_count": 0, "critical_count": 0,
    })
    log_repo.insert_entry({
        "entry_id": "log_a", "run_id": "sync_test_002", "article_id": "blog_test_001",
        "wp_post_id": "501", "slug": "slug-1", "severity": "INFO",
        "reasons": "no_change", "checked_at": "t1",
    })
    with pytest.raises(sqlite3.IntegrityError):
        log_repo.insert_entry({
            "entry_id": "log_b", "run_id": "sync_test_002", "article_id": "blog_test_001",
            "wp_post_id": "501", "slug": "slug-1", "severity": "WARN",
            "reasons": "title_changed", "checked_at": "t2",
        })


# ── B. 본문/발췌 누출 방지 테스트 ──────────────────────────────────────
def test_b_insert_entry_rejects_content_and_excerpt(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    log_repo = SyncLogRepository(adapter)
    log_repo.insert_run({
        "run_id": "sync_test_003", "target": "blog_articles",
        "started_at": "t0", "finished_at": "t1", "duration_ms": 1,
        "result": "PASS", "total_count": 0, "info_count": 0,
        "warn_count": 0, "fail_count": 0, "critical_count": 0,
    })
    with pytest.raises(ValueError):
        log_repo.insert_entry({
            "entry_id": "log_leak", "run_id": "sync_test_003", "article_id": "blog_test_001",
            "wp_post_id": "501", "slug": "slug-1", "severity": "WARN",
            "reasons": "content_changed", "checked_at": "t1",
            "content": "본문 전체가 여기 들어가면 안 됨",
        })
    with pytest.raises(ValueError):
        log_repo.insert_entry({
            "entry_id": "log_leak2", "run_id": "sync_test_003", "article_id": "blog_test_001",
            "wp_post_id": "501", "slug": "slug-1", "severity": "WARN",
            "reasons": "title_changed", "checked_at": "t1",
            "excerpt": "발췌 전체도 안 됨",
        })


def test_b_run_and_log_via_full_flow_never_persists_content(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    _seed_blog_articles(adapter, n=3)
    repo = BlogArticleRepository(adapter)
    log_repo = SyncLogRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": f"slug-{int(post_id)-500}",
                "status": "publish", "date": "d", "modified": "m", "link": f"https://blog.genon.app/slug-{int(post_id)-500}/",
                "title": "바뀐 제목", "content": "매우 긴 본문 내용" * 100, "excerpt": "발췌 내용"}

    results = run_blog_articles_sync_and_log({}, repo=repo, log_repo=log_repo, wp_get_fn=fake_wp_get)
    assert len(results) == 3

    runs = log_repo.list_runs()
    assert len(runs) == 1
    entries = log_repo.get_entries_by_run(runs[0]["run_id"])
    assert len(entries) == 3
    for e in entries:
        serialized = str(e)
        assert "매우 긴 본문 내용" not in serialized
        assert "발췌 내용" not in serialized
        assert "content" not in e
        assert "excerpt" not in e


# ── C. severity 집계 테스트 ────────────────────────────────────────────
def test_c_all_info_is_pass(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    _seed_blog_articles(adapter, n=10)
    repo = BlogArticleRepository(adapter)
    log_repo = SyncLogRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        n = int(post_id) - 500
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": f"slug-{n}",
                "status": "publish", "date": "d", "modified": "2026-09-09T00:00:00",
                "link": f"https://blog.genon.app/slug-{n}/", "title": f"제목 {n}", "content": f"본문 {n}",
                "excerpt": ""}

    run_blog_articles_sync_and_log({}, repo=repo, log_repo=log_repo, wp_get_fn=fake_wp_get)
    runs = log_repo.list_runs()
    assert runs[0]["result"] == "PASS"
    assert runs[0]["info_count"] == 10
    assert runs[0]["warn_count"] == 0
    assert runs[0]["fail_count"] == 0
    assert runs[0]["critical_count"] == 0


def test_c_one_warn_makes_run_warn(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    _seed_blog_articles(adapter, n=10)
    repo = BlogArticleRepository(adapter)
    log_repo = SyncLogRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        n = int(post_id) - 500
        title = "바뀐 제목" if n == 1 else f"제목 {n}"
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": f"slug-{n}",
                "status": "publish", "date": "d", "modified": "2026-09-09T00:00:00",
                "link": f"https://blog.genon.app/slug-{n}/", "title": title, "content": f"본문 {n}",
                "excerpt": ""}

    run_blog_articles_sync_and_log({}, repo=repo, log_repo=log_repo, wp_get_fn=fake_wp_get)
    runs = log_repo.list_runs()
    assert runs[0]["result"] == "WARN"
    assert runs[0]["info_count"] == 9
    assert runs[0]["warn_count"] == 1


def test_c_one_fail_makes_run_fail(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    _seed_blog_articles(adapter, n=10)
    repo = BlogArticleRepository(adapter)
    log_repo = SyncLogRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        n = int(post_id) - 500
        status = "trash" if n == 1 else "publish"
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": f"slug-{n}",
                "status": status, "date": "d", "modified": "2026-09-09T00:00:00",
                "link": f"https://blog.genon.app/slug-{n}/", "title": f"제목 {n}", "content": f"본문 {n}",
                "excerpt": ""}

    run_blog_articles_sync_and_log({}, repo=repo, log_repo=log_repo, wp_get_fn=fake_wp_get)
    runs = log_repo.list_runs()
    assert runs[0]["result"] == "FAIL"
    assert runs[0]["fail_count"] == 1


def test_c_one_critical_makes_run_critical(tmp_path):
    adapter = _adapter(tmp_path)
    _create_sync_log_tables(adapter)
    _seed_blog_articles(adapter, n=1)
    repo = BlogArticleRepository(adapter)
    log_repo = SyncLogRepository(adapter)

    def fake_wp_get(post_id, **kwargs):
        return {"success": False, "http_status": 404, "error": "not found", "wp_post_id": post_id}

    run_blog_articles_sync_and_log({}, repo=repo, log_repo=log_repo, wp_get_fn=fake_wp_get)
    runs = log_repo.list_runs()
    assert runs[0]["result"] == "CRITICAL"
    assert runs[0]["critical_count"] == 1
    entries = log_repo.get_entries_by_run(runs[0]["run_id"])
    assert entries[0]["error_type"] == "wp_post_not_found_404"


# ── D. 로그 저장 실패 격리 테스트 ──────────────────────────────────────
def test_d_log_repo_failure_does_not_break_sync_results(tmp_path):
    adapter = _adapter(tmp_path)
    # 일부러 sync_logs 테이블을 만들지 않는다 -> insert_run()이 예외를 던짐
    _seed_blog_articles(adapter, n=3)
    repo = BlogArticleRepository(adapter)

    class BrokenLogRepo:
        def insert_run(self, run):
            raise RuntimeError("의도적 로그 저장소 장애")

        def insert_entry(self, entry):
            raise RuntimeError("호출되면 안 됨")

    def fake_wp_get(post_id, **kwargs):
        n = int(post_id) - 500
        return {"success": True, "http_status": 200, "id": int(post_id), "slug": f"slug-{n}",
                "status": "publish", "date": "d", "modified": "2026-09-09T00:00:00",
                "link": f"https://blog.genon.app/slug-{n}/", "title": f"제목 {n}", "content": f"본문 {n}",
                "excerpt": ""}

    results = run_blog_articles_sync_and_log({}, repo=repo, log_repo=BrokenLogRepo(), wp_get_fn=fake_wp_get)
    # 로그 저장소가 완전히 고장나도 판정 결과 3건은 정상 반환되어야 한다.
    assert len(results) == 3
    assert all(r["severity"] == SEVERITY_INFO for r in results)
