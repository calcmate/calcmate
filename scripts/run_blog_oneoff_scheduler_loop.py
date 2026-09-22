# -*- coding: utf-8 -*-
"""
scripts/run_blog_oneoff_scheduler_loop.py — Blog 1회성(one-off) 예약 스케줄러
독립 진입점 (CALCMATE-ONEOFF-SCHEDULER-STANDALONE-IMPLEMENT-01)

dashboard.py(Streamlit)의 _start_blog_oneoff_scheduler_thread()와 완전히 동일한
엔진 호출(modules.scheduler.run_oneoff_scheduler_loop + main.resolve_blog_oneoff_
publish_fn)을 재사용하되, Streamlit/dashboard.py/@st.cache_resource 없이 독립
프로세스로 실행한다.

scripts/run_blog_scheduler_loop.py(recurring publish_slots 독립 진입점)와 동일한
패턴을 따른다 — 단, 이 루프는 recurring이 아니라 one-off(예약 1건씩) 전용이며,
Golden10(topic_id 없음)과 Topic Pool(topic_id 있음) 예약을 모두 처리한다. 이
분기는 이미 modules.scheduler.run_oneoff_scheduler_loop()와 main.py의
resolve_blog_oneoff_publish_fn() 내부에 구현되어 있으므로, 이 launcher는 새
분기 로직을 추가하지 않는다 — 설정 준비 → 기존 resolver 연결 → 기존 one-off
loop 실행만 한다.

CALCMATE-ONEOFF-LAUNCHER-GATE-FIX-IMPLEMENT-01: dashboard.py의 one-off 스레드
기동 조건("BLOG_SCHEDULE.enabled OR AUTO_PUBLISHING.enabled")을 이 launcher에
그대로 복제했던 상위 gate를 제거했다. modules.scheduler.run_oneoff_scheduler_loop()
자체는 이 두 플래그에 의존하지 않는다 — Golden10(topic_id 없음) 예약만
run_oneoff_scheduler_loop() 내부의 _blog_schedule_enabled_now() gate로
개별적으로 skip되며, Topic Pool(topic_id 있음) 예약은 이 gate의 영향을
전혀 받지 않고 always 처리되도록 이미 설계되어 있다(모듈 docstring 원문).
dashboard.py의 스레드 기동 조건은 "여러 기능을 공유하는 하나의 프로세스에서
불필요한 스레드를 안 띄우기 위한" 것으로, 이 독립 단일목적 프로세스에는
같은 이유가 적용되지 않는다 — 그래서 이 launcher는 두 플래그와 무관하게
항상 run_oneoff_scheduler_loop()까지 진입한다.

사용법:
  python scripts/run_blog_oneoff_scheduler_loop.py                # 독립 스케줄 루프
  python scripts/run_blog_oneoff_scheduler_loop.py --instance <id> # 멀티 인스턴스 config 사용
"""
import sys
import argparse
from functools import partial
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from modules.config_loader import load_config, ConfigError
from modules.logger import get_logger

LOG = get_logger("blog_oneoff_scheduler")


def parse_args():
    p = argparse.ArgumentParser(description="Blog 1회성(one-off) 예약 스케줄러 독립 루프 (Streamlit 비의존)")
    p.add_argument("--instance", default=None, help="멀티 인스턴스 ID")
    return p.parse_args()


def build_blog_cfg(cfg: dict) -> dict:
    """dashboard.py::_start_blog_oneoff_scheduler_thread()의 blog_cfg 구성과 동일
    (dict(cfg) 복사 + scheduler_line='blog')."""
    blog_cfg = dict(cfg)
    blog_cfg["scheduler_line"] = "blog"
    return blog_cfg


def main():
    args = parse_args()
    if args.instance:
        cfg_path = BASE / "config" / "instances" / args.instance / "config.yaml"
    else:
        cfg_path = BASE / "config" / "config.yaml"
    try:
        cfg = load_config(str(cfg_path))
    except ConfigError as e:
        print(f"[ConfigError] {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"[오류] config.yaml 파일을 찾을 수 없습니다: {cfg_path}")
        sys.exit(1)

    cfg["_root"] = str(BASE)
    cfg["_instance_id"] = args.instance or "default"

    blog_cfg = build_blog_cfg(cfg)

    # dashboard.py::_start_blog_oneoff_scheduler_thread()의 _resolve()와 동일한
    # resolver 연결 — Golden10/Topic Pool 분기는 resolve_blog_oneoff_publish_fn()과
    # run_oneoff_scheduler_loop() 내부에 이미 구현되어 있으므로 여기서 새로
    # 만들지 않는다.
    import main as _PIPE
    from modules.scheduler import run_oneoff_scheduler_loop

    def _resolve(mode, topic_id=None):
        run_fn = _PIPE.resolve_blog_oneoff_publish_fn(blog_cfg, mode, topic_id=topic_id)
        return partial(run_fn, driver_id="standalone_oneoff_scheduler_loop")

    LOG.info("[blog-oneoff-scheduler] Blog 1회성 예약 스케줄러 독립 루프 기동")
    run_oneoff_scheduler_loop(blog_cfg, _resolve)


if __name__ == "__main__":
    main()
