# -*- coding: utf-8 -*-
"""api/services/publishing_planner_service.py — Publishing Planner 수동 실행
서비스(CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01).

modules.publishing_planner.run_planner_once()에 그대로 위임하는 thin wrapper다 —
approved Topic 검색/capacity 계산/slot 계산/WP 중복검사/reservation 생성/
Topic→scheduled 상태 변경은 전부 그 함수 책임이며 이 파일에 재구현하지 않는다.

cfg에 scheduler_line="blog"를 명시한다 — dashboard.py의 "지금 실행" 버튼은 이
표식이 없는 raw cfg를 그대로 run_planner_once()에 넘기는데, modules/scheduler.py
_schedule_dir()는 scheduler_line이 "blog"가 아니면 data/schedule/(최상위)를
사용한다. 반면 FastAPI Worker(api/services/worker_manager.py::_build_worker_cfg())는
항상 scheduler_line="blog"로 data/schedule/blog/oneoff_schedule.json을 읽는다.
이 API가 Streamlit과 동일하게 scheduler_line 표식 없이 호출하면 생성된 예약이
Worker가 읽는 파일과 다른 경로(data/schedule/(최상위)/oneoff_schedule.json)에
저장되어 실제로 실행되지 않는 예약이 되므로, 이 API는 Worker가 실제로 소비하는
경로와 일치하도록 scheduler_line="blog"를 명시적으로 설정한다(기존 dashboard.py의
"1회성 예약 추가" 버튼이 이미 동일하게 하고 있는 것과 같은 방식 — modules/
publishing_planner.py나 modules/scheduler.py의 로직은 전혀 바꾸지 않는다).

CALCMATE-PLANNER-WP-TARGET-FIX-01: wp_target도 같은 이유로 Worker와 일치시킨다.
CALCMATE_WP_TARGET 환경변수를 api/services/worker_manager.py::_build_worker_cfg()와
정확히 동일한 방식으로 읽어 load_config(wp_target=...)에 전달한다 — 이 환경변수를
전달하지 않으면 cfg["WORDPRESS_URL"]이 로컬/테스트 대상(flat WORDPRESS_* 그대로)에
머물러, WP Worker(production target)와 다른 host로 중복검사를 시도하게 된다
(CALCMATE-PLANNER-ONEOFF-E2E-FOLLOWUP-01에서 실제로 salarymate.test 연결 실패로
확인됨). target 해석 규칙(None/"local"=변경 없음, "production"만 secrets.yaml
nested wordpress.*로 교체, 그 외 값은 ConfigError)은 modules/config_loader.py::
_apply_wp_target()의 기존 계약을 그대로 재사용— 이 파일에서 새로 검증하지 않는다."""
import os

from modules.config_loader import load_config
from modules.publishing_planner import run_planner_once as _run_planner_once

_WP_TARGET_ENV = "CALCMATE_WP_TARGET"


def run_once() -> dict:
    target = (os.environ.get(_WP_TARGET_ENV) or "local").strip().lower()
    cfg = dict(load_config(wp_target=target))
    cfg["scheduler_line"] = "blog"
    return _run_planner_once(cfg)
