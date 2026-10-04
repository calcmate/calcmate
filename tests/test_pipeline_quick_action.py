# -*- coding: utf-8 -*-
"""tests/test_pipeline_quick_action.py — STEP S12: Dashboard Quick Action
「▶ 파이프라인 실행(전량)」 React/FastAPI 이관 검증.

dashboard.py "▶ 파이프라인 실행(전량)" 버튼(dashboard.py:472-473, "🔧 고급
실행(수동)" expander 안)과 동일한 실행 의미를 검증한다.
main.py의 run_once()의 실제 구현(진짜 RSS 수집 + 진짜 AI 호출 + 진짜 이미지
생성 + 진짜 WordPress 발행 + 진짜 DB write)은 이 파일의 어떤 테스트에서도
실행하지 않는다 — 항상 monkeypatch로 대체한다. Blog Scheduler/Calculator
Scheduler/Content Sync/Calculator Quick Action이 호출되지 않는지도 구조적으로
확인한다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "pipeline-quick-action-test-viewer-token"
ADMIN_TOKEN = "pipeline-quick-action-test-admin-token"

FAKE_RESULT = {
    "produced": 1, "processed": 4, "dup": 1, "failed": 1, "no_wp": 0, "reason": "ok",
}


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _mock_lock_always_free(monkeypatch):
    monkeypatch.setattr("api.services.pipeline_run_service.load_config", lambda *a, **k: {})
    monkeypatch.setattr("modules.scheduler._acquire_lock", lambda cfg, **kw: True)
    monkeypatch.setattr("modules.scheduler._release_lock", lambda cfg: None)


# ══════════════════════════════════════════════════════════════════════════
# 인증
# ══════════════════════════════════════════════════════════════════════════

def test_run_without_auth_returns_401():
    r = _client().post("/api/scheduler/pipeline/run-once")
    assert r.status_code == 401


def test_run_as_viewer_returns_403():
    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_run_as_admin_returns_200(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("main.run_once", lambda cfg: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 기존 함수 호출 확인 + 반환값 보존
# ══════════════════════════════════════════════════════════════════════════

def test_calls_the_real_main_run_once_with_correct_args(monkeypatch):
    """dashboard.py의 실제 호출부(PIPE.run_once(cfg), max_count 없음)와 동일한
    인자로 호출되는지 확인 — 새로운 payload를 설계하지 않는다는 원칙 검증."""
    _mock_lock_always_free(monkeypatch)
    called = {}
    def _spy(cfg):
        called["cfg"] = cfg
        return dict(FAKE_RESULT)
    monkeypatch.setattr("main.run_once", _spy)
    monkeypatch.setattr("api.services.pipeline_run_service.load_config", lambda *a, **k: {"FAKE": True})

    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert called["cfg"]["FAKE"] is True
    # scheduler_line="blog"는 lock 재사용을 위한 것으로, main.run_once() 자체는
    # 이를 참조하지 않지만 cfg에 포함되어 전달되는 것은 blog_scheduler_service.py의
    # 기존 패턴과 동일하다.
    assert called["cfg"]["scheduler_line"] == "blog"


def test_return_structure_passed_through_unmodified(monkeypatch):
    """main.run_once()의 반환 구조를 임의로 재가공하지 않고 그대로 전달하는지
    확인 — 새로운 포맷을 설계하지 않는다는 원칙 검증."""
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("main.run_once", lambda cfg: dict(FAKE_RESULT))
    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data == FAKE_RESULT


def test_zero_produced_result_is_a_clean_success_envelope(monkeypatch):
    """dashboard.py의 "수집된 항목 없음"/"예산초과" 케이스 — main.run_once() 자체가
    예외 없이 {"produced": 0, "reason": ...}을 반환하는 정상 동작이다. HTTP 200 +
    명확히 구분되는 data.produced=0 이어야 하며, 애매한 구조가 아니다."""
    _mock_lock_always_free(monkeypatch)
    no_items = {"produced": 0, "reason": "no_items"}
    monkeypatch.setattr("main.run_once", lambda cfg: dict(no_items))
    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["produced"] == 0
    assert data["reason"] == "no_items"


def test_unexpected_exception_does_not_produce_a_fabricated_success(monkeypatch):
    """main.run_once() 자체에서 진짜 예상 밖 예외가 나면(blog/run-once의 기존
    처리 방식과 동일하게) 성공으로 위장하지 않아야 한다."""
    _mock_lock_always_free(monkeypatch)
    def _boom(cfg):
        raise RuntimeError("예상치 못한 오류(시뮬레이션)")
    monkeypatch.setattr("main.run_once", _boom)

    from api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════
# 중복 실행 방지(기존 파일 lock 재사용 — 실제 lock 함수로 검증, blog scheduler_line 공유)
# ══════════════════════════════════════════════════════════════════════════

def test_lock_conflict_when_blog_scheduler_holds_the_real_file_lock(monkeypatch, tmp_path):
    """기존 modules.scheduler._acquire_lock()/_release_lock()을 실제로(모킹 없이)
    격리된 tmp_path에 대해 사용해, blog scheduler_line lock이 이미 걸려 있으면
    LOCK_CONFLICT로 명확히 차단되는지 확인한다(§9 — 기존 lock 재사용 검증, blog
    scheduler_line을 공유하므로 Blog Scheduler 실행 중에도 이 endpoint가 겹쳐
    실행되지 않아야 한다)."""
    import modules.scheduler as SCH
    monkeypatch.setattr(SCH, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.pipeline_run_service.load_config", lambda *a, **k: {})

    assert SCH._acquire_lock({"scheduler_line": "blog"}) is True  # 다른 실행이 보유 중이라고 가정
    def _boom(cfg):
        raise AssertionError("lock이 걸려 있는데 main.run_once()가 호출되면 안 된다")
    monkeypatch.setattr("main.run_once", _boom)

    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "LOCK_CONFLICT"

    SCH._release_lock({"scheduler_line": "blog"})  # 정리


def test_concurrent_requests_only_run_once_via_real_lock(monkeypatch, tmp_path):
    """실제 threading으로 두 요청이 진짜 겹치게 만들어, 실제 파일 lock이 두 번째
    요청을 차단하는지 확인한다(동일 요청 중복 실행 방지의 핵심 증거)."""
    import modules.scheduler as SCH
    monkeypatch.setattr(SCH, "_schedule_dir", lambda cfg: tmp_path)
    monkeypatch.setattr("api.services.pipeline_run_service.load_config", lambda *a, **k: {})

    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _slow_run(cfg):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=5)
        return dict(FAKE_RESULT)

    monkeypatch.setattr("main.run_once", _slow_run)

    client = _client()
    results = []

    def _call():
        results.append(client.post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN)))

    t1 = threading.Thread(target=_call)
    t1.start()
    assert entered.wait(timeout=5)

    r2 = client.post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r2.json()["error"]["code"] == "LOCK_CONFLICT"

    release.set()
    t1.join(timeout=5)
    assert call_count["n"] == 1


# ══════════════════════════════════════════════════════════════════════════
# Side Effect 보호 / 다른 기능 미호출
# ══════════════════════════════════════════════════════════════════════════

def test_never_touches_other_domain_modules(monkeypatch):
    _mock_lock_always_free(monkeypatch)
    monkeypatch.setattr("main.run_once", lambda cfg: dict(FAKE_RESULT))

    import sys as _sys
    originally_absent = [
        m for m in (
            "modules.retry_queue", "modules.registry_loader",
            "modules.calculator_pipeline", "modules.content_sync",
            "modules.strategy_room",
        ) if m not in _sys.modules
    ]

    r = _client().post("/api/scheduler/pipeline/run-once", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    for m in originally_absent:
        assert m not in _sys.modules, f"{m}이 파이프라인 실행 중 새로 import됨"


def test_service_only_calls_pipe_run_once():
    """모듈 docstring에는 비교 설명을 위해 resolve_blog_publish_fn/run_blog_once를
    언급하지만, 실제 코드(주석/문자열 제외)에서 PIPE.의 유일한 호출 대상은
    run_once뿐이어야 한다 — 다른 도메인 함수를 실제로 호출하지 않는다는 증거."""
    import ast
    import inspect
    from api.services import pipeline_run_service
    source = inspect.getsource(pipeline_run_service)
    tree = ast.parse(source)
    pipe_attr_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "PIPE"
    }
    assert pipe_attr_calls == {"run_once"}

    for forbidden in (
        "run_calculator_once", "run_sync_once", "run_strategy_room",
        "generate_app", "generate_app_with_contract", "registry_loader",
        "retry_queue",
    ):
        assert forbidden not in source


def test_only_one_new_write_route_added_under_scheduler_pipeline():
    from _route_utils import write_routes
    from api.main import app
    # SMALL-GAPS-02: dashboard.py "📝 글 생성(1건)" 이관(run-one, require_admin) 추가.
    assert sorted(write_routes(app, prefix="/api/scheduler/pipeline")) == [
        ("/api/scheduler/pipeline/run-once", "POST"),
        ("/api/scheduler/pipeline/run-one", "POST"),
    ]
