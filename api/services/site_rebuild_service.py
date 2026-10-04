"""api/services/site_rebuild_service.py — 전체 정적 사이트 재빌드
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01, GAP-03).

dashboard.py "⚙️ Build — {계산기}"(L1809-1880) 이관. 원본 순서를 그대로 지킨다:
READY app_factory 계산기 확인 → pre_build_qa(calc, cfg) → 실패 시 차단 →
scripts/_rebuild_site.py 실행(전체 계산기 + 공통 페이지 + sitemap + published_url 기록) →
결과 확인 → 수동 배포 안내.

POST /api/calculators/{slug}/build(계산기 1개 스냅샷)와는 별개다 — 그 계약은 건드리지 않는다.
BUILD ≠ DEPLOY: 여기서는 Git commit/push, GitHub API, WP, Telegram을 호출하지 않는다.

실행은 원본과 같은 고정 명령([sys.executable, scripts/_rebuild_site.py], cwd=프로젝트 루트,
shell 없음, timeout 180초)이며 사용자 입력은 명령에 들어가지 않는다. stdout/stderr 원문은
반환하지 않고 [OK]/[SKIP]/[ERROR] 줄 수와 slug만 요약한다. _site 전체를 다시 쓰므로
블로그배포/사이트 페이지 배포와 같은 기존 lock(wp_blog_deploy.lock)을 함께 잡는다.
"""
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SITE_REL = "data/workspace/_site"
_SCRIPT_REL = ("scripts", "_rebuild_site.py")
REBUILD_TIMEOUT_SECONDS = 180

REQUIRED_OUTPUTS = (
    "index.html", "sitemap.xml", "robots.txt",
    "about/index.html", "privacy/index.html", "terms/index.html", "contact/index.html",
    "404.html", "site.css",
)

_LINE_RE = re.compile(r"^\s*\[(OK|SKIP|ERROR)\]\s+([A-Za-z0-9][A-Za-z0-9._/-]*)")
_proc_lock = threading.Lock()


class SiteRebuildError(Exception):
    """사전 조건 실패(VALIDATION_ERROR/NOT_FOUND) 또는 TIMEOUT. code를 라우터가 그대로 쓴다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SiteRebuildBusy(Exception):
    """다른 재빌드/사이트 배포가 진행 중."""


def _default_runner(root: Path, timeout: int):
    """원본과 같은 고정 명령. 테스트는 _runner를 대체한다."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(root.joinpath(*_SCRIPT_REL))],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env, shell=False,
    )


_runner = _default_runner


def _summarize_output(stdout: str) -> dict:
    ok, skip, err = [], [], []
    for line in (stdout or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        kind, name = m.group(1), m.group(2).rstrip(":")
        (ok if kind == "OK" else skip if kind == "SKIP" else err).append(name)
    return {"ok_count": len(ok), "skip_count": len(skip), "error_count": len(err),
            "skipped": skip, "errors": err}


def _expected_calculator_slugs(repo, v3_reg: dict) -> list:
    """_rebuild_site.py와 같은 규칙: DB 전체 중 HOLD 제외, Tier2-B인데 template_id 없으면 제외."""
    out = []
    for c in repo.get_all():
        slug = c.get("slug", "")
        v3e = v3_reg.get(slug) or {}
        if not slug or v3e.get("status") == "HOLD":
            continue
        if v3e.get("tier_subtype") == "B" and not c.get("template_id"):
            continue
        out.append(slug)
    return out


def _validate_outputs(site_dir: Path, started: float, expected: list, trigger_slug: str) -> dict:
    missing, stale = [], []
    for rel in REQUIRED_OUTPUTS:
        p = site_dir / rel
        if not p.is_file() or p.stat().st_size == 0:
            missing.append(rel)
        elif p.stat().st_mtime < started - 1:
            stale.append(rel)
    calc_missing = [s for s in expected if not (site_dir / s / "index.html").is_file()]
    sitemap = site_dir / "sitemap.xml"
    in_sitemap = sitemap.is_file() and trigger_slug in sitemap.read_text(encoding="utf-8", errors="replace")
    return {
        "required_missing": missing,
        "required_stale": stale,
        "calculators_expected": len(expected),
        "calculators_missing": calc_missing,
        "target_index": (site_dir / trigger_slug / "index.html").is_file(),
        "target_in_sitemap": bool(in_sitemap),
    }


def _manual_deploy_steps(cfg: dict, slug: str) -> list:
    site_url = str(cfg.get("SITE_URL") or "https://calcmate.kr").strip().rstrip("/")
    return [
        f'Step 1 — git add data/workspace/_site/ docs/registry/ && git commit -m "feat: add {slug} calculator"',
        "Step 2 — git push origin master",
        "Step 3 — GitHub Actions 최신 워크플로 ✅ 완료 확인",
        f"Step 4 — {site_url}/ · {site_url}/{slug}/ · {site_url}/sitemap.xml 실제 확인",
    ]


def rebuild_site(slug: str) -> dict:
    from api.services import calculator_service as CS
    from modules import wp_blog_deploy as WBD
    from modules.review_center import pre_build_qa

    try:
        CS._validate_slug(slug)
    except CS.CalculatorValidationError as e:
        raise SiteRebuildError("VALIDATION_ERROR", str(e)) from None
    try:
        calc, v3_reg, cfg = CS._get_calc_or_raise(slug)
    except CS.CalculatorNotFound:
        raise SiteRebuildError("NOT_FOUND", "계산기를 찾을 수 없습니다.") from None
    v3e = v3_reg.get(slug) or {}
    if not (v3e.get("source") == "app_factory" and v3e.get("status") == "READY"):
        raise SiteRebuildError("VALIDATION_ERROR", "READY 상태의 App Factory 계산기에서만 전체 Build를 실행할 수 있습니다.")

    cfg = dict(cfg)
    cfg["_root"] = str(_ROOT)
    base = {"trigger_slug": slug, "target": f"{_SITE_REL}/", "deployed": False}

    qa = pre_build_qa(calc, cfg)
    qa_view = [{"step": r.get("step"), "label": r.get("label"), "passed": bool(r.get("passed")),
                "skipped": bool(r.get("skipped")), "detail": str(r.get("detail", ""))[:500]} for r in qa]
    qa_failed = [r for r in qa_view if not r["passed"] and not r["skipped"]]
    if qa_failed:
        return {**base, "ok": False, "stage": "qa", "qa": qa_view,
                "message": f"Build 차단 — 사전 QA {len(qa_failed)}개 항목 실패"}

    repo, _ = CS._repo_and_cfg()
    expected = _expected_calculator_slugs(repo, v3_reg)

    if not _proc_lock.acquire(blocking=False):
        raise SiteRebuildBusy("전체 사이트 Build가 이미 실행 중입니다.")
    try:
        if not WBD._acquire_lock(cfg):
            raise SiteRebuildBusy("블로그배포 등 다른 사이트 작업이 진행 중입니다(wp_blog_deploy.lock). 잠시 후 다시 시도하세요.")
        try:
            started = time.time()
            try:
                proc = _runner(_ROOT, REBUILD_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                raise SiteRebuildError("TIMEOUT", f"전체 사이트 Build가 {REBUILD_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다.") from None
            duration = round(time.time() - started, 1)
            summary = _summarize_output(getattr(proc, "stdout", "") or "")
            if proc.returncode != 0:
                return {**base, "ok": False, "stage": "build", "qa": qa_view, "returncode": proc.returncode,
                        "summary": summary, "duration_sec": duration,
                        "message": "❌ Build 실패 — 재빌드 스크립트가 오류로 종료되었습니다(서버 로그 확인)."}
            validation = _validate_outputs(_ROOT / _SITE_REL, started, expected, slug)
            valid = (not validation["required_missing"] and not validation["required_stale"]
                     and not validation["calculators_missing"] and validation["target_index"]
                     and validation["target_in_sitemap"])
            all_ok = valid and summary["error_count"] == 0
            return {
                **base, "ok": all_ok, "stage": "done" if all_ok else "validation", "qa": qa_view,
                "returncode": 0, "summary": summary, "validation": validation, "duration_sec": duration,
                "message": "✅ Build 완료 — _site/ 갱신됨" if all_ok else "⚠️ Build 결과 검증 실패 — 아래 항목을 확인하세요.",
                "manual_deploy_steps": _manual_deploy_steps(cfg, slug),
            }
        finally:
            WBD._release_lock(cfg)
    finally:
        _proc_lock.release()
