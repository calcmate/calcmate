# -*- coding: utf-8 -*-
"""
tests/test_topic_publish_adapter.py
CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01 — modules/topic_publish_adapter.py
(run_topic_once_wp) 검증.

전부 tmp_path 격리 SQLite를 사용하며, generation/publish/duplicate-check는 전부
stub으로 주입한다 — 실제 AI 호출, 실제 WP 호출은 이 파일에서 발생하지 않는다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modules.topic_pool as tp
import modules.topic_publish_adapter as tpa


def _cfg(tmp_path):
    return {"_root": str(tmp_path), "SQLITE_PATH": "test_topic_publish.db",
            "DB_ADAPTER": "sqlite"}


def _seed_calculator(cfg, calculator_id: str):
    """TopicGenerationRequest.validate()의 calculator_id 존재 검증을 통과시키기
    위해, 격리된 tmp_path SQLite에 최소 calculator row 1건을 직접 넣는다
    (production calculators 테이블과 완전히 분리된 파일)."""
    from adapters.db.factory import get_calculator_storage_adapter
    get_calculator_storage_adapter(cfg).insert("calculators", {
        "id": calculator_id, "slug": "seed-calc", "name": "테스트 계산기",
        "category": "테스트", "faq": "[]",
    })


def _make_scheduled_topic(cfg, **overrides):
    """candidate -> approved -> scheduled까지 진행된 topic 1건을 만든다."""
    calculator_id = overrides.pop("calculator_id", "calc_seed_001")
    _seed_calculator(cfg, calculator_id)
    kwargs = dict(slug="new-topic-slug-xyz", topic="새 topic 설명",
                  title="새 제목", intent="howto", calculator_id=calculator_id)
    kwargs.update(overrides)
    t = tp.create_topic(cfg, **kwargs)
    tp.transition_status(cfg, t["topic_id"], "approved", actor="t", reason="r")
    t = tp.transition_status(cfg, t["topic_id"], "scheduled", actor="t", reason="r")
    return t


def _ok_generate_fn(cfg, post, save=False, intent=None):
    return {"article_content": "<p>" + ("본문 " * 60) + "</p>", "blocked": False,
            "integrity_failed": []}


def _ok_dup_check_fn(cfg, slug):
    return {"exists": False, "confirmed": True, "wp_post_id": None,
            "slug": None, "error": None}


def _ok_publish_fn(post_id, seo, article, images, cfg, status="draft",
                    category_name=None, comment_status=None):
    return {"status": status, "wp_post_id": 999, "wp_permalink": "https://example/?p=999"}


# ── E: 잘못된/존재하지 않는 topic_id -> fail-closed, Golden10 없음 ──────

def test_e_nonexistent_topic_id_fails_closed(tmp_path):
    cfg = _cfg(tmp_path)
    result = tpa.run_topic_once_wp(cfg, "topic_does_not_exist",
                                    generate_fn=_ok_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)
    assert result["produced"] == 0
    assert result["reason"] == "topic_not_found"


def test_e_missing_topic_id_fails_closed(tmp_path):
    cfg = _cfg(tmp_path)
    result = tpa.run_topic_once_wp(cfg, "", generate_fn=_ok_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)
    assert result["produced"] == 0
    assert result["reason"] == "missing_topic_id"


def test_e_topic_not_scheduled_status_fails_closed(tmp_path):
    """candidate 상태(scheduled 아님)인 topic은 발행 시도 없이 차단되어야 한다."""
    cfg = _cfg(tmp_path)
    t = tp.create_topic(cfg, slug="s2", topic="t2", title="ti2", intent="howto",
                         calculator_id="calc_x")
    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)
    assert result["produced"] == 0
    assert result["reason"] == "invalid_topic_status"
    # 상태가 그대로 candidate여야 한다 — publishing으로도 전환되지 않아야 함.
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "candidate"


# ── I: Topic 상태 전이(scheduled -> publishing -> published/publish_failed) ──

def test_i_success_path_transitions_to_published(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], status="draft",
                                    generate_fn=_ok_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)

    assert result["produced"] == 1
    final = tp.get_topic(cfg, t["topic_id"])
    assert final["status"] == "published"
    history_statuses = [(e["from_status"], e["to_status"]) for e in final["status_history"]]
    assert ("scheduled", "publishing") in history_statuses
    assert ("publishing", "published") in history_statuses


def test_i_generation_failure_transitions_to_publish_failed(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    def _raising_generate_fn(cfg, post, save=False, intent=None):
        raise RuntimeError("boom")

    result = tpa.run_topic_once_wp(cfg, t["topic_id"],
                                    generate_fn=_raising_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)

    assert result["produced"] == 0
    assert result["reason"] == "generation_error"
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "publish_failed"


def test_i_integrity_gate_blocked_transitions_to_publish_failed(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    def _blocked_generate_fn(cfg, post, save=False, intent=None):
        return {"article_content": "", "blocked": True,
                "integrity_failed": [{"gate": "G-LEGAL", "grade": "critical"}]}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"],
                                    generate_fn=_blocked_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_ok_publish_fn)

    assert result["produced"] == 0
    assert result["reason"] == "integrity_gate_blocked"
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "publish_failed"


def test_i_wp_publish_failure_transitions_to_publish_failed(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    def _failing_publish_fn(post_id, seo, article, images, cfg, status="draft",
                             category_name=None, comment_status=None):
        return {"status": "error", "error": "wp_500"}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                    dup_check_fn=_ok_dup_check_fn,
                                    publish_fn=_failing_publish_fn)

    assert result["produced"] == 0
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "publish_failed"


def test_i_wp_duplicate_confirmed_exists_blocks_publish(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    def _dup_exists_fn(cfg, slug):
        return {"exists": True, "confirmed": True, "wp_post_id": 123,
                "slug": slug, "error": None}

    called = {"publish": False}

    def _publish_fn(*a, **kw):
        called["publish"] = True
        return {"status": "draft"}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                    dup_check_fn=_dup_exists_fn, publish_fn=_publish_fn)

    assert result["produced"] == 0
    assert result["reason"] == "wp_duplicate_exists"
    assert called["publish"] is False, "중복 확정 시 publish_fn이 호출되면 안 된다"
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "publish_failed"


def test_i_dup_check_not_confirmed_fails_closed(tmp_path):
    """중복 확인 자체가 실패(confirmed=False)하면 fail-closed로 발행하지
    않아야 한다(_check_wp_duplicate의 FAIL-CLOSED 계약과 동일한 정신)."""
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    def _dup_unconfirmed_fn(cfg, slug):
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": "http_500"}

    called = {"publish": False}

    def _publish_fn(*a, **kw):
        called["publish"] = True
        return {"status": "draft"}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                    dup_check_fn=_dup_unconfirmed_fn, publish_fn=_publish_fn)

    assert result["produced"] == 0
    assert result["reason"] == "duplicate_check_failed"
    assert called["publish"] is False
    assert tp.get_topic(cfg, t["topic_id"])["status"] == "publish_failed"


# ── C/D: draft/publish status가 publish_fn까지 그대로 전달되는지 ────────

def test_c_draft_status_forwarded_to_publish_fn(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)
    captured = {}

    def _capture_publish_fn(post_id, seo, article, images, cfg, status="draft",
                             category_name=None, comment_status=None):
        captured["status"] = status
        return {"status": status}

    tpa.run_topic_once_wp(cfg, t["topic_id"], status="draft",
                          generate_fn=_ok_generate_fn, dup_check_fn=_ok_dup_check_fn,
                          publish_fn=_capture_publish_fn)
    assert captured["status"] == "draft"


def test_d_publish_status_forwarded_to_publish_fn(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)
    captured = {}

    def _capture_publish_fn(post_id, seo, article, images, cfg, status="draft",
                             category_name=None, comment_status=None):
        captured["status"] = status
        return {"status": status}

    tpa.run_topic_once_wp(cfg, t["topic_id"], status="publish",
                          generate_fn=_ok_generate_fn, dup_check_fn=_ok_dup_check_fn,
                          publish_fn=_capture_publish_fn)
    assert captured["status"] == "publish"


# ── 9번: TopicGenerationRequest에 정확한 필드가 전달되는지 ──────────────

def test_generation_seam_receives_correct_calculator_id(tmp_path):
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg, calculator_id="calc_specific_123")
    captured = {}

    def _capture_generate_fn(cfg, post, save=False, intent=None):
        captured["post_id"] = post.get("id")
        captured["intent"] = intent
        return {"article_content": "<p>" + ("x" * 150) + "</p>", "blocked": False}

    tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_capture_generate_fn,
                          dup_check_fn=_ok_dup_check_fn, publish_fn=_ok_publish_fn)
    assert captured["intent"] == "howto"


# ── J: WP 성공 + 상태 저장 실패(재현만, 신규 복구 시스템 구현 없음) ──────

def test_j_wp_success_then_status_save_failure_propagates(tmp_path, monkeypatch):
    """WP publish_fn은 성공했지만 그 뒤 published로의 상태 저장이 실패하면
    예외가 그대로 전파되어야 한다(현재 구현의 알려진 gap을 재현 — 이번 STEP은
    이 gap을 해결하는 복구 로직을 추가하지 않는다, GAP3-IMPLEMENT-01 STEP13-J)."""
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)

    original_transition = tp.transition_status
    call_count = {"n": 0}

    def _flaky_transition(cfg_arg, topic_id, to_status, **kwargs):
        call_count["n"] += 1
        if to_status == "published":
            raise RuntimeError("simulated_db_write_failure")
        return original_transition(cfg_arg, topic_id, to_status, **kwargs)

    monkeypatch.setattr(tpa.topic_pool, "transition_status", _flaky_transition)

    published_flag = {"wp_called": False}

    def _publish_fn(post_id, seo, article, images, cfg, status="draft",
                    category_name=None, comment_status=None):
        published_flag["wp_called"] = True
        return {"status": status, "wp_post_id": 777}

    with pytest.raises(RuntimeError, match="simulated_db_write_failure"):
        tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                              dup_check_fn=_ok_dup_check_fn, publish_fn=_publish_fn)

    # WP는 이미 호출되어 "성공"했지만, Topic Pool 상태는 published로 갱신되지
    # 못하고 "publishing"에 멈춰 있다 — 이것이 설계 audit에서 식별한 gap이다.
    assert published_flag["wp_called"] is True
    stuck = tp.get_topic(cfg, t["topic_id"])
    assert stuck["status"] == "publishing"


# ── WP-METADATA-GAP-IMPLEMENT-01: category_name/comment_status 전달 ─────

def test_a_topic_category_and_closed_comment_status_reach_publish_fn(tmp_path):
    """Topic.category="건강"이면 publish_fn이 category_name="건강",
    comment_status="closed"를 그대로 받아야 한다(run_topic_once_wp 전체
    경로를 통한 통합 검증)."""
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg, category="건강")
    captured = {}

    def _capture_publish_fn(post_id, seo, article, images, cfg, status="draft",
                             category_name=None, comment_status=None):
        captured["category_name"] = category_name
        captured["comment_status"] = comment_status
        return {"status": status, "wp_post_id": 1}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                   dup_check_fn=_ok_dup_check_fn,
                                   publish_fn=_capture_publish_fn)
    assert result["produced"] == 1
    assert captured["category_name"] == "건강"
    assert captured["comment_status"] == "closed"


def test_b_default_publish_fn_forwards_category_and_comment_status_to_publisher(tmp_path, monkeypatch):
    """_default_publish_fn 자체가(run_topic_once_wp를 거치지 않고) category_name/
    comment_status를 modules.publisher.publish()에 그대로 전달하는지 단위 검증
    (Test A는 run_topic_once_wp 전체 경로, 이 테스트는 seam 1개만 격리)."""
    captured = {}

    def _fake_publisher_publish(post_id, seo, html, images, cfg, *, status="publish",
                                 comment_status=None, category_name=None):
        captured["category_name"] = category_name
        captured["comment_status"] = comment_status
        return {"status": status, "wp_post_id": 42}

    import modules.publisher as publisher
    monkeypatch.setattr(publisher, "publish", _fake_publisher_publish)

    tpa._default_publish_fn("post_1", {}, "<p>x</p>", {}, {}, status="draft",
                            category_name="건강", comment_status="closed")
    assert captured["category_name"] == "건강"
    assert captured["comment_status"] == "closed"


def test_c_unknown_category_fails_closed_no_wp_success(tmp_path):
    """존재하지 않는 카테고리명이면 publisher 레이어(resolve_category_id)가
    실패를 반환하는 상황을 fake publish_fn으로 재현한다 — 기존 publish_error
    fail-closed 경로(_fail("publish_error", ...))가 그대로 유지되는지 확인,
    WP "성공"은 절대 발생하지 않는다."""
    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg, category="없는카테고리")

    def _rejecting_publish_fn(post_id, seo, article, images, cfg, status="draft",
                               category_name=None, comment_status=None):
        assert category_name == "없는카테고리"
        return {"status": "error", "error": f"category_not_found:{category_name}"}

    result = tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                                   dup_check_fn=_ok_dup_check_fn,
                                   publish_fn=_rejecting_publish_fn)
    assert result["produced"] == 0
    assert result["reason"] == "publish_failed"
    stuck = tp.get_topic(cfg, t["topic_id"])
    assert stuck["status"] == "publish_failed"


def test_d_default_publish_fn_old_style_call_forwards_none_none(monkeypatch):
    """기존 호출부가 category_name/comment_status 없이(위치 인자 5개 + status만)
    _default_publish_fn을 호출해도 publisher.publish()는 그대로 None/None을
    받는다 — 기존 계약과 100% 호환(새 kwarg는 옵트인, 기본값 None)."""
    captured = {}

    def _fake_publisher_publish(post_id, seo, html, images, cfg, *, status="publish",
                                 comment_status=None, category_name=None):
        captured["category_name"] = category_name
        captured["comment_status"] = comment_status
        return {"status": status}

    import modules.publisher as publisher
    monkeypatch.setattr(publisher, "publish", _fake_publisher_publish)

    tpa._default_publish_fn("post_1", {}, "<p>x</p>", {}, {}, status="draft")
    assert captured["category_name"] is None
    assert captured["comment_status"] is None


def test_e_golden10_call_site_unaffected_by_metadata_change():
    """modules/blog_scheduler_adapter.py(Golden10 전용 run_blog_once_wp)는
    이번 GAP-IMPLEMENT-01에서 수정 대상이 아니다 — 그 publisher.publish()
    호출부가 category_name/comment_status 키워드 인자를 여전히 전달하지
    않는지(=WP 사이트 기본값 그대로 유지) 소스 텍스트로 확인한다(dashboard.py류
    static 검증과 동일한 관례 — 실제 import/실행 없음)."""
    src = (ROOT / "modules" / "blog_scheduler_adapter.py").read_text(encoding="utf-8")
    assert "pub_result = publisher.publish(post_id, seo, article, {}, cfg, status=status)" in src
    assert "category_name" not in src
    assert "comment_status" not in src


# ── Golden10 보호 ─────────────────────────────────────────────────────

def test_golden10_unchanged_after_topic_publish_adapter_use(tmp_path):
    import hashlib
    from content.blog import GOLDEN_10
    before = hashlib.sha256(repr(GOLDEN_10).encode()).hexdigest()

    cfg = _cfg(tmp_path)
    t = _make_scheduled_topic(cfg)
    tpa.run_topic_once_wp(cfg, t["topic_id"], generate_fn=_ok_generate_fn,
                          dup_check_fn=_ok_dup_check_fn, publish_fn=_ok_publish_fn)

    from content.blog import GOLDEN_10 as GOLDEN_10_AFTER
    after = hashlib.sha256(repr(GOLDEN_10_AFTER).encode()).hexdigest()
    assert before == after
    assert GOLDEN_10 is GOLDEN_10_AFTER
