# -*- coding: utf-8 -*-
"""tests/test_calc_webapp_three_way_hook.py

STEP76: 3-Way(SQLite/Sheets/_site) 이상감지를 기존 운영 실행 경로
(modules/calc_webapp_pipeline.run_calc_webapp_once, 계산기 웹앱 스케줄러)에
연결한 코드의 회귀 테스트.

시나리오 A~H:
  A~E: 3-Way classification별 Telegram 알림 여부(run_three_way_anomaly_check_safely
       단위)
  F/G: INTENTIONAL_HOLD/TEMPLATE_EXCEPTION은 절대 알리지 않음
  H:   알림 계층 실패가 기존 운영 작업(run_calc_webapp_once의 반환값)을
       절대 깨뜨리지 않음

실제 SQLite/Sheets/_site/Telegram/GitHub 배포는 전혀 건드리지 않는다 —
전부 mock/stub으로 완전히 격리한다.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_3way_sync import (
    run_three_way_anomaly_check_safely,
    CLASSIFICATION_MATCH,
    CLASSIFICATION_BACKUP_DRIFT,
    CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT,
    CLASSIFICATION_SQLITE_MAIN_DRIFT,
    CLASSIFICATION_THREE_WAY_CONFLICT,
    CLASSIFICATION_INTENTIONAL_HOLD,
    CLASSIFICATION_TEMPLATE_EXCEPTION,
    SEVERITY_INFO, SEVERITY_WARN, SEVERITY_FAIL, SEVERITY_CRITICAL,
)


def _sheets_out(severity, slug="calc-x", name="이름A"):
    reasons = ["no_change"] if severity == SEVERITY_INFO else ["name_changed"]
    return {"results": [{"slug": slug, "calculator_id": "id-x", "severity": severity,
                          "reasons": reasons}]}


def _site_out(severity, slug="calc-x", reasons=None):
    if reasons is None:
        reasons = ["no_change"] if severity == SEVERITY_INFO else ["index_html_missing"]
    return {"results": [{"slug": slug, "calculator_id": "id-x", "severity": severity,
                          "reasons": reasons, "normalization_applied": []}],
            "deployed_result_source": "local_site_artifact"}


def _run_safely(sheets_out, site_out, sheets_site_agree=None, registry_entry=None):
    patches = [
        patch("modules.calculator_3way_sync.compare_calculators_sqlite_vs_sheets",
              return_value=sheets_out),
        patch("modules.calculator_site_sync.compare_calculators_sqlite_vs_site",
              return_value=site_out),
        patch("modules.calculator_site_sync._load_registry_entry_safe",
              return_value=(registry_entry or {})),
        patch("modules.telegram_ops.notify_level"),
    ]
    if sheets_site_agree is not None:
        patches.append(patch("modules.calculator_3way_sync._sheets_and_site_agree",
                              return_value=sheets_site_agree))
    with patches[0] as _p0, patches[1] as _p1, patches[2] as _p2, patches[3] as mock_notify:
        if len(patches) == 5:
            with patches[4]:
                result = run_three_way_anomaly_check_safely({}, run_id="test-run")
        else:
            result = run_three_way_anomaly_check_safely({}, run_id="test-run")
    return result, mock_notify


# ── A. MATCH → 운영 정상, Telegram 없음 ────────────────────────────

def test_a_match_no_telegram():
    result, mock_notify = _run_safely(_sheets_out(SEVERITY_INFO), _site_out(SEVERITY_INFO))
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_MATCH) == 1
    mock_notify.assert_not_called()


# ── B. BACKUP_DRIFT → 운영 정상, Telegram 1회 ──────────────────────

def test_b_backup_drift_notifies_once():
    result, mock_notify = _run_safely(_sheets_out(SEVERITY_WARN), _site_out(SEVERITY_INFO))
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_BACKUP_DRIFT) == 1
    mock_notify.assert_called_once()


# ── C. DEPLOYED_ARTIFACT_DRIFT → 운영 정상, Telegram 1회 ───────────

def test_c_deployed_artifact_drift_notifies_once():
    result, mock_notify = _run_safely(
        _sheets_out(SEVERITY_INFO),
        _site_out(SEVERITY_FAIL, reasons=["outputs_mismatch"]))
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_DEPLOYED_ARTIFACT_DRIFT) == 1
    mock_notify.assert_called_once()


# ── D. SQLITE_MAIN_DRIFT → 운영 정상, Telegram 1회 ─────────────────

def test_d_sqlite_main_drift_notifies_once():
    result, mock_notify = _run_safely(
        _sheets_out(SEVERITY_FAIL),
        _site_out(SEVERITY_CRITICAL, reasons=["name_changed"]),
        sheets_site_agree=True)
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_SQLITE_MAIN_DRIFT) == 1
    mock_notify.assert_called_once()


# ── E. THREE_WAY_CONFLICT → 운영 정상, Telegram 1회 ────────────────

def test_e_three_way_conflict_notifies_once():
    result, mock_notify = _run_safely(
        _sheets_out(SEVERITY_FAIL),
        _site_out(SEVERITY_CRITICAL, reasons=["name_changed"]),
        sheets_site_agree=False)
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_THREE_WAY_CONFLICT) == 1
    mock_notify.assert_called_once()


# ── F. INTENTIONAL_HOLD → 운영 정상, Telegram 없음 ─────────────────

def test_f_intentional_hold_no_telegram():
    result, mock_notify = _run_safely(
        _sheets_out(SEVERITY_INFO),
        _site_out(SEVERITY_CRITICAL, reasons=["index_html_missing"]),
        registry_entry={"status": "HOLD"})
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_INTENTIONAL_HOLD) == 1
    mock_notify.assert_not_called()


# ── G. TEMPLATE_EXCEPTION → 운영 정상, Telegram 없음 ───────────────

def test_g_template_exception_no_telegram():
    result, mock_notify = _run_safely(
        _sheets_out(SEVERITY_INFO),
        _site_out(SEVERITY_INFO, reasons=["tier2b_template_exception_verified"]))
    assert result["status"] == "ok"
    assert result["counts"].get(CLASSIFICATION_TEMPLATE_EXCEPTION) == 1
    mock_notify.assert_not_called()


# ── H. 알림 계층 실패 격리 ───────────────────────────────────────────

def test_h1_compare_layer_exception_does_not_raise():
    """compare_calculators_sqlite_vs_sheets 자체가 터져도 안전 진입점은
    예외를 던지지 않고 status=error만 반환한다."""
    with patch("modules.calculator_3way_sync.compare_calculators_sqlite_vs_sheets",
               side_effect=RuntimeError("sheets api down")):
        result = run_three_way_anomaly_check_safely({}, run_id="test-run")
    assert result["status"] == "error"
    assert "sheets api down" in result["error"]


def test_h2_notify_layer_exception_does_not_raise():
    """notify_three_way_anomalies 내부(Telegram)가 터져도 안전 진입점은
    예외를 던지지 않는다(STEP75에서 이미 notify 자체 격리 확인 — 여기서는
    안전 진입점 레벨에서 다시 확인)."""
    with patch("modules.calculator_3way_sync.compare_calculators_sqlite_vs_sheets",
               return_value=_sheets_out(SEVERITY_WARN)), \
         patch("modules.calculator_site_sync.compare_calculators_sqlite_vs_site",
               return_value=_site_out(SEVERITY_INFO)), \
         patch("modules.telegram_ops.notify_level", side_effect=RuntimeError("telegram down")):
        result = run_three_way_anomaly_check_safely({}, run_id="test-run")
    assert result["status"] == "ok"  # notify 실패는 개별 notification 항목에만 기록됨
    assert result["notifications"][0]["telegram_result"] == "failed"


def test_h3_calc_webapp_once_success_unaffected_by_three_way_crash(tmp_path):
    """3-Way 안전 진입점 자체가(가정: 버그로) raise 하더라도, 계산기 웹앱
    운영 작업(run_calc_webapp_once)의 정상 반환값은 절대 훼손되지 않는다
    — 호출부의 이중 방어(try/except)를 실제로 검증한다."""
    from modules import calc_webapp_pipeline as pipeline

    cfg = {"CALC_WEBAPP_SCHEDULE": {"mode": "qa_only", "targets": ["calc_1"]}}
    fake_calc = {"id": "calc_1", "slug": "calc-1", "name": "테스트"}

    fake_repo = MagicMock()
    fake_repo.get_by_id.return_value = fake_calc

    with patch("adapters.db.factory.get_db_adapter", return_value=MagicMock()), \
         patch("repositories.calculator_repository.CalculatorRepository", return_value=fake_repo), \
         patch("modules.app_generator.generate_calculator", return_value={"index.html": "<html></html>"}), \
         patch("modules.site_snapshot.read_site_snapshot", return_value=None), \
         patch("modules.site_snapshot.write_site_snapshot", return_value=None), \
         patch("modules.review_center.pre_build_qa", return_value=[{"passed": True, "skipped": False}]), \
         patch("modules.calculator_3way_sync.run_three_way_anomaly_check_safely",
               side_effect=RuntimeError("simulated 3-way bug")):
        result = pipeline.run_calc_webapp_once(cfg)

    assert result["produced"] == 1
    assert result["published"]["keyword"] == "calc-1"
