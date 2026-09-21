# -*- coding: utf-8 -*-
"""
tests/test_topic_wp_reconciliation.py
CALCMATE-AUTO-CONTENT-PUBLISHED-WP-RECONCILIATION-GAP-FOLLOWUP-DECISION-01 —
modules/topic_wp_reconciliation.py::check_published_topic_wp_status() 검증.

전부 tmp_path 격리 SQLite/oneoff_schedule.json을 사용한다 — 실제 WP GET은
이 파일에서 전혀 발생하지 않는다(get_wp_post_readonly를 항상 monkeypatch).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.topic_pool as tp
import modules.scheduler as sch
import modules.topic_wp_reconciliation as rc


def _cfg(tmp_path):
    return {"_root": str(tmp_path), "SQLITE_PATH": "test_topic_wp_reconciliation.db",
            "DB_ADAPTER": "sqlite", "scheduler_line": "blog"}


def _make_published_topic_with_reservation(cfg, wp_post_id=597, calculator_id="calc_x"):
    """candidate -> ... -> published까지 공식 API로 진행시키고, 동일 shape의
    reservation(result.results[0].wp_post_id 포함)을 공식 API로 만든다."""
    t = tp.create_topic(cfg, slug="freelancer-tax-3p3", topic="t", title="ti",
                         intent="calculator", calculator_id=calculator_id)
    t = tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")

    reservation = sch.add_oneoff_reservation(
        cfg, datetime(2026, 9, 23, 10, 26, tzinfo=timezone.utc), "draft",
        topic_id=t["topic_id"])
    tp.update_topic(cfg, t["topic_id"], oneoff_reservation_id=reservation["id"])
    t = tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")

    sch.mark_oneoff_result(cfg, reservation["id"], "completed", result={
        "produced": 1, "reason": "",
        "results": [{"topic_id": t["topic_id"], "status": "DRAFT",
                      "wp_post_id": wp_post_id, "wp_permalink": "https://x/?p=597"}],
    })
    t = tp.transition_status(cfg, t["topic_id"], "published", actor="t", reason="r")
    return t


def _fake_wp_get(status, http_status=200, success=True):
    def _fn(post_id, wp_url="", username="", app_password="", timeout=20):
        if not success:
            return {"success": False, "http_status": http_status,
                    "error": "err", "wp_post_id": post_id}
        return {"success": True, "http_status": 200, "id": post_id,
                "slug": "freelancer-tax-3p3", "status": status, "date": "",
                "modified": "", "link": "", "title": "", "content": "", "excerpt": ""}
    return _fn


# ── Test 3: published + WP publish = MATCH ───────────────────────────

def test_3_published_plus_wp_publish_is_match(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get("publish"))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "MATCH"
    assert result["wp_status"] == "publish"
    assert result["wp_post_id"] == 597


# ── Test 4: published + WP trash = MISMATCH ───────────────────────────

def test_4_published_plus_wp_trash_is_mismatch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get("trash"))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "MISMATCH"
    assert result["wp_status"] == "trash"


# ── Test 5: published + WP draft = MISMATCH ───────────────────────────

def test_5_published_plus_wp_draft_is_mismatch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get("draft"))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "MISMATCH"
    assert result["wp_status"] == "draft"


def test_5b_published_plus_wp_other_status_is_mismatch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get("private"))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "MISMATCH"
    assert result["wp_status"] == "private"


# ── Test 6: WP post id 없음 = WP_POST_ID_UNAVAILABLE ──────────────────

def test_6_no_reservation_id_is_wp_post_id_unavailable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = tp.create_topic(cfg, slug="no-reservation-topic", topic="t", title="ti",
                         intent="howto")
    t = tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "published", actor="t", reason="r")
    assert t["oneoff_reservation_id"] == ""

    def _wp_get_should_not_be_called(*a, **kw):
        raise AssertionError("WP GET이 호출되면 안 된다(wp_post_id 확보 전 종료)")
    monkeypatch.setattr(rc, "get_wp_post_readonly", _wp_get_should_not_be_called)

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "WP_POST_ID_UNAVAILABLE"
    assert result["wp_post_id"] is None


def test_6b_reservation_without_wp_post_id_is_unavailable(tmp_path, monkeypatch):
    """reservation은 있지만 result에 wp_post_id가 없는 경우(예: 실패한 실행)."""
    cfg = _cfg(tmp_path)
    t = tp.create_topic(cfg, slug="failed-exec-topic", topic="t", title="ti", intent="howto")
    t = tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
    reservation = sch.add_oneoff_reservation(
        cfg, datetime(2026, 9, 23, 10, 26, tzinfo=timezone.utc), "draft",
        topic_id=t["topic_id"])
    tp.update_topic(cfg, t["topic_id"], oneoff_reservation_id=reservation["id"])
    t = tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
    sch.mark_oneoff_result(cfg, reservation["id"], "failed", result={
        "produced": 0, "reason": "publish_error", "results": [{"status": "ERROR"}]})
    t = tp.transition_status(cfg, t["topic_id"], "published", actor="t", reason="r")

    def _wp_get_should_not_be_called(*a, **kw):
        raise AssertionError("wp_post_id가 없으면 WP GET을 호출하면 안 된다")
    monkeypatch.setattr(rc, "get_wp_post_readonly", _wp_get_should_not_be_called)

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "WP_POST_ID_UNAVAILABLE"


# ── 추가: TOPIC_NOT_FOUND / TOPIC_NOT_PUBLISHED / WP_POST_NOT_FOUND / WP_CHECK_ERROR ──

def test_topic_not_found(tmp_path):
    cfg = _cfg(tmp_path)
    result = rc.check_published_topic_wp_status(cfg, "topic_does_not_exist")
    assert result["status"] == "TOPIC_NOT_FOUND"


def test_topic_not_published(tmp_path):
    cfg = _cfg(tmp_path)
    t = tp.create_topic(cfg, slug="still-candidate", topic="t", title="ti", intent="howto")
    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "TOPIC_NOT_PUBLISHED"


def test_wp_post_not_found_404(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly",
                         _fake_wp_get(None, http_status=404, success=False))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "WP_POST_NOT_FOUND"


def test_wp_check_error_on_non_404_failure(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly",
                         _fake_wp_get(None, http_status=500, success=False))

    result = rc.check_published_topic_wp_status(cfg, t["topic_id"])
    assert result["status"] == "WP_CHECK_ERROR"


# ── Test 7: reconciliation은 상태 변경을 하지 않음 ────────────────────

def test_7_reconciliation_never_changes_topic_state(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    before = tp.get_topic(cfg, t["topic_id"])

    for wp_status in ("publish", "trash", "draft"):
        monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get(wp_status))
        rc.check_published_topic_wp_status(cfg, t["topic_id"])

    after = tp.get_topic(cfg, t["topic_id"])
    assert after["status"] == before["status"] == "published"
    assert after["status_history"] == before["status_history"]
    assert after["updated_at"] == before["updated_at"]


# ── Test 8: scheduler/planner가 reconciliation을 자동 호출하지 않음 ──

def test_8_scheduler_and_planner_do_not_import_reconciliation():
    """topic_wp_reconciliation은 scheduler.py/publishing_planner.py 어디에서도
    import되지 않는다 — 주기적 자동 실행에 연결되어 있지 않음을 소스 텍스트로
    확인한다(후보 B 미채택 확인)."""
    scheduler_src = (ROOT / "modules" / "scheduler.py").read_text(encoding="utf-8")
    planner_src = (ROOT / "modules" / "publishing_planner.py").read_text(encoding="utf-8")
    assert "topic_wp_reconciliation" not in scheduler_src
    assert "topic_wp_reconciliation" not in planner_src


# ── published -> candidate manual-only 재확인(topic_pool 자체 계약) ──

def test_published_to_candidate_requires_manual_true(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    with pytest.raises(ValueError, match="수동 재활성화 전이"):
        tp.transition_status(cfg, t["topic_id"], "candidate", actor="t", reason="r")


def test_published_to_candidate_succeeds_with_manual_true(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    result = tp.transition_status(cfg, t["topic_id"], "candidate", actor="t",
                                   reason="mismatch_recovery", manual=True)
    assert result["status"] == "candidate"


# ── Golden10 보호 ──────────────────────────────────────────────────────

def test_golden10_unchanged_after_reconciliation_use(tmp_path, monkeypatch):
    import hashlib
    from content.blog import GOLDEN_10
    before = hashlib.sha256(repr(GOLDEN_10).encode()).hexdigest()

    cfg = _cfg(tmp_path)
    t = _make_published_topic_with_reservation(cfg)
    monkeypatch.setattr(rc, "get_wp_post_readonly", _fake_wp_get("publish"))
    rc.check_published_topic_wp_status(cfg, t["topic_id"])

    from content.blog import GOLDEN_10 as GOLDEN_10_AFTER
    after = hashlib.sha256(repr(GOLDEN_10_AFTER).encode()).hexdigest()
    assert before == after
    assert GOLDEN_10 is GOLDEN_10_AFTER
