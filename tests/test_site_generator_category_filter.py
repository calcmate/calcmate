# -*- coding: utf-8 -*-
"""tests/test_site_generator_category_filter.py

modules/site_generator.py의 통합 category 필터/검색 metadata 검증(STEP196).
계산기 registry / WP category / Golden10 원본 값은 이 테스트에서도 절대
수정하지 않으며, 실제 프로젝트 DB(data/blog_auto.db)는 건드리지 않는다 —
get_db_adapter/get_blog_article_storage_adapter를 tmp_path 위의 임시
SQLite로 monkeypatch해 완전히 격리한다(test_site_generator_blog_merge.py와
동일한 격리 패턴).
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.db.sqlite_adapter import SQLiteAdapter
import modules.site_generator as sg
from modules.app_generator import _registry
from modules.registry_loader import load_registry_v3
from content.blog import GOLDEN_10


# ── normalize_category() 단위 테스트 ────────────────────────────────

def test_normalize_category_known_mappings():
    cases = {
        "노무/급여": "labor_pay",
        "노동/고용법": "labor_pay",
        "고용/보험": "employment_insurance",
        "노무/급여/보험": "employment_insurance",
        "세금/정부혜택": "tax_benefit",
        "세금": "tax_benefit",
        "부동산/임대": "real_estate",
        "병역/공무": "military_service",
        "건강/피트니스": "health",
        "건강": "health",
    }
    for raw, expected_key in cases.items():
        key, label = sg.normalize_category(raw)
        assert key == expected_key, f"{raw!r} -> {key!r} (expected {expected_key!r})"
        assert label == sg._CATEGORY_LABELS[expected_key]


def test_normalize_category_unknown_falls_back_to_other():
    key, label = sg.normalize_category("존재하지않는카테고리")
    assert key == "other"
    assert label == "기타"


def test_normalize_category_empty_or_none_falls_back_to_other():
    assert sg.normalize_category("")[0] == "other"
    assert sg.normalize_category(None)[0] == "other"


# ── registry 14개 계산기 category 커버리지 ───────────────────────────

def test_all_14_calculators_have_resolvable_category_key():
    reg = _registry()
    v3 = load_registry_v3()
    assert len(v3) == 14
    for slug, entry in v3.items():
        calc = reg.get(slug)
        assert calc, f"registry에 {slug} 없음"
        raw_cat = entry.get("category", calc.get("category", ""))
        key, label = sg.normalize_category(raw_cat)
        assert key in sg._CATEGORY_FILTER_ORDER, f"{slug}: {raw_cat!r} -> {key!r} (알 수 없는 key)"


# ── 격리된 DB로 Golden10 + BMI 가이드 연결 검증 ───────────────────────

def _seed_calculators_and_articles(tmp_path):
    """calculators 테이블(bmi-calculator 1건) + blog_articles 테이블(Golden10 10건
    + BMI 1건)을 실제 프로덕션 스키마와 동일한 최소 필드로 임시 DB에 재현한다."""
    db_path = str(tmp_path / "test_category_filter.db")
    adapter = SQLiteAdapter({"SQLITE_PATH": "test_category_filter.db", "_root": str(tmp_path)})

    adapter.insert("calculators", {
        "id": "calc_bmi_0001", "slug": "bmi-calculator", "name": "BMI(체질량지수) 계산기",
        "category": "건강/피트니스", "calculator_type": "standard", "status": "READY",
        "version": "1", "site_id": "calcmate",
    })

    golden_calc_ids = {
        "severance-pay": "calc_20260805121653_0065",
        "weekly-holiday-allowance": "calc_20260806100007_18a9",
        "unemployment-benefit": "calc_20260805121656_f443",
        "four-insurances": "calc_20260805121657_98d3",
        "annual-leave-allowance": "calc_20260805121654_01c3",
        "육아휴직_급여_계산기": "calc_20260806223828_6152",
        "연말정산_환급액_계산기": "calc_20260806223827_a5d9",
    }
    golden_categories = {
        "calc_20260805121653_0065": "노무/급여",
        "calc_20260806100007_18a9": "노무/급여",
        "calc_20260805121656_f443": "고용/보험",
        "calc_20260805121657_98d3": "고용/보험",
        "calc_20260805121654_01c3": "노무/급여",
        "calc_20260806223828_6152": "노무/급여/보험",
        "calc_20260806223827_a5d9": "세금/정부혜택",
    }
    for calc_id, category in golden_categories.items():
        adapter.insert("calculators", {
            "id": calc_id, "slug": f"slug-for-{calc_id}", "name": f"계산기-{calc_id}",
            "category": category, "calculator_type": "standard", "status": "READY",
            "version": "1", "site_id": "calcmate",
        })

    article_rows = [
        ("severance-pay", golden_calc_ids["severance-pay"]),
        ("weekly-holiday-allowance", golden_calc_ids["weekly-holiday-allowance"]),
        ("unemployment-benefit", golden_calc_ids["unemployment-benefit"]),
        ("four-insurances", golden_calc_ids["four-insurances"]),
        ("annual-leave-allowance", golden_calc_ids["annual-leave-allowance"]),
        ("severance-pay-documents", golden_calc_ids["severance-pay"]),
        ("육아휴직_급여_계산기", golden_calc_ids["육아휴직_급여_계산기"]),
        ("연말정산_환급액_계산기", golden_calc_ids["연말정산_환급액_계산기"]),
        ("unemployment-benefit-howto", golden_calc_ids["unemployment-benefit"]),
        ("four-insurances-documents", golden_calc_ids["four-insurances"]),
        ("bmi-calculator", None),  # calculator_id 없음 — slug 매칭으로만 연결돼야 함
    ]
    for i, (slug, calc_id) in enumerate(article_rows):
        adapter.insert("blog_articles", {
            "article_id": f"blog_test_{i}", "slug": slug, "title": f"제목-{slug}",
            "content": "<p>본문</p>", "calculator_id": calc_id, "intent": "howto",
            "content_source": "golden10" if calc_id else "wordpress_auto",
            "status": "publish", "wp_post_id": str(500 + i), "wp_status": "publish",
            "wp_permalink": f"https://blog.genon.app/{slug}/",
            "canonical_url": f"https://calcmate.kr/blog/{slug}/",
            "seo_title": None, "meta_description": f"설명-{slug}",
            "published_at": "2026-09-12T00:00:00", "created_at": "2026-09-12T00:00:00",
            "updated_at": "2026-09-12T00:00:00", "last_synced_at": "2026-09-12T00:00:00",
            "sync_status": "synced", "sync_error": None,
        })
    return db_path


def _patched_adapters(tmp_path):
    def fake_get_db_adapter(_cfg):
        return SQLiteAdapter({"SQLITE_PATH": "test_category_filter.db", "_root": str(tmp_path)})
    def fake_get_blog_article_storage_adapter(_cfg):
        return SQLiteAdapter({"SQLITE_PATH": "test_category_filter.db", "_root": str(tmp_path)})
    return (
        mock.patch("adapters.db.factory.get_db_adapter", side_effect=fake_get_db_adapter),
        mock.patch("adapters.db.factory.get_blog_article_storage_adapter",
                   side_effect=fake_get_blog_article_storage_adapter),
    )


def test_guide_calculator_links_resolves_golden10_via_calculator_id(tmp_path):
    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        links = sg._guide_calculator_links({})

    for gc in GOLDEN_10:
        assert gc.slug in links, f"Golden10 {gc.slug}가 calculator_id로 연결되지 않음"


def test_guide_calculator_links_resolves_bmi_via_slug_match(tmp_path):
    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        links = sg._guide_calculator_links({})

    assert links["bmi-calculator"]["calculator_slug"] == "bmi-calculator"
    key, _label = sg.normalize_category(links["bmi-calculator"]["category"])
    assert key == "health"


def test_generate_index_all_11_guides_have_category_key(tmp_path):
    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    assert html.count('data-content-type="calculator"') == 14
    assert html.count('data-content-type="guide"') == 11
    assert html.count('data-category-key="') == 25


def test_generate_index_category_key_distribution_matches_expected(tmp_path):
    import re
    from collections import Counter

    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    keys = re.findall(r'data-category-key="([^"]*)"', html)
    dist = Counter(keys)
    assert dist == Counter({
        "labor_pay": 8,
        "employment_insurance": 8,
        "tax_benefit": 4,
        "real_estate": 2,
        "health": 2,
        "military_service": 1,
    })
    assert sum(dist.values()) == 25


def test_generate_index_search_and_filter_metadata_present(tmp_path):
    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    assert 'id="cm-search-input"' in html
    assert 'id="cm-filter-empty"' in html
    assert 'data-filter-category="all"' in html
    for key in sg._CATEGORY_FILTER_ORDER:
        assert f'data-filter-category="{key}"' in html
    assert 'data-search-text="' in html
    assert 'data-category-raw="' in html


def test_generate_index_preserves_step192_hero_and_meta(tmp_path):
    """STEP192에서 확정한 H1/title/description/모바일 GNB가 STEP196 구현으로
    깨지지 않았는지 재확인한다."""
    _seed_calculators_and_articles(tmp_path)
    p1, p2 = _patched_adapters(tmp_path)
    with p1, p2:
        html = sg.generate_index({"SITE_URL": "https://calcmate.kr"})

    assert '<h1 class="cm-hero-logo">CalcMate — 실생활 계산기 모음</h1>' in html
    assert html.count("<h1") == 1
    assert "<title>CalcMate — 실생활 계산기 모음</title>" in html
    assert '.cm-nav-links a:not(:first-child){display:none}' in sg._SITE_CSS


def test_guide_calculator_links_returns_empty_on_db_error():
    """DB 접근 실패 시 메인 페이지 생성이 죽지 않고 빈 dict로 안전하게 degrade."""
    def failing_get_db_adapter(_cfg):
        raise RuntimeError("db unavailable")

    with mock.patch("adapters.db.factory.get_db_adapter", side_effect=failing_get_db_adapter):
        links = sg._guide_calculator_links({})
    assert links == {}
