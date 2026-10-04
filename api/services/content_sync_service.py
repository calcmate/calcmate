"""api/services/content_sync_service.py — Content Sync 수동 실행 서비스.

STEP S10: dashboard.py "🔄 Sync Now" 버튼(dashboard.py:899-930)과 동일한 실행
의미를 재현한다. modules.content_sync.run_sync_once()를 그대로 호출하며, 새로운
동기화 규칙/판정 로직을 만들지 않는다.

중복 실행 방지는 modules.content_sync._acquire_lock()/_release_lock()(파일 기반
lock, data/schedule/content_sync.lock)을 그대로 재사용한다 — 새 in-memory lock을
만들지 않는다. 이 lock은 프로세스 간(Streamlit의 자동 03:00 백그라운드 스레드 +
FastAPI의 수동 실행) 상호배제를 위해 파일 기반이어야 한다(api/main.py는 자동
worker loop를 기동하지 않으므로, in-memory lock만으로는 Streamlit이 아직 실행
중일 때의 충돌을 막을 수 없다).
"""
from modules.config_loader import load_config
from modules import content_sync as CS


class ContentSyncBusy(Exception):
    """다른 동기화(자동 03:00 스레드 또는 다른 수동 실행)가 이미 lock을 보유 중."""


def run_once(mode: str) -> dict:
    """반환: modules.content_sync.run_sync_once()의 결과 dict 그대로(가공하지
    않음) — {"ok": bool, "reason": str(선택), "mode", "checked", "changed",
    "skipped", "anomalies", ...}. lock 획득 실패 시 ContentSyncBusy를 던진다
    (라우터에서 명확한 실패 응답으로 변환)."""
    cfg = load_config()
    if not CS._acquire_lock(cfg):
        raise ContentSyncBusy("다른 동기화가 진행 중입니다(자동 03:00 또는 다른 실행). 잠시 후 재시도하세요.")
    try:
        return CS.run_sync_once(cfg, mode=mode)
    finally:
        CS._release_lock(cfg)
