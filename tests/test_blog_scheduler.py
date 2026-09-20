# -*- coding: utf-8 -*-
"""
tests/test_blog_scheduler.py — Blog Scheduler Adapter 테스트

검증:
1. BlogScheduleRequest 검증
2. Golden 10 10건 Scheduler Dry-Run
3. Intent별 구조 검증
4. DB 불변성 (article_content hash)
5. WordPress 호출 0
6. Image Pipeline 호출 0
7. isolated output 생성
8. 잘못된 slug/intent 거부
"""
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def golden10_slugs():
    return [
        "severance-pay", "weekly-holiday-allowance", "unemployment-benefit",
        "four-insurances", "annual-leave-allowance", "severance-pay-documents",
        "육아휴직_급여_계산기", "연말정산_환급액_계산기",
        "unemployment-benefit-howto", "four-insurances-documents",
    ]


@pytest.fixture
def golden10_intents():
    return {
        "severance-pay": "eligibility",
        "weekly-holiday-allowance": "howto",
        "unemployment-benefit": "eligibility",
        "four-insurances": "calculator",
        "annual-leave-allowance": "howto",
        "severance-pay-documents": "documents",
        "육아휴직_급여_계산기": "eligibility",
        "연말정산_환급액_계산기": "calculator",
        "unemployment-benefit-howto": "howto",
        "four-insurances-documents": "documents",
    }


_GOLDEN10_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "snapshots", "golden10_blog_snapshot.json")


@pytest.fixture
def temp_blog_root(tmp_path):
    """STEP 28-63: Golden10 스냅샷(tests/snapshots/golden10_blog_snapshot.json)으로
    임시 calculators DB를 만들어, 로컬 전용이던 data/blog_auto.db(gitignored) 없이도
    fresh checkout(CI 포함)에서 test_blog_scheduler.py가 재현되도록 한다.

    스냅샷은 실제 로컬 DB의 Golden10 10건 article_content/faq를 그대로 추출한 것이며
    (임의 작성 아님), blog_scheduler_adapter.py의 기존 cfg["_root"] override 지점을
    그대로 사용하므로 production 코드는 한 줄도 변경하지 않는다.
    """
    with open(_GOLDEN10_SNAPSHOT, encoding="utf-8") as f:
        rows = json.load(f)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "blog_auto.db"

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE calculators ("
        " slug TEXT PRIMARY KEY, name TEXT, article_content TEXT,"
        " faq TEXT, seo_title TEXT, seo_description TEXT)"
    )
    conn.executemany(
        "INSERT INTO calculators (slug, name, article_content, faq, seo_title, seo_description) "
        "VALUES (:slug, :name, :article_content, :faq, :seo_title, :seo_description)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def db_path(temp_blog_root):
    return str(temp_blog_root / "data" / "blog_auto.db")


@pytest.fixture
def cfg(temp_blog_root):
    """Mock config (no OPENAI_API_KEY = mock path).
    _root를 임시 Golden10 DB로 지정해 blog_scheduler_adapter가 그 DB를 사용하게 한다."""
    return {"MAX_RETRY_COUNT": 1, "QUALITY_GATE": {}, "QUALITY_SCORE": {}, "_root": str(temp_blog_root)}


@pytest.fixture
def golden10_hashes(db_path, golden10_slugs):
    """Golden 10 article_content hash 기록."""
    hashes = {}
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for slug in golden10_slugs:
        c.execute("SELECT article_content FROM calculators WHERE slug=?", (slug,))
        row = c.fetchone()
        if row and row[0]:
            hashes[slug] = hashlib.sha256(row[0].encode()).hexdigest()[:16]
    conn.close()
    return hashes


# ============================================================
# TEST 1: BlogScheduleRequest 검증
# ============================================================

class TestBlogScheduleRequest:
    """BlogScheduleRequest 검증 테스트."""

    def test_valid_request(self):
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        req = BlogScheduleRequest(slug="severance-pay", intent="eligibility")
        errors = req.validate()
        assert errors == [], f"Unexpected errors: {errors}"

    def test_invalid_intent(self):
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        req = BlogScheduleRequest(slug="severance-pay", intent="invalid")
        errors = req.validate()
        assert any("Invalid intent" in e for e in errors)

    def test_empty_slug(self):
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        req = BlogScheduleRequest(slug="", intent="eligibility")
        errors = req.validate()
        assert any("slug is empty" in e for e in errors)

    def test_not_golden10(self):
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        req = BlogScheduleRequest(slug="nonexistent", intent="eligibility")
        errors = req.validate()
        assert any("Not in Golden 10" in e for e in errors)

    def test_intent_mismatch(self):
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        req = BlogScheduleRequest(slug="severance-pay", intent="documents")
        errors = req.validate()
        assert any("Intent mismatch" in e for e in errors)

    def test_all_golden10_valid(self, golden10_intents):
        """Golden 10 10건 모두 valid request 생성 가능."""
        from modules.blog_scheduler_adapter import BlogScheduleRequest
        for slug, intent in golden10_intents.items():
            req = BlogScheduleRequest(slug=slug, intent=intent)
            errors = req.validate()
            assert errors == [], f"{slug}/{intent}: {errors}"


# ============================================================
# TEST 2: Golden 10 10건 Scheduler Dry-Run
# ============================================================

class TestGolden10SchedulerDryRun:
    """Golden 10 10건 전체 Scheduler Dry-Run."""

    def test_all_10_produced(self, cfg, golden10_slugs):
        """10건 모두 produced > 0."""
        from modules.blog_scheduler_adapter import run_blog_once
        result = run_blog_once(cfg, max_count=10)
        assert result["produced"] == 10, f"Expected 10, got {result['produced']}"
        assert result["reason"] == ""

    def test_all_10_success(self, cfg):
        """10건 모두 SUCCESS 상태."""
        from modules.blog_scheduler_adapter import run_blog_once
        result = run_blog_once(cfg, max_count=10)
        for r in result["results"]:
            assert r["status"] == "SUCCESS", f"{r['slug']}: {r['status']}"

    def test_no_db_write(self, cfg):
        """DB write = 0."""
        from modules.blog_scheduler_adapter import run_blog_once
        result = run_blog_once(cfg, max_count=10)
        assert result.get("db_write", 0) == 0

    def test_no_wp_call(self, cfg):
        """WordPress call = 0."""
        from modules.blog_scheduler_adapter import run_blog_once
        result = run_blog_once(cfg, max_count=10)
        assert result.get("wordpress_call", 0) == 0

    def test_no_image_call(self, cfg):
        """Image call = 0."""
        from modules.blog_scheduler_adapter import run_blog_once
        result = run_blog_once(cfg, max_count=10)
        assert result.get("image_call", 0) == 0

    def test_isolated_output_created(self, cfg):
        """isolated output 디렉토리에 10건 생성."""
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir
        run_blog_once(cfg, max_count=10)
        out = _output_dir(cfg)
        created = [d.name for d in out.iterdir() if d.is_dir() and d.name != "__pycache__"]
        assert len(created) >= 10, f"Expected >=10 dirs, got {len(created)}"


# ============================================================
# TEST 3: DB 불변성
# ============================================================

class TestDBInvariance:
    """Scheduler Dry-Run 후 DB 변경 없음."""

    def test_article_content_hash_unchanged(self, cfg, db_path, golden10_hashes):
        """Golden 10 article_content hash가 동일."""
        from modules.blog_scheduler_adapter import run_blog_once
        run_blog_once(cfg, max_count=10)

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        for slug, expected_hash in golden10_hashes.items():
            c.execute("SELECT article_content FROM calculators WHERE slug=?", (slug,))
            row = c.fetchone()
            if row and row[0]:
                actual_hash = hashlib.sha256(row[0].encode()).hexdigest()[:16]
                assert actual_hash == expected_hash, \
                    f"{slug} content changed: {expected_hash} → {actual_hash}"
        conn.close()


# ============================================================
# TEST 4: Intent별 구조 검증
# ============================================================

class TestIntentStructure:
    """각 intent별 H2 구조 검증."""

    def test_eligibility_structure(self, cfg):
        """eligibility → 지급 대상 / 근로시간 조건 / 제외 대상 포함."""
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay", "eligibility")
        assert result["success"]
        import re
        html = open(result["result"]["output"], encoding="utf-8").read()
        h2s = [re.sub(r'<[^>]+>', '', h).strip()
               for h in re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)]
        assert any("지급 대상" in h or "대상" in h for h in h2s), \
            f"eligibility missing '지급 대상': {h2s}"

    def test_howto_structure(self, cfg):
        """howto → 이용 절차 포함."""
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "weekly-holiday-allowance", "howto")
        assert result["success"]
        import re
        html = open(result["result"]["output"], encoding="utf-8").read()
        h2s = [re.sub(r'<[^>]+>', '', h).strip()
               for h in re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)]
        assert any("이용 절차" in h or "절차" in h for h in h2s), \
            f"howto missing '이용 절차': {h2s}"

    def test_documents_structure(self, cfg):
        """documents → 필수 서류 포함."""
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay-documents", "documents")
        assert result["success"]
        import re
        html = open(result["result"]["output"], encoding="utf-8").read()
        h2s = [re.sub(r'<[^>]+>', '', h).strip()
               for h in re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)]
        assert any("서류" in h for h in h2s), \
            f"documents missing '서류': {h2s}"

    def test_calculator_structure(self, cfg, monkeypatch):
        """calculator → 계산 원리 포함.

        STEP126: STEP125에서 새로 연결된 run_integrity_gates()의 G-LEGAL-CURRENT가
        four-insurances의 현행 SSOT 요율(건강보험료율 3.595%, 국민연금 4.75% —
        modules/law_ssot.py::get_positive_check_items('four-insurances','calculator')
        로 READ-ONLY 재확인함)을 포함하지 않는 기존 mock 콘텐츠를 major로 정상 차단하게
        됐다. 이 테스트는 계산기/블로그 정합성 게이트가 아니라 순수 H2 구조만 검증하는
        목적이므로, 이 테스트에 한해 mock 콘텐츠를 현행 SSOT 요율을 포함하도록 보정한다
        (production 코드인 content/blog/writer.py::_mock_generate_intent()는 수정하지
        않음 — 이 테스트 파일 내 monkeypatch로만 대체).
        """
        import content.blog.writer as W
        original_mock = W._mock_generate_intent

        def _patched_mock(post, seo, faq, intent):
            if post.get("slug") == "four-insurances" and intent == "calculator":
                return (
                    "<p>4대보험의 계산 원리와 방법을 설명합니다.</p>"
                    "<h2>계산 원리</h2><p>건강보험료율 3.595%, 국민연금 4.75% 등 "
                    "현행 요율을 기준으로 계산합니다.</p>"
                    "<h2>지급 조건</h2><p>대상 조건과 제외 조건을 확인합니다.</p>"
                    "<h2>주의사항</h2><p>자주 발생하는 오류와 주의점을 안내합니다.</p>"
                    "<h2>FAQ</h2><dl><dt>질문</dt><dd>답변</dd></dl>"
                )
            return original_mock(post, seo, faq, intent)

        monkeypatch.setattr(W, "_mock_generate_intent", _patched_mock)

        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "four-insurances", "calculator")
        assert result["success"]
        import re
        html = open(result["result"]["output"], encoding="utf-8").read()
        h2s = [re.sub(r'<[^>]+>', '', h).strip()
               for h in re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)]
        assert any("계산" in h for h in h2s), \
            f"calculator missing '계산': {h2s}"

    def test_calculator_structure_still_blocks_stale_mock_content(self, cfg):
        """STEP126 회귀 안전장치: 위 테스트가 monkeypatch로 우회하지 않는 '있는 그대로의'
        기존 mock 콘텐츠(SSOT 현행 요율 미포함)는 여전히 G-LEGAL-CURRENT major로
        차단되어야 한다 — run_integrity_gates()의 차단 정책이 이번 fixture 보정으로
        약화되지 않았음을 확인한다."""
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "four-insurances", "calculator")
        assert result["success"]
        html = open(result["result"]["output"], encoding="utf-8").read()
        assert html == "", f"stale mock content should still be blocked(empty), got: {html[:80]!r}"


# ============================================================
# TEST 5: 단일 Dry-Run
# ============================================================

class TestSingleDryRun:
    """단일 콘텐츠 Dry-Run."""

    def test_severance_pay_dry_run(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay", "eligibility")
        assert result["success"]
        assert result["result"]["article_len"] > 0
        assert result["result"]["protection_ok"] is True

    def test_single_invalid_slug(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "nonexistent", "eligibility")
        assert not result["success"]
        assert any("Golden 10" in e for e in result["errors"])

    def test_single_invalid_intent(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay", "bogus")
        assert not result["success"]
        assert any("Invalid intent" in e for e in result["errors"])


# ============================================================
# TEST 6: Calculator line 분리
# ============================================================

class TestCalculatorLineSeparation:
    """Blog adapter가 calculator write path를 호출하지 않음."""

    def test_no_db_write_in_blog_line(self, cfg, db_path):
        """Blog line이 calculators 테이블을 수정하지 않음."""
        from modules.blog_scheduler_adapter import run_blog_once
        import hashlib

        # 실행 전 DB hash
        before = hashlib.md5(open(db_path, "rb").read()).hexdigest()

        result = run_blog_once(cfg, max_count=10)

        # 실행 후 DB hash
        after = hashlib.md5(open(db_path, "rb").read()).hexdigest()
        assert before == after, f"DB changed: {before} → {after}"
        assert result.get("db_write", 0) == 0


# ============================================================
# TEST 7: Golden 10 hash 불변성 (run_blog_once 후)
# ============================================================

class TestGolden10HashAfterRun:
    """Scheduler Dry-Run 후 Golden 10 hash 불변."""

    def test_hash_unchanged_after_full_run(self, cfg, db_path, golden10_hashes):
        from modules.blog_scheduler_adapter import run_blog_once
        run_blog_once(cfg, max_count=10)

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        for slug, expected in golden10_hashes.items():
            c.execute("SELECT article_content FROM calculators WHERE slug=?", (slug,))
            row = c.fetchone()
            if row and row[0]:
                actual = hashlib.sha256(row[0].encode()).hexdigest()[:16]
                assert actual == expected, f"{slug}: {expected} → {actual}"
        conn.close()


# ============================================================
# TEST 8: CALCMATE-BLOG-GEN-METADATA-05
# auto_generate_blog_all()의 generation_metadata가 scheduler 저장 계층
# (run_blog_once / run_blog_dry_run)의 기존 *_meta.json에 그대로 보존되는지 검증.
# 실제 OpenAI API/WP/DB write는 전혀 발생하지 않는다(cfg fixture 자체가 mock 경로).
# ============================================================

class TestGenerationMetadataPersistence:

    def test_run_blog_once_meta_json_contains_generation_metadata(self, cfg):
        """run_blog_once()가 쓰는 기존 {slug}_{intent}_meta.json에 generation_metadata가
        추가로 보존되고, 기존 필드(slug/intent/title/description/article_len/
        article_hash/source/db_write/wordpress_call/image_call)는 그대로 유지된다."""
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir
        run_blog_once(cfg, max_count=1)

        out = _output_dir(cfg)
        meta_files = list(out.glob("*/*_meta.json"))
        assert meta_files, "meta.json이 하나도 생성되지 않음"
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))

        # 기존 필드 보존 확인(삭제/이름변경 없음)
        for key in ("slug", "intent", "title", "description", "article_len",
                   "article_hash", "source", "db_write", "wordpress_call", "image_call"):
            assert key in meta, f"기존 필드 유실: {key}"

        # 신규 generation_metadata 필드 존재 + mock 경로 기대값(cfg fixture에 OPENAI_API_KEY 없음)
        assert "generation_metadata" in meta
        gm = meta["generation_metadata"]
        assert gm is not None, "generation_metadata가 None으로 유실됨"
        assert gm["generation_mode"] == "mock"
        assert gm["provider"] is None
        assert gm["model"] is None
        assert gm["prompt_hash"] is None
        assert isinstance(gm["input_hash"], str) and gm["input_hash"]
        assert gm["generation_started_at"]
        assert gm["generation_completed_at"]
        assert gm["config_source"] == "unknown"  # cfg fixture는 load_config()를 거치지 않음
        # STEP6: driver_id는 새로 발명하지 않는다 — run_blog_once()가 auto_generate_blog_all()
        # 호출 시 driver_id를 전달하지 않으므로(이번 STEP에서도 변경하지 않음) "unknown" 그대로.
        assert gm["driver_id"] == "unknown"

    def test_run_blog_dry_run_meta_json_contains_generation_metadata(self, cfg):
        """run_blog_dry_run()의 meta.json에도 동일하게 generation_metadata가 보존된다."""
        from modules.blog_scheduler_adapter import run_blog_dry_run, _output_dir
        result = run_blog_dry_run(cfg, "severance-pay", "eligibility")
        assert result["success"]

        meta_path = Path(result["result"]["output"]).with_name(
            "severance-pay_eligibility_meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        for key in ("slug", "intent", "article_len", "article_hash", "source", "db_write"):
            assert key in meta, f"기존 필드 유실: {key}"

        assert "generation_metadata" in meta
        gm = meta["generation_metadata"]
        assert gm is not None
        assert gm["generation_mode"] == "mock"
        assert gm["input_hash"]

    def test_missing_generation_metadata_does_not_crash_adapter(self, cfg, monkeypatch):
        """auto_generate_blog_all()이 (구버전 호출 등으로) generation_metadata 없는
        result를 반환해도 adapter가 죽지 않아야 한다 — result.get()으로 안전하게 처리."""
        import modules.blog_scheduler_adapter as A

        def _fake_no_metadata(cfg, calc, save=False, intent=None, driver_id=None):
            return {
                "slug": calc.get("slug", ""), "name": calc.get("name", ""),
                "intent": intent, "article_content": "<p>본문</p>",
                "raw_article_content": "<p>본문</p>", "len": 10, "blocked": False,
                "integrity_passed": [], "integrity_failed": [], "legal_current_fails": [],
                # generation_metadata 키 자체가 없는 구버전 형태를 흉내낸다.
            }
        monkeypatch.setattr(A, "auto_generate_blog_all", _fake_no_metadata)

        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay", "eligibility")
        assert result["success"]

        meta_path = Path(result["result"]["output"]).with_name(
            "severance-pay_eligibility_meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta.get("generation_metadata") is None


# ============================================================
# TEST 9: CALCMATE-BLOG-GEN-METADATA-10
# adapter 3함수(run_blog_once/run_blog_dry_run/run_blog_once_wp)가 driver_id를
# auto_generate_blog_all()까지 정확히 전달하는지 검증한다. 실제 OpenAI/WP 호출은
# 발생하지 않는다(cfg fixture 자체가 mock 경로 + WP 미연결 상태).
# ============================================================

class TestDriverIdPropagation:

    def test_run_blog_once_driver_id_reaches_generation_metadata(self, cfg):
        """run_blog_once(driver_id=...) → auto_generate_blog_all(driver_id=...)
        → generation_metadata.driver_id로 정확히 전달되는지 확인."""
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir
        run_blog_once(cfg, max_count=1, driver_id="test-driver")

        out = _output_dir(cfg)
        meta_files = list(out.glob("*/*_meta.json"))
        assert meta_files, "meta.json이 하나도 생성되지 않음"
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert meta["generation_metadata"]["driver_id"] == "test-driver"

    def test_run_blog_dry_run_driver_id_reaches_generation_metadata(self, cfg):
        """run_blog_dry_run(driver_id=...)도 동일한 전달 경로를 검증."""
        from modules.blog_scheduler_adapter import run_blog_dry_run
        result = run_blog_dry_run(cfg, "severance-pay", "eligibility",
                                  driver_id="test-driver")
        assert result["success"]

        meta_path = Path(result["result"]["output"]).with_name(
            "severance-pay_eligibility_meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["generation_metadata"]["driver_id"] == "test-driver"

    def test_run_blog_once_wp_driver_id_survives_wp_not_ready_delegation(self, cfg):
        """run_blog_once_wp()는 WP 미연결 시 run_blog_once()에 위임한다
        (cfg fixture에 WORDPRESS_* 키가 없어 is_wordpress_ready(cfg)==False,
        자연스럽게 위임 분기를 탄다). 이 위임 경로에서도 driver_id가 유실되지
        않고 그대로 generation_metadata까지 도달해야 한다."""
        from modules.blog_scheduler_adapter import run_blog_once_wp, _output_dir
        run_blog_once_wp(cfg, max_count=1, driver_id="test-driver")

        out = _output_dir(cfg)
        meta_files = list(out.glob("*/*_meta.json"))
        assert meta_files, "meta.json이 하나도 생성되지 않음(위임 분기 미작동)"
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert meta["generation_metadata"]["driver_id"] == "test-driver"

    def test_omitted_driver_id_still_defaults_to_unknown(self, cfg):
        """driver_id를 넘기지 않는 기존 호출 방식은 계속 'unknown'으로 동작해야
        한다(기존 TestGenerationMetadataPersistence 테스트와 모순되지 않음)."""
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir
        run_blog_once(cfg, max_count=1)

        out = _output_dir(cfg)
        meta_files = list(out.glob("*/*_meta.json"))
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert meta["generation_metadata"]["driver_id"] == "unknown"


# ============================================================
# TEST 10: METADATA-17 bytes-level article_hash contract
# ============================================================

class TestArticleHashUsesPersistedBytes:
    """article_hash는 text 재인코딩이 아니라 실제 article.html bytes의 hash여야 한다."""

    def test_meta_hash_matches_article_html_read_bytes(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir

        result = run_blog_once(cfg, max_count=1, driver_id="metadata_smoke_test")
        assert result["produced"] == 1
        html_path = _output_dir(cfg) / "severance-pay" / "severance-pay_eligibility.html"
        meta_path = html_path.with_name("severance-pay_eligibility_meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        expected = hashlib.sha256(html_path.read_bytes()).hexdigest()[:16]
        assert meta["article_hash"] == expected

    def test_newline_storage_is_hashed_after_bytes_are_final(self, cfg):
        """LF가 포함된 HTML도 저장된 bytes 기준으로 검증한다 (OS 독립)."""
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir

        run_blog_once(cfg, max_count=1)
        html_path = _output_dir(cfg) / "severance-pay" / "severance-pay_eligibility.html"
        meta_path = html_path.with_name("severance-pay_eligibility_meta.json")
        raw = html_path.read_bytes()
        assert b"\n" in raw
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["article_hash"] == hashlib.sha256(raw).hexdigest()[:16]

    def test_generation_metadata_does_not_enter_html(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir

        run_blog_once(cfg, max_count=1, driver_id="metadata_smoke_test")
        html_path = _output_dir(cfg) / "severance-pay" / "severance-pay_eligibility.html"
        html = html_path.read_text(encoding="utf-8")
        for marker in ("generation_metadata", "driver_id", "metadata_smoke_test",
                       "prompt_hash", "input_hash", "config_source"):
            assert marker not in html

    def test_driver_id_does_not_change_hash_for_same_html(self, cfg):
        from modules.blog_scheduler_adapter import run_blog_once, _output_dir

        run_blog_once(cfg, max_count=1, driver_id="driver-A")
        html_path = _output_dir(cfg) / "severance-pay" / "severance-pay_eligibility.html"
        first_hash = hashlib.sha256(html_path.read_bytes()).hexdigest()[:16]

        run_blog_once(cfg, max_count=1, driver_id="driver-B")
        second_hash = hashlib.sha256(html_path.read_bytes()).hexdigest()[:16]
        assert first_hash == second_hash


# ============================================================
# TEST 11: CALCMATE-STEP170 — run_blog_once_wp() status 전달 계약
#
# STEP167/168에서 확인된 cmd_publish()의 "draft 모드" 주석과 실제 동작(status
# 미전달 → publisher.publish() 기본값 "publish")의 불일치를 해결한 STEP170 변경을
# deterministic하게(실제 WP 미호출) 검증한다. 실제 requests.post 대신
# modules.publisher.publish를 spy로 대체한다.
# ============================================================

class TestRunBlogOnceWpStatusContract:

    def _wp_ready_cfg(self, cfg):
        wp_cfg = dict(cfg)
        wp_cfg.update({
            "WORDPRESS_URL": "https://example.invalid",
            "WORDPRESS_USERNAME": "u", "WORDPRESS_APP_PASSWORD": "p",
        })
        return wp_cfg

    def _patch_common(self, monkeypatch, captured: dict):
        """실제 네트워크(WP GET 중복확인 + WP POST)를 전부 spy로 대체."""
        import modules.blog_scheduler_adapter as adapter
        import modules.publisher as publisher

        # CALCMATE-STEP172: _check_wp_duplicate()는 이제 dict(confirmed/exists 계약)를
        # 반환한다("중복 없음, 확인됨"으로 스텁 — 이 클래스의 목적은 status 전달 검증).
        monkeypatch.setattr(adapter, "_check_wp_duplicate",
                            lambda cfg, slug: {"exists": False, "confirmed": True,
                                                "wp_post_id": None, "slug": None, "error": None})

        def _spy_publish(post_id, seo, html, image_urls, cfg, *, status="publish",
                         comment_status=None, category_name=None):
            captured["status"] = status
            captured["post_id"] = post_id
            # 실제 modules.publisher.publish()의 반환 계약과 동일하게 매핑한다
            # (publisher.py: res["status"] = "published" if status == "publish" else status).
            return {"status": "published" if status == "publish" else status,
                    "wp_post_id": "999", "wp_permalink": "https://example.invalid/p/999"}

        monkeypatch.setattr(publisher, "publish", _spy_publish)

    # ── Test A: TEST-DRAFT 경로 — status="draft"가 publisher.publish까지 전달 ──

    def test_a_explicit_status_draft_reaches_publisher_publish(self, cfg, monkeypatch):
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_common(monkeypatch, captured)
        wp_cfg = self._wp_ready_cfg(cfg)

        result = run_blog_once_wp(wp_cfg, max_count=1, driver_id="test-driver",
                                  status="draft")

        assert captured.get("status") == "draft"
        assert result["produced"] == 1
        assert result["results"][0]["status"] == "DRAFT"

    # ── Test B: 기존 자동 scheduler 경로(status 인자 없음) 무영향 확인 ──

    def test_b_default_status_still_publish_for_existing_callers(self, cfg, monkeypatch):
        """status를 넘기지 않는 기존 호출(자동 scheduler 경로와 동일한 호출 형태)은
        여전히 publisher.publish에 status="publish"가 전달되어야 한다 — STEP170이
        기존 자동 발행 경로에 영향을 주지 않았음을 확인한다."""
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_common(monkeypatch, captured)
        wp_cfg = self._wp_ready_cfg(cfg)

        result = run_blog_once_wp(wp_cfg, max_count=1, driver_id="test-driver")

        assert captured.get("status") == "publish"
        assert result["results"][0]["status"] == "PUBLISHED"


# ── Test C: Dashboard mode label 표기 — CALCMATE-STEP170 ────────────────────
#
# dashboard.py는 import 시 Streamlit/스케줄러 스레드 기동 등 부작용이 있어(기존
# tests/test_dashboard_*.py 컨벤션과 동일하게) 직접 import하지 않고, 소스 텍스트만
# 읽어 표시 문구를 검증한다.

class TestDashboardBlogModeLabel:

    def test_draft_label_no_longer_claims_wp_draft(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parent.parent.joinpath("dashboard.py").read_text(encoding="utf-8")
        assert "Draft (WP 초안)" not in src, "SAFE-DRY-RUN(WP 미호출)을 'WP 초안'으로 오표기하는 문구가 남아있음"
        assert "Dry-Run (WP 미호출)" in src


# ============================================================
# TEST 12: CALCMATE-STEP172 — _check_wp_duplicate() FAIL-CLOSED + slug 매칭 정확성
#
# 이전(STEP171 감사에서 확인): 조회 실패/예외/비정상 응답을 전부 "중복 없음"(None)
# 으로 되돌려 발행을 강행(FAIL-OPEN)했고, 조회 slug에 "blog_" 접두사가 붙어 실제
# 게시 slug(접두사 없음)와 달라 진짜 중복도 찾지 못했다. 이번 STEP에서 둘 다
# 수정했다. 실제 네트워크(requests.get/publisher.publish)는 전부 monkeypatch로
# 대체하며, 실제 WP 호출은 발생하지 않는다.
# ============================================================

class TestCheckWpDuplicateFailClosed:

    def _wp_ready_cfg(self, cfg):
        wp_cfg = dict(cfg)
        wp_cfg.update({
            "WORDPRESS_URL": "https://example.invalid",
            "WORDPRESS_USERNAME": "u", "WORDPRESS_APP_PASSWORD": "p",
        })
        return wp_cfg

    def _patch_publish_spy(self, monkeypatch, captured: dict):
        import modules.publisher as publisher

        def _spy_publish(post_id, seo, html, image_urls, cfg, *, status="publish",
                         comment_status=None, category_name=None):
            captured["publish_called"] = captured.get("publish_called", 0) + 1
            return {"status": "published" if status == "publish" else status,
                    "wp_post_id": "999", "wp_permalink": "https://example.invalid/p/999"}

        monkeypatch.setattr(publisher, "publish", _spy_publish)

    # ── Test 1: duplicate 존재 → POST 금지 ──────────────────────────────────

    def test_1_duplicate_exists_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 200
            def json(self):
                return [{"id": 123, "slug": "severance-pay"}]

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "SKIP_DUPLICATE"
        assert result["results"][0]["wp_post_id"] == 123
        assert captured.get("publish_called", 0) == 0

    # ── Test 2: duplicate 없음 → POST 허용 + 실제 게시 slug와 동일한 값으로 조회 ──

    def test_2_no_duplicate_allows_post_and_queries_bare_slug(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)
        seen_params = {}

        class _Resp:
            status_code = 200
            def json(self):
                return []

        def _fake_get(url, params=None, auth=None, timeout=None):
            seen_params["slug"] = (params or {}).get("slug")
            return _Resp()

        monkeypatch.setattr(requests, "get", _fake_get)
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        # 실제 게시(publisher.publish → payload["slug"] = seo["slug"] = gc.slug)와
        # 동일한 값으로 조회해야 한다 — "blog_" 접두사가 붙어 있으면 FAIL.
        assert seen_params["slug"] == "severance-pay"
        assert result["results"][0]["status"] == "PUBLISHED"
        assert captured.get("publish_called", 0) == 1

    # ── Test 3: timeout → POST 금지 ──────────────────────────────────────────

    def test_3_timeout_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        def _raise(*a, **k):
            raise requests.exceptions.Timeout("simulated timeout")

        monkeypatch.setattr(requests, "get", _raise)
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 4: connection error → POST 금지 ─────────────────────────────────

    def test_4_connection_error_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        def _raise(*a, **k):
            raise requests.exceptions.ConnectionError("simulated connection error")

        monkeypatch.setattr(requests, "get", _raise)
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 5: HTTP 5xx → POST 금지 ─────────────────────────────────────────

    def test_5_http_500_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 500
            def json(self):
                return []

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 6: malformed JSON → POST 금지 ───────────────────────────────────

    def test_6_malformed_json_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 200
            def json(self):
                raise ValueError("simulated JSON decode failure")

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 7: 예상 밖 응답 구조(list가 아님) → POST 금지 ───────────────────

    def test_7_unexpected_response_shape_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 200
            def json(self):
                return {}  # list가 아님

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 8: 함수 내부 예상 밖 exception(list 내부 항목이 dict가 아님) → POST 금지 ──

    def test_8_malformed_post_entry_exception_blocks_post(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 200
            def json(self):
                return [None]  # posts[0].get(...) 호출 시 AttributeError 유발

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

    # ── Test 9: HTTP 404 → "중복 없음"으로 취급하지 않음(POST 금지) ─────────

    def test_9_http_404_is_not_treated_as_no_duplicate(self, cfg, monkeypatch):
        import requests
        from modules.blog_scheduler_adapter import run_blog_once_wp

        captured = {}
        self._patch_publish_spy(monkeypatch, captured)

        class _Resp:
            status_code = 404
            def json(self):
                return []

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        result = run_blog_once_wp(self._wp_ready_cfg(cfg), max_count=1, driver_id="test-driver")

        assert result["results"][0]["status"] == "DUPLICATE_CHECK_FAILED"
        assert captured.get("publish_called", 0) == 0

