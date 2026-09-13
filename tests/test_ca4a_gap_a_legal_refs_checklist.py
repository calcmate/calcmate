# -*- coding: utf-8 -*-
"""tests/test_ca4a_gap_a_legal_refs_checklist.py — CA-4-A Gap A

Mode B에서 Contract 내부에 존재하는 legal_refs가
save_app() → extract_checklist() 경로에서 누락되지 않도록 연결되었는지 검증.

- Test 1: generate_app_with_contract() 결과 app["legal_refs"]에 Contract legal_refs 전달
- Test 2: legal_refs 없는 Contract → result["legal_refs"] == [] (기존 동작)
- Test 3: full chain (build_contract → generate_app_with_contract → extract_checklist)
          legal_basis 항목이 실제 법적 근거를 표시 ("미입력" 없음)
- Test 4: legal_refs 없는 app → 기존 "⚠️ legal_refs 미입력" 동작 유지 (Mode A 보호)
- Test 5: save_app() 전체 경로 — 체크리스트 저장 시 legal_refs 정상 포함

실제 AI API 호출 없음 (_chat monkeypatch), 실제 DB/Registry/instances 쓰기 없음.
실제 운영 파일(docs/registry, docs/contract_schema/instances, legal_master)에는 쓰지 않음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import modules.app_factory as af
from modules.app_factory import build_contract, generate_app_with_contract, save_app
from modules.review_center import extract_checklist
from tests.test_ca1b4_p1b_scope_exclusions_prompt import _capture_chat

# 실제 legal_master entity (severance-pay = worker_retirement_benefit_act_8, confidence=high)
SEVERANCE_PAY_REF = "worker_retirement_benefit_act_8"


def _contract(legal_refs=None, formula_status="operator_confirmed"):
    """Mode B 저장 가능(operator_confirmed) Contract fixture."""
    return build_contract(
        slug="ca4a-severance-test",
        name="CA4A 퇴직금 계산기",
        category="노무/급여",
        tier="Tier2-A",
        input_fields=["avg_monthly_wage", "total_days"],
        output_fields=["severance_pay"],
        legal_refs=legal_refs,
        formula="avg_monthly_wage * (total_days / 365) * 30",
        formula_status=formula_status,
        scope_exclusions=["근로기준법 제34조"],
    )


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


def _patch_save_side_effects(monkeypatch, checklist_spy=None):
    """save_app()의 실제 DB/Registry/파일 쓰기를 mock 처리 (extract_checklist는 실제 유지)."""
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
    monkeypatch.setattr(af, "_save_contract_instance", lambda *a, **k: None)
    monkeypatch.setattr(af, "save_af_checklist", checklist_spy or (lambda *a, **k: None))


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Mode B legal_refs 전달 (generate_app_with_contract)
# ─────────────────────────────────────────────────────────────────────────────

class TestModeBLegalRefsPropagation:

    def test_generate_app_with_contract_carries_legal_refs(self, monkeypatch):
        """Contract legal_refs가 결과 app dict에 그대로 전달된다."""
        contract = _contract(legal_refs=[SEVERANCE_PAY_REF])
        monkeypatch.setattr(af, "_chat", _capture_chat([]))
        result = generate_app_with_contract({"DB_ADAPTER": "memory"}, contract)
        assert result["legal_refs"] == [SEVERANCE_PAY_REF]

    def test_generate_app_with_contract_empty_legal_refs(self, monkeypatch):
        """legal_refs 없는 Contract → result['legal_refs'] == [] (추측 없음)."""
        contract = _contract(legal_refs=None)
        monkeypatch.setattr(af, "_chat", _capture_chat([]))
        result = generate_app_with_contract({"DB_ADAPTER": "memory"}, contract)
        assert result["legal_refs"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 2/3 — Checklist legal_refs 정상 인식 (full chain)
# ─────────────────────────────────────────────────────────────────────────────

class TestChecklistLegalRefs:

    def test_checklist_shows_real_legal_refs(self, monkeypatch):
        """build_contract → generate_app_with_contract → extract_checklist 전체 경로에서
        legal_basis 항목이 실제 법적 근거를 표시한다 ('미입력' 없음)."""
        contract = _contract(legal_refs=[SEVERANCE_PAY_REF])
        monkeypatch.setattr(af, "_chat", _capture_chat([]))
        app = generate_app_with_contract({"DB_ADAPTER": "memory"}, contract)

        items = extract_checklist(app, tier="Tier2-A", category=app.get("category", ""))
        legal = next((i for i in items if i["id"] == "legal_basis"), None)
        assert legal is not None, f"legal_basis 항목 없음: {[i['id'] for i in items]}"
        assert legal["auto_source"] == "legal_refs_present", legal
        assert SEVERANCE_PAY_REF in legal["display_value"], legal["display_value"]
        assert "미입력" not in legal["display_value"], legal["display_value"]

    def test_checklist_empty_legal_refs_keeps_existing_warning(self):
        """legal_refs 없는 app → 기존 '⚠️ legal_refs 미입력' 동작 유지 (Mode A 보호)."""
        app = {
            "name": "A", "category": "세금/세법", "formula": "a * 0.1",
            "legal_refs": [], "input_schema": {"a": "number"},
            "output_schema": {"b": "number"}, "compute_type": "formula",
            "tier": 2,
        }
        items = extract_checklist(app, tier="Tier2-A", category="세금/세법")
        legal = next(i for i in items if i["id"] == "legal_basis")
        assert legal["auto_source"] == "legal_refs_empty", legal
        assert "⚠️ legal_refs 미입력" in legal["display_value"], legal["display_value"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — save_app 전체 경로 (실제 extract_checklist 사용, 나머지 side-effect 차단)
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveAppChecklistFlow:

    def test_save_app_checklist_contains_legal_refs(self, monkeypatch):
        """save_app() → extract_checklist() 경로에서 legal_refs가 체크리스트에 포함된다."""
        saved = []
        _patch_save_side_effects(monkeypatch, checklist_spy=lambda slug, cl: saved.append((slug, cl)))

        contract = _contract(legal_refs=[SEVERANCE_PAY_REF])
        monkeypatch.setattr(af, "_chat", _capture_chat([]))
        app = generate_app_with_contract({"DB_ADAPTER": "memory"}, contract)

        ok, msg = save_app({"DB_ADAPTER": "memory"}, app, slug="ca4a-severance-test")
        assert ok, msg
        assert saved, "save_af_checklist가 호출되지 않음"
        slug, checklist = saved[0]
        assert slug == "ca4a-severance-test"
        legal = next((i for i in checklist if i["id"] == "legal_basis"), None)
        assert legal is not None, f"legal_basis 누락: {[i['id'] for i in checklist]}"
        assert legal["auto_source"] == "legal_refs_present", legal
        assert SEVERANCE_PAY_REF in legal["display_value"], legal["display_value"]
        assert "미입력" not in legal["display_value"], legal["display_value"]
