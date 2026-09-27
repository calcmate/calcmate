# -*- coding: utf-8 -*-
"""
modules/topic_publish_adapter.py — Topic Pool topic 1건을 One-off Scheduler가
실행할 수 있게 하는 실행 계층(CALCMATE-AUTO-CONTENT-TOPIC-GAP3-IMPLEMENT-01)

GAP3-READONLY-DESIGN-AUDIT-01에서 확정한 설계의 "실행 함수" 부분을 구현한다.
기존 modules/blog_scheduler_adapter.py::run_blog_once_wp()(Golden10 전용,
GOLDEN_10[:max_count] 순회)와 병렬로 존재하는 별도 경로이며, 그 함수를
수정하지 않는다 — 오직 Topic Pool의 topic_id 1건을 대상으로 한다.

실행 순서(설계 audit STEP6 그대로):
    topic_id
      -> topic_pool.get_topic() 조회
      -> 존재 확인(없으면 fail-closed)
      -> status=="scheduled" 확인(아니면 fail-closed)
      -> scheduled -> publishing 전환
      -> TopicGenerationRequest 생성(modules/topic_generation_request.py 재사용)
      -> call_generation_entry_point()(재사용, 새 generation API 신설 없음)
      -> FINAL WP duplicate check(_check_wp_duplicate 재사용, 새 알고리즘 신설 없음)
      -> publisher.publish() 재사용(새 WP REST 구현 신설 없음)
      -> 성공: publishing -> published
      -> 실패(생성 오류/게이트 차단/중복확정/중복확인실패/WP오류 전부 포함):
         publishing -> publish_failed
         (이 함수의 상태 다이어그램은 scheduled->publishing->published/publish_failed
         두 갈래만 정의한다 — GAP3-IMPLEMENT-01 STEP7 지시대로 이 STEP에서 새로운
         중간 상태를 임의로 만들지 않는다)

Topic Pool 상태는 이 함수 내부에서만 변경한다 — modules/scheduler.py(Scheduler)는
이 함수를 호출만 하고 Topic Pool을 전혀 import하지 않는다(설계 audit STEP9/11 결론).

테스트 용이성을 위해 generate_fn/publish_fn/dup_check_fn을 주입 가능하게 하되,
기본값은 항상 기존 프로덕션 함수를 그대로 가리킨다(새 함수를 만들지 않음,
지연 import로 무거운 의존성을 테스트에서 강제하지 않음)."""
from modules import topic_pool
from modules.topic_generation_request import (
    TopicGenerationRequest,
    call_generation_entry_point,
)


def _default_generate_fn(cfg, post, save=False, intent=None):
    from content.blog.writer import auto_generate_blog_all
    return auto_generate_blog_all(cfg, post, save=save, intent=intent)


def _default_publish_fn(post_id, seo, article, images, cfg, status="draft",
                         category_name: str | None = None,
                         comment_status: str | None = None):
    """CALCMATE-AUTO-CONTENT-WP-METADATA-GAP-IMPLEMENT-01: category_name/
    comment_status는 신규 keyword-only 옵트인 인자(기본값 None)다. 기존
    호출부가 이 두 인자 없이 호출하면(위치 인자 5개까지만) publisher.publish()도
    그대로 None/None을 받아 기존과 동일하게 동작한다 — publisher.py 자체는
    이미 이 두 인자를 지원하므로(modules/publisher.py:101-103) 이 함수는 그저
    그대로 전달만 한다(새 로직 없음)."""
    import modules.publisher as publisher
    return publisher.publish(post_id, seo, article, images, cfg, status=status,
                             category_name=category_name, comment_status=comment_status)


# SINGLE-OWNER-HARDENING M2: WP REST는 status를 지정하지 않으면 publish만 반환해
# 기존 draft(예: WP 599)를 놓친다. Topic 경로 전용으로 비공개 상태까지 조회한다.
# Golden10 경로(blog_scheduler_adapter._check_wp_duplicate)는 건드리지 않는다.
_TOPIC_DUP_STATUSES = "publish,draft,pending,private,future"


def check_topic_wp_duplicate(cfg: dict, slug: str) -> dict:
    """Topic 전용 WP slug 중복 확인(READ-ONLY GET, FAIL-CLOSED).

    반환 계약은 _check_wp_duplicate와 동일:
      {"exists", "confirmed", "wp_post_id", "slug", "error"}
    "중복 없음"은 HTTP 200 + 빈 list일 때만 확정된다. URL/인증 누락, non-200,
    예외, 비정상 응답은 모두 confirmed=False → 호출부가 새 post 생성을 막는다.
    비공개 상태 조회(context=edit)에는 인증이 필수다."""
    def _fail(error):
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": error}

    wp_url = (cfg.get("WORDPRESS_URL") or "").rstrip("/")
    if not wp_url:
        return _fail("no_wp_url")
    username = cfg.get("WORDPRESS_USERNAME", "")
    app_password = cfg.get("WORDPRESS_APP_PASSWORD", "")
    if not (username and app_password):
        return _fail("no_wp_auth")
    try:
        import requests
        resp = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            params={"slug": slug, "status": _TOPIC_DUP_STATUSES,
                    "context": "edit", "per_page": 1},
            auth=(username, app_password), timeout=10,
        )
    except Exception as e:
        return _fail(f"request_error:{e}")
    if resp.status_code != 200:
        return _fail(f"http_{resp.status_code}")
    try:
        posts = resp.json()
    except Exception as e:
        return _fail(f"decode_error:{e}")
    if not isinstance(posts, list):
        return _fail("unexpected_response_type")
    if posts:
        try:
            return {"exists": True, "confirmed": True,
                    "wp_post_id": posts[0].get("id"), "slug": posts[0].get("slug"),
                    "error": None}
        except Exception as e:
            return _fail(f"malformed_post_entry:{e}")
    return {"exists": False, "confirmed": True, "wp_post_id": None,
            "slug": None, "error": None}


def _default_dup_check_fn(cfg, slug):
    return check_topic_wp_duplicate(cfg, slug)


def run_topic_once_wp(cfg: dict, topic_id: str, status: str = "draft",
                       max_count: int = 1, *, driver_id: str = None,
                       generate_fn=None, publish_fn=None, dup_check_fn=None) -> dict:
    """One-off Scheduler의 run_once_fn(cfg, max_count) 계약을 만족하는 Topic
    전용 실행 함수. topic_id/status는 main.py::resolve_blog_oneoff_publish_fn()이
    partial()로 미리 묶어 전달하므로, 실제 호출 시점에는 (cfg, max_count)만
    받으면 된다(기존 run_blog_once_wp와 동일한 관례).

    max_count는 계약 호환을 위해 받지만 의미상 항상 1건(이 topic_id 자신)만
    처리한다(Golden10 배치처럼 여러 건을 순회하지 않음).

    Returns:
        {"produced": 0|1, "reason": str, "results": [dict]}
    """
    generate_fn = generate_fn or _default_generate_fn
    publish_fn = publish_fn or _default_publish_fn
    dup_check_fn = dup_check_fn or _default_dup_check_fn

    if not str(topic_id or "").strip():
        return {"produced": 0, "reason": "missing_topic_id",
                "results": [{"status": "ERROR", "reason": "missing_topic_id"}]}

    topic = topic_pool.get_topic(cfg, topic_id)
    if topic is None:
        return {"produced": 0, "reason": "topic_not_found",
                "results": [{"topic_id": topic_id, "status": "ERROR",
                             "reason": "topic_not_found"}]}

    if topic.get("status") != "scheduled":
        return {"produced": 0, "reason": "invalid_topic_status",
                "results": [{"topic_id": topic_id, "status": "ERROR",
                             "reason": f"expected status=scheduled, got "
                                       f"{topic.get('status')!r}"}]}

    topic_pool.transition_status(cfg, topic_id, "publishing", actor="oneoff_scheduler",
                                  reason="oneoff_execution_started")

    def _fail(reason: str, error: str = "") -> dict:
        topic_pool.transition_status(cfg, topic_id, "publish_failed",
                                      actor="oneoff_scheduler", reason=reason)
        return {"produced": 0, "reason": reason,
                "results": [{"topic_id": topic_id, "status": "PUBLISH_FAILED",
                             "reason": reason, "error": error}]}

    request = TopicGenerationRequest(
        calculator_id=topic.get("calculator_id", ""),
        slug=topic.get("slug", ""),
        topic=topic.get("topic", ""),
        title=topic.get("title", ""),
        intent=topic.get("intent", ""),
        description=topic.get("description", ""),
        category=topic.get("category", ""),
    )

    try:
        gen_result = call_generation_entry_point(cfg, request, generate_fn=generate_fn)
    except Exception as e:
        return _fail("generation_error", str(e)[:300])

    article = gen_result.get("article_content", "") if isinstance(gen_result, dict) else ""
    if gen_result.get("blocked") if isinstance(gen_result, dict) else False:
        return _fail("integrity_gate_blocked",
                     str(gen_result.get("integrity_failed", ""))[:300])
    if not article or len(article) < 100:
        return _fail("empty_article")

    try:
        dup = dup_check_fn(cfg, topic["slug"])
    except Exception as e:
        return _fail("duplicate_check_error", str(e)[:300])

    if not dup.get("confirmed"):
        return _fail("duplicate_check_failed", dup.get("error", "unknown"))
    if dup.get("exists"):
        return _fail("wp_duplicate_exists", str(dup.get("wp_post_id", "")))

    seo = {
        "seo_title": topic.get("title", ""),
        "seo_description": topic.get("description", ""),
        "slug": topic["slug"],
    }
    post_id = f"topic_{topic_id}"
    try:
        # GAP-IMPLEMENT-01: Topic Pool 자체의 category 필드(계산기의 category와는
        # 별개 — WP-METADATA-GAP-AUDIT-01에서 확인된 대로 계산기 원본 category는
        # WP 카테고리 이름과 일치하지 않을 수 있어 사용하지 않음)를 그대로
        # category_name으로 전달하고, Topic 자동발행에서는 comment_status를
        # 항상 "closed"로 고정한다(호출자가 명시하지 않아도 WP 기본값에
        # 의존하지 않음). resolve_category_id()의 기존 fail-closed 동작
        # (일치하는 카테고리가 없으면 WP POST 자체를 하지 않음)은 무변경.
        pub_result = publish_fn(post_id, seo, article, {}, cfg, status=status,
                                category_name=topic.get("category", ""),
                                comment_status="closed")
    except Exception as e:
        return _fail("publish_error", str(e)[:300])

    pub_status = pub_result.get("status", "") if isinstance(pub_result, dict) else ""
    if pub_status not in ("published", "draft"):
        return _fail("publish_failed", str(pub_result.get("error", "unknown")))

    topic_pool.transition_status(cfg, topic_id, "published", actor="oneoff_scheduler",
                                  reason="wp_publish_succeeded")
    return {
        "produced": 1,
        "reason": "",
        "results": [{
            "topic_id": topic_id, "status": "PUBLISHED" if pub_status == "published" else "DRAFT",
            "wp_post_id": pub_result.get("wp_post_id", ""),
            "wp_permalink": pub_result.get("wp_permalink", ""),
            "article_len": len(article),
        }],
    }
