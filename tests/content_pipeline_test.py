# -*- coding: utf-8 -*-
"""tests/content_pipeline_test.py — Pipeline 테스트"""
import pytest
import json
from pathlib import Path
from unittest.mock import patch
from content_pipeline.orchestrator import ContentPipelineOrchestrator
from content_pipeline.publish_gate import PublishGate
from content_pipeline.publisher_base import NullPublisher

@pytest.fixture
def orchestrator(monkeypatch):
    # DI: 실제 WordPressPublisher 대신 NullPublisher를 명시적으로 주입한다.
    # P0-4: content_pipeline/engine_adapter.py::run_content_generation()이
    # auto_generate_all({}, ...)을 빈 cfg로 호출한다 — 예전에는 OPENAI_API_KEY 부재 시
    # content/calculator/writer.py::generate_article()이 계산기 종류와 무관한 하드코딩
    # mock 본문을 반환해 이 빈 cfg 호출도 "성공"으로 흘러갔지만, 그 mock 자체가
    # cross-calculator contamination 버그였기에 P0-4에서 제거되었다(진짜 예외를 던짐).
    # 이 테스트 파일들은 실제 AI 호출 여부를 검증하는 게 아니라 orchestrator의 단계별
    # 상태 전이를 검증하는 것이 목적이므로, 실제 AI 호출 대신 더미 본문으로 대체한다.
    monkeypatch.setattr("content.calculator.writer.generate_article", lambda *a, **kw: "<p>dummy</p>")
    return ContentPipelineOrchestrator(gate=PublishGate(publisher=NullPublisher()))

def test_pipeline_success(orchestrator):
    """Test 1: 정상 Pipeline 실행"""
    with patch.object(orchestrator.adapter, 'run_h4a_quality', return_value={"status": "PASS", "data": {}}):
        state = orchestrator.run("calc1", {})
        assert state.data["status"] == "SUCCESS"
        assert len(state.data["results"]) >= 4 # H4B, CONTENT, H3, H4A

def test_pipeline_failure(orchestrator):
    """Test 2: 중간 stage 실패"""
    state = orchestrator.run("calc1", {}, mock_fail_stage="H3_FAQ")
    assert state.data["status"] == "FAILED"
    assert "Stage H3_FAQ failed" in state.data["errors"]
    assert "H3_FAQ" not in state.data["results"]

def test_pipeline_log_saved(orchestrator):
    """Test 3: state 저장 확인"""
    calc_id = "calc2"
    orchestrator.run(calc_id, {}, mock_fail_stage="CONTENT_GENERATION")
    
    log_file = Path("logs/content_pipeline") / f"pipeline_p_{calc_id}.json"
    assert log_file.exists()
    
    with open(log_file, "r", encoding="utf-8") as f:
        log_data = json.load(f)
        assert log_data["status"] == "FAILED"
        assert "CONTENT_GENERATION" in log_data["current_stage"]
