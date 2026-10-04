"""api/services/calculator_quick_action_service.py — Dashboard Quick Action
「🧮 계산기 생성」 수동 실행 서비스.

STEP S11: dashboard.py의 "🧮 계산기 생성" 버튼(dashboard.py:474-476, "🔧 고급
실행(수동)" expander 안)과 동일한 실행 의미를 재현한다.
modules.calculator_pipeline.run_calculator_once(cfg, max_count=1)를 그대로
호출하며, 계산기 생성 파이프라인(SEO 글 생산 로직/품질 게이트/Registry 규칙)을
새로 만들거나 수정하지 않는다.

주의: 이 버튼이 호출하는 run_calculator_once()는 "계산기 SEO 글 생산" 파이프라인
(modules/calculator_pipeline.py)이며, /api/scheduler/calculator/status가 조회하는
"Calculator Scheduler"(WorkerManager, CALC_WEBAPP_SCHEDULE, calc-webapp-scheduler-loop
스레드 — modules.calc_webapp_pipeline.run_calc_webapp_once)와는 완전히 다른
파이프라인이다. dashboard.py는 이 SEO 글 파이프라인을 자동으로 기동하는 스레드가
없다 — Quick Action(이 버튼 및 통합 "▶ 실행" 버튼)과 main.py CLI(--calculator-id)
에서만 수동으로 호출된다.

중복 실행 방지: run_calculator_once() 자체에는 락이 없다. modules/scheduler.py의
기존 파일 lock(_acquire_lock/_release_lock)을 재사용한다 — cfg에 scheduler_line을
지정하지 않으면(실제 Quick Action 호출과 동일) modules/scheduler.py가 이를
"Calculator 라인(기존 동작)"으로 취급해 data/schedule/scheduler.lock을 사용한다.
이는 dashboard.py가 기동하는 blog/calc_webapp 라인의 lock(각각 하위 폴더)과
겹치지 않는, 기존에 이미 존재하던 lock 네임스페이스다 — 새 in-memory lock을
만들지 않는다.
"""
from modules.config_loader import load_config
import modules.scheduler as scheduler_engine
from modules import calculator_pipeline as CP


class CalculatorQuickActionBusy(Exception):
    """다른 계산기 생성 실행이 이미 lock을 보유 중."""


def run_once() -> dict:
    """반환: modules.calculator_pipeline.run_calculator_once(cfg, max_count=1)의
    결과 dict 그대로(가공하지 않음) — {"produced", "processed", "failed", "dup",
    "quality_hold", "hold_skip", "reason", "attempted", "published", ...}.
    lock 획득 실패 시 CalculatorQuickActionBusy를 던진다(라우터에서 명확한
    실패 응답으로 변환)."""
    cfg = load_config()
    if not scheduler_engine._acquire_lock(cfg):
        raise CalculatorQuickActionBusy(
            "다른 계산기 생성 실행이 진행 중입니다. 잠시 후 재시도하세요.")
    try:
        return CP.run_calculator_once(cfg, max_count=1)
    finally:
        scheduler_engine._release_lock(cfg)
