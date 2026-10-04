"""api/services/site_pages_service.py — 사이트 공통 페이지 미리보기/로컬 저장/배포
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-SITE-PAGE-DEPLOYMENT-02).

dashboard.py "🌐 사이트 페이지 배포"(L1881-1930) 이관. 생성은 기존
modules.site_generator.generate_all(cfg)를 그대로 쓴다(전역 cfg — SITE_URL/SITE_NAME,
현재 Site와 무관). 9개 산출물: index.html, site.css, about/index.html, privacy/index.html,
terms/index.html, contact/index.html, 404.html, sitemap.xml, robots.txt.

배포 transport만 원본과 다르다: 원본의 GitHub Contents API 파일별 원격 commit
(create_repo/_put_file×9/_enable_pages)은 이관하지 않고, 계산기 Deploy와 같은 로컬 Git
경로(modules.github_deployer.deploy_site_pages — 9개 파일만 stage → 1회 commit →
local HEAD == origin/master일 때만 push)를 쓴다. Pages 반영은 기존 .github/workflows/
deploy.yml이 맡는다.

index.html/sitemap.xml은 블로그배포(modules.wp_blog_deploy)도 같은 generator로 갱신·push
하므로, 배포는 그 기존 lock(wp_blog_deploy.lock)을 함께 잡아 동시에 git 작업을 하지 않게
하고(새 lock을 만들지 않음), 같은 기존 검증(validate_index_html/validate_sitemap_xml:
Golden10 그리드 보존·sitemap URL 삭제 금지)을 통과해야만 진행한다.

부분 생성물은 배포하지 않는다 — 9개가 모두 생성·검증돼야만 파일을 쓰고 배포한다.
"""
from pathlib import Path

from modules.config_loader import load_config

_ROOT = Path(__file__).resolve().parent.parent.parent
_SITE_REL = "data/workspace/_site"


class SitePagesBuildError(Exception):
    """generator 실패 또는 9개 산출물 불완전."""


class SitePagesBusy(Exception):
    """블로그배포(wp_blog_deploy)와 같은 lock을 다른 실행이 보유 중."""


def _cfg() -> dict:
    cfg = dict(load_config())
    cfg.setdefault("_root", str(_ROOT))
    return cfg


def build_site_pages(cfg: dict) -> dict:
    """generate_all(cfg) → 9개 산출물 검증. 하나라도 빠지거나 비어 있으면 SitePagesBuildError."""
    from modules import site_generator
    from modules.github_deployer import SITE_PAGE_FILES
    try:
        pages = site_generator.generate_all(cfg)
    except Exception as e:
        raise SitePagesBuildError(f"사이트 페이지 생성 실패({type(e).__name__})") from None
    names = set(pages or {})
    missing = sorted(set(SITE_PAGE_FILES) - names)
    extra = sorted(names - set(SITE_PAGE_FILES))
    empty = sorted(n for n in names if not isinstance(pages[n], str) or not pages[n])
    if missing or extra or empty:
        raise SitePagesBuildError(f"사이트 페이지 산출물 불완전 — 누락 {missing} / 예상 외 {extra} / 빈 파일 {empty}")
    return {name: pages[name] for name in SITE_PAGE_FILES}


def _site_url(cfg: dict) -> str:
    return str(cfg.get("SITE_URL") or "https://calcmate.kr").strip().rstrip("/") + "/"


def preview_site_pages() -> dict:
    """파일 저장/Git/GitHub 없음 — 생성 결과만 반환한다."""
    cfg = _cfg()
    pages = build_site_pages(cfg)
    return {
        "count": len(pages),
        "site_url": _site_url(cfg),
        "pages": [{"path": p, "content": c, "size": len(c)} for p, c in pages.items()],
    }


def _write_pages(cfg: dict, pages: dict) -> dict:
    site_dir = Path(cfg["_root"]) / _SITE_REL
    saved, failed = [], []
    for path, content in pages.items():
        try:
            fp = site_dir / path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            saved.append(path)
        except Exception as e:
            failed.append({"path": path, "error": type(e).__name__})
    return {"saved": saved, "failed": failed}


def save_site_pages() -> dict:
    """dashboard.py "💾 로컬 저장"과 같이 _site에 9개 파일만 쓴다(Git/GitHub 없음, CNAME 무관)."""
    cfg = _cfg()
    pages = build_site_pages(cfg)
    res = _write_pages(cfg, pages)
    return {"ok": not res["failed"], "count": len(res["saved"]), "saved": res["saved"],
            "failed": res["failed"], "target": f"{_SITE_REL}/"}


def _validate_against_current(cfg: dict, pages: dict) -> str | None:
    """블로그배포와 같은 기존 검증(현재 _site 파일 대비). 실패 사유 또는 None."""
    from modules.wp_blog_deploy import validate_index_html, validate_sitemap_xml
    from content.blog import GOLDEN_10
    site_dir = Path(cfg["_root"]) / _SITE_REL
    golden = {gc.slug for gc in GOLDEN_10}

    def _old(name):
        p = site_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    ok_i, reason_i = validate_index_html(_old("index.html"), pages["index.html"], golden)
    ok_s, reason_s = validate_sitemap_xml(_old("sitemap.xml"), pages["sitemap.xml"], golden)
    if not ok_i or not ok_s:
        return reason_i or reason_s
    return None


def deploy_site_pages(dry_run: bool = False) -> dict:
    """generate → validate → (blog deploy lock) → write _site → 로컬 Git 배포.
    dry_run=True면 파일을 쓰지 않고 현재 _site 기준 배포 계획만 반환한다."""
    from modules import github_deployer as GH
    from modules import wp_blog_deploy as WBD

    cfg = _cfg()
    pages = build_site_pages(cfg)
    if dry_run:
        _, plan = GH.deploy_site_pages(cfg, pages, dry_run=True)
        return {"ok": False, "dry_run": True, "plan": plan, "pages_url": _site_url(cfg)}

    if not WBD._acquire_lock(cfg):
        raise SitePagesBusy("블로그배포 등 다른 사이트 배포가 진행 중입니다(wp_blog_deploy.lock). 잠시 후 다시 시도하세요.")
    try:
        reason = _validate_against_current(cfg, pages)
        if reason:
            return {"ok": False, "deployed": False, "stage": "validation", "message": f"배포하지 않음 — 검증 실패: {reason}",
                    "commit": None, "files": [], "committed": False, "pushed": False, "pages_url": _site_url(cfg)}
        written = _write_pages(cfg, pages)
        if written["failed"]:
            return {"ok": False, "deployed": False, "stage": "write", "message": "배포하지 않음 — 일부 파일 저장 실패",
                    "failed": written["failed"], "commit": None, "files": [], "committed": False,
                    "pushed": False, "pages_url": _site_url(cfg)}
        ok, res = GH.deploy_site_pages(cfg, pages)
        return {"ok": bool(ok), "deployed": bool(ok and res.get("pushed")), "stage": "deploy",
                "pages_url": _site_url(cfg), **res}
    finally:
        WBD._release_lock(cfg)
