# -*- coding: utf-8 -*-
"""tests/content_pipeline_safety_test.py — content_pipeline 원격 WordPress POST 0회 안전성 테스트

이 파일의 테스트는 실제 네트워크에 절대 의존하지 않는다. requests.post/Session.post가
호출되는 즉시 테스트가 실패하도록 감시하는 autouse fixture를 "이 파일 범위"에서만 적용한다
(전체 테스트 스위트에 영향을 주지 않기 위해 conftest.py에는 두지 않는다).
"""
import os
import pytest
import requests
from unittest.mock import patch

from content_pipeline.orchestrator import ContentPipelineOrchestrator
from content_pipeline.publish_gate import PublishGate
from content_pipeline.publisher_base import BasePublisher, NullPublisher
from content_pipeline.wordpress_publisher import WordPressPublisher, REMOTE_WP_POST_BLOCKED


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    """이 파일의 모든 테스트에서 실제 requests.post/Session.post 호출을 즉시 실패로 감지한다."""

    def _forbidden(*args, **kwargs):
        pytest.fail(f"SAFETY: 실제 requests.post 호출 시도 감지! args={args[:1]}")

    monkeypatch.setattr(requests, "post", _forbidden)
    monkeypatch.setattr(requests.Session, "post", _forbidden)
    yield


def _di_orchestrator():
    return ContentPipelineOrchestrator(gate=PublishGate(publisher=NullPublisher()))


def test_pipeline_default_run_zero_remote_post(monkeypatch):
    """기본 생성(ContentPipelineOrchestrator()) 만으로 전체 pipeline을 실행해도 원격 POST가 0회여야 한다."""
    # P0-4: engine_adapter.py가 auto_generate_all({}, ...)을 빈 cfg로 호출한다 — 제거된
    # 하드코딩 mock(cross-calculator contamination 버그)에 암묵적으로 의존하고 있었으므로
    # 더미 본문으로 대체한다(이 테스트의 목적은 원격 POST 0회 확인이지 AI 호출 검증이 아님).
    monkeypatch.setattr("content.calculator.writer.generate_article", lambda *a, **kw: "<p>dummy</p>")
    orchestrator = ContentPipelineOrchestrator()  # DI 인자 없음 — 기본값 자체가 안전해야 함
    assert isinstance(orchestrator.gate.publisher, NullPublisher)
    with patch.object(orchestrator.adapter, "run_h4a_quality", return_value={"status": "PASS", "data": {}}):
        state = orchestrator.run("safety-default-run", {"profile": {"topics": ["계산 방법"]}})
    assert state.data["status"] == "SUCCESS"


def test_publish_stage_zero_remote_post():
    """PUBLISH stage(PublishGate.gate)를 직접 실행해도 원격 POST가 0회여야 한다."""
    orchestrator = _di_orchestrator()
    metadata = {"title": "safety-check", "content": "c", "excerpt": "e"}
    result = orchestrator.gate.gate({"status": "PASS"}, metadata)
    # NullPublisher 경로에서도 로컬 파이프라인 흐름 자체는 정상 완료되어야 한다.
    assert result == "PUBLISHED"


def test_real_credentials_shape_still_zero_post():
    """실제 형태의(더미) credentials가 존재해도 REMOTE_WP_POST_BLOCKED로 인해 원격 POST가 발생하지 않아야 한다."""
    dummy_cfg = {
        "wordpress": {
            "url": "https://dummy-wp.invalid",
            "username": "dummy-user",
            "app_password": "dummy-app-password-not-real",
        }
    }
    publisher = WordPressPublisher(dummy_cfg)
    result = publisher.create_draft({"title": "t", "content": "c", "excerpt": "e"})
    assert result == "FAILED"


def test_null_publisher_replaces_real_publisher():
    """DI로 생성한 orchestrator의 publisher가 정확히 NullPublisher인지 검증한다."""
    orchestrator = _di_orchestrator()
    assert isinstance(orchestrator.gate.publisher, NullPublisher)
    assert isinstance(orchestrator.gate.publisher, BasePublisher)
    assert not isinstance(orchestrator.gate.publisher, WordPressPublisher)


def test_publish_opt_in_required():
    """명시적 opt-in(publisher 인자) 없이 PublishGate()를 생성하면 실제 WordPressPublisher가 아니어야 한다."""
    gate = PublishGate()
    assert isinstance(gate.publisher, NullPublisher)
    assert not isinstance(gate.publisher, WordPressPublisher)

    orchestrator = ContentPipelineOrchestrator()
    assert isinstance(orchestrator.gate.publisher, NullPublisher)
    assert not isinstance(orchestrator.gate.publisher, WordPressPublisher)


def test_remote_wp_post_blocked_remains_active():
    """REMOTE_WP_POST_BLOCKED=True 회귀 고정 — 실제 WordPressPublisher를 직접 만들어도 안전해야 한다."""
    assert REMOTE_WP_POST_BLOCKED is True
    publisher = WordPressPublisher({
        "wordpress": {"url": "https://blog.genon.app", "username": "u", "app_password": "p"}
    })
    result = publisher.create_draft({"title": "t", "content": "c", "excerpt": "e"})
    assert result == "FAILED"
