# -*- coding: utf-8 -*-
"""api/services/topic_pool_service.py — Topic Pool 조회 서비스
(CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01).

modules.topic_pool.list_topics()를 그대로 호출하는 thin wrapper다 — 정렬/필터
로직을 이 파일에 재구현하지 않는다. React가 예약/Planner UI를 구성하는 데 필요한
최소 필드만 선택해 반환한다(전체 topic_pool 행을 그대로 노출하지 않음).
"""
from modules.config_loader import load_config
from modules import topic_pool

_FIELDS = ("topic_id", "slug", "topic", "title", "status", "priority", "created_at", "approved_at")


def list_topics(status: str | None = None) -> list[dict]:
    cfg = load_config()
    topics = topic_pool.list_topics(cfg, status=status)
    return [{k: t.get(k) for k in _FIELDS} for t in topics]
