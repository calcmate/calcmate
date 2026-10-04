# -*- coding: utf-8 -*-
"""tests/test_calculator_site_sync.py

STEP39: modules/calculator_site_sync.compare_calculators_sqlite_vs_site() 회귀 테스트.

Production `_site`/DB는 전혀 건드리지 않는다 — tmp_path에 가짜 `_site` 디렉토리를
직접 만들고, SQLite는 get_all()만 구현한 스텁 Repository로 격리한다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_site_sync import (
    compare_calculators_sqlite_vs_site,
    _normalize_inputs,
    _canonical_compare_type,
    SEVERITY_INFO,
    SEVERITY_FAIL,
    SEVERITY_CRITICAL,
)


class _StubRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기",
          input_schema='{"avg_wage": "number"}', output_schema='{"result": "number"}'):
    return {"id": id, "slug": slug, "name": name,
            "input_schema": input_schema, "output_schema": output_schema}


def _write_site_page(site_dir: Path, slug: str, sm_config: dict, malformed_json: bool = False):
    page_dir = site_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    if malformed_json:
        body = "window.SM_CONFIG = {this is not valid json};"
    else:
        body = f"window.SM_CONFIG = {json.dumps(sm_config, ensure_ascii=False)};"
    html = f"<html><head></head><body><script>{body}</script></body></html>"
    (page_dir / "index.html").write_text(html, encoding="utf-8")


def _matching_sm_config(slug="test-calc", name="테스트 계산기"):
    return {
        "name": name, "slug": slug,
        "inputs": [{"name": "avg_wage", "label": "평균임금", "type": "number", "unit": "원"}],
        "outputs": [{"key": "result", "label": "결과", "unit": "원"}],
    }


# ── 1. 정상 MATCH → INFO ─────────────────────────────────────────────

def test_matching_calculator_is_info(tmp_path):
    calc = _calc()
    _write_site_page(tmp_path, "test-calc", _matching_sm_config())

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["total"] == 1
    assert out["matched"] == 1
    assert out["mismatched"] == 0
    assert out["severity"][SEVERITY_INFO] == 1


# ── 2. slug mismatch → FAIL ───────────────────────────────────────────

def test_slug_mismatch_is_fail(tmp_path):
    calc = _calc(slug="test-calc")
    sm = _matching_sm_config(slug="different-slug")
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_FAIL] == 1
    entry = out["results"][0]
    assert "slug_mismatch" in entry["reasons"]


# ── 3. name mismatch → FAIL ───────────────────────────────────────────

def test_name_mismatch_is_fail(tmp_path):
    calc = _calc(name="원래 이름")
    sm = _matching_sm_config(name="다른 이름")
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_FAIL] == 1
    assert "name_mismatch" in out["results"][0]["reasons"]


# ── 4. inputs mismatch → FAIL ─────────────────────────────────────────

def test_inputs_mismatch_is_fail(tmp_path):
    calc = _calc(input_schema='{"avg_wage": "number"}')
    sm = _matching_sm_config()
    sm["inputs"] = [{"name": "avg_wage", "label": "평균임금", "type": "text", "unit": ""}]  # type 다름
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_FAIL] == 1
    assert "inputs_mismatch" in out["results"][0]["reasons"]


# ── 5. outputs mismatch → FAIL ────────────────────────────────────────

def test_outputs_mismatch_is_fail(tmp_path):
    calc = _calc(output_schema='{"result": "number"}')
    sm = _matching_sm_config()
    sm["outputs"] = [{"key": "different_key", "label": "결과", "unit": "원"}]
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_FAIL] == 1
    assert "outputs_mismatch" in out["results"][0]["reasons"]


# ── 6. `_site` missing → CRITICAL ─────────────────────────────────────

def test_site_missing_is_critical(tmp_path):
    calc = _calc(slug="no-such-page")
    # tmp_path 아래 아무 것도 만들지 않음(디렉토리/파일 자체가 없음)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["missing_in_site"] == ["calc_1"]
    assert out["results"][0]["reasons"] == ["index_html_missing"]


# ── 7. `_site` metadata parse 실패 → CRITICAL ─────────────────────────

def test_site_sm_config_parse_failure_is_critical(tmp_path):
    calc = _calc()
    _write_site_page(tmp_path, "test-calc", {}, malformed_json=True)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["results"][0]["reasons"][0].startswith("json_parse_failed")


# ── 8. 여러 calculator(혼합 severity) 처리 ────────────────────────────

def test_multiple_calculators_mixed_severity(tmp_path):
    calc_ok = _calc(id="calc_ok", slug="calc-ok")
    calc_fail = _calc(id="calc_fail", slug="calc-fail", name="원래")
    calc_missing = _calc(id="calc_missing", slug="calc-missing")

    _write_site_page(tmp_path, "calc-ok", _matching_sm_config(slug="calc-ok", name="테스트 계산기"))
    _write_site_page(tmp_path, "calc-fail", _matching_sm_config(slug="calc-fail", name="다른이름"))
    # calc-missing: _site 페이지 없음

    out = compare_calculators_sqlite_vs_site(
        sqlite_repo=_StubRepo([calc_ok, calc_fail, calc_missing]), site_dir=tmp_path)

    assert out["total"] == 3
    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_FAIL] == 1
    assert out["severity"][SEVERITY_CRITICAL] == 1


# ── 9. normalization: dict vs list 표현 차이는 false positive 아님 ───

def test_normalization_absorbs_representation_difference(tmp_path):
    """SQLite는 {name:type} dict, _site는 list[{name,type,...}] — 구조가
    다르지만 의미가 같으면 INFO여야 한다(표현형 차이로 인한 오탐 방지)."""
    calc = _calc(
        input_schema='{"a": "number", "b": "date"}',
        output_schema='{"x": "number", "y": "number"}',
    )
    sm = _matching_sm_config()
    sm["inputs"] = [
        {"name": "b", "label": "필드B", "type": "date", "unit": ""},   # 순서도 반대로
        {"name": "a", "label": "필드A", "type": "number", "unit": "원"},
    ]
    sm["outputs"] = [
        {"key": "y", "label": "Y", "unit": "원"},
        {"key": "x", "label": "X", "unit": "원"},
    ]
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_FAIL] == 0


# ── 10. source data가 변경되지 않음 ───────────────────────────────────

def test_source_files_and_db_untouched(tmp_path):
    calc = _calc()
    _write_site_page(tmp_path, "test-calc", _matching_sm_config())
    index_path = tmp_path / "test-calc" / "index.html"
    before = index_path.read_text(encoding="utf-8")
    before_files = sorted(str(p) for p in tmp_path.rglob("*"))

    compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    after = index_path.read_text(encoding="utf-8")
    after_files = sorted(str(p) for p in tmp_path.rglob("*"))
    assert before == after
    assert before_files == after_files  # 새 파일 생성/재빌드 없음


# ── STEP48: canonical type 동치 규칙(integer/numeric-select ↔ number) ────
# STEP47에서 READ-ONLY로 안전성을 확인한 두 규칙만 적용한다.
# 원본 SQLite schema 문자열/​_site inputs 리스트는 이 정규화로 절대 변경되지
# 않는다(비교용으로 새로 만든 dict에만 canonical 값을 담는다).

def test_11_integer_vs_number_is_match():
    sqlite_map, site_map = _normalize_inputs(
        '{"months_of_service": "integer"}',
        [{"name": "months_of_service", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map == site_map == {"months_of_service": "number"}


def test_12_number_vs_integer_is_match_symmetric():
    """정규화가 양쪽 대칭으로 적용되는지 확인(_site는 실제로 "integer"를 생성하지
    않지만, _canonical_compare_type() 자체의 대칭성을 검증한다)."""
    sqlite_map, site_map = _normalize_inputs(
        '{"months_of_service": "number"}',
        [{"name": "months_of_service", "label": "x", "type": "integer", "unit": ""}])
    assert sqlite_map == site_map == {"months_of_service": "number"}


def test_13_numeric_select_two_options_vs_number_is_match():
    sqlite_map, site_map = _normalize_inputs(
        '{"deal_type": "select:1=a,2=b"}',
        [{"name": "deal_type", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map == site_map == {"deal_type": "number"}


def test_14_numeric_select_with_zero_vs_number_is_match():
    sqlite_map, site_map = _normalize_inputs(
        '{"eco_type": "select:0=x,1=y,2=z"}',
        [{"name": "eco_type", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map == site_map == {"eco_type": "number"}


def test_15_non_numeric_select_vs_number_stays_mismatch():
    sqlite_map, site_map = _normalize_inputs(
        '{"deal_type": "select:a=x,b=y"}',
        [{"name": "deal_type", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map != site_map
    assert sqlite_map["deal_type"] == "select:a=x,b=y"  # number로 임의 승격되지 않음


def test_16_mixed_numeric_and_nonnumeric_select_stays_mismatch():
    sqlite_map, site_map = _normalize_inputs(
        '{"deal_type": "select:1=a,b=c"}',
        [{"name": "deal_type", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map != site_map
    assert sqlite_map["deal_type"] == "select:1=a,b=c"


def test_17_boolean_vs_number_stays_mismatch():
    sqlite_map, site_map = _normalize_inputs(
        '{"use_flag": "boolean"}',
        [{"name": "use_flag", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map != site_map
    assert sqlite_map["use_flag"] == "boolean"


def test_18_date_vs_number_stays_mismatch():
    sqlite_map, site_map = _normalize_inputs(
        '{"start_date": "date"}',
        [{"name": "start_date", "label": "x", "type": "number", "unit": ""}])
    assert sqlite_map != site_map
    assert sqlite_map["start_date"] == "date"


def test_19_original_sqlite_schema_string_not_mutated():
    original = '{"deal_type": "select:1=a,2=b"}'
    _normalize_inputs(original, [{"name": "deal_type", "type": "number"}])
    assert original == '{"deal_type": "select:1=a,2=b"}'


def test_20_original_site_inputs_list_not_mutated():
    """정규화 과정에서 label 등 원본 _site inputs 항목 정보가 삭제/변경되지 않는다."""
    import copy
    site_inputs = [{"name": "deal_type", "label": "거래유형", "type": "number", "unit": ""}]
    before = copy.deepcopy(site_inputs)
    _normalize_inputs('{"deal_type": "select:1=a,2=b"}', site_inputs)
    assert site_inputs == before


def test_canonical_compare_type_unit_cases():
    assert _canonical_compare_type("integer") == "number"
    assert _canonical_compare_type("number") == "number"
    assert _canonical_compare_type("select:1=a,2=b") == "number"
    assert _canonical_compare_type("select:0=x,1=y,2=z") == "number"
    assert _canonical_compare_type("select:-1=a,-2=b") == "number"
    assert _canonical_compare_type("select:a=x,b=y") == "select:a=x,b=y"
    assert _canonical_compare_type("select:1=a,b=c") == "select:1=a,b=c"
    assert _canonical_compare_type("boolean") == "boolean"
    assert _canonical_compare_type("date") == "date"
    dict_val = {"type": "date", "label": "입영일"}
    assert _canonical_compare_type(dict_val) == dict_val  # dict형(Tier2-B)은 그대로 통과


# ── end-to-end(실제 production 시나리오 재현) ────────────────────────────

def test_integer_field_calculator_is_info_end_to_end(tmp_path):
    calc = _calc(input_schema='{"months_of_service": "integer", "used_days": "integer"}',
                 output_schema='{"total_days": "integer"}')
    sm = {
        "name": "테스트 계산기", "slug": "test-calc",
        "inputs": [{"name": "months_of_service", "label": "x", "type": "number", "unit": ""},
                   {"name": "used_days", "label": "y", "type": "number", "unit": ""}],
        "outputs": [{"key": "total_days", "label": "z", "unit": ""}],
    }
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_FAIL] == 0


def test_numeric_select_field_calculator_is_info_end_to_end(tmp_path):
    calc = _calc(input_schema='{"deal_type": "select:1=매매,2=전세", "deal_amount": "integer"}',
                 output_schema='{"fee": "integer"}')
    sm = {
        "name": "테스트 계산기", "slug": "test-calc",
        "inputs": [{"name": "deal_type", "label": "x", "type": "number", "unit": ""},
                   {"name": "deal_amount", "label": "y", "type": "number", "unit": ""}],
        "outputs": [{"key": "fee", "label": "z", "unit": ""}],
    }
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_FAIL] == 0


def test_non_numeric_select_field_still_fails_end_to_end(tmp_path):
    calc = _calc(input_schema='{"category": "select:a=foo,b=bar"}',
                 output_schema='{"result": "number"}')
    sm = {
        "name": "테스트 계산기", "slug": "test-calc",
        "inputs": [{"name": "category", "label": "x", "type": "number", "unit": ""}],
        "outputs": [{"key": "result", "label": "z", "unit": ""}],
    }
    _write_site_page(tmp_path, "test-calc", sm)

    out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)

    assert out["severity"][SEVERITY_FAIL] == 1


# ── STEP71: Tier2-B(self-contained HTML/template_db) detector coverage gap 예외 ──
# military-discharge-date가 실제 정상 계산기인데 sm_config_not_found로 CRITICAL 처리되던
# 문제(STEP68~70에서 확정된 DETECTOR_COVERAGE_GAP)를 최소 수정한 회귀 테스트.
# 실제 registry YAML은 절대 사용하지 않는다 — _load_registry_entry_safe()를 항상
# mock으로 대체해 production registry 파일에 의존하지 않고 완전히 격리한다.
from unittest.mock import patch


def _tier2b_calc(id="calc_t2b", slug="mil-test", template_id="tpl_1"):
    d = _calc(id=id, slug=slug)
    d["template_id"] = template_id
    return d


def _write_selfcontained_page(site_dir: Path, slug: str, with_script: bool = True):
    page_dir = site_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    if with_script:
        html = ("<!DOCTYPE html><html><body><input type=\"date\">"
                "<script>function calc(){var d=new Date();d.setMonth(d.getMonth()+18);}</script>"
                "</body></html>")
    else:
        html = "<!DOCTYPE html><html><body><input type=\"date\">(no script here)</body></html>"
    (page_dir / "index.html").write_text(html, encoding="utf-8")


def test_tier2b_verified_exception_is_info_not_critical(tmp_path):
    calc = _tier2b_calc()
    _write_selfcontained_page(tmp_path, "mil-test")
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               return_value={"tier_subtype": "B", "html_source": "template_db"}):
        out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)
    assert out["severity"][SEVERITY_INFO] == 1
    assert out["severity"][SEVERITY_CRITICAL] == 0
    assert out["results"][0]["reasons"] == ["tier2b_template_exception_verified"]
    assert calc.get("id") not in out["missing_in_site"]


def test_tier2b_missing_index_html_stays_critical(tmp_path):
    calc = _tier2b_calc(slug="mil-missing")
    # 디렉토리 자체를 만들지 않음 → index_html_missing 경로(Tier2-B 조건 확인 이전에 이미 실패)
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               return_value={"tier_subtype": "B", "html_source": "template_db"}):
        out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)
    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["results"][0]["reasons"] == ["index_html_missing"]


def test_tier2b_without_script_tag_stays_critical(tmp_path):
    calc = _tier2b_calc(slug="mil-noscript")
    _write_selfcontained_page(tmp_path, "mil-noscript", with_script=False)
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               return_value={"tier_subtype": "B", "html_source": "template_db"}):
        out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)
    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["results"][0]["reasons"] == ["sm_config_not_found"]


def test_tier2b_without_template_id_stays_critical(tmp_path):
    calc = _calc(id="calc_no_tpl", slug="mil-no-tpl")  # template_id 필드 자체가 없음
    _write_selfcontained_page(tmp_path, "mil-no-tpl")
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               return_value={"tier_subtype": "B", "html_source": "template_db"}):
        out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)
    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["results"][0]["reasons"] == ["sm_config_not_found"]


def test_normal_calculator_without_sm_config_and_without_tier2b_registry_stays_critical(tmp_path):
    """Tier2-B 조건(registry)이 아예 없는 일반 계산기는 <script>가 있어도 예외 처리되지 않는다."""
    calc = _calc(slug="normal-broken")
    _write_selfcontained_page(tmp_path, "normal-broken")
    with patch("modules.calculator_site_sync._load_registry_entry_safe", return_value={}):
        out = compare_calculators_sqlite_vs_site(sqlite_repo=_StubRepo([calc]), site_dir=tmp_path)
    assert out["severity"][SEVERITY_CRITICAL] == 1
    assert out["results"][0]["reasons"] == ["sm_config_not_found"]


def test_registry_entry_safe_absorbs_exceptions(monkeypatch):
    """_load_registry_entry_safe() 자체는 registry 로드 실패 시 예외를 던지지 않고
    빈 dict를 반환해야 한다(이 detector가 registry 문제로 죽으면 안 됨)."""
    from modules import calculator_site_sync as CSS

    def _boom(force=False):
        raise RuntimeError("registry file corrupted")

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", _boom)
    result = CSS._load_registry_entry_safe("any-slug")
    assert result == {}
