"""api/services/strategy_room_service.py — Strategy Room(전략회의실) 실행 서비스.

dashboard.py "🧠 전략회의실" 탭(elif tab == "🧠 전략회의실":)과 동일한 실행 의미를
재현한다. modules.strategy_room.run_strategy_room()을 그대로 호출하며, 새로운
분석 로직/프롬프트를 만들지 않는다.

analytics 수집도 dashboard.py가 실제로 채우는 필드(total_published, recent_posts)만
그대로 재현한다 — run_strategy_room()이 참조하는 category_ctr/time_slots/
low_ctr_posts는 dashboard.py 자체도 채우지 않으므로(기존 동작), 여기서도 채우지
않는다(추측/보강 금지).

run_strategy_room()은 원본 자체가 내부에서 모든 예외를 흡수해 빈 dict({})를
반환하도록 설계돼 있다(비활성 상태 포함) — 이 함수를 호출하는 바깥쪽에서 예외가
발생하는 경우(예: import 실패 등 진짜 예상 밖의 오류)만 별도로 잡아 명확한 실패로
반환한다(dashboard.py의 바깥쪽 try/except와 동일한 위치의 방어).
"""
import threading

from modules.config_loader import load_config
from modules.dashboard_cache import read as cache_read

# STEP S8: Strategy Room도 AI 호출 비용이 발생하는 실행 액션이므로, S5의
# Cost Manager Resume과 동일한 이유로 in-memory lock을 둔다(대상 id가 없는
# 전역 액션이라 Resume과 동일하게 단일 lock으로 충분 — 새 job store를 만들지 않는다).
_run_lock = threading.Lock()


def _collect_analytics(cfg: dict) -> dict:
    """dashboard.py:3032-3044의 운영 데이터 수집과 정확히 동일 — 실패해도 빈 값으로
    진행한다(예외를 삼키고 부분/빈 analytics로 계속)."""
    analytics = {}
    try:
        posts = cache_read(cfg, "articles")
        published = [p for p in posts if p.get("상태값") in ("발행완료", "검수대기")]
        published.sort(key=lambda x: x.get("발행일시", ""), reverse=True)
        analytics["total_published"] = len(published)
        analytics["recent_posts"] = [
            {"title": p.get("최종추천제목", ""), "url": p.get("발행 URL", ""),
             "date": p.get("발행일시", "")}
            for p in published[:7]
        ]
    except Exception:
        pass
    return analytics


def run_strategy_room_analysis() -> dict:
    """반환: {"enabled": bool, "result": dict, "error": str|None}.

    enabled=False는 cfg.get("ENABLE_STRATEGY_ROOM", True)를 그대로 반영한다
    (run_strategy_room() 내부에서도 동일 체크를 하므로 이중 방어 — 클라이언트가
    무엇을 보내든 서버가 실제 cfg 값만 신뢰한다. 이 endpoint는 애초에 body를
    받지 않는다). 동시/중복 요청은 lock으로 즉시 차단(불필요한 AI 비용 중복 방지)."""
    if not _run_lock.acquire(blocking=False):
        return {"enabled": True, "result": {}, "error": "다른 전략회의실 실행이 이미 진행 중입니다."}
    try:
        cfg = load_config()
        enabled = bool(cfg.get("ENABLE_STRATEGY_ROOM", True))
        analytics = _collect_analytics(cfg)
        try:
            from modules.strategy_room import run_strategy_room
            result = run_strategy_room(analytics, cfg)
            return {"enabled": enabled, "result": result or {}, "error": None}
        except Exception as e:
            return {"enabled": enabled, "result": {}, "error": f"전략회의실 실행 중 오류: {e}"}
    finally:
        _run_lock.release()
