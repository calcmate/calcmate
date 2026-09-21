# -*- coding: utf-8 -*-
"""
modules/topic_wp_reconciliation.py — published Topic 1건의 WordPress 실제
상태를 조회·대조하는 READ-ONLY 전용 모듈.
(CALCMATE-AUTO-CONTENT-PUBLISHED-WP-RECONCILIATION-GAP-FOLLOWUP-DECISION-01)

GAP-AUDIT-01에서 확인된 GAP: Topic이 "published"에 도달한 뒤 그 WP post가
외부에서 trash/삭제되어도 시스템이 이를 감지할 방법이 없었다(자동 대조 없음).

이 모듈은 그 GAP 중 "감지"만 담당한다(채택된 후보 A). 오직 조회와 판정만
수행하며, 어떤 경우에도 Topic 상태를 변경하거나 WP를 수정하지 않는다 —
자동 candidate 전환/자동 republish/자동 restore/자동 WP POST·PUT·DELETE는
전부 이 모듈의 책임이 아니다(범위 밖, 후보 B 채택 안 함).

WP post와의 연결은 오직 다음 경로만 사용한다(추측/fuzzy matching 없음):
    topic.oneoff_reservation_id
    -> scheduler.load_oneoff()에서 동일 id의 reservation 조회
    -> reservation["result"]["results"][0]["wp_post_id"]
이 경로로 wp_post_id를 찾을 수 없으면 WP_POST_ID_UNAVAILABLE로 판정하고
끝낸다(WP를 검색하지 않음).
"""
from modules import topic_pool
from modules.wp_readonly_client import get_wp_post_readonly, WP_PRODUCTION_URL

# WP post의 실제 status가 이 값이면 Topic="published"와 일치(MATCH)한다.
_WP_PUBLISHED_STATUS = "publish"


def _find_wp_post_id_for_topic(cfg: dict, topic: dict):
    """topic["oneoff_reservation_id"]로만 wp_post_id를 찾는다. 없으면 None."""
    reservation_id = str(topic.get("oneoff_reservation_id") or "").strip()
    if not reservation_id:
        return None

    import modules.scheduler as scheduler
    local_cfg = dict(cfg)
    local_cfg["scheduler_line"] = "blog"

    for entry in scheduler.load_oneoff(local_cfg):
        if entry.get("id") != reservation_id:
            continue
        result = entry.get("result") or {}
        results_list = result.get("results") or []
        if results_list:
            wp_post_id = results_list[0].get("wp_post_id")
            if wp_post_id:
                return wp_post_id
        return None
    return None


def check_published_topic_wp_status(cfg: dict, topic_id: str) -> dict:
    """published Topic 1건의 WP 실제 상태를 조회해 대조한다(READ-ONLY, WP GET만).

    Returns:
        {"status": <아래 중 하나>, "topic_id": str, "wp_post_id": int|None,
         "wp_status": str|None}

        status 값:
          - "TOPIC_NOT_FOUND": topic_id가 Topic Pool에 없음
          - "TOPIC_NOT_PUBLISHED": topic은 있으나 status != "published"
          - "WP_POST_ID_UNAVAILABLE": oneoff_reservation_id가 없거나, 그
            reservation에서 wp_post_id를 찾을 수 없음(추측하지 않음)
          - "WP_POST_NOT_FOUND": WP가 HTTP 404를 반환(영구 삭제로 추정)
          - "WP_CHECK_ERROR": WP GET이 404 이외의 이유로 실패(네트워크 오류 등,
            추측성 판정을 피하기 위해 MATCH/MISMATCH 어느 쪽으로도 단정하지 않음)
          - "MATCH": WP status == "publish"(Topic=published와 일치)
          - "MISMATCH": WP status가 draft/trash/기타 publish가 아닌 값
    """
    topic = topic_pool.get_topic(cfg, topic_id)
    if topic is None:
        return {"status": "TOPIC_NOT_FOUND", "topic_id": topic_id,
                "wp_post_id": None, "wp_status": None}

    if topic.get("status") != "published":
        return {"status": "TOPIC_NOT_PUBLISHED", "topic_id": topic_id,
                "wp_post_id": None, "wp_status": None}

    wp_post_id = _find_wp_post_id_for_topic(cfg, topic)
    if not wp_post_id:
        return {"status": "WP_POST_ID_UNAVAILABLE", "topic_id": topic_id,
                "wp_post_id": None, "wp_status": None}

    wp = cfg.get("wordpress", {}) or {}
    wp_url = wp.get("url") or WP_PRODUCTION_URL
    wp_result = get_wp_post_readonly(
        wp_post_id, wp_url=wp_url,
        username=wp.get("username", ""), app_password=wp.get("app_password", ""),
    )

    if not wp_result.get("success"):
        if wp_result.get("http_status") == 404:
            return {"status": "WP_POST_NOT_FOUND", "topic_id": topic_id,
                    "wp_post_id": wp_post_id, "wp_status": None}
        return {"status": "WP_CHECK_ERROR", "topic_id": topic_id,
                "wp_post_id": wp_post_id, "wp_status": None}

    wp_status = wp_result.get("status", "")
    verdict = "MATCH" if wp_status == _WP_PUBLISHED_STATUS else "MISMATCH"
    return {"status": verdict, "topic_id": topic_id,
            "wp_post_id": wp_post_id, "wp_status": wp_status}
