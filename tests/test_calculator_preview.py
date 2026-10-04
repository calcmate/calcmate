# -*- coding: utf-8 -*-
"""tests/test_calculator_preview.py — P0-3: React HTML Preview 이관.

dashboard.py "🔎 앱 미리보기"와 동일한 modules.app_generator.render_inline_calculator()를
재사용하는 api.services.calculator_service.preview_calculator()를 검증한다.

Preview는 build_calculator()가 실제로 쓴 스냅샷(data/workspace/_site/{slug}/)만 읽는다
(재생성하지 않음 — 순수 조회). write_site_snapshot()은 all_ok=True일 때만 호출되므로
스냅샷 부재 = "빌드 결과 없음"이다.

안전 설계: 실제 DB/Registry/파일시스템 호출 없음 — 전부 monkeypatch로 대체한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "preview-test-admin-token"

FAKE_CALC = {"id": "calc_1", "slug": "fake-slug", "name": "가짜계산기", "status": "active"}


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()


class _FakeRepo:
    def get_by_slug(self, slug):
        return dict(FAKE_CALC) if slug == FAKE_CALC["slug"] else None


def _patch_common(monkeypatch, snapshot_files, *, v3_entry=None):
    import api.services.calculator_service as svc

    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (_FakeRepo(), {}))
    monkeypatch.setattr(svc, "_registry", lambda: {FAKE_CALC["slug"]: v3_entry or {}})
    monkeypatch.setattr(svc, "read_site_snapshot", lambda cfg, calc: dict(snapshot_files))


# ══════════════════════════════════════════════════════════════════════════
# preview_calculator() — 단위 테스트
# ══════════════════════════════════════════════════════════════════════════

class TestPreviewCalculator:
    def test_previewable_when_snapshot_exists(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {
            "index.html": (
                '<!DOCTYPE html><html><head><title>t</title>'
                '<link rel="stylesheet" href="style.css"></head><body>'
                '<div id="app"><input id="a"><button onclick="c()">계산</button></div>'
                '<script src="script.js"></script></body></html>'
            ),
            "style.css": "#app{color:red}",
            "script.js": "function c(){}",
        })
        result = svc.preview_calculator(FAKE_CALC["slug"])
        assert result["previewable"] is True
        assert result["build_status"] == "built"
        assert "<style>#app{color:red}</style>" in result["html"]
        assert "function c(){}" in result["html"]
        # 원본 상대경로 참조는 인라인화 후 남아있으면 안 된다.
        assert 'href="style.css"' not in result["html"]
        assert 'src="script.js"' not in result["html"]
        # <html>/<head>/<body> 문서 골격은 React가 iframe에 씌우므로 preview HTML 자체에도
        # 최소 골격(doctype/head/body)이 있어야 srcdoc으로 바로 렌더링 가능하다.
        assert "<body>" in result["html"]

    def test_blocked_when_no_snapshot(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {})
        result = svc.preview_calculator(FAKE_CALC["slug"])
        assert result["previewable"] is False
        assert result["build_status"] == "not_built"
        assert result["html"] is None

    def test_blocked_when_snapshot_missing_index_html(self, monkeypatch):
        """style.css/script.js만 있고 index.html이 없는 비정상 스냅샷(예: Tier2-B류
        일부 파일 누락)도 미리보기 불가로 처리해야 한다."""
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {"style.css": "body{}", "script.js": "x"})
        result = svc.preview_calculator(FAKE_CALC["slug"])
        assert result["previewable"] is False
        assert result["build_status"] == "not_built"

    def test_blocked_when_render_raises(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {"index.html": "<html><body>x</body></html>"})
        monkeypatch.setattr(
            "modules.app_generator.render_inline_calculator",
            lambda files: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = svc.preview_calculator(FAKE_CALC["slug"])
        assert result["previewable"] is False
        assert result["build_status"] == "render_error"
        assert result["html"] is None

    def test_not_found_raises(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch, {})
        with pytest.raises(svc.CalculatorNotFound):
            svc.preview_calculator("no-such-slug")

    def test_preview_does_not_call_generate_calculator(self, monkeypatch):
        """Preview는 재생성을 수행하지 않는다 — generate_calculator()가 절대 호출되면
        안 된다(그건 Build 버튼의 역할)."""
        import api.services.calculator_service as svc

        def _boom(calc, cfg):
            raise AssertionError("preview_calculator()가 generate_calculator()를 호출하면 안 된다")

        monkeypatch.setattr("modules.app_generator.generate_calculator", _boom)
        _patch_common(monkeypatch, {
            "index.html": "<html><body>x</body></html>", "style.css": "", "script.js": "",
        })
        result = svc.preview_calculator(FAKE_CALC["slug"])
        assert result["previewable"] is True


# ══════════════════════════════════════════════════════════════════════════
# 실제 endpoint(React가 호출) 통합 테스트
# ══════════════════════════════════════════════════════════════════════════

def _client():
    from api.main import app
    return TestClient(app)


class TestPreviewEndpoint:
    def test_preview_requires_no_auth(self, monkeypatch):
        """다른 GET 조회 endpoint(예: /{slug}, /{slug}/status)와 동일하게 인증 없이
        공개되어야 한다 — 새 인증 체계를 도입하지 않는다."""
        _patch_common(monkeypatch, {
            "index.html": "<html><body>x</body></html>", "style.css": "", "script.js": "",
        })
        r = _client().get(f"/api/calculators/{FAKE_CALC['slug']}/preview")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["previewable"] is True

    def test_preview_not_found_returns_structured_failure(self, monkeypatch):
        _patch_common(monkeypatch, {})
        r = _client().get("/api/calculators/no-such-slug/preview")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_preview_blocked_when_not_built_is_still_http_200(self, monkeypatch):
        _patch_common(monkeypatch, {})
        r = _client().get(f"/api/calculators/{FAKE_CALC['slug']}/preview")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["previewable"] is False
        assert body["data"]["build_status"] == "not_built"

    def test_preview_is_not_a_write_route(self):
        from api.main import app
        write_paths = write_routes(app, prefix="/api/calculators")
        assert ("/api/calculators/{slug}/preview", "GET") not in write_paths
        assert not any(p == "/api/calculators/{slug}/preview" for p, _m in write_paths)


def test_real_registry_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
