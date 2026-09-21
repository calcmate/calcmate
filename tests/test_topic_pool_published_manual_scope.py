# -*- coding: utf-8 -*-
"""
tests/test_topic_pool_published_manual_scope.py
CALCMATE-AUTO-CONTENT-PUBLISHED-WP-RECONCILIATION-SCOPE-CLEANUP-01 —
WIREUP-01에서 tests/test_topic_pool.py에 추가됐던 다음 테스트 1건을 기존
dirty 파일과 완전히 분리된 독립 커밋 후보로 만들기 위해 이 신규 파일로
그대로 옮긴다(내용 변경 없음, 기존 tests/test_topic_pool.py는 수정하지 않음):
    test_published_manual_grant_is_scoped_only_to_published_source

전부 tmp_path로 격리된 SQLite를 사용한다 — 실제 production DB/Sheets에는
어떤 topic도 생성하지 않는다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.topic_pool as tp


def _cfg(tmp_path):
    return {"_root": str(tmp_path), "SQLITE_PATH": "test_topic_pool_published_manual_scope.db",
            "DB_ADAPTER": "sqlite"}


def _make(cfg, **overrides):
    kwargs = dict(slug="jeonse-vs-monthly", topic="전세vs월세 신규 topic",
                  intent="howto", title="t", priority=100)
    kwargs.update(overrides)
    return tp.create_topic(cfg, **kwargs)


def _to_scheduled(cfg, topic_id, *, reservation_id="test-reservation-id"):
    """approved -> scheduled까지 진행시키고 oneoff_reservation_id를 채워두는
    헬퍼(실제 Planner를 거치지 않고 update_topic()으로 직접 채움 — 이 파일은
    scheduler/planner를 전혀 import하지 않는 순수 topic_pool 단위 테스트)."""
    tp.transition_status(cfg, topic_id, "approved", actor="t", reason="r")
    tp.update_topic(cfg, topic_id, oneoff_reservation_id=reservation_id)
    return tp.transition_status(cfg, topic_id, "scheduled", actor="t", reason="r")


def test_published_manual_grant_is_scoped_only_to_published_source(tmp_path):
    """WIREUP-01 STEP4 항목 6: "published": {"candidate"}는 오직
    from_status="published"에만 적용되어야 한다 — 예를 들어 "publishing"
    상태에서는 manual=True를 줘도 여전히 candidate로 갈 수 없어야 한다
    (다른 상태에서 이 manual-only 허용이 잘못 넓게 적용되지 않는지 확인)."""
    cfg = _cfg(tmp_path)
    t = _make(cfg)
    _to_scheduled(cfg, t["topic_id"])
    tp.transition_status(cfg, t["topic_id"], "publishing", actor="t", reason="r")
    before = tp.get_topic(cfg, t["topic_id"])
    assert before["status"] == "publishing"
    with pytest.raises(ValueError):
        tp.transition_status(cfg, t["topic_id"], "candidate", actor="test",
                              reason="r", manual=True)
    after = tp.get_topic(cfg, t["topic_id"])
    assert after["status"] == before["status"] == "publishing"
