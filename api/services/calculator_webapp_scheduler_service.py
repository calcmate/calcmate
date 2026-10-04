"""api/services/calculator_webapp_scheduler_service.py — Calculator WebApp Scheduler 수동 실행 서비스.

CALCMATE-CALCULATOR-SCHEDULER-FASTAPI-WORKER-IMPLEMENT-01

SEO Calculator Quick Action(calculator_quick_action_service)과 완전히 별개다.
이 서비스는 정적 계산기 웹앱(Build → QA → _site) 1회 생성을 담당한다.
GitHub Deploy / Registry Publish는 자동 수행하지 않는다(qa_deploy 모드라도).
"""
from typing import Any, Dict

from modules.config_loader import load_config
from modules.calc_webapp_pipeline import run_calc_webapp_once
from modules.scheduler import _acquire_lock, _release_lock


class CalculatorWebAppSchedulerBusy(Exception):
    """Calculator WebApp Scheduler가 다른 작업 중일 때 발생."""
    pass


def run_once() -> Dict[str, Any]:
    """Calculator WebApp Scheduler 1회 실행 (Build → QA → _site 스냅샷).

    Returns:
        dict: {"produced": int, "published": {...}, "reason": str}
    """
    cfg = load_config()
    cfg["scheduler_line"] = "calc_webapp"

    # 이 단계에서는 qa_deploy 모드라도 배포하지 않음 (BUILD/QA/_SITE만 자동)
    # Deploy/Registry는 별도 명시적 endpoint로 분리한다.
    sched_cfg = dict(cfg.get("CALC_WEBAPP_SCHEDULE", {}) or {})
    sched_cfg["mode"] = "qa_only"
    cfg["CALC_WEBAPP_SCHEDULE"] = sched_cfg

    # Lock 획득 시도 (동시 실행 방지)
    if not _acquire_lock(cfg):
        raise CalculatorWebAppSchedulerBusy("Calculator WebApp Scheduler가 이미 실행 중입니다.")

    try:
        # run_calc_webapp_once 호출 (max_count=1로 단일 calculator 실행)
        result = run_calc_webapp_once(cfg, max_count=1)
        return result
    finally:
        _release_lock(cfg)