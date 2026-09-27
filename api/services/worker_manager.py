"""api/services/worker_manager.py — Scheduler Worker 관리 (STEP 18-I-A 확장).

FastAPI 프로세스 내 worker lifecycle을 관리한다:
- Blog Scheduler (recurring publish_slots)
- Blog One-off Scheduler (one-off reservations)

기존 scheduler core 로직(modules/scheduler.py)은 재작성하지 않고 그대로 재사용한다.
"""
import os
import threading
import time
from typing import Callable, Optional

from api.services.config_service import ConfigService, ConfigSectionNotAllowed

# Worker names managed by FastAPI
_WORKER_NAMES = ("blog", "oneoff")

# Thread names (must match dashboard.py for status consistency)
_THREAD_NAMES = {
    "blog": "blog-scheduler-loop",
    "oneoff": "blog-oneoff-scheduler-loop",
}

# Worker name -> config section mapping
_CONFIG_SECTIONS = {
    "blog": "BLOG_SCHEDULE",
    "oneoff": "BLOG_SCHEDULE",  # One-off uses BLOG_SCHEDULE for Golden10 gating
}

# AUTO_PUBLISHING section for oneoff gating
_AUTO_PUBLISHING_SECTION = "AUTO_PUBLISHING"

# Enabled defaults matching dashboard.py
_ENABLED_DEFAULT = {"blog": False, "oneoff": False}

# Internal thread registry
_worker_threads: dict[str, threading.Thread] = {}
_worker_stop_events: dict[str, threading.Event] = {}
_worker_lock = threading.RLock()


def _thread_alive(name: str) -> bool:
    """Check if worker thread is alive by name."""
    with _worker_lock:
        thread = _worker_threads.get(name)
    if thread is None:
        return False
    return thread.is_alive()


def _config_enabled(name: str) -> bool:
    """Check if worker is enabled in config.yaml."""
    section = _CONFIG_SECTIONS.get(name)
    if not section:
        return _ENABLED_DEFAULT.get(name, False)
    try:
        data = ConfigService().get_section(section)
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT.get(name, False)
    return bool(data.get("enabled", _ENABLED_DEFAULT.get(name, False)))


def _auto_publishing_enabled() -> bool:
    """Check if AUTO_PUBLISHING is enabled (for oneoff worker)."""
    try:
        data = ConfigService().get_section("AUTO_PUBLISHING")
    except ConfigSectionNotAllowed:
        return False
    return bool(data.get("enabled", False))


_WP_TARGET_ENV = "CALCMATE_WP_TARGET"


def _build_worker_cfg() -> dict:
    """Worker 전용 runtime cfg(CALCMATE-WP-ENDPOINT-FIX-IMPLEMENT-01).

    이전에는 ConfigService().get_section("BLOG_SCHEDULE")(BLOG_SCHEDULE 안쪽 dict,
    secrets 미병합)만 넘겨 WORDPRESS_*/MODEL_* 등이 전부 빠졌다(no_wp_url).
    이제 standalone launcher(scripts/run_blog_oneoff_scheduler_loop.build_blog_cfg)와
    동일하게 load_config() 전체 cfg에 scheduler_line/_root만 덧붙인다.

    CALCMATE_WP_TARGET 환경변수는 오직 여기서만 읽는다(미설정 = "local"). 같은
    uvicorn 프로세스의 API route들은 인자 없는 load_config()를 쓰므로 이 값의
    영향을 받지 않는다. 허용값 검증은 load_config()의 _apply_wp_target()이
    ConfigError로 수행한다(fallback 없음)."""
    import logging
    from urllib.parse import urlparse
    from modules.config_loader import load_config

    target = (os.environ.get(_WP_TARGET_ENV) or "local").strip().lower()
    cfg = load_config(wp_target=target)
    cfg["scheduler_line"] = "blog"
    cfg["_root"] = os.getcwd()
    logging.getLogger("worker").info(
        "Worker cfg: wp_target=%s wp_host=%s", target,
        urlparse(cfg.get("WORDPRESS_URL") or "").hostname)
    return cfg


def _worker_enabled(name: str) -> bool:
    """Check if worker should be started based on config."""
    if name == "blog":
        return _config_enabled("blog")
    if name == "oneoff":
        return _config_enabled("oneoff") or _auto_publishing_enabled()
    return False


class WorkerManager:
    """Blog Scheduler & One-off Scheduler lifecycle manager.

    Manages worker threads for:
    - blog: recurring publish_slots scheduler (run_scheduler_loop)
    - oneoff: one-off reservation scheduler (run_oneoff_scheduler_loop)

    Reuses existing scheduler core logic from modules.scheduler.
    """

    def __init__(self):
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def get_status(self, name: str = None):
        """Get worker status (enabled, running, thread_alive)."""
        if name is not None:
            if name not in _WORKER_NAMES:
                raise KeyError(f"unknown worker: {name}")
            return self._status_of(name)
        return {n: self._status_of(n) for n in _WORKER_NAMES}

    def _status_of(self, name: str) -> dict:
        alive = _thread_alive(name)
        return {
            "name": name,
            "enabled": _worker_enabled(name),
            "running": alive,
            "thread_alive": alive,
        }

    def start_worker(self, name: str) -> bool:
        """Start a worker thread if enabled and not already running.

        Returns:
            True if worker started, False if already running or disabled.
        """
        if name not in _WORKER_NAMES:
            raise KeyError(f"unknown worker: {name}")

        with _worker_lock:
            # Already running?
            if _thread_alive(name):
                return False

            # Check if enabled
            if not _worker_enabled(name):
                return False

            # Create stop event
            stop_event = threading.Event()
            _worker_stop_events[name] = stop_event

            # Create and start thread
            if name == "blog":
                thread = threading.Thread(
                    target=self._run_blog_scheduler,
                    args=(stop_event,),
                    name="blog-scheduler-loop",
                    daemon=True,
                )
            elif name == "oneoff":
                thread = threading.Thread(
                    target=self._run_oneoff_scheduler,
                    args=(stop_event,),
                    name="blog-oneoff-scheduler-loop",
                    daemon=True,
                )
            else:
                raise KeyError(f"unknown worker: {name}")

            _worker_threads[name] = thread
            thread.start()
            return True

    def stop_worker(self, name: str) -> bool:
        """Stop a worker thread gracefully.

        Returns:
            True if worker was running and stop signal sent, False if not running.
        """
        if name not in _WORKER_NAMES:
            raise KeyError(f"unknown worker: {name}")

        with _worker_lock:
            stop_event = _worker_stop_events.get(name)
            thread = _worker_threads.get(name)

            if thread is None or not thread.is_alive():
                return False

            # Signal stop
            stop_event.set()

            # Wait for thread to finish (with timeout)
            thread.join(timeout=10.0)

            # Clean up
            _worker_stop_events.pop(name, None)
            _worker_threads.pop(name, None)
            return True

    def stop_all_workers(self):
        """Stop all running workers."""
        for name in list(_worker_threads.keys()):
            self.stop_worker(name)

    # Worker loop implementations (reusing existing scheduler core)

    def _run_blog_scheduler(self, stop_event: threading.Event):
        """Run Blog Scheduler loop (recurring publish_slots)."""
        try:
            from modules.scheduler import run_scheduler_loop
            import main as _PIPE
            from functools import partial

            # Blog-specific config (전체 runtime cfg + scheduler_line/_root)
            blog_cfg = _build_worker_cfg()

            def _loop():
                run_fn = _PIPE.resolve_blog_publish_fn(blog_cfg)
                from modules.scheduler import run_scheduler_loop
                run_scheduler_loop(blog_cfg, partial(run_fn, driver_id="fastapi_scheduler_loop"))

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled
                    if not _worker_enabled("blog"):
                        break
                    # Run one iteration of scheduler loop (this is a blocking call)
                    _loop()
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("Blog scheduler error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check (poll_seconds = 30)
                stop_event.wait(timeout=30.0)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("Blog scheduler thread fatal error: %s", e, exc_info=True)

    def _run_oneoff_scheduler(self, stop_event: threading.Event):
        """Run One-off Scheduler loop (one-off reservations)."""
        try:
            from modules.scheduler import run_oneoff_scheduler_loop
            import main as _PIPE
            from functools import partial

            # Blog-specific config (전체 runtime cfg + scheduler_line/_root)
            blog_cfg = _build_worker_cfg()

            def _resolve(mode, topic_id=None):
                run_fn = __import__("main").resolve_blog_oneoff_publish_fn(blog_cfg, mode, topic_id=topic_id)
                from functools import partial
                return partial(run_fn, driver_id="fastapi_oneoff_scheduler_loop")

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled (oneoff uses OR condition)
                    if not _worker_enabled("oneoff"):
                        break
                    # Run one iteration of one-off scheduler loop
                    from modules.scheduler import run_oneoff_scheduler_loop
                    run_oneoff_scheduler_loop(blog_cfg, lambda mode, topic_id=None: _resolve(mode, topic_id))
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("One-off scheduler error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check
                stop_event.wait(timeout=30.0)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("One-off scheduler thread fatal error: %s", e, exc_info=True)


_manager: WorkerManager | None = None


def get_worker_manager() -> WorkerManager:
    """프로세스 내 단일 WorkerManager 인스턴스를 반환한다(중복 생성 방지)."""
    global _manager
    if _manager is None:
        _manager = WorkerManager()
    return _manager