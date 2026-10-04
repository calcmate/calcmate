"""api/services/worker_manager.py — Scheduler Worker 관리 (STEP 18-I-A 확장).

FastAPI 프로세스 내 worker lifecycle을 관리한다:
- Blog Scheduler (recurring publish_slots)
- Blog One-off Scheduler (one-off reservations)
- Content Sync Worker (daily 03:00 sync)
- Publishing Planner Worker (AUTO_PUBLISHING enabled loop)
- WP Blog Sync Worker (WP publish → blog_articles sync)

기존 scheduler core 로직(modules/scheduler.py)은 재작성하지 않고 그대로 재사용한다.
"""
import os
import threading
import time
from typing import Callable, Optional

from api.services.config_service import ConfigService, ConfigSectionNotAllowed

# Worker names managed by FastAPI
_WORKER_NAMES = ("blog", "oneoff", "content_sync", "publishing_planner", "wp_blog_sync", "calc_webapp")

# Thread names (must match dashboard.py for status consistency)
_THREAD_NAMES = {
    "blog": "blog-scheduler-loop",
    "oneoff": "blog-oneoff-scheduler-loop",
    "content_sync": "content-sync-loop",
    "publishing_planner": "publishing-planner-loop",
    "wp_blog_sync": "wp-blog-sync-loop",
    "calc_webapp": "calc-webapp-scheduler-loop",
}

# Worker name -> config section mapping
_CONFIG_SECTIONS = {
    "blog": "BLOG_SCHEDULE",
    "oneoff": "BLOG_SCHEDULE",  # One-off uses BLOG_SCHEDULE for Golden10 gating
    "content_sync": "CONTENT_SYNC",
    "publishing_planner": "AUTO_PUBLISHING",
    "wp_blog_sync": "WP_BLOG_SYNC",
    "calc_webapp": "CALC_WEBAPP_SCHEDULE",
}

# AUTO_PUBLISHING section for oneoff gating
_AUTO_PUBLISHING_SECTION = "AUTO_PUBLISHING"

# Enabled defaults matching dashboard.py
_ENABLED_DEFAULT = {"blog": False, "oneoff": False, "content_sync": True, "publishing_planner": False, "wp_blog_sync": False, "calc_webapp": False}

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


# FASTAPI_WORKER_MODE guard — FastAPI가 Content Sync owner일 때 Streamlit이
# 동일 루프를 시작하지 않도록 한다(STEP S14 ownership guard).
_FASTAPI_WORKER_MODE_ENV = "CALCMATE_FASTAPI_WORKER_MODE"


def _fastapi_worker_mode() -> bool:
    """FastAPI Worker Mode가 활성화되어 있는지 확인."""
    return os.environ.get(_FASTAPI_WORKER_MODE_ENV, "").strip().lower() in ("1", "true", "yes")


def _content_sync_enabled() -> bool:
    """Content Sync Worker가 활성화되어야 하는지 확인.

    - CONFIG_SYNC.enabled가 true여야 함
    - FASTAPI_WORKER_MODE=1일 때만 FastAPI가 owner가 됨(Streamlit은 실행 안 함)
    - FASTAPI_WORKER_MODE가 아니면 FastAPI도 실행 안 함(기존 동작 보존)
    """
    if not _fastapi_worker_mode():
        return False
    try:
        data = ConfigService().get_section("CONTENT_SYNC")
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT.get("content_sync", True)
    return bool(data.get("enabled", _ENABLED_DEFAULT.get("content_sync", True)))


def _publishing_planner_enabled() -> bool:
    """Publishing Planner Worker가 활성화되어야 하는지 확인.

    - AUTO_PUBLISHING.enabled가 true여야 함
    - FASTAPI_WORKER_MODE=1일 때만 FastAPI가 owner가 됨(Streamlit은 실행 안 함)
    - FASTAPI_WORKER_MODE가 아니면 FastAPI도 실행 안 함(기존 동작 보존)
    """
    if not _fastapi_worker_mode():
        return False
    try:
        data = ConfigService().get_section("AUTO_PUBLISHING")
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT.get("publishing_planner", False)
    return bool(data.get("enabled", _ENABLED_DEFAULT.get("publishing_planner", False)))


def _wp_blog_sync_enabled() -> bool:
    """WP Blog Sync Worker가 활성화되어야 하는지 확인.

    - WP_BLOG_SYNC.enabled가 true여야 함
    - FASTAPI_WORKER_MODE=1일 때만 FastAPI가 owner가 됨
    - FASTAPI_WORKER_MODE가 아니면 FastAPI도 실행 안 함(기존 동작 보존)
    """
    if not _fastapi_worker_mode():
        return False
    try:
        data = ConfigService().get_section("WP_BLOG_SYNC")
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT.get("wp_blog_sync", False)
    return bool(data.get("enabled", _ENABLED_DEFAULT.get("wp_blog_sync", False)))


def _calc_webapp_enabled() -> bool:
    """Calculator WebApp Scheduler Worker가 활성화되어야 하는지 확인.

    - CALC_WEBAPP_SCHEDULE.enabled가 true여야 함
    - FASTAPI_WORKER_MODE=1일 때만 FastAPI가 owner가 됨(Streamlit은 실행 안 함)
    - FASTAPI_WORKER_MODE가 아니면 FastAPI도 실행 안 함(기존 동작 보존)
    """
    if not _fastapi_worker_mode():
        return False
    try:
        data = ConfigService().get_section("CALC_WEBAPP_SCHEDULE")
    except ConfigSectionNotAllowed:
        return _ENABLED_DEFAULT.get("calc_webapp", False)
    return bool(data.get("enabled", _ENABLED_DEFAULT.get("calc_webapp", False)))


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
    if name == "content_sync":
        return _content_sync_enabled()
    if name == "publishing_planner":
        return _publishing_planner_enabled()
    if name == "wp_blog_sync":
        return _wp_blog_sync_enabled()
    if name == "calc_webapp":
        return _calc_webapp_enabled()
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
            elif name == "content_sync":
                thread = threading.Thread(
                    target=self._run_content_sync,
                    args=(stop_event,),
                    name="content-sync-loop",
                    daemon=True,
                )
            elif name == "publishing_planner":
                thread = threading.Thread(
                    target=self._run_publishing_planner,
                    args=(stop_event,),
                    name="publishing-planner-loop",
                    daemon=True,
                )
            elif name == "wp_blog_sync":
                thread = threading.Thread(
                    target=self._run_wp_blog_sync,
                    args=(stop_event,),
                    name="wp-blog-sync-loop",
                    daemon=True,
                )
            elif name == "calc_webapp":
                thread = threading.Thread(
                    target=self._run_calc_webapp_scheduler,
                    args=(stop_event,),
                    name="calc-webapp-scheduler-loop",
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

    def _run_content_sync(self, stop_event: threading.Event):
        """Run Content Sync loop (daily 03:00 sync, reusing existing run_sync_loop)."""
        try:
            from modules.content_sync import run_sync_loop

            # Content Sync-specific config (전체 runtime cfg + scheduler_line/_root)
            import logging
            from modules.config_loader import load_config
            from urllib.parse import urlparse

            target = (os.environ.get(_WP_TARGET_ENV) or "local").strip().lower()
            content_sync_cfg = load_config(wp_target=target)
            content_sync_cfg["scheduler_line"] = "content_sync"
            content_sync_cfg["_root"] = os.getcwd()
            logging.getLogger("worker").info(
                "Content Sync worker cfg: wp_target=%s wp_host=%s", target,
                urlparse(content_sync_cfg.get("WORDPRESS_URL") or "").hostname)

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled
                    if not _worker_enabled("content_sync"):
                        break
                    # Run one iteration of content sync loop (this is a blocking call with internal polling)
                    run_sync_loop(content_sync_cfg)
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("Content Sync error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check (poll_seconds from config, default 60)
                cs = content_sync_cfg.get("CONTENT_SYNC", {}) or {}
                poll = int(cs.get("poll_seconds", 60))
                stop_event.wait(timeout=poll)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("Content Sync thread fatal error: %s", e, exc_info=True)

    def _run_publishing_planner(self, stop_event: threading.Event):
        """Run Publishing Planner loop (AUTO_PUBLISHING enabled polling, reusing existing run_planner_loop)."""
        try:
            from modules.publishing_planner import run_planner_loop

            # Publishing Planner-specific config (전체 runtime cfg + scheduler_line/_root)
            import logging
            from modules.config_loader import load_config
            from urllib.parse import urlparse

            target = (os.environ.get(_WP_TARGET_ENV) or "local").strip().lower()
            planner_cfg = load_config(wp_target=target)
            planner_cfg["scheduler_line"] = "publishing_planner"
            planner_cfg["_root"] = os.getcwd()
            logging.getLogger("worker").info(
                "Publishing Planner worker cfg: wp_target=%s wp_host=%s", target,
                urlparse(planner_cfg.get("WORDPRESS_URL") or "").hostname)

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled
                    if not _worker_enabled("publishing_planner"):
                        break
                    # Run one iteration of planner loop (this is a blocking call with internal polling)
                    run_planner_loop(planner_cfg)
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("Publishing Planner error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check (poll_seconds from config, default 300)
                ap = planner_cfg.get("AUTO_PUBLISHING", {}) or {}
                poll = int(ap.get("poll_seconds", 300))
                stop_event.wait(timeout=poll)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("Publishing Planner thread fatal error: %s", e, exc_info=True)

    def _run_wp_blog_sync(self, stop_event: threading.Event):
        """Run WP Blog Sync loop (WP publish -> blog_articles sync, reusing existing run_wp_blog_sync_loop)."""
        try:
            from modules.wp_blog_sync import run_wp_blog_sync_loop

            # WP Blog Sync-specific config (전체 runtime cfg + scheduler_line/_root)
            import logging
            from modules.config_loader import load_config
            from urllib.parse import urlparse

            # WP Blog Sync uses production target only
            target = (os.environ.get(_WP_TARGET_ENV) or "production").strip().lower()
            wp_sync_cfg = load_config(wp_target=target)
            wp_sync_cfg["scheduler_line"] = "wp_blog_sync"
            wp_sync_cfg["_root"] = os.getcwd()
            logging.getLogger("worker").info(
                "WP Blog Sync worker cfg: wp_target=%s wp_host=%s", target,
                urlparse(wp_sync_cfg.get("WORDPRESS_URL") or "").hostname)

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled
                    if not _worker_enabled("wp_blog_sync"):
                        break
                    # Run one iteration of WP blog sync loop (this is a blocking call with internal polling)
                    run_wp_blog_sync_loop(wp_sync_cfg)
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("WP Blog Sync error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check (poll_seconds from config, default 1800)
                wb = wp_sync_cfg.get("WP_BLOG_SYNC", {}) or {}
                poll = int(wb.get("poll_seconds", 1800))
                stop_event.wait(timeout=poll)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("WP Blog Sync thread fatal error: %s", e, exc_info=True)

    def _run_calc_webapp_scheduler(self, stop_event: threading.Event):
        """Run Calculator WebApp Scheduler loop (reusing existing run_scheduler_loop).

        자동 Worker는 qa_deploy 모드라도 배포하지 않는다(BUILD/QA/_SITE만 자동).
        Deploy/Registry는 별도 명시적 endpoint로 분리한다.
        """
        try:
            from modules.scheduler import run_scheduler_loop
            from modules.calc_webapp_pipeline import run_calc_webapp_once
            import logging
            from modules.config_loader import load_config
            from urllib.parse import urlparse

            # Calculator WebApp Scheduler-specific config (전체 runtime cfg + scheduler_line/_root)
            target = (os.environ.get(_WP_TARGET_ENV) or "local").strip().lower()
            calc_webapp_cfg = load_config(wp_target=target)
            calc_webapp_cfg["scheduler_line"] = "calc_webapp"
            calc_webapp_cfg["_root"] = os.getcwd()
            logging.getLogger("worker").info(
                "Calculator WebApp Scheduler worker cfg: wp_target=%s wp_host=%s", target,
                urlparse(calc_webapp_cfg.get("WORDPRESS_URL") or "").hostname)

            # 자동 실행 시에는 무조건 qa_only 모드로 강제 (배포 방지)
            # qa_deploy 모드라도 자동 Worker에서는 배포하지 않음
            def _run_calc_webapp_once_auto(cfg: dict, max_count: int = 1) -> dict:
                # config 복사 후 mode를 qa_only로 강제 오버라이드
                auto_cfg = dict(cfg)
                sched_cfg = dict(auto_cfg.get("CALC_WEBAPP_SCHEDULE", {}) or {})
                sched_cfg["mode"] = "qa_only"
                auto_cfg["CALC_WEBAPP_SCHEDULE"] = sched_cfg
                return run_calc_webapp_once(auto_cfg, max_count)

            # Run with stop event check
            while not stop_event.is_set():
                try:
                    # Check if still enabled
                    if not _worker_enabled("calc_webapp"):
                        break
                    # Run one iteration of scheduler loop (this is a blocking call with internal polling)
                    run_scheduler_loop(calc_webapp_cfg, _run_calc_webapp_once_auto)
                except Exception as e:
                    import logging
                    logging.getLogger("worker").error("Calculator WebApp Scheduler error: %s", e, exc_info=True)
                    # Continue on error (matching dashboard.py behavior)

                # Sleep with stop event check (poll_seconds from config, default 30)
                cw = calc_webapp_cfg.get("CALC_WEBAPP_SCHEDULE", {}) or {}
                poll = int(cw.get("poll_seconds", 30))
                stop_event.wait(timeout=poll)

        except Exception as e:
            import logging
            logging.getLogger("worker").error("Calculator WebApp Scheduler thread fatal error: %s", e, exc_info=True)


_manager: WorkerManager | None = None


def get_worker_manager() -> WorkerManager:
    """프로세스 내 단일 WorkerManager 인스턴스를 반환한다(중복 생성 방지)."""
    global _manager
    if _manager is None:
        _manager = WorkerManager()
    return _manager