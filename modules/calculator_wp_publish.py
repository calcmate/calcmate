# -*- coding: utf-8 -*-
"""
modules/calculator_wp_publish.py — CalcMate 계산기 → WordPress 신규 글 게시 표준 진입점

사람이 "다음 CalcMate WordPress 글을 쓰기로" 결정했을 때 직접 호출하는 얇은
wrapper 하나만 제공한다. 스케줄러/트리거/자동 실행 경로는 전혀 포함하지 않는다 —
publish_calculator_post()를 누군가 직접 호출해야만 동작한다.

이미 검증된 기존 부품만 조립하며, 콘텐츠 생성 로직을 재구현하지 않는다:
  - repositories.calculator_repository.CalculatorRepository.get_by_slug()
  - content.calculator.writer.auto_generate_all()  (SEO/FAQ/본문 생성, 기존 그대로)
  - content.blog.template.build_blog_html()        (HTML 조립, 기존 그대로)
  - modules.publisher.publish()                     (comment_status/category_name/
    resolve_category_id() 포함 — 전부 기존 구현 그대로, 이 파일에서 재작성하지 않음)

WP 인증정보는 이 모듈이 직접 다루지 않는다. publisher.publish()가 내부적으로
쓰는 기존 cfg 경로(WORDPRESS_URL/WORDPRESS_USERNAME/WORDPRESS_APP_PASSWORD,
config/secrets.yaml 기반)를 그대로 통과시킬 뿐이다 — 과거 1회성 스크립트처럼
인증정보를 이 파일에 하드코딩하지 않는다.
"""
import json

from adapters.db.factory import get_db_adapter
from repositories.calculator_repository import CalculatorRepository
from content.calculator.writer import auto_generate_all
from content.blog.template import build_blog_html
from modules import publisher
from modules.logger import get_logger

LOG = get_logger()


def publish_calculator_post(slug: str, cfg: dict, *, status: str = "publish") -> dict:
    """calculator slug 하나만으로 WordPress 신규 글을 게시한다.

    실패는 전부 {"success": False, "error": <code>, "slug": slug} 형태로 반환하며,
    어떤 실패 경로도 WP POST를 실행하지 않는다(WP 쓰기 요청 자체가 발생하지 않음).

    error 코드:
      - "calculator_not_found": slug로 계산기를 찾지 못함
      - "category_missing": calculators.category가 비어 있음
      - "category_not_found:<name>": WP에 이름이 정확히 일치하는 카테고리가 없음
        (publisher.resolve_category_id()가 판정 — 이 함수는 그 결과를 그대로 전달)

    comment_status는 호출자가 지정할 필요 없이 이 함수가 항상 "closed"로
    publisher.publish()에 전달한다.
    """
    db = get_db_adapter(cfg)
    calc = CalculatorRepository(db).get_by_slug(slug)
    if not calc:
        LOG.error("[calculator_wp_publish] calculator not found: slug=%s", slug)
        return {"success": False, "error": "calculator_not_found", "slug": slug}

    category_name = (calc.get("category") or "").strip()
    if not category_name:
        LOG.error("[calculator_wp_publish] category missing: slug=%s", slug)
        return {"success": False, "error": "category_missing", "slug": slug}

    result = auto_generate_all(cfg, calc, save=False)

    faq = result.get("faq", "[]")
    if isinstance(faq, str):
        faq = json.loads(faq)

    html = build_blog_html(
        result.get("article_content", ""), faq,
        calc_slug=calc.get("slug", ""), calc_name=calc.get("name", ""),
    )

    seo = {
        "seo_title": result.get("seo_title", calc.get("name", "")),
        "seo_description": result.get("seo_description", ""),
        "slug": calc.get("slug", ""),
    }

    return publisher.publish(
        f"calc_{slug}", seo, html, {}, cfg,
        status=status,
        comment_status="closed",
        category_name=category_name,
    )
