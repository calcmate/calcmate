"""api/services/workboard_service.py — 작업 현황 보드(Kanban) 조회 서비스.

STEP S9: dashboard.py "📋 작업 보드" 탭(elif tab == "📋 작업 보드":, dashboard.py:534-557)
과 정확히 동일한 6개 컬럼 그룹핑을 그대로 재현한다. 순수 읽기 전용 — 상태 변경/
드래그앤드롭/DB write 등 새 기능을 추가하지 않는다.

데이터 소스는 log_service.py/publish_service.py가 이미 쓰는 것과 동일한
modules.dashboard_cache.read(cfg, "articles")(dashboard.py의 cached_posts()와
동일 메커니즘)를 그대로 재사용한다 — 새 조회 로직을 만들지 않는다.

정렬: 원본 dashboard.py 코드에 정렬이 전혀 없다(입력 순서 그대로 필터링만) —
여기서도 임의로 정렬을 추가하지 않는다.
"""
from modules.config_loader import load_config
from modules.dashboard_cache import read as cache_read

from api.services.log_service import mask_secrets

# dashboard.py:542-548의 6개 컬럼 정의와 정확히 동일(제목/이모지/상태값 매핑 그대로 포트).
KANBAN_COLUMNS = [
    ("🟡 수집중", ["대기", "진행중"]),
    ("🔵 작성중", ["작성중"]),
    ("🟠 검수중", ["검수대기"]),
    ("⏳ 발행대기", ["보류", "복구대기", "재처리대기"]),
    ("🟢 발행완료", ["발행완료"]),
    ("🔴 오류", ["작성오류", "이미지오류", "발행실패", "만료"]),
]

# dashboard.py:555-557의 카드 표시 규칙과 정확히 동일(제목만, 22자 절삭 + …).
_CARD_LIMIT = 15
_TITLE_MAX = 22


def _card_title(row: dict) -> str:
    t = str(row.get("최종추천제목") or row.get("정책명") or "(제목없음)")
    t = mask_secrets(t)
    return t[:_TITLE_MAX] + ("…" if len(t) > _TITLE_MAX else "")


def get_workboard() -> dict:
    """반환: {"columns": [{"title": str, "count": int, "items": [{"id", "title"}]}]}.

    count는 dashboard.py의 st.metric("건수", len(items))과 동일하게 컬럼의 실제
    전체 건수다(items 배열 자체는 dashboard.py의 items[:15]와 동일하게 15개로
    제한된다 — 화면에 나열되는 카드 수와 정확히 일치시키기 위함)."""
    cfg = load_config()
    posts = cache_read(cfg, "articles")

    columns = []
    for title, states in KANBAN_COLUMNS:
        items = [p for p in posts if p.get("상태값") in states]
        columns.append({
            "title": title,
            "count": len(items),
            "items": [
                {"id": p.get("ID", ""), "title": _card_title(p)}
                for p in items[:_CARD_LIMIT]
            ],
        })
    return {"columns": columns}
