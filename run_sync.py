# -*- coding: utf-8 -*-
"""
run_sync.py — Content Sync Engine 독립 진입점

Blog Schedule(Dashboard/scripts/run_blog_scheduler.py)와 완전히 분리된
독립 서비스로 기동한다. WordPress를 기준으로 Google Sheets 상태를 동기화한다.

사용법:
  python run_sync.py                 # 독립 스케줄 루프(매일 CONTENT_SYNC.run_at 실행)
  python run_sync.py --once          # 1회만 실행(mode 기본 recent)
  python run_sync.py --once --mode full
  python run_sync.py --instance <id> # 멀티 인스턴스 config 사용
"""
import sys
import json
import argparse
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from modules.config_loader import load_config, ConfigError
from modules.logger import get_logger
from modules.content_sync import run_sync_once, run_sync_loop

LOG = get_logger("content_sync")


def parse_args():
    p = argparse.ArgumentParser(description="Content Sync Engine (WP→Sheets 동기화)")
    p.add_argument("--once", action="store_true", help="루프 대신 1회만 동기화 실행")
    p.add_argument("--mode", choices=["recent", "full"], default="recent",
                   help="recent=최근 N일 / full=전체 스캔 (기본 recent)")
    p.add_argument("--instance", default=None, help="멀티 인스턴스 ID")
    p.add_argument("--dry-run", action="store_true",
                   help="--once와 함께: 판정만 출력하고 state/이력/텔레그램에 아무것도 쓰지 않음")
    return p.parse_args()


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

    if args.dry_run and not args.once:
        print("[오류] --dry-run은 --once와 함께만 사용할 수 있습니다.")
        sys.exit(2)

    if args.once:
        LOG.info("Content Sync 1회 실행 (mode=%s, dry_run=%s)", args.mode, args.dry_run)
        summary = run_sync_once(cfg, mode=args.mode, dry_run=args.dry_run)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    LOG.info("Content Sync 독립 스케줄러 기동")
    run_sync_loop(cfg)


if __name__ == "__main__":
    main()
