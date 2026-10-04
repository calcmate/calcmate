# -*- coding: utf-8 -*-
"""tests/test_contract_generation.py — P0-5: Mode B(Contract 기반 생성) + 실제 샘플
기대값 검증 React/FastAPI 이관.

dashboard.py "📋 Contract 기반 생성" 버튼과 동일한 backend 함수(modules.app_factory.
build_contract/check_hold_rules/generate_app_with_contract/save_app,
modules.formula_engine.validate_formula_with_samples,
modules.review_center.check_slug_conflict)를 검증한다.

안전 설계: modules.app_factory.generate_app_with_contract()/save_app()의 실제 구현은
이 파일의 어떤 테스트에서도 실행하지 않는다 — 항상 monkeypatch로 대체한다(신규
계산기 생성/Registry 변경 없음). validate_formula_with_samples()만은 실제 순수 함수를
그대로 사용한다(AI 호출이 없는 결정적 계산이므로 안전 — 이것이 이 STEP의 핵심 검증
대상이다). Job store는 매 테스트마다 새로 생성한다(test_step_4h5_calculator_generate.py
와 동일한 패턴 재사용).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

VIEWER_TOKEN = "contract-gen-test-viewer-token"
ADMIN_TOKEN = "contract-gen-test-admin-token"
_ROOT = Path(__file__).resolve().parent.parent


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def _fresh_job_store():
    import api.services.generation_job_store as job_store_module
    job_store_module._store = None
    yield
    if job_store_module._store is not None:
        job_store_module._store.shutdown(wait=True)
        job_store_module._store = None


@pytest.fixture(autouse=True)
def _never_touch_real_config_loader(monkeypatch):
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


FAKE_CONTRACT_BODY = {
    "name": "가짜 연차 계산기", "category": "노무/급여", "description": "테스트용",
    "tier": "Tier2-A", "slug": "fake-contract-slug",
    "input_fields": ["years_of_service", "used_days"],
    "output_fields": ["total_days", "remaining_days"],
    # dict formula의 각 출력 키는 input_schema 변수만 참조 가능(다른 출력 키 참조 불가
    # — modules.formula_engine.validate_formula()의 실제 제약, 실측으로 확인됨).
    "formula": {"total_days": "min(15 + max(0, (years_of_service - 1) // 2), 25)",
                "remaining_days": "min(15 + max(0, (years_of_service - 1) // 2), 25) - used_days"},
    "test_cases": [
        {"input": {"years_of_service": 1, "used_days": 0}, "expected": {"total_days": 15, "remaining_days": 15}},
        {"input": {"years_of_service": 3, "used_days": 5}, "expected": {"total_days": 16, "remaining_days": 11}},
    ],
}

FAKE_APP_RESULT = {
    "name": FAKE_CONTRACT_BODY["name"], "tier": 2, "_tokens": 100,
    "_formula_valid": True, "_formula_msg": "", "_steps": [("spec", "ok")],
    "html": ('<html><body><input id="a"><button onclick="c()">계산</button>'
             '<script>function c(){}</script></body></html>'),
    "seo_title": "t", "faq": [],
    "formula": FAKE_CONTRACT_BODY["formula"],
    "input_schema": {"years_of_service": "number", "used_days": "number"},
    "output_schema": {"total_days": "number", "remaining_days": "number"},
    "slug": FAKE_CONTRACT_BODY["slug"],
}


def _mock_generate_success(monkeypatch, contract_validation_valid=True, formula_override=None):
    def _fake_generate_with_contract(cfg, contract):
        app = dict(FAKE_APP_RESULT)
        if formula_override is not None:
            app["formula"] = formula_override
        app["_contract"] = contract
        app["_contract_validation"] = {
            "valid": contract_validation_valid,
            "slug_mismatch": False, "slug_contract": contract["slug"], "slug_ai": contract["slug"],
            "schema_drift": {"drifted": False, "changes": []},
            "formula_changed": not contract_validation_valid,
            "messages": [] if contract_validation_valid else ["formula 변경: AI가 Contract 확정 formula를 수정했습니다"],
        }
        return app

    monkeypatch.setattr("modules.app_factory.generate_app_with_contract", _fake_generate_with_contract)
    monkeypatch.setattr("modules.app_factory.check_hold_rules", lambda contract: {"held": False, "rules": [], "messages": []})


def _mock_save_success(monkeypatch):
    monkeypatch.setattr("modules.app_factory.save_app",
                         lambda cfg, app, site_id="", slug=None: (True, f"✅ 저장 완료(mock): {slug}"))


def _mock_save_blocked(monkeypatch, message="🔒 Contract Formula 상태가 유효하지 않아 저장할 수 없습니다."):
    monkeypatch.setattr("modules.app_factory.save_app", lambda cfg, app, site_id="", slug=None: (False, message))


def _wait_for_terminal(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/calculators/generate/contract/{job_id}", headers=_auth(ADMIN_TOKEN))
        data = r.json()["data"]
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id}이 {timeout}초 내에 종료 상태에 도달하지 못함")


# ══════════════════════════════════════════════════════════════════════════
# validate_formula_with_samples() 실제 연결 — 순수 함수, 실제 구현 그대로 사용
# ══════════════════════════════════════════════════════════════════════════

class TestValidateContractFormula:
    def test_all_samples_pass_yields_operator_confirmed(self):
        import api.services.calculator_service as svc
        result = svc.validate_contract_formula(
            FAKE_CONTRACT_BODY["formula"], FAKE_CONTRACT_BODY["input_fields"],
            FAKE_CONTRACT_BODY["test_cases"])
        assert result["valid"] is True
        assert result["all_samples_pass"] is True
        assert result["formula_status"] == "operator_confirmed"
        assert len(result["sample_results"]) == 2
        assert all(s["match"] is True for s in result["sample_results"])

    def test_mismatched_expected_value_fails_sample(self):
        """실제 formula 실행 → 기대값 비교가 진짜로 이루어지는지 확인(핵심 요구사항).
        의도적으로 틀린 expected 값을 사용해 sample 3이 FAIL해야 한다."""
        import api.services.calculator_service as svc
        bad_test_cases = [
            {"input": {"years_of_service": 1, "used_days": 0}, "expected": {"total_days": 15, "remaining_days": 15}},
            {"input": {"years_of_service": 3, "used_days": 5}, "expected": {"total_days": 20, "remaining_days": 20}},
        ]
        result = svc.validate_contract_formula(
            FAKE_CONTRACT_BODY["formula"], FAKE_CONTRACT_BODY["input_fields"], bad_test_cases)
        assert result["valid"] is True  # AST/schema 자체는 유효(Level 1/2)
        assert result["all_samples_pass"] is False  # 기대값 불일치(Level 3)
        assert result["formula_status"] == "pending_validation"
        failed = [s for s in result["sample_results"] if s["match"] is False]
        assert len(failed) == 1
        assert failed[0]["expected"] == {"total_days": 20, "remaining_days": 20}
        assert failed[0]["output"] == {"total_days": 16, "remaining_days": 11}

    def test_invalid_formula_syntax_fails_before_samples(self):
        import api.services.calculator_service as svc
        result = svc.validate_contract_formula(
            "this is not valid( formula", ["a"], [{"input": {"a": 1}, "expected": {"result": 1}}])
        assert result["valid"] is False
        assert result["formula_status"] == "formula_invalid"
        assert result["sample_results"] == []

    def test_no_test_cases_yields_pending_validation_not_confirmed(self):
        """test_cases가 없으면 formula가 유효해도 operator_confirmed가 될 수 없다
        (샘플 기대값 검증 자체가 이루어지지 않았으므로)."""
        import api.services.calculator_service as svc
        result = svc.validate_contract_formula(FAKE_CONTRACT_BODY["formula"],
                                                FAKE_CONTRACT_BODY["input_fields"], [])
        assert result["formula_status"] == "pending_validation"


# ══════════════════════════════════════════════════════════════════════════
# slug 중복 확인
# ══════════════════════════════════════════════════════════════════════════

class TestSlugCheck:
    def test_conflict_detected(self, monkeypatch):
        import api.services.calculator_service as svc
        monkeypatch.setattr("modules.review_center.check_slug_conflict",
                             lambda slug, cfg: (slug, True, f"'{slug}' 슬러그가 이미 존재합니다."))
        result = svc.check_contract_slug_conflict("annual-leave-remaining")
        assert result["conflict"] is True

    def test_no_conflict(self, monkeypatch):
        import api.services.calculator_service as svc
        monkeypatch.setattr("modules.review_center.check_slug_conflict",
                             lambda slug, cfg: (slug, False, ""))
        result = svc.check_contract_slug_conflict("brand-new-unused-slug")
        assert result["conflict"] is False


# ══════════════════════════════════════════════════════════════════════════
# Contract 생성 Job — Formula Hard Gate/Contract 검증과의 관계
# ══════════════════════════════════════════════════════════════════════════

class TestSubmitContractGeneration:
    def test_generation_succeeds_and_confirms_formula_status_serverside(self, monkeypatch):
        """클라이언트가 확정했다고 주장하지 않아도, 서버가 실제 샘플 검증을 재실행해
        operator_confirmed를 스스로 계산해야 한다(핵심 보안 요구사항)."""
        import api.services.calculator_service as svc
        _mock_generate_success(monkeypatch)
        client = _client()
        r = client.post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY,
                         headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        job_id = r.json()["data"]["job_id"]
        data = _wait_for_terminal(client, job_id)
        assert data["status"] == "succeeded"
        result = data["result"]
        assert result["contract"]["formula_status"] == "operator_confirmed"
        assert result["formula_valid"] is True
        assert result["contract_validation"]["valid"] is True
        assert result["post_generation_sample_validation"]["all_samples_pass"] is True

    def test_generation_with_bad_test_cases_does_not_confirm(self, monkeypatch):
        import api.services.calculator_service as svc
        _mock_generate_success(monkeypatch)
        body = dict(FAKE_CONTRACT_BODY)
        body["test_cases"] = [
            {"input": {"years_of_service": 1, "used_days": 0}, "expected": {"total_days": 999, "remaining_days": 999}},
        ]
        client = _client()
        r = client.post("/api/calculators/generate/contract", json=body, headers=_auth(ADMIN_TOKEN))
        job_id = r.json()["data"]["job_id"]
        data = _wait_for_terminal(client, job_id)
        result = data["result"]
        assert result["contract"]["formula_status"] != "operator_confirmed"

    def test_contract_drift_surfaced_in_result(self, monkeypatch):
        import api.services.calculator_service as svc
        _mock_generate_success(monkeypatch, contract_validation_valid=False)
        client = _client()
        r = client.post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY,
                         headers=_auth(ADMIN_TOKEN))
        job_id = r.json()["data"]["job_id"]
        data = _wait_for_terminal(client, job_id)
        assert data["result"]["contract_validation"]["valid"] is False

    def test_busy_returns_409(self, monkeypatch):
        _mock_generate_success(monkeypatch)

        def _slow_generate(cfg, contract):
            time.sleep(0.3)
            app = dict(FAKE_APP_RESULT)
            app["_contract"] = contract
            app["_contract_validation"] = {"valid": True}
            return app
        monkeypatch.setattr("modules.app_factory.generate_app_with_contract", _slow_generate)
        monkeypatch.setattr("modules.app_factory.check_hold_rules", lambda c: {"held": False, "rules": [], "messages": []})

        client = _client()
        r1 = client.post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY, headers=_auth(ADMIN_TOKEN))
        assert r1.status_code == 200
        r2 = client.post("/api/calculators/generate/contract",
                          json={**FAKE_CONTRACT_BODY, "slug": "another-fake-slug"},
                          headers=_auth(ADMIN_TOKEN))
        assert r2.status_code == 409
        _wait_for_terminal(client, r1.json()["data"]["job_id"])

    def test_without_auth_returns_401(self):
        r = _client().post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY)
        assert r.status_code == 401

    def test_as_viewer_returns_403(self):
        r = _client().post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY,
                            headers=_auth(VIEWER_TOKEN))
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# 저장 차단 — Formula Hard Gate(save_app 내부) + Contract 불일치(신규 서버측 확인)
# ══════════════════════════════════════════════════════════════════════════

class TestSubmitContractSave:
    def _generate_job(self, client, monkeypatch, **mock_kwargs):
        _mock_generate_success(monkeypatch, **mock_kwargs)
        r = client.post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY, headers=_auth(ADMIN_TOKEN))
        job_id = r.json()["data"]["job_id"]
        _wait_for_terminal(client, job_id)
        return job_id

    def test_save_succeeds_when_all_gates_pass(self, monkeypatch):
        client = _client()
        job_id = self._generate_job(client, monkeypatch)
        _mock_save_success(monkeypatch)
        r = client.post(f"/api/calculators/generate/contract/{job_id}/save",
                         json={"slug": FAKE_CONTRACT_BODY["slug"]}, headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["ok"] is True

    def test_save_blocked_by_contract_drift(self, monkeypatch):
        """Contract 불일치(_contract_validation.valid=False)는 Streamlit에서 disabled
        버튼으로만 막던 것 — 서버가 실제로 차단하는지 확인(핵심 보안 요구사항)."""
        client = _client()
        job_id = self._generate_job(client, monkeypatch, contract_validation_valid=False)
        save_called = []
        monkeypatch.setattr("modules.app_factory.save_app",
                             lambda cfg, app, site_id="", slug=None: save_called.append(1) or (True, "unused"))
        r = client.post(f"/api/calculators/generate/contract/{job_id}/save",
                         json={"slug": FAKE_CONTRACT_BODY["slug"]}, headers=_auth(ADMIN_TOKEN))
        body = r.json()["data"]
        assert body["ok"] is False
        assert "Contract 불일치" in body["blocked_reason"]
        assert save_called == [], "Contract 불일치 시 save_app()을 호출하면 안 된다"

    def test_save_blocked_by_formula_not_confirmed_hard_gate(self, monkeypatch):
        """save_app() 자체의 operator_confirmed Hard-Gate(CA-1B-4 P1-C, 기존 로직)가
        여전히 작동하는지 확인 — 이 STEP에서 이 게이트를 만들거나 바꾸지 않았다."""
        client = _client()
        job_id = self._generate_job(client, monkeypatch)
        _mock_save_blocked(monkeypatch)
        r = client.post(f"/api/calculators/generate/contract/{job_id}/save",
                         json={"slug": FAKE_CONTRACT_BODY["slug"]}, headers=_auth(ADMIN_TOKEN))
        body = r.json()["data"]
        assert body["ok"] is False
        assert "저장할 수 없습니다" in body["blocked_reason"]

    def test_save_blocked_when_job_not_found(self, monkeypatch):
        r = _client().post("/api/calculators/generate/contract/no-such-job/save",
                            json={"slug": "x"}, headers=_auth(ADMIN_TOKEN))
        assert r.json()["success"] is False

    def test_save_blocked_when_job_not_yet_succeeded(self, monkeypatch):
        def _slow_generate(cfg, contract):
            time.sleep(1)
            app = dict(FAKE_APP_RESULT)
            app["_contract"] = contract
            app["_contract_validation"] = {"valid": True}
            return app
        monkeypatch.setattr("modules.app_factory.generate_app_with_contract", _slow_generate)
        monkeypatch.setattr("modules.app_factory.check_hold_rules", lambda c: {"held": False, "rules": [], "messages": []})

        client = _client()
        r = client.post("/api/calculators/generate/contract", json=FAKE_CONTRACT_BODY, headers=_auth(ADMIN_TOKEN))
        job_id = r.json()["data"]["job_id"]
        r2 = client.post(f"/api/calculators/generate/contract/{job_id}/save",
                          json={"slug": FAKE_CONTRACT_BODY["slug"]}, headers=_auth(ADMIN_TOKEN))
        body = r2.json()["data"]
        assert body["ok"] is False
        _wait_for_terminal(client, job_id, timeout=3)

    def test_without_auth_returns_401(self):
        r = _client().post("/api/calculators/generate/contract/some-job/save", json={"slug": "x"})
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# route 등록 확인 + Registry 무손상
# ══════════════════════════════════════════════════════════════════════════

def test_contract_write_routes_registered():
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert ("/api/calculators/generate/contract/slug-check", "POST") in write_paths
    assert ("/api/calculators/generate/contract/validate", "POST") in write_paths
    assert ("/api/calculators/generate/contract", "POST") in write_paths
    assert ("/api/calculators/generate/contract/{job_id}/save", "POST") in write_paths


def test_real_registry_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
