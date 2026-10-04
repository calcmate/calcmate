# -*- coding: utf-8 -*-
"""tests/test_review_approval.py — STEP S1: Human Review Approval 게이트 복원.

dashboard.py "🧮 계산기 관리" 탭의 "👤 사람 검수"(dashboard.py:1753-1796)와 동일한 안전
의미(QA PASS 후에만 승인 가능, 승인 없이는 배포 불가)를 React/FastAPI 경로에도 복원한다.

Streamlit의 session_state(브라우저 세션 메모리, 영속화 안 됨)와 동일한 성격의 서버측
in-memory 저장소(api/services/review_approval_store.py)를 사용하되, "재생성 버튼을
누르는 행위 자체"로 무조건 초기화하던 Streamlit과 달리, 여기서는 스냅샷 내용의 해시로
승인 대상을 식별해 "실제로 내용이 달라졌는가"를 판단한다 — 더 정확한 재현이다.

안전 설계: 실제 DB/Registry/파일시스템/GitHub API 호출 없음 — 전부 monkeypatch로 대체.
신규 계산기 생성/HOLD 계산기 수정 없음(fake 데이터만 사용). 실제 production deploy 없음.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "review-approval-test-admin-token"
VIEWER_TOKEN = "review-approval-test-viewer-token"

FAKE_CALC = {"id": "calc_1", "slug": "fake-slug", "name": "가짜계산기", "status": "active"}
COMPLETE_HTML = (
    '<!DOCTYPE html><html lang="ko"><head><title>t</title></head><body>'
    '<input id="a"><button onclick="c()">계산</button>'
    '<script>function c(){}</script></body></html>'
)


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()


@pytest.fixture(autouse=True)
def _fresh_review_approval_store():
    import api.services.review_approval_store as review_store_module
    review_store_module._store = None
    yield
    review_store_module._store = None


def _passing_qa_steps():
    return [{"step": i, "label": f"단계{i}", "passed": True, "skipped": False, "detail": "OK"}
            for i in range(1, 4)]


def _failing_qa_steps():
    return [
        {"step": 1, "label": "단계1", "passed": True, "skipped": False, "detail": "OK"},
        {"step": 2, "label": "단계2", "passed": False, "skipped": False, "detail": "실패함"},
    ]


class _FakeRepo:
    def get_by_slug(self, slug):
        return dict(FAKE_CALC) if slug == FAKE_CALC["slug"] else None

    def publish(self, cid, url):
        pass


class _FakeSnapshotFS:
    """read_site_snapshot()을 in-memory dict로 흉내낸다 — write_site_snapshot()이
    호출되면 그 내용을 저장하고, 이후 read_site_snapshot()이 그 내용을 반환한다.
    실제 파일시스템에 전혀 접근하지 않는다."""
    def __init__(self):
        self.saved = {}

    def write(self, cfg, calc, files):
        self.saved = dict(files)
        return "/fake/_site/fake-slug"

    def read(self, cfg, calc):
        return dict(self.saved)


def _patch_common(monkeypatch, *, v3_entry=None, needs_human_legal=False,
                   generate_calculator_result=None, qa_steps=None, fs=None):
    import api.services.calculator_service as svc

    fake_repo = _FakeRepo()
    fs = fs if fs is not None else _FakeSnapshotFS()
    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (fake_repo, {"GITHUB_REPO": "x"}))
    monkeypatch.setattr(svc, "_registry", lambda: {FAKE_CALC["slug"]: (v3_entry or {"status": "READY", "source": "app_factory"})})
    monkeypatch.setattr(svc, "read_site_snapshot", fs.read)
    monkeypatch.setattr("modules.site_snapshot.write_site_snapshot", fs.write)
    monkeypatch.setattr(
        "modules.registry_loader.load_registry",
        lambda force=True: ({FAKE_CALC["slug"]: {"needs_human_legal": True}} if needs_human_legal else {}),
    )
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
    return fake_repo, fs


def _good_build_kwargs():
    return dict(
        generate_calculator_result={
            "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
            "_formula_valid": True, "_formula_msg": "OK",
        },
        qa_steps=_passing_qa_steps(),
    )


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
# STEP 1 분석 재확인 — get_calculator_review_status()
# ══════════════════════════════════════════════════════════════════════════

class TestReviewStatus:
    def test_no_snapshot_yet(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch)
        status = svc.get_calculator_review_status(FAKE_CALC["slug"])
        assert status["has_snapshot"] is False
        assert status["approved"] is False

    def test_not_found_raises(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch)
        with pytest.raises(svc.CalculatorNotFound):
            svc.get_calculator_review_status("no-such-slug")


# ══════════════════════════════════════════════════════════════════════════
# CASE E — QA 실패 시 승인 불가 (dashboard.py:1772-1773과 동일 의미)
# ══════════════════════════════════════════════════════════════════════════

class TestApproveBlockedByQA:
    def test_qa_failure_blocks_approval(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, qa_steps=_failing_qa_steps(),
                      generate_calculator_result={
                          "index.html": COMPLETE_HTML, "style.css": "", "script.js": "",
                          "_formula_valid": True, "_formula_msg": "OK",
                      })
        result = svc.approve_calculator_review(FAKE_CALC["slug"], "admin-1")
        assert result["ok"] is False
        assert "QA 실패" in result["blocked_reason"]

        status = svc.get_calculator_review_status(FAKE_CALC["slug"])
        assert status["approved"] is False


# ══════════════════════════════════════════════════════════════════════════
# 승인 → 배포 허용, 승인 없이 → 배포 차단 (CASE B/C)
# ══════════════════════════════════════════════════════════════════════════

class TestApproveThenDeploy:
    def test_approve_succeeds_after_qa_pass_and_unblocks_deploy(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, **_good_build_kwargs())

        approve_result = svc.approve_calculator_review(FAKE_CALC["slug"], "admin-1")
        assert approve_result["ok"] is True
        assert approve_result["approved_by"] == "admin-1"

        status = svc.get_calculator_review_status(FAKE_CALC["slug"])
        assert status["approved"] is True
        assert status["approved_by"] == "admin-1"

        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": (True, "https://example.github.io/x/fake-slug/"))
        deploy_result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert deploy_result["ok"] is True

    def test_deploy_blocked_without_approval_case_b(self, monkeypatch):
        """CASE B: Build 성공 + QA PASS + 검수 미승인 → Deploy BLOCK."""
        import api.services.calculator_service as svc
        deploy_calls = []
        _patch_common(monkeypatch, **_good_build_kwargs())
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"))

        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["stage"] == "review"
        assert deploy_calls == []


# ══════════════════════════════════════════════════════════════════════════
# CASE D — Build 재실행 시 기존 승인 무효화(내용이 실제로 바뀐 경우)
# ══════════════════════════════════════════════════════════════════════════

class TestApprovalInvalidatedByRebuild:
    def test_approval_invalidated_when_rebuilt_content_differs(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, **_good_build_kwargs())

        approve_result = svc.approve_calculator_review(FAKE_CALC["slug"], "admin-1")
        assert approve_result["ok"] is True
        assert svc.get_calculator_review_status(FAKE_CALC["slug"])["approved"] is True

        # 재빌드 시 실제로 다른 HTML이 생성되도록 mock을 교체(포뮬러/코드가 바뀐 상황 재현).
        monkeypatch.setattr(
            "modules.app_generator.generate_calculator",
            lambda calc, cfg: {
                "index.html": COMPLETE_HTML.replace("계산", "재계산"), "style.css": "", "script.js": "",
                "_formula_valid": True, "_formula_msg": "OK",
            },
        )
        build_result = svc.build_calculator(FAKE_CALC["slug"])
        assert build_result["ok"] is True

        status = svc.get_calculator_review_status(FAKE_CALC["slug"])
        assert status["approved"] is False
        assert status["stale"] is True, "내용이 바뀐 재빌드 이후에는 이전 승인이 더 이상 유효하지 않아야 한다"

        deploy_calls = []
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"))
        deploy_result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert deploy_result["ok"] is False
        assert deploy_result["stage"] == "review"
        assert deploy_calls == [], "내용이 바뀐 재빌드 이후 재승인 없이 배포되면 안 된다"

    def test_approval_survives_rebuild_when_content_identical(self, monkeypatch):
        """참고 확인: 내용이 실제로 동일하면(예: 단순 재클릭) 승인이 불필요하게
        무효화되지 않는다 — Streamlit의 '무조건 초기화'보다 더 정확한 재현."""
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, **_good_build_kwargs())

        svc.approve_calculator_review(FAKE_CALC["slug"], "admin-1")
        assert svc.get_calculator_review_status(FAKE_CALC["slug"])["approved"] is True

        build_result = svc.build_calculator(FAKE_CALC["slug"])
        assert build_result["ok"] is True

        status = svc.get_calculator_review_status(FAKE_CALC["slug"])
        assert status["approved"] is True, "내용이 실제로 동일하면 기존 승인이 계속 유효해야 한다"


# ══════════════════════════════════════════════════════════════════════════
# 승인 취소
# ══════════════════════════════════════════════════════════════════════════

class TestUnapprove:
    def test_unapprove_blocks_deploy_again(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, **_good_build_kwargs())
        svc.approve_calculator_review(FAKE_CALC["slug"], "admin-1")
        assert svc.get_calculator_review_status(FAKE_CALC["slug"])["approved"] is True

        unapprove_result = svc.unapprove_calculator_review(FAKE_CALC["slug"])
        assert unapprove_result["ok"] is True
        assert svc.get_calculator_review_status(FAKE_CALC["slug"])["approved"] is False

        deploy_calls = []
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"))
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert deploy_calls == []


# ══════════════════════════════════════════════════════════════════════════
# CASE F — HOLD 계산기: 기존 정책 유지(HOLD가 Human Review보다 먼저 차단)
# ══════════════════════════════════════════════════════════════════════════

class TestHoldStillBlocksRegardlessOfApproval:
    def test_hold_blocks_even_if_approved(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, v3_entry={"status": "HOLD", "source": "app_factory"},
                      **_good_build_kwargs())
        # HOLD 상태에서는 build_calculator()를 거치지 않으므로 승인 자체가 안 되지만,
        # 만에 하나 스토어에 승인이 남아있어도 HOLD가 먼저 차단해야 한다(기존 정책 무변경).
        from api.services.review_approval_store import get_review_approval_store
        get_review_approval_store().approve(FAKE_CALC["slug"], "any-hash", "admin-1")

        deploy_calls = []
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"))
        result = svc.deploy_calculator(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["stage"] == "gate"
        assert "HOLD" in result["blocked_reason"]
        assert deploy_calls == []


# ══════════════════════════════════════════════════════════════════════════
# CASE A — Build 전 Deploy → BLOCK(기존 동작, 회귀 없음 확인)
# ══════════════════════════════════════════════════════════════════════════

def test_case_a_deploy_before_build_blocks(monkeypatch):
    import api.services.calculator_service as svc
    _patch_common(monkeypatch, generate_calculator_result={
        "index.html": "", "style.css": "", "script.js": "",
        "_formula_valid": False, "_formula_msg": "no formula",
    }, qa_steps=_passing_qa_steps())
    result = svc.deploy_calculator(FAKE_CALC["slug"])
    assert result["ok"] is False
    assert result["stage"] == "build"


# ══════════════════════════════════════════════════════════════════════════
# CASE G — React UI를 완전히 우회한 실제 endpoint 직접 호출도 차단되어야 한다
# (가장 중요한 테스트 — 서버측 강제 확인)
# ══════════════════════════════════════════════════════════════════════════

class TestDirectApiCallCannotBypassApproval:
    @pytest.fixture(autouse=True)
    def _isolated_tokens(self, monkeypatch):
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
        yield

    def test_deploy_endpoint_blocks_without_approval_even_with_admin_token(self, monkeypatch):
        """React를 전혀 거치지 않고 admin 토큰으로 직접 POST /deploy를 호출해도
        (클라이언트가 'approved=true' 같은 값을 보낼 방법 자체가 없다 — 서버가
        저장한 승인 상태만 신뢰) 차단되어야 한다."""
        _patch_common(monkeypatch, **_good_build_kwargs())
        deploy_calls = []
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": deploy_calls.append(1) or (True, "unused"))

        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/deploy", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["ok"] is False
        assert body["stage"] == "review"
        assert deploy_calls == []

    def test_deploy_endpoint_succeeds_after_real_approve_endpoint_call(self, monkeypatch):
        """실제 승인 endpoint를 먼저 호출한 뒤에는(같은 프로세스의 서버측 상태를
        통해) 배포 endpoint가 정상적으로 진행된다."""
        _patch_common(monkeypatch, **_good_build_kwargs())
        monkeypatch.setattr("modules.github_deployer.deploy_app",
                             lambda cfg, files, repo=None, subdir="": (True, "https://example.github.io/x/fake-slug/"))

        r1 = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/review/approve", headers=_auth(ADMIN_TOKEN))
        assert r1.status_code == 200
        assert r1.json()["data"]["ok"] is True

        r2 = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/deploy", headers=_auth(ADMIN_TOKEN))
        assert r2.json()["data"]["ok"] is True

    def test_approve_without_auth_returns_401(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/review/approve")
        assert r.status_code == 401

    def test_approve_as_viewer_returns_403(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/review/approve", headers=_auth(VIEWER_TOKEN))
        assert r.status_code == 403

    def test_unapprove_without_auth_returns_401(self):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/review/unapprove")
        assert r.status_code == 401

    def test_review_status_get_requires_no_auth(self, monkeypatch):
        """다른 GET 조회 endpoint와 동일하게 인증 없이 공개된다(읽기 전용)."""
        _patch_common(monkeypatch)
        r = _client().get(f"/api/calculators/{FAKE_CALC['slug']}/review")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_review_not_found_returns_structured_failure(self, monkeypatch):
        _patch_common(monkeypatch)
        r = _client().get("/api/calculators/no-such-slug/review")
        assert r.json()["success"] is False
        assert r.json()["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════
# route 등록 확인 + Registry 무손상
# ══════════════════════════════════════════════════════════════════════════

def test_review_write_routes_registered():
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    assert ("/api/calculators/{slug}/review/approve", "POST") in write_paths
    assert ("/api/calculators/{slug}/review/unapprove", "POST") in write_paths


def test_real_registry_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
