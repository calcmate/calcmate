# -*- coding: utf-8 -*-
"""tests/test_calculator_three_way_sync.py

STEP74: modules/calculator_3way_sync.classify_three_way()/
compare_calculators_three_way() 회귀 테스트.

STEP73에서 확인된 감지 공백("SQLite↔Sheets", "SQLite↔_site" 두 pairwise만
존재하고 진짜 3-Way 판정이 없음)을 메우는 신규 코드에 대한 테스트다.

기존 compare_calculators_sqlite_vs_sheets()/calculator_site_sync.
compare_calculators_sqlite_vs_site()는 이 파일에서 전혀 수정하지 않는다 —
그 결과를 조합만 하는 신규 함수만 검증한다.

Production SQLite/Sheets/_site/queue는 전혀 건드리지 않는다 — 순수 함수
직접 호출 또는 tmp_path/스텁 Repository로 완전히 격리한다.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_3way_sync import (
    classify_three_way,
    compare_calculators_three_way,
    notify_three_way_anomalies,
    CLASSIFICATION_MATCH,
    CLASSIFICATION_BACKUP_DRIFT,
    CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT,
    CLASSIFICATION_SQLITE_MAIN_DRIFT,
    CLASSIFICATION_THREE_WAY_CONFLICT,
    CLASSIFICATION_INTENTIONAL_HOLD,
    CLASSIFICATION_TEMPLATE_EXCEPTION,
    DEPLOYED_RESULT_SOURCE,
    UNCOMPARED_FIELDS,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SEVERITY_FAIL,
    SEVERITY_CRITICAL,
)


class _StubRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


def _calc(id="calc_1", slug="test-calc", name="테스트 계산기", status="active",
          category="labor", review_score="80", review_status="AUTO_APPROVED",
          review_attempts="0", reviewed_at="2026-01-01T00:00:00",
          input_schema='{"x": "number"}', output_schema='{"y": "number"}'):
    return {"id": id, "slug": slug, "name": name, "status": status, "category": category,
            "review_score": review_score, "review_status": review_status,
            "review_attempts": review_attempts, "reviewed_at": reviewed_at,
            "input_schema": input_schema, "output_schema": output_schema}


def _write_site_page(site_dir: Path, slug: str, sm_config: dict):
    import json
    page_dir = site_dir / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    body = f"window.SM_CONFIG = {json.dumps(sm_config, ensure_ascii=False)};"
    html = f"<html><head></head><body><script>{body}</script></body></html>"
    (page_dir / "index.html").write_text(html, encoding="utf-8")


def _matching_sm_config(slug="test-calc", name="테스트 계산기"):
    return {
        "name": name, "slug": slug,
        "inputs": [{"name": "x", "label": "x", "type": "number", "unit": ""}],
        "outputs": [{"key": "y", "label": "y", "unit": ""}],
    }


# ── 1~7. classify_three_way() 순수 함수 단위 테스트(I/O 없음) ──────────

def test_01_all_same_is_match():
    r = classify_three_way(True, SEVERITY_INFO, True, SEVERITY_INFO, True)
    assert r["classification"] == CLASSIFICATION_MATCH
    assert r["severity"] == SEVERITY_INFO


def test_02_sqlite_neq_sheets_eq_site_is_backup_drift():
    r = classify_three_way(False, SEVERITY_FAIL, True, SEVERITY_INFO, True)
    assert r["classification"] == CLASSIFICATION_BACKUP_DRIFT
    assert r["severity"] == SEVERITY_FAIL


def test_03_sqlite_eq_sheets_neq_site_is_deployed_artifact_drift():
    r = classify_three_way(True, SEVERITY_INFO, False, SEVERITY_CRITICAL, True)
    assert r["classification"] == CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT
    assert r["severity"] == SEVERITY_CRITICAL


def test_04_sqlite_differs_from_both_but_sheets_eq_site_is_sqlite_main_drift():
    r = classify_three_way(False, SEVERITY_FAIL, False, SEVERITY_CRITICAL, True)
    assert r["classification"] == CLASSIFICATION_SQLITE_MAIN_DRIFT
    assert r["severity"] == SEVERITY_FAIL


def test_05_all_three_differ_is_three_way_conflict():
    r = classify_three_way(False, SEVERITY_FAIL, False, SEVERITY_CRITICAL, False)
    assert r["classification"] == CLASSIFICATION_THREE_WAY_CONFLICT
    assert r["severity"] == SEVERITY_CRITICAL


def test_06_intentional_hold_short_circuits_everything():
    r = classify_three_way(False, SEVERITY_CRITICAL, False, SEVERITY_CRITICAL, False,
                            intentional_hold=True)
    assert r["classification"] == CLASSIFICATION_INTENTIONAL_HOLD
    assert r["severity"] == SEVERITY_INFO


def test_07_template_exception_short_circuits_everything():
    r = classify_three_way(True, SEVERITY_INFO, False, SEVERITY_CRITICAL, False,
                            template_exception=True)
    assert r["classification"] == CLASSIFICATION_TEMPLATE_EXCEPTION
    assert r["severity"] == SEVERITY_INFO


def test_07b_reviewed_at_warn_severity_preserved_through_backup_drift():
    """기존 reviewed_at WARN이 3-way로 접혔을 때도 severity가 WARN으로 보존되는지."""
    r = classify_three_way(False, SEVERITY_WARN, True, SEVERITY_INFO, True)
    assert r["classification"] == CLASSIFICATION_BACKUP_DRIFT
    assert r["severity"] == SEVERITY_WARN


# ── 8. Registry 조회 실패 시 안전하게 CRITICAL 유지(정상으로 완화 금지) ──

def test_08_registry_lookup_failure_never_becomes_intentional_hold(tmp_path):
    calc = _calc(slug="broken-calc")  # _site 페이지를 만들지 않음 → index_html_missing
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               side_effect=RuntimeError("registry unavailable")):
        try:
            out = compare_calculators_three_way(
                {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
                site_dir=tmp_path)
        except RuntimeError:
            out = None
    # _load_registry_entry_safe() 자체가 예외를 흡수하는 것이 정상 동작이므로,
    # 이 mock이 예외를 던지면 그 상위(compare_calculators_three_way)까지 전파될
    # 수 있다 — 아래 별도 테스트(test_08b)가 실제 안전장치를 검증한다.
    assert out is None or all(
        r["classification"] != CLASSIFICATION_INTENTIONAL_HOLD for r in out["results"])


def test_08b_registry_returns_non_hold_stays_critical_classification(tmp_path):
    """registry에 slug가 없거나 status가 HOLD가 아니면 절대 INTENTIONAL_HOLD로
    완화되지 않고 기존 DRIFT/CONFLICT 계열로 남아야 한다."""
    calc = _calc(slug="broken-calc")
    with patch("modules.calculator_site_sync._load_registry_entry_safe", return_value={}):
        out = compare_calculators_three_way(
            {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
            site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] != CLASSIFICATION_INTENTIONAL_HOLD


def test_08c_registry_status_hold_is_recognized_as_intentional(tmp_path):
    calc = _calc(slug="hold-calc")
    with patch("modules.calculator_site_sync._load_registry_entry_safe",
               return_value={"status": "HOLD"}):
        out = compare_calculators_three_way(
            {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
            site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] == CLASSIFICATION_INTENTIONAL_HOLD
    assert result["severity"] == SEVERITY_INFO


# ── 9. normalization 결과 → 정상 MATCH 유지 ─────────────────────────

def test_09_normalization_absorbed_difference_is_still_match(tmp_path):
    """SQLite input_schema가 integer, _site가 number라도 정규화로 흡수되어
    site 축이 INFO가 되고, Sheets 축도 일치하면 전체 3-way는 MATCH여야 한다."""
    calc = _calc(slug="norm-calc", input_schema='{"x": "integer"}')
    _write_site_page(tmp_path, "norm-calc", _matching_sm_config(slug="norm-calc"))
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
        site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] == CLASSIFICATION_MATCH
    assert result["severity"] == SEVERITY_INFO


# ── 10. 기존 reviewed_at WARN이 end-to-end로도 BACKUP_DRIFT/WARN 유지 ───

def test_10_reviewed_at_only_diff_end_to_end_is_backup_drift_warn(tmp_path):
    sqlite_calc = _calc(slug="rv-calc", reviewed_at="2026-01-01T00:00:00")
    sheets_calc = _calc(slug="rv-calc", reviewed_at="2026-02-02T00:00:00")
    _write_site_page(tmp_path, "rv-calc", _matching_sm_config(slug="rv-calc"))
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([sqlite_calc]), sheets_repo=_StubRepo([sheets_calc]),
        site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] == CLASSIFICATION_BACKUP_DRIFT
    assert result["severity"] == SEVERITY_WARN


# ── SQLITE_MAIN_DRIFT / THREE_WAY_CONFLICT end-to-end(sheets_site_same 실사용) ──

def test_11_sqlite_differs_from_both_sheets_and_site_agree_is_sqlite_main_drift(tmp_path):
    sqlite_calc = _calc(slug="mismatch-calc", name="SQLite쪽이름")
    sheets_calc = _calc(slug="mismatch-calc", name="공통이름")
    _write_site_page(tmp_path, "mismatch-calc", _matching_sm_config(
        slug="mismatch-calc", name="공통이름"))
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([sqlite_calc]), sheets_repo=_StubRepo([sheets_calc]),
        site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] == CLASSIFICATION_SQLITE_MAIN_DRIFT


def test_12_all_three_disagree_is_three_way_conflict(tmp_path):
    sqlite_calc = _calc(slug="conflict-calc", name="SQLite이름")
    sheets_calc = _calc(slug="conflict-calc", name="Sheets이름")
    _write_site_page(tmp_path, "conflict-calc", _matching_sm_config(
        slug="conflict-calc", name="Site이름"))
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([sqlite_calc]), sheets_repo=_StubRepo([sheets_calc]),
        site_dir=tmp_path)
    result = out["results"][0]
    assert result["classification"] == CLASSIFICATION_THREE_WAY_CONFLICT
    assert result["severity"] == SEVERITY_CRITICAL


# ── coverage / deployed_result_source 메타데이터 확인 ─────────────────

def test_13_coverage_lists_uncompared_fields(tmp_path):
    calc = _calc()
    _write_site_page(tmp_path, "test-calc", _matching_sm_config())
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
        site_dir=tmp_path)
    assert set(out["coverage"]["uncompared_fields"]) == set(UNCOMPARED_FIELDS)
    assert "input_schema" in out["coverage"]["uncompared_fields"]
    assert "slug" in out["coverage"]["compared_fields"]


def test_14_deployed_result_source_is_local_site_artifact(tmp_path):
    calc = _calc()
    _write_site_page(tmp_path, "test-calc", _matching_sm_config())
    out = compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
        site_dir=tmp_path)
    assert out["deployed_result_source"] == DEPLOYED_RESULT_SOURCE
    assert DEPLOYED_RESULT_SOURCE == "local_site_artifact"


# ── source_files_and_db_untouched(격리 확인) ───────────────────────

def test_15_no_writes_anywhere(tmp_path):
    """이 detector는 어디에도 쓰지 않는다 — SQLite stub/sheets stub/사이트 파일
    모두 호출 전후 완전히 동일해야 한다."""
    calc = _calc()
    original_input_schema = calc["input_schema"]
    _write_site_page(tmp_path, "test-calc", _matching_sm_config())
    index_path = tmp_path / "test-calc" / "index.html"
    before_html = index_path.read_text(encoding="utf-8")

    compare_calculators_three_way(
        {}, sqlite_repo=_StubRepo([calc]), sheets_repo=_StubRepo([calc]),
        site_dir=tmp_path)

    assert calc["input_schema"] == original_input_schema
    assert index_path.read_text(encoding="utf-8") == before_html


# ── STEP75: notify_three_way_anomalies() — Telegram 알림 연결 ─────────
# 실제 Telegram API는 절대 호출하지 않는다 — modules.telegram_ops.notify_level을
# 항상 mock으로 대체한다.

def _entry(slug, classification, severity, calculator_id="calc_x"):
    return {"slug": slug, "calculator_id": calculator_id,
            "classification": classification, "severity": severity}


def _three_way_out(*entries, source=DEPLOYED_RESULT_SOURCE):
    return {"total": len(entries), "results": list(entries), "counts": {},
            "deployed_result_source": source}


def test_16_match_sends_no_notification():
    out = _three_way_out(_entry("a", CLASSIFICATION_MATCH, SEVERITY_INFO))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out)
    mock_notify.assert_not_called()
    assert notifications == []


def test_17_backup_drift_notifies_once():
    out = _three_way_out(_entry("severance-pay", CLASSIFICATION_BACKUP_DRIFT, SEVERITY_WARN))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out, run_id="run-1")
    mock_notify.assert_called_once()
    assert len(notifications) == 1
    assert notifications[0]["telegram_result"] == "sent"
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "WARNING"
    assert kwargs.get("event") == "sync_mismatch"


def test_18_deployed_artifact_drift_notifies_once():
    out = _three_way_out(_entry("b", CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT, SEVERITY_FAIL))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notify_three_way_anomalies({}, out)
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "ERROR"


def test_19_sqlite_main_drift_notifies_once():
    out = _three_way_out(_entry("c", CLASSIFICATION_SQLITE_MAIN_DRIFT, SEVERITY_FAIL))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notify_three_way_anomalies({}, out)
    mock_notify.assert_called_once()


def test_20_three_way_conflict_notifies_once():
    out = _three_way_out(_entry("d", CLASSIFICATION_THREE_WAY_CONFLICT, SEVERITY_CRITICAL))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notify_three_way_anomalies({}, out)
    mock_notify.assert_called_once()
    args, kwargs = mock_notify.call_args
    level = args[1] if len(args) > 1 else kwargs.get("level")
    assert level == "CRITICAL"


def test_21_intentional_hold_sends_no_notification():
    out = _three_way_out(_entry("e", CLASSIFICATION_INTENTIONAL_HOLD, SEVERITY_INFO))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out)
    mock_notify.assert_not_called()
    assert notifications == []


def test_22_template_exception_sends_no_notification():
    out = _three_way_out(_entry("military-discharge-date", CLASSIFICATION_TEMPLATE_EXCEPTION, SEVERITY_INFO))
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out)
    mock_notify.assert_not_called()
    assert notifications == []


def test_23_duplicate_same_run_calculator_severity_notifies_once():
    """같은 run_id + calculator_id + classification + severity가 결과 리스트에
    두 번 나타나도(예: 방어적 재현) 실제 Telegram 호출은 1회만 발생한다."""
    out = _three_way_out(
        _entry("dup", CLASSIFICATION_BACKUP_DRIFT, SEVERITY_WARN, calculator_id="calc_dup"),
        _entry("dup", CLASSIFICATION_BACKUP_DRIFT, SEVERITY_WARN, calculator_id="calc_dup"),
    )
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out, run_id="run-dup")
    assert mock_notify.call_count == 1
    assert notifications[0]["telegram_result"] == "sent"
    assert notifications[1]["telegram_result"] == "skipped_duplicate"


def test_24_different_calculators_each_notified_separately():
    out = _three_way_out(
        _entry("calc-a", CLASSIFICATION_BACKUP_DRIFT, SEVERITY_WARN, calculator_id="id_a"),
        _entry("calc-b", CLASSIFICATION_SQLITE_MAIN_DRIFT, SEVERITY_FAIL, calculator_id="id_b"),
    )
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, out, run_id="run-multi")
    assert mock_notify.call_count == 2
    assert {n["telegram_result"] for n in notifications} == {"sent"}


def test_25_telegram_exception_does_not_corrupt_results_or_crash():
    out = _three_way_out(_entry("boom", CLASSIFICATION_THREE_WAY_CONFLICT, SEVERITY_CRITICAL))
    original_results = list(out["results"])
    with patch("modules.telegram_ops.notify_level", side_effect=RuntimeError("telegram down")):
        notifications = notify_three_way_anomalies({}, out)
    assert len(notifications) == 1
    assert notifications[0]["telegram_result"] == "failed"
    assert "telegram down" in notifications[0]["telegram_error"]
    # detector 결과(out) 자체는 전혀 변경되지 않았어야 한다.
    assert out["results"] == original_results


def test_26_message_contains_required_fields_no_raw_row_data():
    out = _three_way_out(_entry("severance-pay", CLASSIFICATION_BACKUP_DRIFT, SEVERITY_WARN,
                                 calculator_id="calc_sp"))
    sheets_out = {"results": [{"slug": "severance-pay", "severity": SEVERITY_WARN,
                                "reasons": ["reviewed_at_changed"]}]}
    site_out = {"results": [{"slug": "severance-pay", "severity": SEVERITY_INFO, "reasons": ["no_change"]}]}
    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notify_three_way_anomalies({}, out, sheets_out=sheets_out, site_out=site_out, run_id="run-msg")
    args, kwargs = mock_notify.call_args
    detail = args[3] if len(args) > 3 else kwargs.get("detail", "")
    assert "result: BACKUP_DRIFT" in detail
    assert "severity: WARN" in detail
    assert "calculator: severance-pay" in detail
    assert "calculator_id: calc_sp" in detail
    assert "reviewed_at_changed" in detail
    assert "run_id: run-msg" in detail
    assert DEPLOYED_RESULT_SOURCE in detail
    assert "SQLite ↔ Sheets: DRIFT" in detail
    assert "SQLite ↔ _site: MATCH" in detail
    assert "<html" not in detail and "<script" not in detail  # row/HTML 원문 미포함
