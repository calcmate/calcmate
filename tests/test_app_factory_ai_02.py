# -*- coding: utf-8 -*-
"""tests/test_app_factory_ai_02.py — CALCMATE-STREAMLIT-REMAINING-MIGRATION-APP-FACTORY-02.

dashboard.py App Factory AI 추천 6종 + Mode B slug 제안 + Formula 운영자 확정 +
Tier2-B 자동 확정의 FastAPI 이관 검증.

실제 AI provider·BudgetTracker·Sheets/DB·Registry 쓰기는 일어나지 않는다:
app_factory._chat(모든 AI 호출의 단일 경로)과 BudgetTracker, 기존 계산기 목록
조회(storage adapter), save_app/generate_app_with_contract를 monkeypatch로 대체한다.
기존 Dashboard 테스트(step23_2/23_3/24_2/25_2/26_1)의 **기능 계약**을 API 수준에서
다시 검증한다(Streamlit 소스 문자열 검사는 옮기지 않는다).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER_TOKEN = "af02-viewer-token"
ADMIN_TOKEN = "af02-admin-token"
SECRET = "sk-live-SECRETKEY123 Authorization: Bearer abc.def"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _fresh_job_store():
    import api.services.generation_job_store as m
    m._store = None
    yield
    if m._store is not None:
        m._store.shutdown(wait=True)
        m._store = None


@pytest.fixture(autouse=True)
def _no_real_ai_or_storage(monkeypatch):
    """모든 AI 호출(_chat)·비용 기록·계산기 목록 조회를 차단한다. 테스트가 _chat을
    다시 지정하지 않으면 호출 자체가 실패로 기록된다."""
    from modules import app_factory
    from api.services import calculator_service as cs
    calls = {"chat": [], "budget": 0}

    def _blocked_chat(*a, **k):
        calls["chat"].append(a)
        raise AssertionError("real AI call attempted")

    class _NoBudget:
        def __init__(self, *a, **k):
            calls["budget"] += 1

        def record(self, *a, **k):
            pass

    class _EmptyRepo:
        def __init__(self, *a, **k):
            pass

        def get_all(self):
            return []

    monkeypatch.setattr(app_factory, "_chat", _blocked_chat)
    monkeypatch.setattr(app_factory, "BudgetTracker", _NoBudget)
    monkeypatch.setattr(app_factory, "CalculatorRepository", _EmptyRepo)
    monkeypatch.setattr(app_factory, "get_calculator_storage_adapter", lambda cfg: None)
    monkeypatch.setattr(cs, "CalculatorRepository", _EmptyRepo)
    monkeypatch.setattr(cs, "get_calculator_storage_adapter", lambda cfg: None)
    monkeypatch.setattr(cs, "load_config", lambda *a, **k: {})
    return calls


def _chat_returns(monkeypatch, text):
    from modules import app_factory
    seen = []

    def _chat(cfg, role, system, user, max_tokens=1200):
        seen.append({"role": role, "user": user, "max_tokens": max_tokens})
        return text, "mock-model", 10
    monkeypatch.setattr(app_factory, "_chat", _chat)
    return seen


def _chat_raises(monkeypatch):
    from modules import app_factory

    def _chat(*a, **k):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(app_factory, "_chat", _chat)


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(token=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _post(path, body=None, token=ADMIN_TOKEN):
    return _client().post(path, headers=_h(token), json=body if body is not None else {})


AI_ROUTES = [
    ("/api/calculators/ai/suggest-idea", {}),
    ("/api/calculators/ai/suggest-mode", {"name": "x"}),
    ("/api/calculators/ai/suggest-tier", {"name": "x"}),
    ("/api/calculators/ai/tier2b-keywords", {"name": "x"}),
    ("/api/calculators/ai/suggest-spec", {"name": "x"}),
    ("/api/calculators/ai/suggest-formula", {"name": "x"}),
    ("/api/calculators/generate/contract/slug-suggest", {"name": "x"}),
    ("/api/calculators/generate/contract/job/confirm-formula", None),
]


@pytest.mark.parametrize("path,body", AI_ROUTES)
def test_viewer_forbidden_and_no_ai_call(path, body, _no_real_ai_or_storage):
    r = _post(path, body, token=VIEWER_TOKEN)
    assert r.status_code == 403
    assert _no_real_ai_or_storage["chat"] == []


@pytest.mark.parametrize("path,body", AI_ROUTES)
def test_unauthenticated_rejected(path, body):
    r = _client().post(path, json=body or {})
    assert r.status_code == 401


# ── 1. Idea ───────────────────────────────────────────────────────────────

def test_idea_success_with_keyword(monkeypatch):
    seen = _chat_returns(monkeypatch, '{"name":"육아휴직 급여 계산기","category":"노무/급여","desc":"월 급여 기준"}')
    r = _post("/api/calculators/ai/suggest-idea", {"keyword": "육아휴직"})
    assert r.json()["data"] == {"name": "육아휴직 급여 계산기", "category": "노무/급여", "desc": "월 급여 기준"}
    assert seen[0]["role"] == "orchestrator" and seen[0]["max_tokens"] == 400


def test_idea_free_suggestion_without_keyword(monkeypatch):
    _chat_returns(monkeypatch, '{"name":"A","category":"B","desc":"C"}')
    assert _post("/api/calculators/ai/suggest-idea", {"keyword": None}).json()["data"]["name"] == "A"


def test_idea_failure_hides_raw_exception(monkeypatch):
    _chat_raises(monkeypatch)
    r = _post("/api/calculators/ai/suggest-idea", {"keyword": "x"})
    assert r.status_code == 200
    assert r.json()["success"] is False and r.json()["error"]["code"] == "AI_SUGGEST_FAILED"
    assert "SECRETKEY" not in r.text and "Authorization" not in r.text and "Bearer" not in r.text


# ── 2. Mode (step25_2 계약) ────────────────────────────────────────────────

def test_mode_success_preserves_mode_reason_confidence(monkeypatch):
    _chat_returns(monkeypatch, '{"mode":"A","reason":"단순 산술","confidence":"high"}')
    d = _post("/api/calculators/ai/suggest-mode", {"name": "BMI 계산기", "category": "건강", "description": "키/몸무게"}).json()["data"]
    assert d == {"mode": "A", "reason": "단순 산술", "confidence": "high"}


def test_mode_legal_keyword_downgrades_a_high_to_medium(monkeypatch):
    _chat_returns(monkeypatch, '{"mode":"A","reason":"r","confidence":"high"}')
    d = _post("/api/calculators/ai/suggest-mode", {"name": "근로기준법 수당", "description": ""}).json()["data"]
    assert d["mode"] == "A" and d["confidence"] == "medium"


def test_mode_malformed_defaults_to_b(monkeypatch):
    _chat_returns(monkeypatch, '{"mode":"Z"}')
    assert _post("/api/calculators/ai/suggest-mode", {"name": "x"}).json()["data"]["mode"] == "B"


def test_mode_failure_safe_default_b_without_raw_exception(monkeypatch):
    _chat_raises(monkeypatch)
    r = _post("/api/calculators/ai/suggest-mode", {"name": "x"})
    d = r.json()["data"]
    assert d["mode"] == "B" and d["confidence"] == "low"
    assert "SECRETKEY" not in r.text and "Bearer" not in r.text


# ── 3/4. Tier2-B 감지 / Tier (step23_2, step23_3 계약) ─────────────────────

@pytest.mark.parametrize("name,desc,expected", [
    ("군인 전역일 계산기", "", True), ("D-Day 계산기", "", True), ("육아휴직", "종료일 계산", True),
    ("복무기간", "", True), ("근무 개월수", "", True), ("BMI 계산기", "체질량", False), ("", "", False),
])
def test_tier2b_keywords_server_side_rule(name, desc, expected, _no_real_ai_or_storage):
    d = _post("/api/calculators/ai/tier2b-keywords", {"name": name, "description": desc}).json()["data"]
    assert d == {"detected": expected}
    assert _no_real_ai_or_storage["chat"] == []   # AI 호출 없음


def test_tier_success_tier2b_signal(monkeypatch):
    _chat_returns(monkeypatch, '{"tier":"Tier2-B","reason":"날짜 덧셈","confidence":"low"}')
    d = _post("/api/calculators/ai/suggest-tier", {"name": "전역일 계산기"}).json()["data"]
    assert d["tier"] == "Tier2-B" and d["confidence"] == "low"
    assert d["tier_int"] == 2 and d["tier2b_suggested"] is True   # confidence와 무관(step23_2)


@pytest.mark.parametrize("tier,tier_int", [("Tier1", 1), ("Tier2-A", 2)])
def test_tier_mapping(monkeypatch, tier, tier_int):
    _chat_returns(monkeypatch, f'{{"tier":"{tier}","reason":"r","confidence":"high"}}')
    d = _post("/api/calculators/ai/suggest-tier", {"name": "x"}).json()["data"]
    assert d["tier_int"] == tier_int and d["tier2b_suggested"] is False and d["confidence"] == "high"


def test_tier_failure_fallback_without_raw_exception(monkeypatch):
    _chat_raises(monkeypatch)
    r = _post("/api/calculators/ai/suggest-tier", {"name": "x"})
    d = r.json()["data"]
    assert d["tier"] == "Tier2-A" and d["confidence"] == "low"
    assert "SECRETKEY" not in r.text


# ── 5. Spec / 필드 제안 (step24_2 계약) ─────────────────────────────────────

def test_spec_success_returns_field_keys_formula_text_and_labels(monkeypatch):
    from modules import app_factory
    seen = {}

    def _spec(cfg, name, category, desc, tier, existing, _contract=None):
        seen.update(name=name, tier=tier, existing=existing, contract=_contract)
        return ({"input_schema": {"years": "number", "wage": "number"}, "output_schema": {"pay": "number"},
                 "formula": {"pay": "years*wage"}, "labels": {"years": "근속연수"}}, [])
    monkeypatch.setattr(app_factory, "_suggest_spec", _spec)
    d = _post("/api/calculators/ai/suggest-spec", {"name": "퇴직금", "tier": "Tier1"}).json()["data"]
    assert d["input_fields"] == ["years", "wage"] and d["output_fields"] == ["pay"]
    assert d["formula"] == '{"pay": "years*wage"}' and d["labels"] == {"years": "근속연수"}
    assert seen["tier"] == 1 and seen["existing"] == [] and seen["contract"] is None


def test_spec_empty_suggestion_returns_empty_lists(monkeypatch):
    from modules import app_factory
    monkeypatch.setattr(app_factory, "_suggest_spec", lambda *a, **k: ({"input_schema": {}, "output_schema": {}}, []))
    d = _post("/api/calculators/ai/suggest-spec", {"name": "x"}).json()["data"]
    assert d == {"input_fields": [], "output_fields": [], "formula": "", "labels": {}}


def test_spec_failure_hides_raw_exception(monkeypatch):
    from modules import app_factory

    def _boom(*a, **k):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(app_factory, "_suggest_spec", _boom)
    r = _post("/api/calculators/ai/suggest-spec", {"name": "x"})
    assert r.json()["error"]["code"] == "AI_SUGGEST_FAILED"
    assert "SECRETKEY" not in r.text


# ── 6. Formula 제안 ────────────────────────────────────────────────────────

def test_formula_success_is_not_confirmation(monkeypatch):
    _chat_returns(monkeypatch, '{"formula":"a*b","reason":"곱","assumptions":["x"],"warnings":[]}')
    d = _post("/api/calculators/ai/suggest-formula",
              {"name": "x", "input_fields": ["a", "b"], "output_fields": ["r"]}).json()["data"]
    assert d["success"] is True and d["formula"] == "a*b" and d["status"] == "ai_suggested"
    assert d["status"] != "operator_confirmed" and d["assumptions"] == ["x"]


def test_formula_rejects_undefined_variable(monkeypatch):
    _chat_returns(monkeypatch, '{"formula":"a*zzz","reason":"r","assumptions":[],"warnings":[]}')
    d = _post("/api/calculators/ai/suggest-formula",
              {"name": "x", "input_fields": ["a"], "output_fields": ["r"]}).json()["data"]
    assert d["success"] is False and d["status"] == "not_generated"


def test_formula_requires_fields_without_ai_call(_no_real_ai_or_storage):
    d = _post("/api/calculators/ai/suggest-formula", {"name": "x", "input_fields": [], "output_fields": ["r"]}).json()["data"]
    assert d["success"] is False and _no_real_ai_or_storage["chat"] == []


def test_formula_ai_failure_hides_raw_exception(monkeypatch):
    _chat_raises(monkeypatch)
    r = _post("/api/calculators/ai/suggest-formula", {"name": "x", "input_fields": ["a"], "output_fields": ["r"]})
    d = r.json()["data"]
    assert d["success"] is False and d["reason"] == "AI 호출 실패" and d["warnings"] == []
    assert "SECRETKEY" not in r.text and "Bearer" not in r.text


# ── 7. Mode B slug 제안 (step26_1 계약) ─────────────────────────────────────

def test_slug_suggest_uses_generate_slug(_no_real_ai_or_storage):
    from modules.slug_generator import generate_slug
    d = _post("/api/calculators/generate/contract/slug-suggest", {"name": "퇴직금 계산기"}).json()["data"]
    assert d == {"slug": generate_slug("퇴직금 계산기")}
    assert _post("/api/calculators/generate/contract/slug-suggest", {"name": "  "}).json()["data"] == {"slug": ""}
    assert _no_real_ai_or_storage["chat"] == []


# ── 8/9. Formula 운영자 확정 / Tier2-B 자동 확정 ──────────────────────────────

@pytest.fixture
def contract_env(monkeypatch):
    """generate_app_with_contract/save_app만 대체 — build_contract/check_hold_rules/
    _run_sample_validation(validate_formula_with_samples)은 실제 코드."""
    from modules import app_factory
    saved = []

    def _gen(cfg, contract):
        return {"_contract": contract, "_contract_validation": {"valid": True, "messages": []},
                "html": "<html></html>", "tier": 2, "_formula_valid": True, "_steps": [],
                "formula": contract.get("formula"), "input_schema": {f: "number" for f in contract["input_fields"]}}

    def _save(cfg, app, slug=None):
        # 실제 save_app의 Mode B Hard-Gate와 같은 조건만 재현(쓰기 없음)
        fs = (app.get("_contract") or {}).get("formula_status")
        if fs != "operator_confirmed":
            return False, f"🔒 formula 미확정 (현재 상태: {fs})"
        saved.append(slug)
        return True, f"저장 완료: {slug}"
    monkeypatch.setattr(app_factory, "generate_app_with_contract", _gen)
    monkeypatch.setattr(app_factory, "save_app", _save)
    return saved


def _gen_contract(c, **over):
    body = {"name": "테스트", "slug": "test-calc", "tier": "Tier2-A", "input_fields": ["a", "b"],
            "output_fields": ["r"], "formula": "a*b", "test_cases": []}
    body.update(over)
    r = c.post("/api/calculators/generate/contract", headers=_h(), json=body)
    assert r.status_code == 200, r.text
    job_id = r.json()["data"]["job_id"]
    for _ in range(100):
        d = c.get(f"/api/calculators/generate/contract/{job_id}", headers=_h()).json()["data"]
        if d["status"] in ("succeeded", "failed"):
            assert d["status"] == "succeeded", d
            return job_id, d["result"]
        time.sleep(0.02)
    raise AssertionError("job timeout")


def test_confirm_without_test_cases_allows_save(contract_env):
    """Dashboard 의미: test_cases가 없어도 Level 1/2 통과 후 운영자 확정 → 저장 가능."""
    c = _client()
    job_id, res = _gen_contract(c)
    assert res["contract"]["formula_status"] == "pending_validation"
    assert any("HOLD-1" in m for m in res["hold_messages"])
    blocked = c.post(f"/api/calculators/generate/contract/{job_id}/save", headers=_h(), json={"slug": "test-calc"}).json()["data"]
    assert blocked["ok"] is False and contract_env == []

    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h()).json()["data"]
    assert d["ok"] is True and d["formula_status"] == "operator_confirmed" and d["validation"]["valid"] is True
    res2 = c.get(f"/api/calculators/generate/contract/{job_id}", headers=_h()).json()["data"]["result"]
    assert res2["contract"]["formula_status"] == "operator_confirmed"
    assert res2["app"]["_contract"]["formula_status"] == "operator_confirmed"
    assert not any("HOLD-1" in m for m in res2["hold_messages"])

    ok_ = c.post(f"/api/calculators/generate/contract/{job_id}/save", headers=_h(), json={"slug": "test-calc"}).json()["data"]
    assert ok_["ok"] is True and contract_env == ["test-calc"]


def test_confirm_rejects_invalid_formula_server_side(contract_env):
    c = _client()
    job_id, res = _gen_contract(c, formula="a*undefined_var")
    # 클라이언트가 확정 플래그/상태를 보내도 무시된다(body 없는 endpoint).
    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h(),
               json={"formula_status": "operator_confirmed", "operator_confirmed": True}).json()["data"]
    assert d["ok"] is False and d["formula_status"] != "operator_confirmed"
    res2 = c.get(f"/api/calculators/generate/contract/{job_id}", headers=_h()).json()["data"]["result"]
    assert res2["contract"]["formula_status"] != "operator_confirmed"


def test_confirm_runs_level3_when_test_cases_exist(contract_env):
    c = _client()
    job_id, res = _gen_contract(c, test_cases=[{"input": {"a": 2, "b": 3}, "expected": {"result": 7}}])
    assert res["contract"]["formula_status"] == "pending_validation"
    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h()).json()["data"]
    assert d["ok"] is False and d["validation"]["all_samples_pass"] is False


def test_existing_auto_confirm_with_passing_test_cases_kept(contract_env):
    c = _client()
    job_id, res = _gen_contract(c, test_cases=[{"input": {"a": 2, "b": 3}, "expected": {"result": 6}}])
    assert res["contract"]["formula_status"] == "operator_confirmed"
    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h()).json()["data"]
    assert d["ok"] is True


def test_confirm_requires_formula_for_non_tier2b(contract_env):
    c = _client()
    job_id, res = _gen_contract(c, formula=None)
    assert res["contract"]["formula_status"] == "not_generated"
    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h()).json()["data"]
    assert d["ok"] is False and d["formula_status"] == "not_generated"


def test_tier2b_auto_confirmed_at_generation_and_saveable(contract_env):
    """Dashboard 의미: Tier2-B는 formula 없이도 자동 operator_confirmed."""
    c = _client()
    job_id, res = _gen_contract(c, tier="Tier2-B", formula=None, input_fields=["start_date"], output_fields=["end_date"])
    assert res["contract"]["formula_status"] == "operator_confirmed"
    assert res["app"]["_contract"]["formula_status"] == "operator_confirmed"
    d = c.post(f"/api/calculators/generate/contract/{job_id}/confirm-formula", headers=_h()).json()["data"]
    assert d["ok"] is True and d["formula_status"] == "operator_confirmed" and d["validation"] is None
    ok_ = c.post(f"/api/calculators/generate/contract/{job_id}/save", headers=_h(), json={"slug": "test-calc"}).json()["data"]
    assert ok_["ok"] is True


def test_confirm_rejects_unknown_non_contract_and_running_jobs(contract_env):
    import threading
    c = _client()
    assert c.post("/api/calculators/generate/contract/nope/confirm-formula", headers=_h()).json()["error"]["code"] == "NOT_FOUND"
    from api.services.generation_job_store import get_job_store
    store = get_job_store()
    _, _, other = store.submit("preview:x", lambda: {"app": {}})
    for _ in range(100):
        if store.get(other).status == "succeeded":
            break
        time.sleep(0.02)
    assert c.post(f"/api/calculators/generate/contract/{other}/confirm-formula",
                  headers=_h()).json()["error"]["code"] == "CONTRACT_STATE_INVALID"
    gate = threading.Event()
    _, _, running = store.submit("contract:slow", lambda: (gate.wait(5), {"contract": {}})[1])
    try:
        assert c.post(f"/api/calculators/generate/contract/{running}/confirm-formula",
                      headers=_h()).json()["error"]["code"] == "CONTRACT_STATE_INVALID"
    finally:
        gate.set()


def test_no_budget_tracker_or_real_ai_used_by_suite(_no_real_ai_or_storage):
    # 이 fixture가 활성인 동안 실제 BudgetTracker 인스턴스는 생성되지 않는다.
    assert _no_real_ai_or_storage["budget"] == 0
