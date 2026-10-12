# -*- coding: utf-8 -*-
"""scripts/deploy_freeze_guard.py — CALCMATE-PUBLIC-SAFETY-DEPLOY-FREEZE (안 B3).

Calculator deploy freeze guard for .github/workflows/deploy.yml.

Runs in CI before the Pages artifact is uploaded. It compares the committed git
tree of data/workspace/_site at HEAD with a frozen baseline (path -> git blob id).
Calculator directories (everything under _site that is not a shared site entry)
must be byte-identical to the baseline: no changed, added or removed calculator
file is allowed. Shared site files (index.html, sitemap.xml, common pages ...)
are not compared, so blog index/sitemap updates keep deploying.

Fail-closed: a missing/invalid baseline, a git error or any calculator diff
exits non-zero, which stops the job before upload/deploy.

Blob ids come from `git ls-tree` (committed bytes), so working-tree line endings
(core.autocrlf on Windows) cannot cause false matches or mismatches.

Usage:
  python scripts/deploy_freeze_guard.py check  --baseline .github/deploy_freeze_baseline.json
  python scripts/deploy_freeze_guard.py export --commit <sha> --out <file>   # baseline creation (manual, approved)
"""
import argparse
import json
import subprocess
import sys

SITE = "data/workspace/_site"
# Shared site entries (same set as modules/github_deployer.py _RESERVED_SITE_ENTRIES).
SHARED = frozenset({
    "index.html", "sitemap.xml", "CNAME", "about", "contact", "privacy", "terms",
    "404", "404.html", "robots.txt", "site.css",
})


def _calculator_blobs(commit: str) -> dict:
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-tree", "-r", commit, "--", SITE],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git ls-tree failed: {r.stderr.strip()}")
    blobs = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        rel = path[len(SITE) + 1:]
        if rel.split("/", 1)[0] in SHARED:
            continue
        blobs[rel] = meta.split()[2]
    return blobs


def check(baseline_path: str) -> int:
    try:
        with open(baseline_path, encoding="utf-8") as f:
            base = json.load(f)
        want = base["calculator_blobs"]
        if not isinstance(want, dict) or not want:
            raise ValueError("calculator_blobs empty or not a mapping")
    except Exception as e:
        print(f"FREEZE_GUARD_FAIL baseline unreadable: {e}")
        return 2
    try:
        got = _calculator_blobs("HEAD")
    except Exception as e:
        print(f"FREEZE_GUARD_FAIL {e}")
        return 2
    added = sorted(set(got) - set(want))
    removed = sorted(set(want) - set(got))
    changed = sorted(p for p in set(want) & set(got) if want[p] != got[p])
    if added or removed or changed:
        print("FREEZE_GUARD_FAIL calculator files differ from the frozen baseline "
              f"(commit {base.get('commit')}):")
        for label, items in (("added", added), ("removed", removed), ("changed", changed)):
            for p in items[:50]:
                print(f"  {label}: {p}")
        return 1
    print(f"FREEZE_GUARD_OK {len(got)} calculator files identical to baseline {base.get('commit')}")
    return 0


def export(commit: str, out: str) -> int:
    blobs = _calculator_blobs(commit)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"schema": 1, "commit": commit, "calculator_blobs": blobs}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print(f"exported {len(blobs)} calculator files from {commit}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--baseline", required=True)
    e = sub.add_parser("export")
    e.add_argument("--commit", required=True)
    e.add_argument("--out", required=True)
    a = ap.parse_args()
    return check(a.baseline) if a.cmd == "check" else export(a.commit, a.out)


if __name__ == "__main__":
    sys.exit(main())
