# -*- coding: utf-8 -*-
"""tests/test_step_4h7_formula_hard_gate.py — STEP 4-H-7: Mode A Formula Hard Gate.

진단 결론(STEP 4-H-7): modules.formula_engine.validate_formula()는 이미
modules.app_factory._suggest_spec()을 통해 generate_app() 내부에서 호출되고
있었고, 그 결과가 app["_formula_valid"]/app["_formula_msg"]에 담겨 반환되고
있었다. dashboard.py의 Mode A 수동 저장 경로는 이 값을 화면 경고로 보여주고
사람이 판단해 저장하지만(운영자 검토 존재), STEP 4-H-5의 자동 API 경로
(api.services.calculator_service.submit_calculator_generation)는 이 값을
전혀 확인하지 않고 그대로 save_app()을 호출했다 — 검증되지 않은 formula가
저장 단계까지 통과할 수 있는 공백이었다.

수정: submit_calculator_generation()의 target 클로저에 한 줄 체크만 추가해
app["_formula_valid"]가 False면 save_app()을 호출하지 않고 즉시 실패 처리한다.
새 formula parser/validator는 만들지 않았다 — 이미 계산되어 있던 값을 처음으로
"확인"하기만 한다.

이 파일은 두 계층을 검증한다.
1. Unit: 실제 modules.formula_engine.validate_formula()가 각 실패 유형을 실제로
   어떻게 분류하는지(AI 호출 없는 순수 함수 — mock 불필요).
2. Integration: STEP 4-H-5와 동일하게 modules.app_factory.generate_app()/
   save_app()을 완전히 대체(mock)한 상태로, HTTP 계층까지 통해 Hard Gate가
   save_app() 호출을 실제로 막는지 확인한다(STEP 4-H-4 사고 재발 방지 설계를
   그대로 계승 — 실제 파일 시스템 접근 코드 경로 자체가 실행되지 않는다).

실제 AI API 호출 없음. 실제 Registry/DB/config 파일 접근 없음(전부 mock).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from modules.formula_engine import validate_formula

VIEWER_TOKEN = "step4h7-test-viewer-token"
ADMIN_TOKEN = "step4h7-test-admin-token"


# ══════════════════════════════════════════════════════════════════════════
# 1) Unit — 실제 validate_formula()가 각 실패 유형을 실제로 분류하는지
#    (AI 호출 없음, 순수 함수, mock 불필요)
# ══════════════════════════════════════════════════════════════════════════

class TestValidateFormulaRealClassification:
    """generate_app()이 실제로 만들 수 있는 formula 문법(단일 산술 표현식,
    input_schema 변수 + min/max/round/abs/int/float만 허용)을 기준으로
    실제 실패 케이스를 검증한다."""

    def test_a_formula_none_is_invalid(self):
        ok, msg = validate_formula(None, {"a": "number"})
        assert ok is False
        assert msg

    def test_b_empty_formula_is_invalid(self):
        ok, msg = validate_formula("", {"a": "number"})
        assert ok is False

    def test_c_syntax_error_is_invalid(self):
        ok, msg = validate_formula("a +", {"a": "number"})
        assert ok is False

    def test_d_unknown_variable_is_invalid(self):
        ok, msg = validate_formula("unknown_field * 100", {"a": "number"})
        assert ok is False
        assert "unknown_field" in msg

    def test_e_division_by_zero_at_dummy_eval_is_invalid(self):
        """더미값은 모든 변수=1.0이므로, 상수 0으로 나누는 식은 dummy 실행 단계에서
        바로 실패해야 한다(실행 불가능한 formula의 실제 사례)."""
        ok, msg = validate_formula("a / 0", {"a": "number"})
        assert ok is False

    def test_e2_disallowed_syntax_is_invalid(self):
        """허용되지 않은 구문(속성 접근 등)도 실행 불가 formula로 분류되어야 한다."""
        ok, msg = validate_formula("a.__class__", {"a": "number"})
        assert ok is False

    def test_g_normal_formula_is_valid(self):
        ok, msg = validate_formula("a * 0.1 + b", {"a": "number", "b": "number"})
        assert ok is True

    def test_g2_normal_multi_output_formula_is_valid(self):
        ok, msg = validate_formula(
            {"total": "a + b", "avg": "round((a + b) / 2, 2)"},
            {"a": "number", "b": "number"},
        )
        assert ok is True

    def test_g3_normal_formula_with_whitelisted_funcs_is_valid(self):
        ok, msg = validate_formula("min(max(a, 0), 100)", {"a": "number"})
        assert ok is True


# ══════════════════════════════════════════════════════════════════════════
# 2) Integration — HTTP 계층을 통한 Hard Gate 검증
#    (STEP 4-H-5와 동일하게 generate_app/save_app을 완전히 mock — 실제 파일
#    시스템 접근 코드 경로 자체가 실행되지 않는다)
# ══════════════════════════════════════════════════════════════════════════

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


def _block_external_http(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise AssertionError("Formula Hard Gate 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


def _mock_generate(monkeypatch, *, formula_valid=True, formula_msg="OK", extra=None):
    def _fake_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        base = {
            "name": name, "category": category, "description": desc, "tier": tier,
            "formula": "a", "input_schema": {"a": "number"}, "output_schema": {"b": "number"},
            # P0-1 HTML/JS 완결성 게이트를 통과하는 최소-완결 HTML(input+button+script,
            # </html> 존재) — 이 파일은 Formula Hard Gate 자체를 테스트하는 것이라
            # HTML 완결성 검증에서 걸리면 안 된다.
            "html": ('<html><body><input id="a">'
                     '<button onclick="c()">계산</button>'
                     '<script>function c(){}</script></body></html>'),
            "seo_title": "", "seo_desc": "", "faq": [],
            "_formula_valid": formula_valid, "_formula_msg": formula_msg,
        }
        if extra:
            base.update(extra)
        return base

    monkeypatch.setattr("modules.app_factory.generate_app", _fake_generate)


def _mock_generate_failure(monkeypatch, message="AI 생성 실패(mock)"):
    def _boom(cfg, name, category="", desc="", tier=2, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr("modules.app_factory.generate_app", _boom)


def _mock_save(monkeypatch, *, ok=True, message="✅ 저장 완료(mock)"):
    calls = []

    def _fake_save(cfg, app, site_id="", slug=None):
        calls.append(app.get("name"))
        return ok, message

    monkeypatch.setattr("modules.app_factory.save_app", _fake_save)
    return calls


def _wait_for_terminal(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/calculators/generate/{job_id}", headers=_auth(ADMIN_TOKEN))
        data = r.json()["data"]
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id}이 {timeout}초 내에 종료 상태에 도달하지 못함")


def _submit(client, name="테스트계산기"):
    r = client.post("/api/calculators/generate", json={"name": name}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()["data"]["job_id"]


# ── Test 1 — 정상 formula ────────────────────────────────────────────────

def test_1_valid_formula_passes_gate_and_saves(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate(monkeypatch, formula_valid=True, formula_msg="OK")
    save_calls = _mock_save(monkeypatch, ok=True, message="✅ 저장 완료")

    c = _client()
    job_id = _submit(c, name="정상포뮬러계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "succeeded"
    assert final["result"]["name"] == "정상포뮬러계산기"
    assert save_calls == ["정상포뮬러계산기"]


# ── Test 2 — formula 누락 ────────────────────────────────────────────────

def test_2_missing_formula_blocks_save(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate(
        monkeypatch, formula_valid=False, formula_msg="formula 없음",
        extra={"formula": None},
    )
    save_calls = _mock_save(monkeypatch)

    c = _client()
    job_id = _submit(c, name="포뮬러누락계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "formula" in final["error"]
    assert final["result"] is None
    assert save_calls == []


# ── Test 3 — invalid formula(문법 오류) ──────────────────────────────────

def test_3_invalid_syntax_formula_blocks_save(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate(
        monkeypatch, formula_valid=False, formula_msg="invalid syntax",
        extra={"formula": "a +"},
    )
    save_calls = _mock_save(monkeypatch)

    c = _client()
    job_id = _submit(c, name="문법오류계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "invalid syntax" in final["error"] or "formula" in final["error"]
    assert save_calls == []


# ── Test 4 — 실행 불가 formula ────────────────────────────────────────────

def test_4_unexecutable_formula_blocks_save(monkeypatch):
    _block_external_http(monkeypatch)
    _mock_generate(
        monkeypatch, formula_valid=False,
        formula_msg="input_schema에 없는 변수: unknown_field",
        extra={"formula": "unknown_field * 100"},
    )
    save_calls = _mock_save(monkeypatch)

    c = _client()
    job_id = _submit(c, name="실행불가계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "unknown_field" in final["error"]
    assert save_calls == []


# ── Test 5 — generate_app 자체 실패 ───────────────────────────────────────

def test_5_generate_app_failure_skips_gate_and_save(monkeypatch):
    """generate_app() 자체가 실패하면 Formula Gate 평가 자체가 필요 없다 —
    save_app이 호출되지 않아야 한다(Formula Gate 실패와 혼동하지 않는다)."""
    _block_external_http(monkeypatch)
    _mock_generate_failure(monkeypatch, message="AI 호출 실패(mock)")
    save_calls = _mock_save(monkeypatch)

    c = _client()
    job_id = _submit(c, name="생성자체실패계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "AI 호출 실패" in final["error"]
    assert "formula" not in final["error"].lower()  # Gate 메시지와 혼동되지 않음
    assert save_calls == []


# ── Test 6 — save_app 실패(Formula는 PASS) ────────────────────────────────

def test_6_save_app_failure_after_formula_pass_is_not_confused_with_gate(monkeypatch):
    """formula는 PASS했고 save_app()도 실제로 호출됐지만, save_app() 자체가
    (False, msg)를 반환하는 경우 — Formula Gate 실패와 구분되어야 한다."""
    _block_external_http(monkeypatch)
    _mock_generate(monkeypatch, formula_valid=True, formula_msg="OK")
    save_calls = _mock_save(monkeypatch, ok=False, message="중복 계산기명: 이미 등록됨")

    c = _client()
    job_id = _submit(c, name="저장실패계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    assert "중복 계산기명" in final["error"]
    assert save_calls == ["저장실패계산기"]  # save_app이 실제로 호출은 됐음(Gate는 통과했으므로)


# ── secret 노출 검증 ──────────────────────────────────────────────────────

def test_no_secrets_leak_when_formula_gate_blocks(monkeypatch):
    _block_external_http(monkeypatch)
    secret_marker = "sk-should-never-leak-step4h7"
    monkeypatch.setattr(
        "modules.config_loader.load_config",
        lambda *a, **k: {"OPENAI_API_KEY": secret_marker},
    )

    def _fake_generate(cfg, name, category="", desc="", tier=2, **kwargs):
        assert cfg.get("OPENAI_API_KEY") == secret_marker
        return {
            "name": name, "category": category, "formula": None,
            "input_schema": {}, "output_schema": {},
            "_formula_valid": False, "_formula_msg": "formula 없음",
        }

    monkeypatch.setattr("modules.app_factory.generate_app", _fake_generate)
    _mock_save(monkeypatch)

    c = _client()
    job_id = _submit(c, name="보안테스트계산기")
    final = _wait_for_terminal(c, job_id)

    assert final["status"] == "failed"
    dumped = str(final)
    assert secret_marker not in dumped


# ── 인증/보안 회귀 ────────────────────────────────────────────────────────

def test_generate_still_requires_admin_after_gate_added(monkeypatch):
    _block_external_http(monkeypatch)
    r = _client().post(
        "/api/calculators/generate", json={"name": "x"}, headers=_auth(VIEWER_TOKEN)
    )
    assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# 운영 Registry/DB/config 불변 (실측)
# ══════════════════════════════════════════════════════════════════════════

_ROOT = Path(__file__).resolve().parent.parent


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


def _file_mtime(rel_path):
    p = _ROOT / rel_path
    return p.stat().st_mtime if p.exists() else None


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()
_BEFORE_CONFIG_MTIME = _file_mtime("config/config.yaml")
_BEFORE_DB_MTIME = _file_mtime("data/blog_auto.db")


def test_real_registry_unchanged_by_this_test_file():
    """이 테스트 파일의 어떤 테스트도 실제 운영 Registry/config/DB를 건드리지
    않았어야 한다 — '이 파일 실행 전후로 완전히 동일해야 한다'를 확인한다."""
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
    assert _file_mtime("config/config.yaml") == _BEFORE_CONFIG_MTIME, "운영 config.yaml mtime 변경됨"
    assert _file_mtime("data/blog_auto.db") == _BEFORE_DB_MTIME, "운영 DB mtime 변경됨"
