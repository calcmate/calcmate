"""api/services/topic_reconciliation_service.py — published Topic ↔ WP 상태 대조 +
수동 candidate 복귀 (CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01).

dashboard.py "🔍 published Topic ↔ WP 상태 대조"(1219-1289)를 그대로 이관한다.
새 판정/전이 로직을 만들지 않는다:
  - 대조: modules.topic_wp_reconciliation.check_published_topic_wp_status()
    (READ-ONLY, WP GET 1회). 버튼을 누를 때만 실행되며 주기적 실행에 연결하지 않는다.
  - 복귀: modules.topic_pool.transition_status(cfg, topic_id, "candidate",
    actor="dashboard_operator", reason=f"wp_reconciliation_{status}", manual=True)
    — 원본과 동일한 인자. published→candidate는 topic_pool이 manual=True로만 허용한다.

원본은 직전 대조 결과(session_state)가 MISMATCH/WP_POST_NOT_FOUND일 때만 복귀 버튼을
보여줬다. API는 클라이언트가 보낸 결과를 믿지 않고 복귀 직전에 같은 대조를 1회 다시
수행해, 그 결과가 두 상태 중 하나일 때만 전이한다(대조 실패 시 상태 변경 없음).
"""
from modules import topic_pool
from modules.config_loader import load_config
from modules.topic_wp_reconciliation import check_published_topic_wp_status

REVERTABLE_STATUSES = ("MISMATCH", "WP_POST_NOT_FOUND")


class TopicNotRevertable(Exception):
    """대조 결과가 복귀 대상(MISMATCH/WP_POST_NOT_FOUND)이 아님."""

    def __init__(self, check: dict):
        super().__init__(f"복귀 대상이 아닙니다(판정: {check.get('status')})")
        self.check = check


def check_topic(topic_id: str) -> dict:
    return check_published_topic_wp_status(load_config(), topic_id)


def revert_to_candidate(topic_id: str) -> dict:
    """복귀 직전 재대조 → 복귀 대상이면 transition_status(manual=True) 1회.
    transition_status가 ValueError를 내면 Topic 상태는 그대로다(원본과 동일)."""
    cfg = load_config()
    check = check_published_topic_wp_status(cfg, topic_id)
    if check.get("status") not in REVERTABLE_STATUSES:
        raise TopicNotRevertable(check)
    topic = topic_pool.transition_status(
        cfg, topic_id, "candidate", actor="dashboard_operator",
        reason=f"wp_reconciliation_{check.get('status')}", manual=True)
    return {"check": check, "topic_id": topic_id, "status": (topic or {}).get("status", "candidate")}
