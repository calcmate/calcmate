# -*- coding: utf-8 -*-
"""
modules/topic_generation_request.py — Topic Pool -> 기존 Blog Generation 연결 계약
(CALCMATE-AUTO-CONTENT-TOPIC-IMPLEMENT-02)

경계:
    Topic Pool (modules/topic_pool.py)
        v
    TopicGenerationRequest (이 모듈) — 강한 입력 검증
        v
    기존 Blog Generation entry point(content.blog.writer.auto_generate_blog_all)
        -> 내부에서 기존 9-gate run_integrity_gates()를 그대로 통과

이 모듈이 하지 않는 것(다음 단계 범위):
    - AI Topic 자동 생성
    - 실제 generate_fn 프로덕션 연결(호출자가 명시적으로 주입해야 하며 기본값이
      없다 — 이 모듈이 실수로 실제 generation을 실행하지 않도록 하는 안전장치)
    - Publishing Planner / Dashboard / One-off Scheduler 연결
    - WordPress 호출(WP category ID resolve 포함)

기존 BlogScheduleRequest(modules/blog_scheduler_adapter.py)와의 차이:
    BlogScheduleRequest는 slug가 Golden10 membership을 갖는 것을 강제한다(신규
    topic은 애초에 Golden10에 없으므로 이 경로를 쓸 수 없다). 이 모듈의
    TopicGenerationRequest는 Golden10 membership을 요구하지 않는 대신(오히려
    Golden10과 겹치면 명시적으로 거부한다 — 아래 validate() 참고),
    calculator_id의 실제 DB 존재 여부를 직접 조회해 검증 약화가 되지 않도록
    한다. 두 계약은 서로 다른 클래스이며 서로 참조/상속하지 않는다.

설계 리뷰(IMPLEMENT-02 STEP3, "approved -> generation_failed/schedule_failed"):
    이 모듈이 제공하는 call_generation_entry_point()는 아직 스케줄이 배정되지
    않은 "approved" 상태의 topic에 대해 스케줄링 이전 단계에서 호출되는 것을
    전제로 설계됐다 — 즉 콘텐츠 생성 시도는 approved 상태에서 발생하고, 생성이
    성공하면 Publishing Planner가 스케줄을 배정(배정 실패 시 schedule_failed),
    생성 자체가 실패하면 generation_failed로 기록된다(modules/topic_pool.py::
    record_failure()). 따라서 IMPLEMENT-01에서 추가된 "approved ->
    generation_failed/schedule_failed" 전이는 구조적으로 필요하다고 확인되며
    이번 STEP에서는 유지한다(state machine 자체는 변경하지 않음).
"""
from dataclasses import dataclass

from content.blog import VALID_INTENTS, is_golden10, validate_intent


# ── DB 조회 헬퍼(READ-ONLY, 어떤 테이블도 수정하지 않음) ──────────────────

def _find_calculator_by_id(cfg: dict, calculator_id: str) -> dict | None:
    from adapters.db.factory import get_calculator_storage_adapter
    adapter = get_calculator_storage_adapter(cfg)
    rows = adapter.get_where("calculators", {"id": calculator_id})
    return rows[0] if rows else None


def _slug_exists_in_blog_articles(cfg: dict, slug: str) -> bool:
    from adapters.db.factory import get_blog_article_storage_adapter
    adapter = get_blog_article_storage_adapter(cfg)
    rows = adapter.get_where("blog_articles", {"slug": slug})
    return bool(rows)


# ── TopicGenerationRequest ───────────────────────────────────────────

@dataclass
class TopicGenerationRequest:
    """Topic Pool의 topic 1건 -> Blog Generation 입력 계약.

    최소 필드: calculator_id, slug, topic, title, intent (필수) /
    description, category (선택, 기본값 "").

    validate(cfg)를 호출하기 전까지는 어떤 검증도 수행되지 않는다(dataclass
    생성 자체는 항상 성공— BlogScheduleRequest와 동일한 관례)."""
    calculator_id: str
    slug: str
    topic: str
    title: str
    intent: str
    description: str = ""
    category: str = ""

    def validate(self, cfg: dict) -> list[str]:
        """검증 — 오류 메시지 리스트 반환(빈 리스트면 정상).

        DB는 READ-ONLY로만 조회한다(calculators/blog_articles 어느 것도
        수정하지 않음). Golden10(GOLDEN_10/`_GOLDEN_MAP`)도 읽기만 한다."""
        errors: list[str] = []

        if not str(self.calculator_id or "").strip():
            errors.append("calculator_id is empty")
        else:
            calc = _find_calculator_by_id(cfg, self.calculator_id)
            if calc is None:
                errors.append(f"calculator_id not found: {self.calculator_id}")

        if not str(self.slug or "").strip():
            errors.append("slug is empty")
        else:
            if is_golden10(self.slug):
                errors.append(
                    f"slug collides with Golden10 (신규 topic은 Golden10 slug를 "
                    f"사용할 수 없습니다): {self.slug}"
                )
            elif _slug_exists_in_blog_articles(cfg, self.slug):
                errors.append(f"slug already used in blog_articles: {self.slug}")

        if not isinstance(self.topic, str) or not self.topic.strip():
            errors.append("topic is empty")

        if not isinstance(self.title, str) or not self.title.strip():
            errors.append("title is empty")

        if not isinstance(self.description, str):
            errors.append("description must be a string")

        if not validate_intent(self.intent):
            errors.append(
                f"Invalid intent: {self.intent!r}. Must be one of {sorted(VALID_INTENTS)}"
            )

        if not isinstance(self.category, str):
            errors.append("category must be a string")

        return errors


# ── 기존 Blog Generation entry point와의 연결 계약 ────────────────────

def build_generation_post(cfg: dict, request: TopicGenerationRequest) -> dict:
    """calculator_id로 DB에서 계산기 원본(READ-ONLY)을 읽어, 기존
    auto_generate_blog_all(cfg, post, ...)의 post 인자와 동일한 shape의 dict를
    반환한다. modules/blog_scheduler_adapter.py::_load_calculator()가 반환하는
    row와 동일한 구조(같은 adapter, 같은 테이블)이므로 기존 generation 경로가
    그대로 소비할 수 있다. DB write 없음.

    CALCMATE-ONEOFF-GCALC-CONTEXT-WIRING-IMPLEMENT-01: modules/calculator_wp_publish.py
    (기존 Calculator 자체 블로그 생성 경로)와 동일하게 content.calculator.
    example_builder.build_example_context(calc)를 호출해 post["example_context"]를
    채운다 — 이 호출 하나만 추가하며 build_example_context()/run_integrity_gates()/
    G-CALC 자체는 전혀 수정하지 않는다. 미등록 slug는 None을 그대로 반환하므로
    (build_example_context()의 기존 계약), 그 경우 post["example_context"]=None이
    되어 지금까지의 동작(G-CALC vacuous PASS)과 완전히 동일하게 유지된다 —
    즉 이 변경은 "예시가 등록된 calculator만 실제로 검증되기 시작"하는 순수
    additive 변경이다."""
    calc = _find_calculator_by_id(cfg, request.calculator_id)
    if calc is None:
        raise ValueError(f"calculator_id not found: {request.calculator_id}")
    from content.calculator.example_builder import build_example_context
    calc = dict(calc)
    calc["example_context"] = build_example_context(calc)
    return calc


def call_generation_entry_point(cfg: dict, request: TopicGenerationRequest, *,
                                 generate_fn) -> dict:
    """검증 -> 기존 Blog Generation entry point 호출까지의 계약.

    순서: validate() -> build_generation_post()(READ-ONLY) -> generate_fn(...).
    generate_fn이 실제 content.blog.writer.auto_generate_blog_all이면 그 내부에서
    기존 9-gate run_integrity_gates()가 그대로 실행되므로, 이 함수는 그 게이트를
    우회하거나 재구현하지 않는다.

    generate_fn은 호출자가 반드시 명시적으로 주입해야 한다(기본값 없음) — 이
    STEP에서는 실제 생성을 실행하지 않으며, production 연결(예: 실제
    auto_generate_blog_all 주입)은 다음 단계(Publishing Planner)의 범위다.
    save=False로 고정 호출해 DB 저장을 방지한다."""
    errors = request.validate(cfg)
    if errors:
        raise ValueError(f"TopicGenerationRequest validation failed: {errors}")
    post = build_generation_post(cfg, request)
    return generate_fn(cfg, post, save=False, intent=request.intent)
