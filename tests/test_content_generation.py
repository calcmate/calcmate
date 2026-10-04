# -*- coding: utf-8 -*-
"""tests/test_content_generation.py — P0-4: 계산기 콘텐츠 생성 React/FastAPI 이관.

dashboard.py "🤖 AI 자동 생성"(SEO/FAQ/본문/이미지 개별 버튼 + "⚡ 전체 자동생성")과 동일한
생성기(modules.calculator_seo_generator/calculator_faq_generator/content.calculator.writer/
modules.calculator_image_prompt_generator)를 재사용하는
api.services.calculator_service.generate_calculator_content_*()를 검증한다.

안전 설계: 실제 DB/Registry/AI 호출 없음 — 전부 monkeypatch로 대체한다. 신규 계산기를
생성하거나 기존 계산기를 실제로 수정하지 않는다(fake 데이터만 사용).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from _route_utils import write_routes

_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "content-gen-test-admin-token"
VIEWER_TOKEN = "content-gen-test-viewer-token"

FAKE_CALC = {"id": "calc_1", "slug": "fake-slug", "name": "가짜 계산기", "status": "active"}
OTHER_CALC = {"id": "calc_2", "slug": "other-slug", "name": "다른 계산기", "status": "active"}


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()


class _FakeRepo:
    def __init__(self):
        self.update_generated_calls = []

    def get_by_slug(self, slug):
        if slug == FAKE_CALC["slug"]:
            return dict(FAKE_CALC)
        if slug == OTHER_CALC["slug"]:
            return dict(OTHER_CALC)
        return None

    def get_all(self):
        return [dict(FAKE_CALC), dict(OTHER_CALC)]

    def update_generated(self, cid, data):
        self.update_generated_calls.append((cid, dict(data)))


def _patch_common(monkeypatch, *, is_golden10=False):
    import api.services.calculator_service as svc

    fake_repo = _FakeRepo()
    monkeypatch.setattr(svc, "_repo_and_cfg", lambda: (fake_repo, {}))
    monkeypatch.setattr(svc, "_registry", lambda: {FAKE_CALC["slug"]: {}, OTHER_CALC["slug"]: {}})
    monkeypatch.setattr("content.blog.is_golden10", lambda slug: is_golden10)
    return fake_repo


GOOD_SEO = {"seo_title": "가짜 계산기 안내", "seo_description": "가짜 계산기를 계산하는 방법"}
GOOD_FAQ = [{"question": "가짜 계산기는 어떻게 쓰나요?", "answer": "값을 입력하면 됩니다"}]
GOOD_ARTICLE = "<h1>가짜 계산기</h1>" + "<p>가짜 계산기 사용법을 설명합니다.</p>" * 30
GOOD_IMG = {"thumbnail": "가짜 계산기 아이콘 일러스트", "body": "가짜 계산기 사용 장면"}
CONTAMINATED_ARTICLE = "<h1>다른 계산기</h1><p>다른 계산기 사용법을 설명합니다.</p>"


# ══════════════════════════════════════════════════════════════════════════
# SEO
# ══════════════════════════════════════════════════════════════════════════

class TestGenerateContentSeo:
    def test_saves_when_qa_passes(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_seo_generator.generate_seo_title",
                             lambda cfg, calc: GOOD_SEO["seo_title"])
        monkeypatch.setattr("modules.calculator_seo_generator.generate_meta_description",
                             lambda cfg, calc: GOOD_SEO["seo_description"])

        result = svc.generate_calculator_content_seo(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert result["saved"] is True
        assert fake_repo.update_generated_calls == [(FAKE_CALC["id"], GOOD_SEO)]

    def test_blocked_by_cross_contamination(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_seo_generator.generate_seo_title",
                             lambda cfg, calc: "다른 계산기 안내")
        monkeypatch.setattr("modules.calculator_seo_generator.generate_meta_description",
                             lambda cfg, calc: "다른 계산기를 계산하는 방법")

        result = svc.generate_calculator_content_seo(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert any(f["gate"] == "CROSS_CONTAMINATION" for f in result["qa"]["failed"])
        assert fake_repo.update_generated_calls == []

    def test_blocked_by_golden10(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch, is_golden10=True)
        result = svc.generate_calculator_content_seo(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["saved"] is False
        assert "Golden10" in result["blocked_reason"]
        assert fake_repo.update_generated_calls == []

    def test_generation_exception_blocks_without_saving(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)

        def _boom(cfg, calc):
            raise RuntimeError("OPENAI_API_KEY missing")
        monkeypatch.setattr("modules.calculator_seo_generator.generate_seo_title", _boom)

        result = svc.generate_calculator_content_seo(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["saved"] is False
        assert "생성 실패" in result["blocked_reason"]
        assert fake_repo.update_generated_calls == []

    def test_not_found_raises(self, monkeypatch):
        import api.services.calculator_service as svc
        _patch_common(monkeypatch)
        with pytest.raises(svc.CalculatorNotFound):
            svc.generate_calculator_content_seo("no-such-slug")


# ══════════════════════════════════════════════════════════════════════════
# FAQ
# ══════════════════════════════════════════════════════════════════════════

class TestGenerateContentFaq:
    def test_saves_when_qa_passes(self, monkeypatch):
        import api.services.calculator_service as svc
        import json as _json
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_faq_generator.generate_faq", lambda cfg, calc: GOOD_FAQ)

        result = svc.generate_calculator_content_faq(FAKE_CALC["slug"])
        assert result["saved"] is True
        assert fake_repo.update_generated_calls == [
            (FAKE_CALC["id"], {"faq": _json.dumps(GOOD_FAQ, ensure_ascii=False)})
        ]

    def test_blocked_by_empty_faq(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_faq_generator.generate_faq", lambda cfg, calc: [])

        result = svc.generate_calculator_content_faq(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert any(f["gate"] == "EMPTY" for f in result["qa"]["failed"])
        assert fake_repo.update_generated_calls == []


# ══════════════════════════════════════════════════════════════════════════
# 본문(Body)
# ══════════════════════════════════════════════════════════════════════════

class TestGenerateContentBody:
    def test_saves_when_qa_and_legal_current_pass(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("content.calculator.writer.generate_article", lambda *a, **kw: GOOD_ARTICLE)
        monkeypatch.setattr("modules.law_ssot.get_ssot_prompt_block", lambda slug: "")
        monkeypatch.setattr("modules.content_integrity.check_g_legal_current", lambda article, slug: [])
        monkeypatch.setattr("modules.content_integrity.build_content_tracking_fields",
                             lambda article, slug, source: {"content_source": source})

        result = svc.generate_calculator_content_body(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert result["saved"] is True
        assert len(fake_repo.update_generated_calls) == 1
        cid, payload = fake_repo.update_generated_calls[0]
        assert cid == FAKE_CALC["id"]
        assert payload["article_content"] == GOOD_ARTICLE
        assert payload["content_source"] == "api_body_generate"

    def test_blocked_by_cross_contamination(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("content.calculator.writer.generate_article",
                             lambda *a, **kw: CONTAMINATED_ARTICLE)
        monkeypatch.setattr("modules.law_ssot.get_ssot_prompt_block", lambda slug: "")
        monkeypatch.setattr("modules.content_integrity.check_g_legal_current", lambda article, slug: [])

        result = svc.generate_calculator_content_body(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert any(f["gate"] == "CROSS_CONTAMINATION" for f in result["qa"]["failed"])
        assert fake_repo.update_generated_calls == []

    def test_blocked_by_legal_current_failure(self, monkeypatch):
        """P0-4: 본문의 G-LEGAL-CURRENT는 레거시(비차단 warning)와 달리 저장을 차단한다."""
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("content.calculator.writer.generate_article", lambda *a, **kw: GOOD_ARTICLE)
        monkeypatch.setattr("modules.law_ssot.get_ssot_prompt_block", lambda slug: "")
        monkeypatch.setattr(
            "modules.content_integrity.check_g_legal_current",
            lambda article, slug: [{"gate": "G-LEGAL-CURRENT", "grade": "critical", "detail": "낡은 수치"}],
        )

        result = svc.generate_calculator_content_body(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert any(f["gate"] == "G-LEGAL-CURRENT" for f in result["qa"]["failed"])
        assert fake_repo.update_generated_calls == []

    def test_no_api_key_raises_and_does_not_return_mock(self, monkeypatch):
        """P0-4 회귀 고정: OPENAI_API_KEY 없음 → generate_article()이 실제 예외를 던지고
        (계산기 무관 하드코딩 mock을 더 이상 반환하지 않음), body endpoint는 이를
        생성 실패로 명확히 처리한다."""
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)

        def _real_generate_article_raises_without_key(*a, **kw):
            from modules.ai_provider import build_provider_for_role
            build_provider_for_role("writing", {})  # cfg에 OPENAI_API_KEY 없음 -> KeyError
        monkeypatch.setattr("content.calculator.writer.generate_article",
                             _real_generate_article_raises_without_key)
        monkeypatch.setattr("modules.law_ssot.get_ssot_prompt_block", lambda slug: "")

        result = svc.generate_calculator_content_body(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["saved"] is False
        assert result["content"] is None
        assert "주휴수당" not in str(result)
        assert fake_repo.update_generated_calls == []


# ══════════════════════════════════════════════════════════════════════════
# 이미지 프롬프트
# ══════════════════════════════════════════════════════════════════════════

class TestGenerateContentImage:
    def test_saves_when_qa_passes(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_thumbnail_prompt",
                             lambda cfg, calc: GOOD_IMG["thumbnail"])
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_body_prompt",
                             lambda cfg, calc: GOOD_IMG["body"])

        result = svc.generate_calculator_content_image(FAKE_CALC["slug"])
        assert result["saved"] is True
        assert fake_repo.update_generated_calls == [
            (FAKE_CALC["id"], {"image_prompt_thumbnail": GOOD_IMG["thumbnail"],
                               "image_prompt_body": GOOD_IMG["body"]})
        ]

    def test_english_prompt_without_korean_identity_tokens_still_saves(self, monkeypatch):
        """실 E2E(annual-leave-remaining, 실제 Gemini/GPT 호출)에서 발견된 오탐 고정:
        이미지 프롬프트는 modules/calculator_image_prompt_generator.py 설계상 영문으로
        시각적 개념만 묘사한다(계산기의 한글 이름이 문자 그대로 등장하지 않음) — 이를
        '무관한 콘텐츠'로 오판해 차단하면 안 된다(require_identity=False)."""
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        english_img = {
            "thumbnail": "Modern, minimalist vector illustration of a calendar with a highlighted "
                         "number, symbolizing remaining days. Clean lines, professional color palette.",
            "body": "A realistic, professional photograph of an organized office desk.",
        }
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_thumbnail_prompt",
                             lambda cfg, calc: english_img["thumbnail"])
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_body_prompt",
                             lambda cfg, calc: english_img["body"])

        result = svc.generate_calculator_content_image(FAKE_CALC["slug"])
        assert result["saved"] is True
        assert not any(f["gate"] == "IDENTITY" for f in result["qa"]["failed"])
        assert len(fake_repo.update_generated_calls) == 1

    def test_blocked_by_empty_prompt(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_thumbnail_prompt",
                             lambda cfg, calc: "")
        monkeypatch.setattr("modules.calculator_image_prompt_generator.generate_body_prompt",
                             lambda cfg, calc: GOOD_IMG["body"])

        result = svc.generate_calculator_content_image(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert fake_repo.update_generated_calls == []


# ══════════════════════════════════════════════════════════════════════════
# 전체 생성(Full)
# ══════════════════════════════════════════════════════════════════════════

def _good_gen_result(review_status="AUTO_APPROVED"):
    import json as _json
    return {
        "seo_title": GOOD_SEO["seo_title"], "seo_description": GOOD_SEO["seo_description"],
        "seo_desc": GOOD_SEO["seo_description"],
        "faq": _json.dumps(GOOD_FAQ, ensure_ascii=False),
        "article_content": GOOD_ARTICLE,
        "image_prompt_thumbnail": GOOD_IMG["thumbnail"], "image_prompt_body": GOOD_IMG["body"],
        "review_status": review_status, "review_score": 90 if review_status != "NEEDS_REVIEW" else 40,
        "review_reason": "ok", "review_attempts": 0, "reviewed_at": "2026-01-01T00:00:00",
        "_saved": False,
    }


class TestGenerateContentFull:
    def test_saves_when_qa_and_review_pass(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("content.calculator.writer.auto_generate_all",
                             lambda cfg, calc, save, auto_review: _good_gen_result("AUTO_APPROVED"))
        monkeypatch.setattr("modules.content_integrity.build_content_tracking_fields",
                             lambda article, slug, source: {"content_source": source})

        result = svc.generate_calculator_content_full(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert result["saved"] is True
        assert result["review"]["review_status"] == "AUTO_APPROVED"
        assert len(fake_repo.update_generated_calls) == 1

    def test_needs_review_does_not_save(self, monkeypatch):
        """P0-4: 레거시 auto_generate_all은 NEEDS_REVIEW여도 항상 저장했다 — 여기서는
        저장하지 않는다(운영 안전성 우선, STEP 7 판단)."""
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)
        monkeypatch.setattr("content.calculator.writer.auto_generate_all",
                             lambda cfg, calc, save, auto_review: _good_gen_result("NEEDS_REVIEW"))

        result = svc.generate_calculator_content_full(FAKE_CALC["slug"])
        assert result["ok"] is True
        assert result["saved"] is False
        assert "NEEDS_REVIEW" in result["blocked_reason"]
        assert fake_repo.update_generated_calls == []

    def test_cross_contamination_blocks_before_review_check(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)

        def _contaminated(cfg, calc, save, auto_review):
            gen = _good_gen_result("AUTO_APPROVED")
            gen["article_content"] = CONTAMINATED_ARTICLE
            return gen
        monkeypatch.setattr("content.calculator.writer.auto_generate_all", _contaminated)

        result = svc.generate_calculator_content_full(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert any(f["gate"] == "CROSS_CONTAMINATION" for f in result["qa"]["failed"])
        assert fake_repo.update_generated_calls == []

    def test_blocked_by_golden10(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch, is_golden10=True)
        result = svc.generate_calculator_content_full(FAKE_CALC["slug"])
        assert result["saved"] is False
        assert "Golden10" in result["blocked_reason"]
        assert fake_repo.update_generated_calls == []

    def test_generation_exception_blocks(self, monkeypatch):
        import api.services.calculator_service as svc
        fake_repo = _patch_common(monkeypatch)

        def _boom(cfg, calc, save, auto_review):
            raise RuntimeError("생성 실패")
        monkeypatch.setattr("content.calculator.writer.auto_generate_all", _boom)

        result = svc.generate_calculator_content_full(FAKE_CALC["slug"])
        assert result["ok"] is False
        assert result["saved"] is False
        assert fake_repo.update_generated_calls == []


# ══════════════════════════════════════════════════════════════════════════
# 실제 endpoint(React가 호출) 통합 테스트 — 인증/응답 envelope
# ══════════════════════════════════════════════════════════════════════════

def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


CONTENT_ENDPOINTS = ["seo", "faq", "body", "image", "generate"]


class TestContentEndpoints:
    @pytest.fixture(autouse=True)
    def _isolated_tokens(self, monkeypatch):
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
        monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
        yield

    @pytest.mark.parametrize("path", CONTENT_ENDPOINTS)
    def test_without_auth_returns_401(self, path):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/content/{path}")
        assert r.status_code == 401

    @pytest.mark.parametrize("path", CONTENT_ENDPOINTS)
    def test_as_viewer_returns_403(self, path):
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/content/{path}", headers=_auth(VIEWER_TOKEN))
        assert r.status_code == 403

    @pytest.mark.parametrize("path", CONTENT_ENDPOINTS)
    def test_not_found_returns_404(self, path, monkeypatch):
        _patch_common(monkeypatch)
        r = _client().post(f"/api/calculators/no-such-slug/content/{path}", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 404

    def test_seo_endpoint_returns_structured_blocked_result_as_200(self, monkeypatch):
        _patch_common(monkeypatch, is_golden10=True)
        r = _client().post(f"/api/calculators/{FAKE_CALC['slug']}/content/seo", headers=_auth(ADMIN_TOKEN))
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["saved"] is False
        assert "Golden10" in body["data"]["blocked_reason"]


def test_content_write_routes_registered():
    from api.main import app
    write_paths = sorted(write_routes(app, prefix="/api/calculators"))
    for path in CONTENT_ENDPOINTS:
        assert (f"/api/calculators/{{slug}}/content/{path}", "POST") in write_paths


def test_real_registry_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
