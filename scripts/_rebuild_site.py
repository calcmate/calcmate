# -*- coding: utf-8 -*-
"""CalcMate 계산기 + 사이트 페이지 _site 재생성.
status=HOLD 계산기(App Factory 생성 후 legal 미검증)는 빌드 제외.

main()으로 감싸 격리 테스트(tmp_path DB/mock AG·SG)에서 안전하게 호출할 수
있게 한다 — CLI 실행(`python scripts/_rebuild_site.py`)은 기존과 동일하게
동작한다(모듈 임포트만으로는 아무 것도 실행되지 않음)."""
import os, sys
sys.path.insert(0, ".")


def _record_published_url_if_missing(repo, cfg, c: dict) -> None:
    """전체 재빌드 성공 후 published_url이 비어있는 계산기에만 실제 공개 URL을 기록한다.
    이미 값이 있으면 건드리지 않는다(개별 배포 경로가 기록한 URL 보존).
    GitHub 배포/git push는 절대 실행하지 않으며, 기존 CalculatorRepository.update()로
    published_url 필드만 갱신한다(status 등 다른 필드는 변경하지 않음)."""
    if (c.get("published_url") or "").strip():
        return
    slug = c.get("slug", "")
    site_url = str(cfg.get("SITE_URL", "https://calcmate.kr")).rstrip("/")
    url = f"{site_url}/{slug}/"
    repo.update(c.get("id", ""), {"published_url": url})
    print(f"  [PUBLISHED_URL] {slug} -> {url}")


def main(cfg=None, repo=None, site_dir=None, ag=None, sg=None):
    """cfg/repo/site_dir/ag/sg를 주입하지 않으면 실제 설정/운영 DB/기본 경로를 사용한다
    (기존 CLI 동작과 동일). 테스트는 반드시 이 인자들로 격리된 값을 주입해야 한다."""
    from pathlib import Path
    from modules.config_loader import load_config
    from adapters.db.factory import get_db_adapter, get_template_storage_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules import app_generator as AG
    from modules import site_generator as SG
    from modules.registry_loader import load_registry_v3

    if cfg is None:
        cfg = load_config()
    if repo is None:
        repo = CalculatorRepository(get_db_adapter(cfg))
    if ag is None:
        ag = AG
    if sg is None:
        sg = SG
    calcs = repo.get_all()
    _v3 = load_registry_v3()

    if site_dir is None:
        base = Path(__file__).resolve().parent.parent
        site_dir = base / "data" / "workspace" / "_site"
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)

    errors = []

    # ─── 1. 사이트 공통 페이지 재생성 ───────────────────────────────────────
    print("=== 사이트 공통 페이지 재생성 ===")
    site_pages = {}
    try:
        site_pages = sg.generate_all(cfg)
        for path, content in site_pages.items():
            fp = site_dir / path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            print(f"  [OK] {path}")
    except Exception as e:
        print(f"  [ERROR] site pages: {e}")
        errors.append(f"site: {e}")

    # ─── 2. 계산기 재생성 (HOLD 제외) ────────────────────────────────────────────────
    print("\n=== 계산기 재생성 (status=HOLD 제외) ===")
    for c in calcs:
        slug = c.get("slug", "")
        v3_entry = _v3.get(slug) or {}
        # App Factory HOLD 계산기 — READY 전환 후에만 빌드
        if v3_entry.get("status") == "HOLD":
            print(f"  [SKIP] {slug} — HOLD 상태 (READY 전환 후 재빌드)")
            continue
        # Tier2-B: html_template을 DB에서 직접 복사 (AI 재생성 없음)
        if v3_entry.get("tier_subtype") == "B":
            tpl_id = c.get("template_id")
            if not tpl_id:
                print(f"  [SKIP] {slug} — Tier2-B이나 template_id 없음")
                continue
            try:
                from repositories.template_repository import TemplateRepository
                tpl = TemplateRepository(get_template_storage_adapter(cfg)).get_by_id(tpl_id)
                html = (tpl or {}).get("html_template", "")
                if not html:
                    raise ValueError("html_template이 비어있음")
                slug_dir = site_dir / slug
                slug_dir.mkdir(parents=True, exist_ok=True)
                (slug_dir / "index.html").write_text(html, encoding="utf-8")
                print(f"  [OK] {slug} (Tier2-B 템플릿 직접 복사)")
                _record_published_url_if_missing(repo, cfg, c)
            except Exception as e:
                print(f"  [ERROR] {slug}: {e}")
                errors.append(f"{slug}: {e}")
            continue
        try:
            files = ag.generate_calculator(c, cfg)
            slug_dir = site_dir / slug
            slug_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in files.items():
                if fname in ("index.html", "style.css", "script.js"):
                    (slug_dir / fname).write_text(content, encoding="utf-8")
            print(f"  [OK] {slug}")
            _record_published_url_if_missing(repo, cfg, c)
        except Exception as e:
            print(f"  [ERROR] {slug}: {e}")
            errors.append(f"{slug}: {e}")

    # ─── 3. 요약 ─────────────────────────────────────────────────────────────
    _hold_count = sum(1 for c in calcs if (_v3.get(c.get("slug", "")) or {}).get("status") == "HOLD")
    print(f"\n=== 완료: {len(calcs)}종 DB / HOLD 제외 빌드 / {len(site_pages)}개 사이트 페이지 ===")
    if _hold_count:
        print(f"  [INFO] HOLD 상태로 빌드 제외: {_hold_count}종 (READY 전환 후 재빌드 필요)")
    if errors:
        print("에러:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("에러 없음")
    return {"calcs": calcs, "site_pages": site_pages, "errors": errors}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
