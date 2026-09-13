# -*- coding: utf-8 -*-
"""tests/test_step_4h3_app_factory_diagnosis.py — STEP 4-H-3 App Factory 진단에서
발견한 P0 문제 재현 + 수정 검증.

P0-1 (고아 레코드 영구 잠금): save_app()이 DB 저장(calculators/app_templates)에는
성공했지만 v3 Registry 기록([Step B])에서 실패하면, 계산기는 DB에만 남아 계산기
관리 화면/FastAPI 어디에도 보이지 않는 "고아" 상태가 된다. 이 상태에서 동일
slug로 재시도하면 "이미 등록됨(DB)"에 막혀 영구히 복구 불가능했다.
→ 수정: save_app()이 이 상태를 감지해 고아 레코드를 자동 정리한 뒤 재시도를
  허용한다(modules/app_factory.py save_app()).

P0-2 (Legal Hold 우회): 체크리스트 자동 추출/저장([Step C])이 예외로 실패하면
review_checklist가 비어 있는 채로 남는데, promote_to_ready()는 체크리스트가
비어 있으면(`if checklist:`) critical 미완료 검사 자체를 건너뛰어 아무 법적
검토 없이 READY 승격이 가능했다.
→ 수정: Step C 실패 시 승격을 계속 차단하는 폴백 critical 항목을 대신 기록한다
  (promote_to_ready() 자체는 이번 STEP에서 변경하지 않음).

실제 AI API 호출 없음(_chat monkeypatch로 대체), 실제 DB/Registry에는 쓰지 않음
(전부 fake repo + monkeypatch, promote_to_ready() 검증만 tmp_path 격리 registry 사용).
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import yaml

import modules.app_factory as af
from modules.app_factory import generate_app, save_app, promote_to_ready
from tests.test_ca1b4_p1b_scope_exclusions_prompt import _capture_chat

CFG = {"DB_ADAPTER": "memory"}


class _FakeDb:
    """app_templates 삭제 호출만 기록하는 최소 대역(save_app이 DB 삭제 시 쓰는 경로)."""

    def __init__(self):
        self.deleted = []

    def delete(self, table, id_):
        self.deleted.append((table, id_))


def _make_fake_calc_repo(shared_rows):
    """shared_rows(dict)를 상태 저장소로 공유하는 CalculatorRepository 대역.
    save_app()이 함수 내부에서 매번 새로 CalculatorRepository(db)를 만들기 때문에,
    호출 간 상태(고아 레코드 등)를 이어가려면 클로저로 공유 dict를 묶어야 한다."""

    class _Repo:
        def __init__(self, db):
            self.db = db

        def get_all(self):
            return [dict(r) for r in shared_rows.values()]

        def save(self, data):
            _id = f"calc_{len(shared_rows) + 1}"
            row = dict(data)
            row["id"] = _id
            shared_rows[_id] = row
            return _id

        def delete(self, id_):
            shared_rows.pop(id_, None)

    return _Repo


class _FakeTplRepo:
    def __init__(self, db):
        self.db = db
        self.saved = []

    def save(self, data):
        self.saved.append(data)
        return f"tpl_{len(self.saved)}"


def _patch_common(monkeypatch, fake_db, shared_rows, v3_slugs, write_v3_ok=True, checklist_spy=None):
    monkeypatch.setattr(af, "get_db_adapter", lambda cfg: fake_db)
    # IRP-23: app_templates 저장은 get_template_storage_adapter(cfg)를 거치므로
    # (SQLite-원본/Sheets-백업 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_template_storage_adapter", lambda cfg: fake_db)
    # STEP93: calculators 저장은 get_calculator_storage_adapter(cfg)를 거치므로
    # (SQLite MAIN/Sheets BACKUP 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_calculator_storage_adapter", lambda cfg: fake_db)
    monkeypatch.setattr(af, "CalculatorRepository", _make_fake_calc_repo(shared_rows))
    monkeypatch.setattr(af, "TemplateRepository", _FakeTplRepo)
    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=True: dict(v3_slugs))
    monkeypatch.setattr("modules.registry_loader.add_auto_entry", lambda *a, **k: None)
    monkeypatch.setattr("modules.registry_loader.remove_auto_entry", lambda *a, **k: True)
    if write_v3_ok:
        monkeypatch.setattr(af, "_write_registry_v3", lambda *a, **k: None)
    else:
        def _boom(*a, **k):
            raise RuntimeError("registry write boom")
        monkeypatch.setattr(af, "_write_registry_v3", _boom)
    monkeypatch.setattr(af, "_write_calculator_index", lambda *a, **k: None)
    monkeypatch.setattr(af, "_save_contract_instance", lambda *a, **k: None)
    monkeypatch.setattr(af, "save_af_checklist", checklist_spy or (lambda *a, **k: None))


def _gen_app(monkeypatch, name):
    monkeypatch.setattr(af, "_chat", _capture_chat([]))
    return generate_app(CFG, name, category="세금/세법", desc="설명", tier=2)


# ══════════════════════════════════════════════════════════════════════════
# P0-1: 고아 레코드(DB에만 존재) 자동 정리
# ══════════════════════════════════════════════════════════════════════════

def test_orphan_db_only_record_is_auto_cleaned_and_retry_succeeds(monkeypatch):
    """재현: 이전 시도가 DB(calculators+app_templates)에는 저장됐지만 v3
    Registry에는 없는 상태(고아). 수정 후: 동일 slug 재시도 시 고아를 자동
    정리하고 정상적으로 새로 저장되어야 한다(기존엔 '이미 등록됨(DB)'로 영구 차단)."""
    fake_db = _FakeDb()
    shared_rows = {
        "calc_orphan": {
            "id": "calc_orphan", "slug": "orphan-calc", "name": "이전 시도(고아)",
            "template_id": "tpl_orphan",
        }
    }
    saved_checklists = []
    _patch_common(
        monkeypatch, fake_db, shared_rows, v3_slugs={},  # v3 Registry엔 없음 = 고아
        checklist_spy=lambda slug, cl: saved_checklists.append((slug, cl)),
    )
    app = _gen_app(monkeypatch, name="새 이름 계산기")

    ok, msg = save_app(CFG, app, slug="orphan-calc")

    assert ok, msg
    assert ("app_templates", "tpl_orphan") in fake_db.deleted
    assert "calc_orphan" not in shared_rows
    assert any(
        r["slug"] == "orphan-calc" and r["name"] == "새 이름 계산기"
        for r in shared_rows.values()
    )
    assert saved_checklists, "고아 정리 후에도 정상적으로 checklist 단계까지 도달해야 한다"


def test_genuine_duplicate_slug_still_rejected_without_cleanup(monkeypatch):
    """회귀: slug가 DB와 v3 Registry 양쪽에 모두 존재하는 '진짜' 중복은 고아가
    아니므로 정리 로직이 발동하지 않고 기존과 동일하게 거부되어야 한다."""
    fake_db = _FakeDb()
    shared_rows = {
        "calc_existing": {
            "id": "calc_existing", "slug": "already-there", "name": "이미 있음",
            "template_id": "tpl_existing",
        }
    }
    _patch_common(
        monkeypatch, fake_db, shared_rows,
        v3_slugs={"already-there": {"source": "app_factory", "status": "HOLD"}},
    )
    app = _gen_app(monkeypatch, name="다른 이름")

    ok, msg = save_app(CFG, app, slug="already-there")

    assert not ok
    assert "이미 등록됨" in msg
    assert fake_db.deleted == []
    assert "calc_existing" in shared_rows


def test_registry_load_failure_skips_orphan_cleanup_conservatively(monkeypatch):
    """v3 Registry 조회 자체가 실패하면(_v3_has_slug=None) 고아 여부를 판단할 수
    없으므로, 파괴적인 자동 정리를 시도하지 않고 기존과 동일하게 안전하게
    거부해야 한다(오탐으로 인한 오삭제 방지)."""
    fake_db = _FakeDb()
    shared_rows = {
        "calc_x": {"id": "calc_x", "slug": "maybe-orphan", "name": "불확실", "template_id": "tpl_x"},
    }
    _patch_common(monkeypatch, fake_db, shared_rows, v3_slugs={})

    def _boom_load(force=True):
        raise RuntimeError("registry read boom")

    monkeypatch.setattr("modules.registry_loader.load_registry_v3", _boom_load)
    app = _gen_app(monkeypatch, name="다른 이름2")

    ok, msg = save_app(CFG, app, slug="maybe-orphan")

    assert not ok
    assert "이미 등록됨" in msg
    assert fake_db.deleted == []
    assert "calc_x" in shared_rows


def test_orphan_cleanup_failure_returns_clear_error_and_does_not_proceed(monkeypatch):
    """고아 정리 자체가 실패하면(예: DB 삭제 권한 오류) 저장을 계속 진행하지
    않고 명확한 에러로 중단해야 한다(부분 상태가 더 꼬이는 것을 방지)."""
    class _BoomDb(_FakeDb):
        def delete(self, table, id_):
            raise RuntimeError("delete denied")

    fake_db = _BoomDb()
    shared_rows = {
        "calc_orphan2": {
            "id": "calc_orphan2", "slug": "orphan-calc-2", "name": "고아2",
            "template_id": "tpl_orphan2",
        }
    }
    _patch_common(monkeypatch, fake_db, shared_rows, v3_slugs={})
    app = _gen_app(monkeypatch, name="정리실패계산기")

    ok, msg = save_app(CFG, app, slug="orphan-calc-2")

    assert not ok
    assert "정리" in msg or "자동 정리" in msg
    assert "calc_orphan2" in shared_rows  # 정리 실패 시 원본은 그대로 보존


# ══════════════════════════════════════════════════════════════════════════
# P0-2: 체크리스트 생성 실패 시 Legal Hold 우회 방지(폴백)
# ══════════════════════════════════════════════════════════════════════════

def test_checklist_failure_falls_back_to_blocking_critical_item(monkeypatch):
    """재현: extract_checklist/save_af_checklist가 예외를 던지는 상황.
    수정 후: 빈 체크리스트 대신 checked=False critical 폴백 항목이 저장되어야
    한다(promote_to_ready()의 '체크리스트 비어있으면 검사 생략' 취약점을 닫음)."""
    fake_db = _FakeDb()
    shared_rows = {}
    calls = []

    def _spy(slug, checklist):
        calls.append((slug, checklist))
        if len(calls) == 1:
            raise RuntimeError("checklist io boom")

    _patch_common(monkeypatch, fake_db, shared_rows, v3_slugs={}, checklist_spy=_spy)
    app = _gen_app(monkeypatch, name="체크리스트실패계산기")

    ok, msg = save_app(CFG, app, slug="checklist-fail-calc")

    assert ok, msg
    assert len(calls) == 2, "1차 실패 후 폴백 저장이 재시도되어야 한다"
    fallback_slug, fallback_checklist = calls[1]
    assert fallback_slug == "checklist-fail-calc"
    assert len(fallback_checklist) == 1
    assert fallback_checklist[0]["severity"] == "critical"
    assert fallback_checklist[0]["checked"] is False
    assert fallback_checklist[0]["id"] == "checklist_generation_failed"


def test_checklist_double_failure_logs_error_but_save_still_succeeds(monkeypatch, caplog):
    """체크리스트 저장이 폴백까지 두 번 다 실패하는 최악의 경우에도, save_app()
    자체는 기존 철학(체크리스트 실패가 계산기 저장을 막지 않음)을 유지하되
    ERROR 레벨로 강하게 로그를 남겨 운영자가 놓치지 않도록 해야 한다."""
    fake_db = _FakeDb()
    shared_rows = {}

    def _always_boom(slug, checklist):
        raise RuntimeError("always boom")

    _patch_common(monkeypatch, fake_db, shared_rows, v3_slugs={}, checklist_spy=_always_boom)
    app = _gen_app(monkeypatch, name="이중실패계산기")

    with caplog.at_level(logging.ERROR, logger="pipeline"):
        ok, msg = save_app(CFG, app, slug="double-fail-calc")

    assert ok, msg
    assert any("Legal Hold" in r.message for r in caplog.records)


def test_checklist_normal_success_is_unaffected(monkeypatch):
    """정상 경로 회귀: extract_checklist/save_af_checklist가 성공하면 폴백
    없이 기존과 동일하게 1회만 저장되어야 한다."""
    fake_db = _FakeDb()
    shared_rows = {}
    calls = []
    _patch_common(
        monkeypatch, fake_db, shared_rows, v3_slugs={},
        checklist_spy=lambda slug, cl: calls.append((slug, cl)),
    )
    app = _gen_app(monkeypatch, name="정상계산기")

    ok, msg = save_app(CFG, app, slug="normal-calc")

    assert ok, msg
    assert len(calls) == 1
    _, checklist = calls[0]
    assert any(i["id"] == "checklist_generation_failed" for i in checklist) is False


# ══════════════════════════════════════════════════════════════════════════
# P0-2 종단 검증: 실제 promote_to_ready()가 폴백 체크리스트로 승격을 막는지
# (tmp_path 격리 Registry — 실제 운영 docs/registry/*.yaml에는 쓰지 않음)
# ══════════════════════════════════════════════════════════════════════════

def test_promote_to_ready_is_blocked_after_checklist_fallback(tmp_path, monkeypatch):
    """종단 검증: save_app()을 실제로 호출해(단, DB/AI만 대역으로 대체) Step B/Step C가
    실제 tmp_path 격리 Registry에 기록되게 하고, extract_checklist()만 실패시킨다.
    그 후 수정하지 않은 원본 promote_to_ready()를 호출하면, save_app()이 기록한
    폴백 critical 항목 때문에 여전히 HOLD로 차단되어야 한다 — 이 STEP이 닫으려는
    취약점이 실제로 막혔다는 최종 증거(save_af_checklist()/promote_to_ready() 모두
    원본 그대로 사용, Registry 읽기/쓰기 경로만 격리)."""
    import modules.registry_loader as registry_loader

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    monkeypatch.setattr(registry_loader, "_REG_DIR", reg_dir)
    monkeypatch.setattr(af, "_REG_DIR", reg_dir)
    # STEP 4-H-4에서 발견: add_auto_entry()가 쓰는 registry_auto.yaml 경로(_AUTO_PATH)는
    # _REG_DIR과 완전히 별개의 모듈 상수라 위 두 줄만으로는 격리되지 않는다 — 격리하지
    # 않으면 실제 운영 docs/registry_auto.yaml에 테스트 데이터가 그대로 기록된다
    # (이 STEP에서 실제로 재현되어 즉시 수정함). _REG_DIR과 동일하게 tmp_path로 격리한다.
    monkeypatch.setattr(registry_loader, "_AUTO_PATH", tmp_path / "registry_auto.yaml")
    registry_loader.invalidate()

    fake_db = _FakeDb()
    shared_rows = {}
    # get_db_adapter/CalculatorRepository/TemplateRepository만 대역 처리하고,
    # registry_loader.load_registry_v3/add_auto_entry, _write_registry_v3,
    # save_af_checklist는 전부 원본을 그대로 사용해 격리된 파일에 기록되게 한다.
    monkeypatch.setattr(af, "get_db_adapter", lambda cfg: fake_db)
    monkeypatch.setattr(af, "get_template_storage_adapter", lambda cfg: fake_db)
    # STEP93: calculators 저장은 get_calculator_storage_adapter(cfg)를 거치므로
    # (SQLite MAIN/Sheets BACKUP 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_calculator_storage_adapter", lambda cfg: fake_db)
    monkeypatch.setattr(af, "CalculatorRepository", _make_fake_calc_repo(shared_rows))
    monkeypatch.setattr(af, "TemplateRepository", _FakeTplRepo)
    monkeypatch.setattr(af, "_write_calculator_index", lambda *a, **k: None)
    monkeypatch.setattr(af, "_save_contract_instance", lambda *a, **k: None)

    def _boom_extract(*a, **k):
        raise RuntimeError("extract boom")

    monkeypatch.setattr("modules.review_center.extract_checklist", _boom_extract)

    app = _gen_app(monkeypatch, name="종단검증계산기")
    ok, msg = save_app(CFG, app, slug="checklist-e2e-calc")
    assert ok, msg  # 체크리스트 폴백 실패는 save_app() 자체를 막지 않는다(기존 철학 유지)

    registry_loader.invalidate()
    promote_ok, promote_msg = promote_to_ready("checklist-e2e-calc")

    assert promote_ok is False
    assert "필수 검토" in promote_msg or "미완료" in promote_msg

    yaml_files = list(reg_dir.glob("*_af.yaml"))
    assert yaml_files, "v3 Registry 파일이 기록되지 않음"
    data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert data["checklist-e2e-calc"]["status"] == "HOLD"
    checklist = data["checklist-e2e-calc"]["review_checklist"]
    assert len(checklist) == 1
    assert checklist[0]["id"] == "checklist_generation_failed"
    assert checklist[0]["checked"] is False


def test_promote_to_ready_empty_checklist_bypass_still_exists_by_design(tmp_path, monkeypatch):
    """대조군: promote_to_ready() 자체는 이번 STEP에서 변경하지 않았으므로,
    review_checklist가 정말로 빈 배열([])이면 여전히(기존 동작 그대로) 검사
    없이 승격된다 — 바로 이 취약점을 save_app() 쪽 폴백으로 막았다는 것을
    보여주는 대조 테스트(회귀 방지: promote_to_ready()를 몰래 바꾸지 않았음을 증명)."""
    import modules.registry_loader as registry_loader

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    # "세금/세법"은 _CATEGORY_AF_YAML_MAP에 없어 labor_af로 폴백된다(_category_to_af_yaml).
    (reg_dir / "labor_af.yaml").write_text(
        "empty-checklist-calc:\n"
        "  source: app_factory\n"
        "  status: HOLD\n"
        "  category: '세금/세법'\n"
        "  review_checklist: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(registry_loader, "_REG_DIR", reg_dir)
    monkeypatch.setattr(af, "_REG_DIR", reg_dir)
    registry_loader.invalidate()

    ok, msg = promote_to_ready("empty-checklist-calc")

    assert ok is True  # promote_to_ready() 자체의 기존 동작은 의도적으로 그대로 둠(지시서 §4/§9)
