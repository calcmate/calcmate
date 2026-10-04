# -*- coding: utf-8 -*-
"""tests/test_build_deploy_calculator.py — P0-2: Build/Deploy 기능 React/FastAPI 이관.

dashboard.py의 "🧮 계산기 관리" 탭 "🧮 생성"→QA→"🚀 배포" 흐름과 동일한 함수
(modules.app_generator.generate_calculator, modules.review_center.pre_build_qa,
modules.github_deployer.deploy_app, modules.site_snapshot)를 재사용하는
api.services.calculator_service.build_calculator()/deploy_calculator()를 검증한다.

안전 설계: 실제 DB/Registry/파일시스템/GitHub API 호출 없음 — 전부 monkeypatch로
대체한다. 신규 계산기를 생성하거나 기존 HOLD 계산기를 수정하지 않는다(둘 다
fake 데이터만 사용).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes


@pytest.fixture(autouse=True)
def _fresh_review_approval_store():
    """STEP S1: review_approval_store는 프로세스 전역 in-memory 싱글턴이므로,
    테스트 간 승인 상태가 새지 않도록 매 테스트마다 새로 만든다."""
    import api.services.review_approval_store as review_store_module
    review_store_module._store = None
    yield
    review_store_module._store = None

_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "build-deploy-test-admin-token"
VIEWER_TOKEN = "build-deploy-test-viewer-token"


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()

COMPLETE_HTML = (
    '<!DOCTYPE html><html lang="ko"><head><title>t</title></head><body>'
    '<input id="a"><button onclick="c()">계산</button>'
    '<script>function c(){}</script></body></html>'
)
TRUNCATED_HTML = (
    '<!DOCTYPE html><html lang="ko"><head><title>t</title></head><body>'
    '<input id="a"><button onclick="c()">계산</button>'
    '<script>function c(){ const x = `잘림'
)

FAKE_CALC = {"id": "calc_1", "slug": "fake-slug", "name": "가짜계산기", "status": "active"}


def _passing_qa_steps():
    return [{"step": i, "label": f"단계{i}", "passed": True, "skipped": False, "detail": "OK"}
            for i in range(1, 4)]


def _failing_qa_steps():
    return [
        {"step": 1, "label": "단계1", "passed": True, "skipped": False, "detail": "OK"},
        {"step": 2, "label": "단계2", "passed": False, "skipped": False, "detail": "실패함"},
    ]


# ══════════════════════════════════════════════════════════════════════════
# 공통 monkeypatch 헬퍼
# ══════════════════════════════════════════════════════════════════════════

class _FakeRepo:
    def __init__(self):
        self.publish_calls = []

    def get_by_slug(self, slug):
        return dict(FAKE_CALC) if slug == FAKE_CALC["slug"] else None

    def publish(self, cid, url):
        self.publish_calls.append((cid, url))


import hashlib

# _patch_common()이 read_site_snapshot()을 항상 빈 dict로 대체하므로, 그 빈 스냅샷의
# 해시는 항상 동일하다 — Human Review Approval(STEP S1)을 미리 승인해 두어야 하는
# 테스트에서 재사용한다.
_EMPTY_SNAPSHOT_HASH = hashlib.sha256(b"").hexdigest()


def _patch_common(monkeypatch, v3_entry, *, needs_human_legal=False,
                   generate_calculator_result=None, qa_steps=None,
                   write_snapshot_spy=None, deploy_app_spy=None,
                   deploy_app_return=(True, "https://example.github.io/repo/fake-slug/"),
                   approved=False):
    import api.services.calculator_service as svc

    fake_repo = _FakeRepo()
    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (fake_repo, {"GITHUB_REPO": "x"}))
    monkeypatch.setattr(svc, "_registry", lambda: {FAKE_CALC["slug"]: v3_entry})
    monkeypatch.setattr(svc, "read_site_snapshot", lambda cfg, calc: {})

    monkeypatch.setattr(
        "modules.registry_loader.load_registry",
        lambda force=True: ({FAKE_CALC["slug"]: {"needs_human_legal": True}} if needs_human_legal else {}),
    )

    if approved:
        # STEP S1: 이 테스트는 실제로 deploy_app()까지 도달해야 하므로, "빈 스냅샷"
        # 해시에 대해 미리 Human Review 승인을 심어 둔다(레거시 Formula/HOLD 게이트와
        # 무관한 신규 게이트이므로, 이 게이트를 검증하지 않는 기존 테스트는 항상
        # 승인된 상태로 두어 기존 동작을 그대로 재검증할 수 있게 한다).
        from api.services.review_approval_store import get_review_approval_store
        get_review_approval_store().approve(FAKE_CALC["slug"], _EMPTY_SNAPSHOT_HASH, "test-actor")

    if generate_calculator_result is not None:
        monkeypatch.setattr(
            "modules.app_generator.generate_calculator",
            lambda calc, cfg: dict(generate_calculator_result),
        )
    if qa_steps is not None:
        monkeypatch.setattr(
            "modules.review_center.pre_build_qa",
            lambda calc, cfg, prev_files=None: list(qa_steps),
        )
    if write_snapshot_spy is not None:
        monkeypatch.setattr("modules.site_snapshot.write_site_snapshot", write_snapshot_spy)
    if deploy_app_spy is not None:
        monkeypatch.setattr("modules.github_deployer.deploy_app", deploy_app_spy)
    else:
        monkeypatch.setattr(
            "modules.github_deployer.deploy_app",
            lambda cfg, files, repo=None, subdir="": deploy_app_return,
        )
    return fake_repo


# ══════════════════════════════════════════════════════════════════════════
# Build — 단위 테스트
# ══════════════════════════════════════════════════════════════════════════

class TestBuildCalculator:
    def test_build_passes_when_all_gates_pass(self, monkeypatch):
        import api.services.calculator_service as svc
        write_calls = []

        def _spy_write(cfg, calc, files):
            write_calls.append((calc.get("slug"), files))
            return "/fake/_site/fake-slug"

        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=_spy_write,
        )
        result = svc.build_calculator(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert result["formula_valid"] is True
        assert result["html_completeness"]["ok"] is True
        assert result["qa_ok"] is True
        assert len(write_calls) == 1
        assert result["snapshot_dir"] == "/fake/_site/fake-slug"

    def test_build_blocked_by_formula_hard_gate(self, monkeypatch):
        import api.services.calculator_service as svc
        write_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": False, "_formula_msg": "input_schema에 없는 변수: x",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: write_calls.append(1) or "unused",
        )
        result = svc.build_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["formula_valid"] is False
        assert write_calls == [], "Formula Hard Gate 실패 시 스냅샷을 쓰면 안 된다"

    def test_build_blocked_by_html_completeness(self, monkeypatch):
        import api.services.calculator_service as svc
        write_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": TRUNCATED_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: write_calls.append(1) or "unused",
        )
        result = svc.build_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["html_completeness"]["ok"] is False
        assert write_calls == [], "HTML/JS 완결성 검증 실패 시 스냅샷을 쓰면 안 된다"

    def test_build_blocked_by_pre_build_qa_failure(self, monkeypatch):
        import api.services.calculator_service as svc
        write_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_failing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: write_calls.append(1) or "unused",
        )
        result = svc.build_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["qa_ok"] is False
        assert write_calls == [], "pre_build_qa 실패 시 스냅샷을 쓰면 안 된다"

    def test_build_not_found_raises(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {"status": "READY", "source": "app_factory"})
        with pytest.raises(svc.CalculatorNotFound):
            svc.build_calculator("no-such-slug")


# ══════════════════════════════════════════════════════════════════════════
# Deploy — 단위 테스트
# ══════════════════════════════════════════════════════════════════════════

class TestDeployCalculator:
    def test_deploy_succeeds_when_all_gates_pass(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []

        def _spy_deploy(cfg, files, repo=None, subdir=""):
            deploy_calls.append({"repo": repo, "subdir": subdir, "files_keys": sorted(files.keys())})
            return True, "https://example.github.io/x/fake-slug/"

        fake_repo = _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: "/fake/_site/fake-slug",
            deploy_app_spy=_spy_deploy,
            approved=True,
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert len(deploy_calls) == 1
        assert deploy_calls[0]["subdir"] == "fake-slug"
        assert fake_repo.publish_calls == [("calc_1", "https://example.github.io/x/fake-slug/")]

    def test_deploy_blocked_when_hold(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "HOLD", "source": "app_factory"},
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert "HOLD" in result["blocked_reason"]
        assert deploy_calls == [], "HOLD 상태에서는 deploy_app()을 호출하면 안 된다"

    def test_deploy_blocked_when_needs_human_legal(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            needs_human_legal=True,
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert "needs_human_legal" in result["blocked_reason"]
        assert deploy_calls == [], "needs_human_legal=true 상태에서는 deploy_app()을 호출하면 안 된다"

    def test_deploy_blocked_when_build_fails_formula(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": False, "_formula_msg": "실패",
            },
            qa_steps=_passing_qa_steps(),
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["build_result"]["ok"] is False
        assert deploy_calls == [], "Build 실패(Formula) 시 deploy_app()을 호출하면 안 된다"

    def test_deploy_blocked_when_html_incomplete(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": TRUNCATED_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["build_result"]["html_completeness"]["ok"] is False
        assert deploy_calls == [], "HTML/JS 미완결 시 deploy_app()을 호출하면 안 된다"

    def test_deploy_blocked_when_pre_build_qa_fails(self, monkeypatch):
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_failing_qa_steps(),
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert deploy_calls == [], "pre_build_qa 실패 시 deploy_app()을 호출하면 안 된다"

    def test_deploy_reports_deploy_app_failure_without_marking_success(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: "/fake/_site/fake-slug",
            deploy_app_return=(False, "GITHUB_TOKEN 미설정 — 배포 건너뜀"),
            approved=True,
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert "GITHUB_TOKEN" in result["blocked_reason"]
        assert fake_repo.publish_calls == [], "deploy_app() 자체가 실패하면 published_url을 기록하면 안 된다"

    def test_deploy_non_app_factory_calculator_not_blocked_by_hold_logic(self, monkeypatch):
        """source != app_factory(기존 8개 계산기 등)는 HOLD 개념이 없으므로
        is_legal_hold가 항상 False — 이 경로에서 차단되지 않아야 한다."""
        import api.services.calculator_service as svc
        _patch_common(
            monkeypatch, {"status": None, "source": "curated"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: "/fake/_site/fake-slug",
            approved=True,
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is True

    def test_deploy_blocked_when_not_reviewed_even_if_all_other_gates_pass(self, monkeypatch):
        """STEP S1 핵심 회귀 고정: HOLD/needs_human_legal/Formula/HTML/QA를 전부
        통과해도 Human Review Approval이 없으면 배포되면 안 된다."""
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
            write_snapshot_spy=lambda cfg, calc, files: "/fake/_site/fake-slug",
            deploy_app_spy=lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"),
            approved=False,
        )
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["stage"] == "review"
        assert "검수 승인" in result["blocked_reason"]
        assert deploy_calls == [], "Human Review Approval 없이는 deploy_app()을 호출하면 안 된다"


# ══════════════════════════════════════════════════════════════════════════
# 실제 endpoint(React가 호출) 통합 테스트 — 인증/응답 envelope
# ══════════════════════════════════════════════════════════════════════════

def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestBuildDeployEndpoints:
    @pytest.fixture(autouse=True)
    def _isolated_tokens(self, monkeypatch):
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
        yield

    def test_build_without_auth_returns_401(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/build")
        assert r.status_code == 401

    def test_build_as_viewer_returns_403(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/build", headers=_auth(VIEWER_TOKEN))
        assert r.status_code == 403

    def test_deploy_without_auth_returns_401(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/deploy")
        assert r.status_code == 401

    def test_deploy_as_viewer_returns_403(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/deploy", headers=_auth(VIEWER_TOKEN))
        assert r.status_code == 403

    def test_build_not_found_returns_404(self, monkeypatch):
        _patch_common(monkeypatch, {"status": "READY", "source": "app_factory"})
        r = _client().post("/api/calculators/no-such-slug/build", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 404

    def test_deploy_not_found_returns_404(self, monkeypatch):
        _patch_common(monkeypatch, {"status": "READY", "source": "app_factory"})
        r = _client().post("/api/calculators/no-such-slug/deploy", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 404

    def test_build_endpoint_returns_structured_blocked_result_as_200(self, monkeypatch):
        """차단(ok=False)도 HTTP 200으로 반환되어야 한다(React가 상세 사유를
        보여줘야 하므로 400/500이 아니다)."""
        _patch_common(
            monkeypatch, {"status": "READY", "source": "app_factory"},
            generate_calculator_result={
                "index.html": TRUNCATED_HTML, "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
            qa_steps=_passing_qa_steps(),
        )
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/build", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True  # envelope 자체는 성공(요청 처리 성공)
        assert body["data"]["ok"] is False  # 실제 build 결과는 차단됨

    def test_deploy_endpoint_returns_structured_blocked_result_as_200(self, monkeypatch):
        _patch_common(monkeypatch, {"status": "HOLD", "source": "app_factory"})
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/deploy", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["ok"] is False
        assert "HOLD" in body["data"]["blocked_reason"]


def test_calculators_write_routes_include_build_and_deploy():
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert ("/api/calculators/{slug}/build", "POST") in write_paths
    assert ("/api/calculators/{slug}/deploy", "POST") in write_paths


def test_real_registry_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
