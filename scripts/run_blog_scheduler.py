# -*- coding: utf-8 -*-
"""
scripts/run_blog_scheduler.py — Blog Scheduler 독립 실행 진입점

Calculator Line과 완전히 분리된 Blog Line CLI.

용도:
  python scripts/run_blog_scheduler.py                  # Golden 10 전체 dry-run
  python scripts/run_blog_scheduler.py --slug severance-pay --intent eligibility  # 단일 dry-run
  python scripts/run_blog_scheduler.py --validate         # 기존 콘텐츠 구조 검증
  python scripts/run_blog_scheduler.py --full             # dry-run + 검증 + 보호 확인

주의:
  - DB write = 0 (isolated output만 생성)
  - WordPress = 0
  - Image = 0
  - Calculator Line 호출 = 0
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _cfg():
    """Minimal config (no OPENAI_API_KEY = mock path)."""
    return {
        "MAX_RETRY_COUNT": 1,
        "QUALITY_GATE": {},
        "QUALITY_SCORE": {},
    }


def _db_hash(db_path: str) -> str:
    return hashlib.md5(open(db_path, "rb").read()).hexdigest()


def cmd_full_dry_run(args):
    """Golden 10 전체 dry-run."""
    from modules.blog_scheduler_adapter import run_blog_once, _output_dir

    cfg = _cfg()
    db_path = str(ROOT / "data" / "blog_auto.db")

    # pre-run hash
    db_hash_before = _db_hash(db_path)

    t0 = time.time()
    result = run_blog_once(cfg, max_count=10, driver_id="cli_run_blog_scheduler")
    elapsed = time.time() - t0

    # post-run hash
    db_hash_after = _db_hash(db_path)
    db_unchanged = db_hash_before == db_hash_after

    # output summary
    out_dir = _output_dir(cfg)
    print(f"\n{'='*60}")
    print(f"[Blog Scheduler] Dry-Run Complete")
    print(f"{'='*60}")
    print(f"  Produced: {result['produced']}/10")
    print(f"  Time:     {elapsed:.2f}s")
    print(f"  Output:   {out_dir}")
    print(f"  DB hash:  {db_hash_before} -> {db_hash_after} ({'UNCHANGED' if db_unchanged else 'CHANGED!'})")
    print(f"  DB write: {result.get('db_write', 0)}")
    print(f"  WP call:  {result.get('wordpress_call', 0)}")
    print(f"  Img call: {result.get('image_call', 0)}")
    print()

    # per-item summary
    for r in result["results"]:
        status = r["status"]
        icon = "[OK]" if status == "SUCCESS" else "[!!]"
        print(f"  {icon} {r['slug']:30s} {r['intent']:15s} {status}")

    # protection check
    if not db_unchanged:
        print("\n*** WARNING: DB was modified! ***")
        return 1

    failed = [r for r in result["results"] if r["status"] != "SUCCESS"]
    if failed:
        print(f"\n*** {len(failed)} items failed ***")
        return 1

    print(f"\nAll 10/10 PASS - DB unchanged, no WP/Image calls.")
    return 0


def cmd_single_dry_run(args):
    """단일 콘텐츠 dry-run."""
    from modules.blog_scheduler_adapter import run_blog_dry_run

    cfg = _cfg()
    result = run_blog_dry_run(cfg, args.slug, args.intent, driver_id="cli_run_blog_scheduler")

    if result["success"]:
        r = result["result"]
        print(f"PASS: {r['slug']}/{r['intent']}")
        print(f"  article_len: {r['article_len']}")
        print(f"  protection:  {r['protection_ok']}")
        print(f"  output:      {r['output']}")
        return 0
    else:
        print(f"FAIL: {result['errors']}")
        return 1


def cmd_validate(args):
    """기존 콘텐츠 구조 검증."""
    import re
    from content.blog import GOLDEN_10

    db_path = str(ROOT / "data" / "blog_auto.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    passed = 0
    failed = 0

    for gc in GOLDEN_10:
        c.execute("SELECT article_content FROM calculators WHERE slug=?", (gc.slug,))
        row = c.fetchone()
        if not row or not row["article_content"]:
            print(f"  [!!] {gc.slug:30s} — no article_content in DB")
            failed += 1
            continue

        html = row["article_content"]

        # H2 check
        h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)
        h2_texts = [re.sub(r"<[^>]+>", "", h).strip() for h in h2s]

        # FAQ check
        has_faq = "<dl" in html or "FAQ" in html

        # intent-specific check
        intent_ok = True
        if gc.intent == "eligibility":
            intent_ok = any("대상" in h or "조건" in h for h in h2_texts)
        elif gc.intent == "howto":
            intent_ok = any("절차" in h or "방법" in h for h in h2_texts)
        elif gc.intent == "documents":
            intent_ok = any("서류" in h for h in h2_texts)
        elif gc.intent == "calculator":
            intent_ok = any("계산" in h for h in h2_texts)

        if intent_ok and h2_texts and has_faq:
            print(f"  [OK] {gc.slug:30s} {gc.intent:15s} H2={len(h2_texts)} FAQ=yes")
            passed += 1
        else:
            print(f"  [!!] {gc.slug:30s} {gc.intent:15s} H2={len(h2_texts)} FAQ={'yes' if has_faq else 'no'} intent_ok={intent_ok}")
            failed += 1

    conn.close()

    print(f"\nValidation: {passed}/10 PASS, {failed} FAIL")
    return 0 if failed == 0 else 1


def cmd_full(args):
    """Full verification: dry-run + validate + protection."""
    from modules.blog_scheduler_adapter import run_blog_once, _output_dir
    from content.blog import GOLDEN_10

    cfg = _cfg()
    db_path = str(ROOT / "data" / "blog_auto.db")

    # pre hashes
    db_hash_before = _db_hash(db_path)
    golden_hashes = {}
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for gc in GOLDEN_10:
        c.execute("SELECT article_content FROM calculators WHERE slug=?", (gc.slug,))
        row = c.fetchone()
        if row and row[0]:
            golden_hashes[gc.slug] = hashlib.sha256(row[0].encode()).hexdigest()[:16]
    conn.close()

    # dry-run
    t0 = time.time()
    result = run_blog_once(cfg, max_count=10, driver_id="cli_run_blog_scheduler")
    elapsed = time.time() - t0

    # post hashes
    db_hash_after = _db_hash(db_path)
    golden_hashes_after = {}
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for gc in GOLDEN_10:
        c.execute("SELECT article_content FROM calculators WHERE slug=?", (gc.slug,))
        row = c.fetchone()
        if row and row[0]:
            golden_hashes_after[gc.slug] = hashlib.sha256(row[0].encode()).hexdigest()[:16]
    conn.close()

    # validate structure
    import re
    struct_pass = 0
    struct_fail = 0
    for gc in GOLDEN_10:
        calc = None
        conn2 = sqlite3.connect(db_path)
        c2 = conn2.cursor()
        c2.execute("SELECT article_content FROM calculators WHERE slug=?", (gc.slug,))
        row2 = c2.fetchone()
        conn2.close()
        if not row2 or not row2[0]:
            struct_fail += 1
            continue
        html = row2[0]
        h2s = [re.sub(r"<[^>]+>", "", h).strip()
               for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)]
        has_faq = "<dl" in html or "FAQ" in html
        intent_ok = True
        if gc.intent == "eligibility":
            intent_ok = any("대상" in h or "조건" in h for h in h2s)
        elif gc.intent == "howto":
            intent_ok = any("절차" in h or "방법" in h for h in h2s)
        elif gc.intent == "documents":
            intent_ok = any("서류" in h for h in h2s)
        elif gc.intent == "calculator":
            intent_ok = any("계산" in h for h in h2s)
        if intent_ok and h2s and has_faq:
            struct_pass += 1
        else:
            struct_fail += 1

    # protection
    hashes_unchanged = all(
        golden_hashes.get(s) == golden_hashes_after.get(s)
        for s in golden_hashes
    )
    db_unchanged = db_hash_before == db_hash_after

    # output
    print(f"\n{'='*60}")
    print(f"[Blog Scheduler] Full Verification")
    print(f"{'='*60}")
    print(f"  Dry-run:      {result['produced']}/10 produced ({elapsed:.2f}s)")
    print(f"  Structure:    {struct_pass}/10 PASS")
    print(f"  DB hash:      {'UNCHANGED' if db_unchanged else 'CHANGED!'}")
    print(f"  Golden hash:  {'UNCHANGED' if hashes_unchanged else 'CHANGED!'}")
    print(f"  DB write:     {result.get('db_write', 0)}")
    print(f"  WP call:      {result.get('wordpress_call', 0)}")
    print(f"  Img call:     {result.get('image_call', 0)}")

    all_ok = (
        result["produced"] == 10
        and struct_pass == 10
        and db_unchanged
        and hashes_unchanged
        and result.get("db_write", 0) == 0
        and result.get("wordpress_call", 0) == 0
        and result.get("image_call", 0) == 0
    )

    if all_ok:
        print(f"\n  FINAL: PASS - 10/10, all protections verified.")
    else:
        print(f"\n  FINAL: FAIL - see details above.")

    return 0 if all_ok else 1


def cmd_publish(args):
    """TEST-DRAFT: 단일 콘텐츠를 실제 WordPress에 status="draft"(비공개 초안)로
    게시한다. 실제 WP POST가 발생하지만 공개(publish)되지는 않는다.

    CALCMATE-STEP170: BLOG_SCHEDULE.mode="draft"(SAFE-DRY-RUN, WP 자체를 호출하지
    않음)와 이 명령의 "draft"는 서로 다른 개념이다 — 혼동 방지를 위해 명시한다.
    """
    import yaml
    cfg = _cfg()
    # config/secrets 로드
    for fname in ["config/config.yaml", "config/secrets.yaml"]:
        fp = str(ROOT / fname)
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    cfg.update(data)

    from modules.blog_scheduler_adapter import run_blog_once_wp, _output_dir

    db_hash_before = _db_hash(str(ROOT / "data" / "blog_auto.db"))

    result = run_blog_once_wp(cfg, max_count=1, driver_id="cli_run_blog_scheduler",
                              status="draft")

    db_hash_after = _db_hash(str(ROOT / "data" / "blog_auto.db"))
    db_unchanged = db_hash_before == db_hash_after

    print(f"\n{'='*60}")
    print(f"[Blog Scheduler] TEST-DRAFT (WP 비공개 초안 생성)")
    print(f"{'='*60}")
    print(f"  Produced: {result['produced']}")
    print(f"  DB hash:  {db_hash_before} -> {db_hash_after} ({'UNCHANGED' if db_unchanged else 'CHANGED!'})")
    print(f"  DB write: {result.get('db_write', 0)}")
    print(f"  WP call:  {result.get('wordpress_call', 0)}")
    print(f"  Img call: {result.get('image_call', 0)}")

    for r in result["results"]:
        status = r["status"]
        print(f"  [{status}] {r['slug']:30s} {r['intent']:15s} {status}")
        if "wp_post_id" in r:
            print(f"    wp_post_id: {r['wp_post_id']}")

    if not db_unchanged:
        print("\n*** WARNING: DB was modified! ***")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Blog Scheduler CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Golden 10 전체 dry-run")
    sub.add_parser("full", help="Full verification (dry-run + validate + protection)")
    sub.add_parser("publish", help="TEST-DRAFT: 단일 WP 초안 생성(status=draft, 비공개, 실제 WP POST 발생)")

    p_single = sub.add_parser("single", help="단일 콘텐츠 dry-run")
    p_single.add_argument("--slug", required=True)
    p_single.add_argument("--intent", required=True)

    sub.add_parser("validate", help="기존 콘텐츠 구조 검증")

    args = parser.parse_args()

    if args.command == "run":
        return cmd_full_dry_run(args)
    elif args.command == "single":
        return cmd_single_dry_run(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "full":
        return cmd_full(args)
    elif args.command == "publish":
        return cmd_publish(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
