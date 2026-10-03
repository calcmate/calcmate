# -*- coding: utf-8 -*-
"""tests/test_test_isolation_guard.py — CALCMATE-TEST-ISOLATION-FIX-01.

tests/conftest.py의 세 가지 격리가 실제로 동작하는지 확인한다.
- TEST-FIX-01: BudgetTracker.record()가 운영 data/logs/budget.json 대신 테스트별 임시 파일에 저장
- TEST-FIX-02: 운영 config를 거친 _root는 테스트 프로젝트 root(복사본이면 복사본) — 다른 config/
               직접 만든 cfg의 _root는 그대로
- TEST-FIX-03: publisher._save_preview()가 운영 data/outputs 대신 임시 디렉터리에 저장

각 테스트는 쓰기 전에 격리가 켜져 있는지 먼저 확인하고, 아니면 아무것도 쓰지 않고 실패한다.
"""
import hashlib
import json
from pathlib import Path

import conftest as C
import modules.logger as L
import modules.publisher as P
from modules import config_loader


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "absent"


def test_budget_record_goes_to_isolated_file_not_production():
    assert L.BudgetTracker._save is C._isolated_budget_save            # 격리가 켜져 있어야만 진행
    iso = C._ISOLATED["budget"]
    assert iso is not None and iso.resolve() != C._PROD_BUDGET_FILE
    before = _sha(C._PROD_BUDGET_FILE)

    bt = L.BudgetTracker({})
    cost = bt.record("isolation-check-model", 1000)

    assert cost > 0                                                    # 계산/반환은 그대로
    assert bt.path.resolve() == C._PROD_BUDGET_FILE                    # 인스턴스 경로 자체는 불변
    assert _sha(C._PROD_BUDGET_FILE) == before                         # 운영 파일 무변경
    saved = json.loads(iso.read_text(encoding="utf-8"))
    assert "isolation-check-model" in saved["by_model"]
    # 같은 테스트 안에서 다시 읽으면 방금 기록이 보인다(_load도 임시 파일 기준)
    assert "isolation-check-model" in L.BudgetTracker({}).data["by_model"]


def test_budget_custom_path_is_not_redirected(tmp_path):
    bt = L.BudgetTracker({})
    bt.path = tmp_path / "custom_budget.json"
    bt.record("custom-path-model", 10)
    assert (tmp_path / "custom_budget.json").exists()
    assert not C._ISOLATED["budget"].exists()


def test_production_config_root_is_test_project_root():
    assert config_loader.merge_secrets is C._test_root_merge_secrets
    cfg = config_loader.load_config()                                  # 읽기 전용
    assert Path(cfg["_root"]).resolve() == C._REPO_ROOT


def test_copy_scenario_foreign_root_is_replaced_for_production_config():
    """복사본에서 config.yaml이 다른 저장소를 가리키는 상황을 흉내 낸다."""
    foreign = str(Path(C._REPO_ROOT).parent / "some-other-checkout")
    merged = config_loader.merge_secrets({"_root": foreign}, str(C._PROD_CONFIG_FILE))
    assert Path(merged["_root"]).resolve() == C._REPO_ROOT


def test_non_production_config_root_is_preserved(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("x: 1\n", encoding="utf-8")
    merged = config_loader.merge_secrets({"_root": str(tmp_path)}, str(cfg_path))
    assert merged["_root"] == str(tmp_path)


def test_foreign_root_data_dir_is_guarded_for_sqlite():
    for d in C._PROD_DATA_DIRS:
        assert C._is_production_sqlite(d / "blog_auto.db")


def test_publisher_preview_goes_to_isolated_outputs():
    assert P.OUTPUT_DIR == C._ISOLATED["outputs"]                      # 격리가 켜져 있어야만 진행
    prod_outputs = C._REPO_ROOT / "data" / "outputs"
    before = sorted(p.name for p in prod_outputs.glob("*")) if prod_outputs.exists() else []

    path = P._save_preview({"seo_title": "격리 확인", "meta_description": "", "tags_list": ""},
                           "<p>본문</p>", link="http://wp.test/p/1")

    assert path.parent == C._ISOLATED["outputs"] and path.exists()
    assert "격리 확인" in path.read_text(encoding="utf-8")
    after = sorted(p.name for p in prod_outputs.glob("*")) if prod_outputs.exists() else []
    assert after == before
