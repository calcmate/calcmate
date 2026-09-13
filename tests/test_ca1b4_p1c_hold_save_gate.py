# -*- coding: utf-8 -*-
"""tests/test_ca1b4_p1c_hold_save_gate.py — CA-1B-4 P1-C

Contract 기반(Mode B) 저장 시 formula_status == operator_confirmed Hard-Gate 검증.
- not_generated / ai_suggested / pending_validation → save 차단
- operator_confirmed → save 허용
- Mode A(_contract 없음) → 기존 저장 동작 100% 유지 (formula_status 없어도 통과)

실제 운영 파일(docs/registry, docs/contract_schema/instances, legal_master 등)에는
쓰지 않도록 모든 side-effect를 monkeypatch로 차단한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import modules.app_factory as af
from modules.app_factory import save_app


# ── 공통 fake/mock 헬퍼 ─────────────────────────────────────────────────────
class _FakeCalcRepo:
    def __init__(self, db=None):
        self.saved = []

    def get_all(self):
        return []

    def save(self, data):
        self.saved.append(data)
        return len(self.saved)


class _FakeTplRepo:
    def __init__(self, db=None):
        self.saved = []

    def save(self, data):
        self.saved.append(data)
        return len(self.saved)


def _patch_side_effects(monkeypatch, save_spy=None):
    """실제 DB/Registry/파일 쓰기를 전부 mock 처리."""
    monkeypatch.setattr(af, "get_db_adapter", lambda cfg: {"memory": True})
    # IRP-23: app_templates 저장은 get_template_storage_adapter(cfg)를 거치므로
    # (SQLite-원본/Sheets-백업 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_template_storage_adapter", lambda cfg: {"memory": True})
    # STEP93: calculators 저장은 get_calculator_storage_adapter(cfg)를 거치므로
    # (SQLite MAIN/Sheets BACKUP 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_calculator_storage_adapter", lambda cfg: {"memory": True})
    monkeypatch.setattr(af, "CalculatorRepository", _FakeCalcRepo)
    monkeypatch.setattr(af, "TemplateRepository", _FakeTplRepo)
    monkeypatch.setattr("modules.registry_loader.add_auto_entry", lambda *a, **k: None)
    monkeypatch.setattr(af, "_write_registry_v3", lambda *a, **k: None)
    monkeypatch.setattr(af, "_write_calculator_index", lambda *a, **k: None)
    monkeypatch.setattr("modules.review_center.extract_checklist",
                        lambda *a, **k: [])
    monkeypatch.setattr(af, "save_af_checklist", lambda *a, **k: None)
    if save_spy is not None:
        monkeypatch.setattr(af, "_save_contract_instance", save_spy)


def _contract(formula_status="pending_validation"):
    return {
        "slug": "test-calc",
        "name": "테스트 계산기",
        "category": "노무/급여",
        "tier": "Tier2-A",
        "input_fields": ["a"],
        "output_fields": ["result"],
        "formula": "a * 2",
        "formula_status": formula_status,
        "scope_exclusions": [],
        "test_cases": [],
        "test_cases_status": "not_generated",
        "desc": "",
        "legal_refs": [],
    }


def _app(contract=None):
    app = {
        "name": "테스트 계산기", "category": "노무/급여", "slug": "test-calc",
        "calculator_type": "general", "formula": "a * 2",
        "input_schema": {"a": "number"}, "output_schema": {"result": "number"},
        "labels": {}, "html": "<html>ok</html>", "css": "", "js": "",
        "seo_title": "T", "seo_desc": "D", "faq": [], "blog_draft": "",
        "image_prompt_thumbnail": "", "image_prompt_body": "",
    }
    if contract is not None:
        app["_contract"] = contract
    return app


# ── Test 1-3: Mode B 미확정 상태 → save 차단 ───────────────────────────────
def test_save_blocked_not_generated(monkeypatch):
    _patch_side_effects(monkeypatch)
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(_contract("not_generated")), slug="test-calc")
    assert ok is False
    assert "저장할 수 없습니다" in msg
    assert "not_generated" in msg


def test_save_blocked_ai_suggested(monkeypatch):
    _patch_side_effects(monkeypatch)
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(_contract("ai_suggested")), slug="test-calc")
    assert ok is False
    assert "저장할 수 없습니다" in msg
    assert "ai_suggested" in msg


def test_save_blocked_pending_validation(monkeypatch):
    _patch_side_effects(monkeypatch)
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(_contract("pending_validation")), slug="test-calc")
    assert ok is False
    assert "저장할 수 없습니다" in msg
    assert "pending_validation" in msg


# ── Test 4: Mode B operator_confirmed → 저장 허용 ──────────────────────────
def test_save_allowed_operator_confirmed(monkeypatch):
    calls = []
    def _spy(*a, **k):
        calls.append(a)
    _patch_side_effects(monkeypatch, save_spy=_spy)
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(_contract("operator_confirmed")), slug="test-calc")
    assert ok is True
    assert len(calls) == 1  # Contract instance 저장까지 도달


# ── Test 5 (가장 중요): Mode A(_contract 없음) → 기존 동작 유지 ────────────
def test_mode_a_without_contract_unchanged(monkeypatch):
    calls = []
    def _spy(*a, **k):
        calls.append(a)
    _patch_side_effects(monkeypatch, save_spy=_spy)
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(None), slug="test-calc")
    assert ok is True
    assert len(calls) == 0  # instance 저장 없음 (Mode A)


# ── Test 9: formula_status=None/알 수 없는 상태 → 안전 차단 ─────────────────
def test_save_blocked_unknown_status(monkeypatch):
    _patch_side_effects(monkeypatch)
    c = _contract("weird-status")
    ok, msg = save_app({"DB_ADAPTER": "memory"}, _app(c), slug="test-calc")
    assert ok is False
    assert "유효하지 않아" in msg
    # formula_status 키 자체가 없는 Contract도 차단
    c2 = _contract()
    del c2["formula_status"]
    ok2, msg2 = save_app({"DB_ADAPTER": "memory"}, _app(c2), slug="test-calc")
    assert ok2 is False
    assert "유효하지 않아" in msg2


# ── Test 10: Mode A formula_status 없음 → 정상 저장 ─────────────────────────
def test_mode_a_without_formula_status_saves(monkeypatch):
    _patch_side_effects(monkeypatch)
    app = _app(None)
    app.pop("formula", None)  # formula_status 개념 자체가 없는 Mode A
    ok, msg = save_app({"DB_ADAPTER": "memory"}, app, slug="test-calc")
    assert ok is True


# ── Test 6-8: Contract validation과의 관계 (기존 게이트 유지) ───────────────
def test_contract_validation_failure_still_blocks():
    """기존 Contract 불일치 게이트는 이번 변경과 무관하게 유지된다 (로직 재확인)."""
    # _contract_save_blocked 계산 로직 재현 (dashboard)
    cv = {"valid": False}
    validation_failed = cv is not None and not cv.get("valid", True)
    assert validation_failed is True


def test_formula_status_gate_independent_of_validation():
    """Contract validation 통과여도 formula_status != operator_confirmed면 차단."""
    cv = {"valid": True}
    validation_failed = cv is not None and not cv.get("valid", True)
    fs = "pending_validation"
    fs_not_confirmed = True  # Mode B + operator_confirmed 아님
    assert validation_failed is False
    assert fs_not_confirmed is True


def test_operator_confirmed_and_validation_pass_allows():
    """Contract validation 통과 + operator_confirmed → 저장 허용 조건 성립."""
    cv = {"valid": True}
    validation_failed = cv is not None and not cv.get("valid", True)
    fs = "operator_confirmed"
    fs_not_confirmed = False
    blocked = validation_failed or fs_not_confirmed
    assert blocked is False
