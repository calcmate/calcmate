# -*- coding: utf-8 -*-
"""
tests/test_topic_generation_request.py
CALCMATE-AUTO-CONTENT-TOPIC-IMPLEMENT-02 — TopicGenerationRequest
validation/adapter 계약 검증.

전부 production config(load_config())의 실제 DB를 READ-ONLY로만 조회한다
(calculator_id 존재 확인/slug 충돌 확인). 어떤 테스트도 calculators/
blog_articles/Golden10을 수정하지 않으며, WordPress를 호출하지 않는다
(modules.publisher는 이 파일에서 import하지 않는다).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.config_loader import load_config
from modules.topic_generation_request import (
    TopicGenerationRequest,
    build_generation_post,
    call_generation_entry_point,
)
from content.blog import GOLDEN_10
from modules.blog_scheduler_adapter import BlogScheduleRequest


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def real_calculator_id(cfg):
    """DB에 실제로 존재하는 calculator_id 1개(READ-ONLY 조회만)."""
    from adapters.db.factory import get_calculator_storage_adapter
    rows = get_calculator_storage_adapter(cfg).get_all("calculators")
    assert rows, "테스트 전제 조건: calculators 테이블에 최소 1건이 있어야 한다"
    return rows[0]["id"]


def _req(real_calculator_id, **overrides):
    kwargs = dict(
        calculator_id=real_calculator_id,
        slug="brand-new-topic-slug-for-test-2260921",
        topic="신규 topic 문자열",
        title="신규 제목",
        intent="howto",
    )
    kwargs.update(overrides)
    return TopicGenerationRequest(**kwargs)


# ── 정상 케이스 ───────────────────────────────────────────────────────

class TestValidRequests:
    def test_new_calculator_new_slug_valid_intent_passes(self, cfg, real_calculator_id):
        req = _req(real_calculator_id)
        assert req.validate(cfg) == []

    def test_slug_not_in_golden10_passes(self, cfg, real_calculator_id):
        golden_slugs = {gc.slug for gc in GOLDEN_10}
        req = _req(real_calculator_id, slug="definitely-not-golden10-slug-xyz")
        assert req.slug not in golden_slugs
        assert req.validate(cfg) == []

    @pytest.mark.parametrize("intent", ["eligibility", "howto", "documents", "calculator"])
    def test_each_valid_intent_passes(self, cfg, real_calculator_id, intent):
        req = _req(real_calculator_id, intent=intent,
                    slug=f"brand-new-slug-intent-{intent}")
        assert req.validate(cfg) == []


# ── 실패 케이스 ───────────────────────────────────────────────────────

class TestInvalidRequests:
    def test_empty_calculator_id_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, calculator_id="")
        errors = req.validate(cfg)
        assert any("calculator_id" in e for e in errors)

    def test_nonexistent_calculator_id_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, calculator_id="calc_does_not_exist_999")
        errors = req.validate(cfg)
        assert any("not found" in e for e in errors)

    def test_empty_slug_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, slug="")
        errors = req.validate(cfg)
        assert any("slug is empty" in e for e in errors)

    def test_empty_topic_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, topic="")
        errors = req.validate(cfg)
        assert any("topic is empty" in e for e in errors)

    def test_empty_title_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, title="")
        errors = req.validate(cfg)
        assert any("title is empty" in e for e in errors)

    def test_invalid_intent_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, intent="not_a_real_intent")
        errors = req.validate(cfg)
        assert any("Invalid intent" in e for e in errors)

    def test_invalid_category_type_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, category=12345)
        errors = req.validate(cfg)
        assert any("category" in e for e in errors)

    def test_invalid_description_type_fails(self, cfg, real_calculator_id):
        req = _req(real_calculator_id, description=12345)
        errors = req.validate(cfg)
        assert any("description" in e for e in errors)

    def test_golden10_slug_is_rejected(self, cfg, real_calculator_id):
        """신규 topic이 기존 Golden10 slug를 그대로 가져다 쓰는 것은 충돌로
        간주해 거부한다(Golden10 membership을 요구하지 않는 것과는 별개)."""
        golden_slug = GOLDEN_10[0].slug
        req = _req(real_calculator_id, slug=golden_slug)
        errors = req.validate(cfg)
        assert any("Golden10" in e for e in errors)

    def test_multiple_errors_all_reported(self, cfg):
        req = _req("", slug="", topic="", title="", intent="bogus")
        errors = req.validate(cfg)
        assert len(errors) >= 4


# ── Golden10 보호 ─────────────────────────────────────────────────────

def test_golden10_unchanged_before_after_validation(cfg, real_calculator_id):
    import hashlib
    before = hashlib.sha256(repr(GOLDEN_10).encode()).hexdigest()
    before_list = list(GOLDEN_10)

    req = _req(real_calculator_id)
    req.validate(cfg)
    bad_req = _req(real_calculator_id, slug=GOLDEN_10[0].slug)
    bad_req.validate(cfg)

    from content.blog import GOLDEN_10 as GOLDEN_10_AFTER
    after = hashlib.sha256(repr(GOLDEN_10_AFTER).encode()).hexdigest()
    assert before == after
    assert before_list == list(GOLDEN_10_AFTER)
    assert GOLDEN_10 is GOLDEN_10_AFTER


def test_golden10_object_not_mutated_by_repeated_validation(cfg, real_calculator_id):
    req = _req(real_calculator_id)
    for _ in range(5):
        req.validate(cfg)
    assert len(GOLDEN_10) == 10


# ── BlogScheduleRequest와의 분리 ─────────────────────────────────────

class TestSeparationFromBlogScheduleRequest:
    def test_blog_schedule_request_requires_golden10_membership(self):
        """기존 계약(BlogScheduleRequest)은 여전히 Golden10 membership을
        강제해야 한다 — 이번 STEP이 그 동작을 손상시키지 않았는지 확인."""
        req = BlogScheduleRequest(slug="brand-new-topic-slug-for-test",
                                   intent="howto")
        errors = req.validate()
        assert any("Golden 10" in e for e in errors)

    def test_topic_generation_request_does_not_require_golden10_membership(
        self, cfg, real_calculator_id
    ):
        """반대로 TopicGenerationRequest는 Golden10 membership을 요구하지
        않는다 — 신규(비Golden10) slug가 정상 통과함을 재확인."""
        req = _req(real_calculator_id, slug="separation-check-new-slug")
        errors = req.validate(cfg)
        assert errors == []

    def test_golden10_member_slug_valid_for_blog_schedule_but_not_for_topic_gen(
        self, cfg, real_calculator_id
    ):
        golden = GOLDEN_10[0]
        blog_req = BlogScheduleRequest(slug=golden.slug, intent=golden.intent)
        assert blog_req.validate() == []

        topic_req = _req(real_calculator_id, slug=golden.slug, intent=golden.intent)
        assert topic_req.validate(cfg) != []


# ── 기존 Blog Generation과의 연결 계약(mock/stub만 사용, 실제 생성 없음) ──

class TestGenerationEntryPointContract:
    def test_build_generation_post_returns_calculator_row(self, cfg, real_calculator_id):
        req = _req(real_calculator_id)
        post = build_generation_post(cfg, req)
        assert post["id"] == real_calculator_id

    # CALCMATE-ONEOFF-GCALC-CONTEXT-WIRING-IMPLEMENT-01: build_generation_post()가
    # build_example_context(calc)를 호출해 example_context/verified_examples를
    # 채우는지 확인한다(READ-ONLY, DB write 없음, WP 호출 없음).
    def test_build_generation_post_fills_example_context_for_registered_calculator(self, cfg):
        from adapters.db.factory import get_calculator_storage_adapter
        rows = get_calculator_storage_adapter(cfg).get_where("calculators", {"slug": "severance-pay"})
        assert rows, "테스트 전제 조건: severance-pay calculator가 DB에 있어야 한다"
        calculator_id = rows[0]["id"]

        req = _req(calculator_id, slug="brand-new-topic-slug-gcalc-wiring-test")
        post = build_generation_post(cfg, req)

        assert post.get("example_context") is not None
        examples = post["example_context"].get("verified_examples")
        assert isinstance(examples, list) and len(examples) > 0
        for ex in examples:
            assert "inputs" in ex and "result" in ex

    def test_build_generation_post_leaves_example_context_none_for_unregistered_calculator(self, cfg, real_calculator_id, monkeypatch):
        # example_builder.PROVIDERS에 없는 slug -> build_example_context()가 None을
        # 반환하는 기존 계약이 그대로 유지되는지 확인(하위호환, vacuous PASS 동작 불변).
        import modules.topic_generation_request as tgr

        def _fake_find(cfg, calculator_id):
            return {"id": calculator_id, "slug": "no-such-provider-registered-anywhere"}

        monkeypatch.setattr(tgr, "_find_calculator_by_id", _fake_find)
        req = _req(real_calculator_id, slug="brand-new-topic-slug-gcalc-wiring-test-2")
        post = build_generation_post(cfg, req)
        assert post.get("example_context") is None

    def test_build_generation_post_raises_for_missing_calculator(self, cfg):
        req = _req("calc_does_not_exist_999")
        with pytest.raises(ValueError):
            build_generation_post(cfg, req)

    def test_call_generation_entry_point_invokes_stub_with_correct_args(
        self, cfg, real_calculator_id
    ):
        captured = {}

        def _stub_generate_fn(cfg_arg, post_arg, save=True, intent=None):
            captured["cfg"] = cfg_arg
            captured["post"] = post_arg
            captured["save"] = save
            captured["intent"] = intent
            return {"article_content": "STUB_ARTICLE", "generation_metadata": {}}

        req = _req(real_calculator_id, intent="eligibility")
        result = call_generation_entry_point(cfg, req, generate_fn=_stub_generate_fn)

        assert result["article_content"] == "STUB_ARTICLE"
        assert captured["post"]["id"] == real_calculator_id
        assert captured["save"] is False
        assert captured["intent"] == "eligibility"

    def test_call_generation_entry_point_raises_on_validation_failure_without_calling_stub(
        self, cfg
    ):
        called = {"count": 0}

        def _stub_generate_fn(*a, **kw):
            called["count"] += 1
            return {}

        req = _req("", slug="")
        with pytest.raises(ValueError):
            call_generation_entry_point(cfg, req, generate_fn=_stub_generate_fn)
        assert called["count"] == 0

    def test_generate_fn_requires_explicit_injection(self, cfg, real_calculator_id):
        """generate_fn에 기본값이 없어 호출자가 반드시 명시해야 한다(실제
        generation이 실수로 실행되는 것을 막는 안전장치)."""
        req = _req(real_calculator_id)
        with pytest.raises(TypeError):
            call_generation_entry_point(cfg, req)  # generate_fn 누락

    def test_module_does_not_import_publisher(self):
        """이 계약 모듈 자체는 modules.publisher를 import하지 않는다 —
        WordPress 호출 경로와 완전히 분리되어 있음을 보장."""
        import modules.topic_generation_request as tgr
        assert "publisher" not in dir(tgr)
        src = Path(tgr.__file__).read_text(encoding="utf-8")
        assert "modules.publisher" not in src
        assert "import publisher" not in src
