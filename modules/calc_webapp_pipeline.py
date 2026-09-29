# -*- coding: utf-8 -*-
"""modules/calc_webapp_pipeline.py — 계산기 웹앱(Phase A~E) 자동 스케줄러 wrapper.

기존 Calculator Scheduler(main.py resolve_publish_fn → modules/calculator_pipeline.py
run_calculator_once, SEO 아티클을 WordPress에 발행하는 파이프라인)와는 완전히 별개다.
이 모듈은 그 함수를 호출하지 않는다.

여기서 자동화하는 대상은 정적 계산기 웹앱이다:
  AG.generate_calculator() → _site/{slug}/ 스냅샷 저장(Phase B) → pre_build_qa(Phase E)
  → [mode=qa_deploy이고 QA PASS인 경우에만] GitHub Pages 배포

modules/scheduler.py의 슬롯 스케줄러(run_scheduler_loop)는 artifact-agnostic한 엔진이므로
그대로 재사용하고, run_once_fn 자리에 이 모듈의 run_calc_webapp_once()를 연결한다.

config.yaml 설정(CALC_WEBAPP_SCHEDULE, 선택 — 미설정 시 비활성):
  CALC_WEBAPP_SCHEDULE:
    enabled: true
    mode: qa_only    # qa_only(①생성+검증만) | qa_deploy(②생성+검증+QA PASS 시 배포)
    targets: [calculator_id, ...]   # 라운드로빈으로 1건씩 처리
"""
from .logger import get_logger

LOG = get_logger()

# 프로세스 내 라운드로빈 커서. 재시작 시 0으로 복귀 — targets 내 대상을 결국 모두
# 순회하게 되므로(스케줄러가 poll마다 재호출) 정확도에 영향 없음.
_cursor = {"i": 0}


def _pick_target_id(cfg: dict):
    sched_cfg = cfg.get("CALC_WEBAPP_SCHEDULE", {}) or {}
    targets = [str(t).strip() for t in (sched_cfg.get("targets") or []) if str(t).strip()]
    if not targets:
        return None
    i = _cursor["i"] % len(targets)
    _cursor["i"] = (i + 1) % len(targets)
    return targets[i]


def run_calc_webapp_once(cfg: dict, max_count: int = 1) -> dict:
    """계산기 웹앱 1건 생성→스냅샷→QA→[배포]. modules/scheduler.py 호환 시그니처
    (execute_due_post/immediate_publish가 기대하는 (cfg, max_count=1)->dict)."""
    sched_cfg = cfg.get("CALC_WEBAPP_SCHEDULE", {}) or {}
    mode = str(sched_cfg.get("mode", "qa_only")).strip().lower()
    if mode not in ("qa_only", "qa_deploy"):
        LOG.warning("알 수 없는 CALC_WEBAPP_SCHEDULE.mode=%r → qa_only로 처리", mode)
        mode = "qa_only"

    calc_id = _pick_target_id(cfg)
    if not calc_id:
        return {"produced": 0, "reason": "no_calculators"}

    try:
        from adapters.db.factory import get_calculator_storage_adapter
        from repositories.calculator_repository import CalculatorRepository
        from modules import app_generator as AG
        from modules import github_deployer as GH
        from modules.review_center import pre_build_qa
        from modules.site_snapshot import write_site_snapshot, read_site_snapshot

        repo = CalculatorRepository(get_calculator_storage_adapter(cfg))
        calc = repo.get_by_id(calc_id)
        if not calc:
            LOG.warning("계산기 웹앱 스케줄 대상 없음(id=%s)", calc_id)
            return {"produced": 0, "reason": "no_calculators"}

        prev_files = read_site_snapshot(cfg, calc)
        files = AG.generate_calculator(calc, cfg)  # Tier2-B 라우팅은 내부에서 자동 처리(Phase D)
        write_site_snapshot(cfg, calc, files)
        qa_results = pre_build_qa(calc, cfg, prev_files=prev_files)
        qa_pass = all(r["passed"] or r["skipped"] for r in qa_results)

        deployed = False
        deploy_url = ""
        if mode == "qa_deploy" and qa_pass:
            if GH.is_configured(cfg):
                deploy_files = read_site_snapshot(cfg, calc)  # Phase E 원칙: 재생성 없이 스냅샷 그대로 배포
                ok, res = GH.deploy_app(cfg, deploy_files,
                                        repo=cfg.get("GITHUB_REPO", "salarymate-calculators"),
                                        subdir=calc.get("slug", calc_id))
                if ok:
                    repo.publish(calc_id, res)
                    deployed = True
                    deploy_url = res
                else:
                    LOG.warning("계산기 웹앱 자동 배포 실패(slug=%s): %s", calc.get("slug", ""), res)
            else:
                LOG.warning("CALC_WEBAPP_SCHEDULE mode=qa_deploy 이지만 GITHUB_TOKEN 미설정 — 배포 건너뜀")

        LOG.info("계산기 웹앱 자동 실행 완료(id=%s, mode=%s, qa_pass=%s, deployed=%s)",
                 calc_id, mode, qa_pass, deployed)

        # STEP76: 3-Way(SQLite/Sheets/_site) 이상감지 — observability 계층이라
        # 이 호출이 실패해도 위 결과(생성/QA/배포)에는 절대 영향을 주지 않는다.
        # run_three_way_anomaly_check_safely()는 내부적으로 모든 예외를 이미
        # 흡수하지만, 이 운영 경로 자체를 절대 깨뜨리지 않는다는 원칙을 이중으로
        # 보장하기 위해 호출부에서도 한 번 더 방어한다.
        try:
            from datetime import datetime as _dt
            from modules.calculator_3way_sync import run_three_way_anomaly_check_safely
            run_three_way_anomaly_check_safely(
                cfg, run_id=f"calc_webapp_{_dt.now().strftime('%Y%m%d%H%M%S')}")
        except Exception as _e3way:
            LOG.warning("[3way] 이상감지 호출 자체 실패(운영 작업에는 영향 없음): %s", _e3way)

        return {
            "produced": 1,
            "published": {
                "keyword": calc.get("slug", calc_id),
                "title": calc.get("name", ""),
                "wp_post_id": "",
                "wp_url": deploy_url,
            },
        }
    except Exception as e:
        LOG.error("계산기 웹앱 자동 실행 오류(id=%s): %s", calc_id, e, exc_info=True)
        return {"produced": 0, "reason": f"오류:{str(e)[:80]}"}
