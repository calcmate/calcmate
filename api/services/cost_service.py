"""api/services/cost_service.py — 비용/Retry Queue 조회 + 실행 서비스.

get_cost_status()는 순수 읽기 전용(STEP 18-G) — BudgetTracker.record(),
cost_manager.resume()/pause(), retry_queue.retry()/remove()/enqueue() 등 쓰기
함수를 호출하지 않는다.

STEP S5: resume_cost_manager()/retry_pending_item()은 dashboard.py의 "▶ 지금
수동 재개"/"🔁 재발행" 버튼과 동일한 실행 의미를 재현한다. cost_manager.resume()/
retry_queue.retry()를 그대로 호출하며, 새 정책(retry 횟수 제한 등)을 만들지
않는다. 서버가 실제 상태(is_paused()/list_pending())를 확인한 뒤에만 실행하고,
클라이언트가 보낸 상태값은 신뢰하지 않는다. 동일 요청 중복 실행은 in-memory
lock으로 막는다(신규 job store를 만들 필요가 없을 만큼 빠른 동기 작업이므로
GenerationJobStore 같은 무거운 구조를 새로 만들지 않는다).

STEP S6: remove_pending_item()은 dashboard.py의 "🗑 제거"와 동일 — 원본
retry_queue.remove()는 존재 여부를 확인하지 않고 조용히 no-op하므로, 여기서
list_pending()으로 먼저 존재를 확인한 뒤에만 호출한다(원본 함수는 수정하지
않는다). 동시성 가드는 Retry와 같은 _retry_in_flight 집합을 공유한다 — 같은
id에 대해 재발행과 제거가 동시에 실행되는 경쟁도 함께 막기 위함이며, 새
전역 동시성 구조를 따로 만들지 않기 위함이다.
"""
import threading

from modules.config_loader import load_config
from modules.logger import BudgetTracker
from modules import cost_manager
from modules import retry_queue

_resume_lock = threading.Lock()
_retry_lock = threading.Lock()
_retry_in_flight: set[str] = set()


def get_cost_status() -> dict:
    cfg = load_config()
    bt = BudgetTracker(cfg)
    budget = bt.check_budget()
    cm_status = cost_manager.status(cfg)
    paused = cost_manager.is_paused(cfg)
    pending = retry_queue.list_pending()

    return {
        "today": {
            "used": budget["daily_used"],
            "limit": budget["daily_limit"],
            "exceeded": budget["daily_exceeded"],
            "tokens": int(bt.get_today_tokens()),
        },
        "month": {
            "used": budget["monthly_used"],
            "limit": budget["monthly_limit"],
            "exceeded": budget["monthly_exceeded"],
        },
        "total_cost": bt.get_total_cost(),
        "by_provider_month": bt.get_provider_breakdown("monthly"),
        "by_model_month": bt.get_model_breakdown("monthly"),
        "cost_manager": {"pct": cm_status["pct"], "paused": paused},
        "retry_queue": {
            "pending_count": len(pending),
            "items": [
                {
                    "id": it.get("id"),
                    "title": (it.get("seo") or {}).get("seo_title", ""),
                    "created_at": it.get("created_at", ""),
                    "error": (it.get("error") or "")[:200],
                }
                for it in pending[:20]
            ],
        },
    }


def resume_cost_manager() -> dict:
    """dashboard.py "▶ 지금 수동 재개"와 동일 — paused 상태일 때만
    cost_manager.resume()을 호출한다. 반환: {"ok": bool, "message": str}."""
    if not _resume_lock.acquire(blocking=False):
        return {"ok": False, "message": "다른 재개 요청이 이미 처리 중입니다."}
    try:
        try:
            cfg = load_config()
            if not cost_manager.is_paused(cfg):
                return {"ok": False, "message": "일시정지 상태가 아닙니다 — 재개할 대상이 없습니다."}
            cost_manager.resume(cfg)
            return {"ok": True, "message": "재개됨"}
        except Exception as e:
            return {"ok": False, "message": f"재개 실패: {e}"}
    finally:
        _resume_lock.release()


def retry_pending_item(pid: str) -> dict:
    """dashboard.py "🔁 재발행"과 동일 — 서버가 실제 Retry Queue를 확인한 뒤에만
    retry_queue.retry()를 호출한다. 반환: {"ok": bool, "message": str}."""
    pid = str(pid or "").strip()
    if not pid:
        return {"ok": False, "message": "id가 필요합니다."}

    with _retry_lock:
        if pid in _retry_in_flight:
            return {"ok": False, "message": "이미 처리 중인 항목입니다."}
        item = next((i for i in retry_queue.list_pending() if i.get("id") == pid), None)
        if item is None:
            return {"ok": False, "message": "대기 항목 없음(존재하지 않거나 이미 처리됨)."}
        _retry_in_flight.add(pid)

    try:
        try:
            cfg = load_config()
            ok, msg = retry_queue.retry(cfg, pid)
            return {"ok": ok, "message": msg}
        except Exception as e:
            return {"ok": False, "message": f"재발행 실패: {e}"}
    finally:
        with _retry_lock:
            _retry_in_flight.discard(pid)


def remove_pending_item(pid: str) -> dict:
    """dashboard.py "🗑 제거"와 동일 — 서버가 실제 Retry Queue를 확인한 뒤에만
    retry_queue.remove()를 호출한다. 반환: {"ok": bool, "message": str}."""
    pid = str(pid or "").strip()
    if not pid:
        return {"ok": False, "message": "id가 필요합니다."}

    with _retry_lock:
        if pid in _retry_in_flight:
            return {"ok": False, "message": "이미 처리 중인 항목입니다."}
        item = next((i for i in retry_queue.list_pending() if i.get("id") == pid), None)
        if item is None:
            return {"ok": False, "message": "대기 항목 없음(존재하지 않거나 이미 처리됨)."}
        _retry_in_flight.add(pid)

    try:
        try:
            retry_queue.remove(pid)
            return {"ok": True, "message": "제거됨"}
        except Exception as e:
            return {"ok": False, "message": f"제거 실패: {e}"}
    finally:
        with _retry_lock:
            _retry_in_flight.discard(pid)
