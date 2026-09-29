# -*- coding: utf-8 -*-
"""tests/content_pipeline_integration_test.py — 파이프라인 통합 테스트"""
import pytest
from content_pipeline.orchestrator import ContentPipelineOrchestrator
from content_pipeline.publish_gate import PublishGate
from content_pipeline.publisher_base import NullPublisher
from unittest.mock import patch

@pytest.fixture
def orchestrator(monkeypatch):
    # DI: 실제 WordPressPublisher 대신 NullPublisher를 명시적으로 주입한다.
    # P0-4: content_pipeline/engine_adapter.py가 auto_generate_all({}, ...)을 빈 cfg로
    # 호출한다 — 제거된 하드코딩 mock(cross-calculator contamination 버그)에 암묵적으로
    # 의존하고 있었으므로, 이 orchestrator 단계-전이 테스트 목적에 맞게 더미 본문으로
    # 대체한다(실제 AI 호출 없음).
    monkeypatch.setattr("content.calculator.writer.generate_article", lambda *a, **kw: "<p>dummy</p>")
    return ContentPipelineOrchestrator(gate=PublishGate(publisher=NullPublisher()))

def test_pipeline_normal_flow(orchestrator):
    """Test 1: 전체 정상 Flow"""
    with patch.object(orchestrator.adapter, 'run_h4a_quality', return_value={"status": "PASS", "data": {}}):
        state = orchestrator.run("calc1", {"profile": {"topics": ["계산 방법"]}})
        assert state.data["status"] == "SUCCESS"
        assert "PUBLISH" in state.data["results"]

def test_pipeline_h4a_hold(orchestrator):
    """Test 2: H4A 결과 HOLD"""
    # Mock H4A to return HOLD
    with patch.object(orchestrator.adapter, 'run_h4a_quality', return_value={"status": "HOLD", "data": {}}):
        state = orchestrator.run("calc2", {"profile": {"topics": ["계산 방법"]}})
        assert state.data["status"] == "FAILED"
        assert "Stage H4A_QUALITY returned HOLD" in state.data["errors"]

def test_pipeline_h3_fail(orchestrator):
    """Test 3: H3 실패"""
    with patch.object(orchestrator.adapter, 'run_h3_faq', return_value={"status": "HOLD", "data": {}}):
        state = orchestrator.run("calc3", {"profile": {"topics": ["계산 방법"]}})
        assert state.data["status"] == "FAILED"
        assert "Stage H3_FAQ returned HOLD" in state.data["errors"]

def test_pipeline_warning_flow(orchestrator):
    """Test 4: WARNING 흐름"""
    with patch.object(orchestrator.adapter, 'run_h4a_quality', return_value={"status": "WARNING", "data": {}}):
        state = orchestrator.run("calc4", {"profile": {"topics": ["계산 방법"]}})
        assert state.data["status"] == "SUCCESS"
        assert state.data["results"]["PUBLISH"]["status"] == "PUBLISHED_WITH_WARNING_LOG"
