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

# WP REST의 공개 상태 값.
_WP_PUBLISHED_STATUS = "publish"

# CALCMATE-TOPIC-DRAFT-STATUS-FIX-C-IMPLEMENT-01: Topic="published"는 "WP post 생성
# 성공(draft 포함)"을 뜻하므로(topic_publish_adapter), 기대 WP 상태는 Topic이 아니라
# 그 Topic을 실행한 reservation의 요청 모드로 정한다.
#   reservation.mode(우선) → 기대 WP status
_MODE_TO_WP_STATUS = {"draft": "draft", "publish": _WP_PUBLISHED_STATUS}
#   mode가 없는 legacy reservation용 fallback: result.results[0].status(요청값 에코)
_RESULT_STATUS_TO_WP_STATUS = {"DRAFT": "draft", "PUBLISHED": _WP_PUBLISHED_STATUS}


def _find_reservation_info_for_topic(cfg: dict, topic: dict) -> dict:
    """topic["oneoff_reservation_id"]로만 reservation을 찾아
    {"wp_post_id", "reservation_mode", "result_status"}를 반환한다(없는 값은 None)."""
    info = {"wp_post_id": None, "reservation_mode": None, "result_status": None}
    reservation_id = str(topic.get("oneoff_reservation_id") or "").strip()
    if not reservation_id:
        return info

    import modules.scheduler as scheduler
    local_cfg = dict(cfg)
    local_cfg["scheduler_line"] = "blog"

    for entry in scheduler.load_oneoff(local_cfg):
        if entry.get("id") != reservation_id:
            continue
        info["reservation_mode"] = entry.get("mode") or None
        result = entry.get("result") or {}
        results_list = result.get("results") or []
        if results_list:
            info["wp_post_id"] = results_list[0].get("wp_post_id") or None
            info["result_status"] = results_list[0].get("status") or None
        return info
    return info


def _find_wp_post_id_for_topic(cfg: dict, topic: dict):
    """topic["oneoff_reservation_id"]로만 wp_post_id를 찾는다. 없으면 None."""
    return _find_reservation_info_for_topic(cfg, topic)["wp_post_id"]


def _expected_wp_status(reservation_mode, result_status):
    """reservation.mode 우선, 없으면 results[0].status fallback. 둘 다 없으면 None."""
    if reservation_mode:
        return _MODE_TO_WP_STATUS.get(str(reservation_mode).strip().lower())
    if result_status:
        return _RESULT_STATUS_TO_WP_STATUS.get(str(result_status).strip().upper())
    return None


def check_published_topic_wp_status(cfg: dict, topic_id: str) -> dict:
    """published Topic 1건의 WP 실제 상태를 조회해 대조한다(READ-ONLY, WP GET만).

    Returns:
        {"status": <아래 중 하나>, "topic_id": str, "wp_post_id": int|None,
         "wp_status": str|None, "expected_wp_status": str|None,
         "reservation_mode": str|None}
        (expected_wp_status/reservation_mode는 additive 필드 — 기존 호출부는
         status/wp_post_id/wp_status만 사용한다)

        기대 WP status: reservation.mode("draft"→draft, "publish"→publish).
        mode가 없는 legacy reservation은 result.results[0].status
        ("DRAFT"→draft, "PUBLISHED"→publish)를 fallback으로 사용한다.

        status 값:
          - "TOPIC_NOT_FOUND": topic_id가 Topic Pool에 없음
          - "TOPIC_NOT_PUBLISHED": topic은 있으나 status != "published"
          - "WP_POST_ID_UNAVAILABLE": oneoff_reservation_id가 없거나, 그
            reservation에서 wp_post_id를 찾을 수 없음(추측하지 않음)
          - "MODE_UNAVAILABLE": wp_post_id는 있으나 mode와 results[0].status가
            모두 없어 기대 WP status를 정할 수 없음(WP GET 없이 종료)
          - "WP_POST_NOT_FOUND": WP가 HTTP 404를 반환(영구 삭제로 추정)
          - "WP_CHECK_ERROR": WP GET이 404 이외의 이유로 실패(네트워크 오류 등,
            추측성 판정을 피하기 위해 MATCH/MISMATCH 어느 쪽으로도 단정하지 않음)
          - "MATCH": WP status == 기대 WP status
          - "UNEXPECTED_PUBLISHED": draft로 요청했는데 WP가 publish(사람이 공개했을
            수 있음 — MISMATCH와 달리 candidate 복귀 대상이 아님)
          - "MISMATCH": 그 외(publish 요청인데 draft, trash, private/pending/future 등)
    """
    def _result(status, wp_post_id=None, wp_status=None, expected=None, mode=None):
        return {"status": status, "topic_id": topic_id, "wp_post_id": wp_post_id,
                "wp_status": wp_status, "expected_wp_status": expected,
                "reservation_mode": mode}

    topic = topic_pool.get_topic(cfg, topic_id)
    if topic is None:
        return _result("TOPIC_NOT_FOUND")

    if topic.get("status") != "published":
        return _result("TOPIC_NOT_PUBLISHED")

    info = _find_reservation_info_for_topic(cfg, topic)
    wp_post_id = info["wp_post_id"]
    mode = info["reservation_mode"]
    if not wp_post_id:
        return _result("WP_POST_ID_UNAVAILABLE", mode=mode)

    expected = _expected_wp_status(mode, info["result_status"])
    if expected is None:
        return _result("MODE_UNAVAILABLE", wp_post_id=wp_post_id, mode=mode)

    wp = cfg.get("wordpress", {}) or {}
    wp_url = wp.get("url") or WP_PRODUCTION_URL
    wp_result = get_wp_post_readonly(
        wp_post_id, wp_url=wp_url,
        username=wp.get("username", ""), app_password=wp.get("app_password", ""),
    )

    if not wp_result.get("success"):
        if wp_result.get("http_status") == 404:
            return _result("WP_POST_NOT_FOUND", wp_post_id=wp_post_id,
                           expected=expected, mode=mode)
        return _result("WP_CHECK_ERROR", wp_post_id=wp_post_id,
                       expected=expected, mode=mode)

    wp_status = wp_result.get("status", "")
    if wp_status == expected:
        verdict = "MATCH"
    elif expected == "draft" and wp_status == _WP_PUBLISHED_STATUS:
        verdict = "UNEXPECTED_PUBLISHED"
    else:
        verdict = "MISMATCH"
    return _result(verdict, wp_post_id=wp_post_id, wp_status=wp_status,
                   expected=expected, mode=mode)
