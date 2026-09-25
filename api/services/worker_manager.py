"""api/services/worker_manager.py — Scheduler Worker 실제 상태 조회 (STEP 18-I-A).

STEP 18-C의 placeholder(모두 하드코딩 False)를 걷어내고, 기존 Scheduler 엔진의 실제 상태를
그대로 조회하도록 연결한다. FastAPI는 Scheduler 로직을 재구현하지 않는다:

- enabled: config/config.yaml의 실제 값을 api.services.config_service.ConfigService로 읽는다
  (STEP 18-C/18-E에서 이미 검증된 읽기 경로 재사용).
- running / thread_alive: dashboard.py가 실제 워커 스레드를 식별하는 것과 동일한 방식
  (dashboard.py:938 `_blog_alive = any(t.name == "blog-scheduler-loop" and t.is_alive() ...)`)을
  그대로 재사용한다 — threading.enumerate()로 실제 OS 스레드를 조회할 뿐, 새 스레드를
  만들거나 흉내내지 않는다.

FastAPI 프로세스는 lifespan에서 어떤 워커도 기동하지 않으므로(STEP 18-C 원칙 유지),
Streamlit(dashboard.py) 등 별도 프로세스가 띄운 스레드는 이 프로세스의 threading.enumerate()에
보이지 않는다 — 그 경우 running/thread_alive=False가 "모르는 상태"가 아니라 "이 프로세스
관점에서 실제로 그런 상태"이며, 정확한 값이다(mock이 아니다).
"""
import threading

from api.services.config_service import ConfigService, ConfigSectionNotAllowed

_WORKER_NAMES = ("blog", "calculator", "content_sync")

# dashboard.py가 실제로 기동하는 스레드 이름(재정의하지 않고 문자열만 재사용).
# 근거: dashboard.py:94(blog-scheduler-loop), :133(calc-webapp-scheduler-loop), :168(content-sync-loop)
_THREAD_NAMES = {
    "blog": "blog-scheduler-loop",
    "calculator": "calc-webapp-scheduler-loop",
    "content_sync": "content-sync-loop",
}

# WorkerManager 이름 → config.yaml 섹션. "calculator"는 CALC_WEBAPP_SCHEDULE에 대응한다
# (PUBLISH_SCHEDULE은 dashboard.py가 자동 기동하는 스레드가 없는 별개 라인이라 제외).
_CONFIG_SECTIONS = {
    "blog": "BLOG_SCHEDULE",
    "calculator": "CALC_WEBAPP_SCHEDULE",
    "content_sync": "CONTENT_SYNC",
}

# dashboard.py의 enabled 기본값과 동일하게 맞춘다: CONTENT_SYNC만 기본 True(dashboard.py:173),
# 나머지는 기본 False(dashboard.py:99, :137).
_ENABLED_DEFAULT = {"blog": False, "calculator": False, "content_sync": True}


def _thread_alive(name: str) -> bool:
    thread_name = _THREAD_NAMES[name]
    return any(t.name == thread_name and t.is_alive() for t in threading.enumerate())


def _config_enabled(name: str) -> bool:
    section = _CONFIG_SECTIONS[name]
    try:
        data = ConfigService().get_section(section)
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT[name]
    return bool(data.get("enabled", _ENABLED_DEFAULT[name]))


class WorkerManager:
    """blog / calculator / content_sync 실제 상태 조회 전용(STEP 18-I-A).

    이 클래스는 워커를 소유하거나 기동하지 않는다 — 매 호출마다 실제 config와 실제
    threading.enumerate() 상태를 조회만 하는 stateless 컴포넌트다. 따라서 "중복 워커"가
    생길 여지 자체가 없다(§7). start_worker()/stop_worker()는 여전히 미구현이며, 실제
    워커 기동/정지 연결은 운영전환 단계에서 별도로 설계/승인한다.
    """

    def get_status(self, name: str = None):
        if name is not None:
            if name not in _WORKER_NAMES:
                raise KeyError(f"unknown worker: {name}")
            return self._status_of(name)
        return {n: self._status_of(n) for n in _WORKER_NAMES}

    @staticmethod
    def _status_of(name: str) -> dict:
        # running과 thread_alive는 이 워커 계열에서 서로 다른 실측 신호가 없다 — 기존
        # run_scheduler_loop()/run_sync_loop()는 "처리 중"과 "폴링 대기 중"을 구분해 노출하지
        # 않으므로, 두 필드 모두 동일한 실측값(named thread의 is_alive())을 그대로 반영한다.
        alive = _thread_alive(name)
        return {
            "name": name,
            "enabled": _config_enabled(name),
            "running": alive,
            "thread_alive": alive,
        }

    def start_worker(self, name: str):
        """실제 worker loop 기동 지점(placeholder). 운영전환 단계에서 별도 검증 후 구현한다."""
        raise NotImplementedError(
            "worker 실행은 이번 STEP 범위 밖입니다 — 운영전환 단계에서 별도 설계/승인 후 구현합니다."
        )

    def stop_worker(self, name: str):
        """실제 worker loop 정지 지점(placeholder). 운영전환 단계에서 별도 검증 후 구현한다."""
        raise NotImplementedError(
            "worker 정지는 이번 STEP 범위 밖입니다 — 운영전환 단계에서 별도 설계/승인 후 구현합니다."
        )


_manager: WorkerManager | None = None


def get_worker_manager() -> WorkerManager:
    """프로세스 내 단일 WorkerManager 인스턴스를 반환한다(중복 생성 방지)."""
    global _manager
    if _manager is None:
        _manager = WorkerManager()
    return _manager
