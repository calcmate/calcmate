# -*- coding: utf-8 -*-
"""
modules/blog_scheduler_adapter.py — Scheduler → Blog line 연결 어댑터

Scheduler의 run_once_fn(contract) 인터페이스를 만족시키면서
blog adapter(content.blog)를 통해 intent별 콘텐츠를 생성한다.

핵심 보호:
- calculators.article_content 절대 수정 안 함
- WordPress 호출 안 함
- Image Pipeline 호출 안 함
- 모든 출력은 isolated directory에 저장
"""
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from content.blog import GOLDEN_10, get_golden10, validate_intent, get_content_request
from content.blog.writer import generate_blog_article, auto_generate_blog_all


def _db_path(cfg: dict) -> Path:
    """DB 파일 경로 반환."""
    root = Path(cfg.get("_root", str(ROOT)))
    return root / "data" / "blog_auto.db"


def _output_dir(cfg: dict) -> Path:
    """isolated output 디렉토리."""
    root = Path(cfg.get("_root", str(ROOT)))
    d = root / "data" / "reproduction" / "scheduler_blog"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_calculator(cfg: dict, slug: str) -> dict | None:
    """DB에서 계산기 데이터 로드 (READ-ONLY)."""
    db = _db_path(cfg)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM calculators WHERE slug=?", (slug,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def _record_hash(cfg: dict, slug: str, phase: str) -> str:
    """DB article_content hash 기록 (전/후 비교용)."""
    calc = _load_calculator(cfg, slug)
    if not calc or not calc.get("article_content"):
        return ""
    return hashlib.sha256(calc["article_content"].encode()).hexdigest()[:16]


# ============================================================
# Blog ScheduleRequest
# ============================================================

class BlogScheduleRequest:
    """Scheduler → Blog adapter 요청 객체."""
    
    def __init__(self, slug: str, intent: str, title: str = "",
                 description: str = "", mode: str = "dry-run"):
        self.slug = slug
        self.intent = intent
        self.title = title
        self.description = description
        self.mode = mode  # "dry-run" | "generate"
    
    def validate(self) -> list[str]:
        """검증 — 오류 메시지 리스트 반환 (빈 리스트면 정상)."""
        errors = []
        if not self.slug:
            errors.append("slug is empty")
        if not validate_intent(self.intent):
            errors.append(f"Invalid intent: {self.intent}")
        # Golden 10 Contract 확인
        gc = get_golden10(self.slug)
        if gc is None:
            errors.append(f"Not in Golden 10 Contract: {self.slug}")
        elif gc.intent != self.intent:
            errors.append(
                f"Intent mismatch: {self.slug} expects '{gc.intent}', got '{self.intent}'"
            )
        return errors


# ============================================================
# Blog Scheduler Adapter — core
# ============================================================

def run_blog_once(cfg: dict, max_count: int = 10, *, driver_id: str = None) -> dict:
    """Scheduler 호환 run_once_fn(contract).
    
    Golden 10 전체를 대상으로 blog 콘텐츠를 생성하고
    isolated output에 저장한다.
    
    DB write = 0 보장.
    WordPress = 0 보장.
    Image = 0 보장.
    
    Returns:
        {"produced": int, "reason": str, "results": list}
    """
    output_dir = _output_dir(cfg)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    produced = 0
    
    for gc in GOLDEN_10[:max_count]:
        req = BlogScheduleRequest(
            slug=gc.slug,
            intent=gc.intent,
            title=gc.title,
            description=gc.description,
        )
        
        # 검증
        errors = req.validate()
        if errors:
            results.append({
                "slug": gc.slug, "intent": gc.intent,
                "status": "VALIDATION_ERROR", "errors": errors,
            })
            continue
        
        # DB에서 계산기 데이터 로드 (READ-ONLY)
        calc = _load_calculator(cfg, gc.slug)
        if not calc:
            results.append({
                "slug": gc.slug, "intent": gc.intent,
                "status": "ERROR", "reason": "not_in_db",
            })
            continue
        
        # hash 기록 (전)
        hash_before = _record_hash(cfg, gc.slug, "before")
        
        # blog 콘텐츠 생성
        try:
            result = auto_generate_blog_all(cfg, calc, save=False, intent=gc.intent,
                                            driver_id=driver_id)
            article = result.get("article_content", "")

            # isolated output 저장
            slug_dir = output_dir / gc.slug
            slug_dir.mkdir(parents=True, exist_ok=True)
            
            html_file = slug_dir / f"{gc.slug}_{gc.intent}.html"
            # Hash the exact bytes written to disk. Using write_text() on Windows can
            # translate newlines after hashing, so write_bytes() is intentional.
            article_bytes = article.encode("utf-8")
            html_file.write_bytes(article_bytes)
            article_hash = hashlib.sha256(article_bytes).hexdigest()[:16]
            
            meta = {
                "slug": gc.slug,
                "intent": gc.intent,
                "title": gc.title,
                "description": gc.description,
                "article_len": len(article),
                "article_hash": article_hash,
                "source": "scheduler_blog_adapter",
                "db_write": False,
                "wordpress_call": False,
                "image_call": False,
                # METADATA-05: auto_generate_blog_all()이 이미 반환하는 generation_metadata를
                # 그대로 보존한다(METADATA-03/04에서 확정된 구조를 다시 계산/변경하지 않음).
                # 기존 필드는 하나도 삭제/이름변경하지 않았다.
                "generation_metadata": result.get("generation_metadata"),
            }
            meta_file = slug_dir / f"{gc.slug}_{gc.intent}_meta.json"
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            
            produced += 1
            results.append({
                "slug": gc.slug, "intent": gc.intent,
                "status": "SUCCESS",
                "article_len": len(article),
                "output": str(html_file),
            })
            
        except Exception as e:
            results.append({
                "slug": gc.slug, "intent": gc.intent,
                "status": "ERROR", "reason": str(e),
            })
        
        # hash 기록 (후) — DB 변경 없음을 검증
        hash_after = _record_hash(cfg, gc.slug, "after")
        if hash_before and hash_after and hash_before != hash_after:
            results.append({
                "slug": gc.slug, "intent": gc.intent,
                "status": "PROTECTION_FAIL",
                "reason": f"DB content changed: {hash_before} → {hash_after}",
            })
    
    # 요약 저장
    summary = {
        "total": len(results),
        "produced": produced,
        "results": results,
        "db_write": 0,
        "wordpress_call": 0,
        "image_call": 0,
    }
    summary_file = output_dir / "scheduler_blog_summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    
    return {
        "produced": produced,
        "reason": "" if produced > 0 else "no_items",
        "results": results,
    }


def run_blog_dry_run(cfg: dict, slug: str, intent: str, *, driver_id: str = None) -> dict:
    """단일 콘텐츠 Scheduler dry-run.
    
    Args:
        cfg: 설정 dict
        slug: 계산기 slug
        intent: 검색 의도
    
    Returns:
        {"success": bool, "result": dict, "errors": list}
    """
    req = BlogScheduleRequest(slug=slug, intent=intent)
    errors = req.validate()
    if errors:
        return {"success": False, "result": None, "errors": errors}
    
    calc = _load_calculator(cfg, slug)
    if not calc:
        return {"success": False, "result": None, "errors": [f"Not in DB: {slug}"]}
    
    hash_before = _record_hash(cfg, slug, "before")
    
    try:
        result = auto_generate_blog_all(cfg, calc, save=False, intent=intent,
                                        driver_id=driver_id)
        article = result.get("article_content", "")

        output_dir = _output_dir(cfg) / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        
        html_file = output_dir / f"{slug}_{intent}.html"
        # Keep metadata hash aligned with the exact bytes persisted in article.html.
        article_bytes = article.encode("utf-8")
        html_file.write_bytes(article_bytes)
        article_hash = hashlib.sha256(article_bytes).hexdigest()[:16]
        
        meta = {
            "slug": slug, "intent": intent,
            "article_len": len(article),
            "article_hash": article_hash,
            "source": "scheduler_blog_dry_run",
            "db_write": False,
            # METADATA-05: run_blog_once()와 동일하게 generation_metadata를 그대로 보존.
            "generation_metadata": result.get("generation_metadata"),
        }
        meta_file = output_dir / f"{slug}_{intent}_meta.json"
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        
        hash_after = _record_hash(cfg, slug, "after")
        protection_ok = (hash_before == hash_after) if hash_before else True
        
        return {
            "success": True,
            "result": {
                "slug": slug, "intent": intent,
                "article_len": len(article),
                "output": str(html_file),
                "protection_ok": protection_ok,
                "hash_before": hash_before,
                "hash_after": hash_after,
            },
            "errors": [],
        }
    except Exception as e:
        return {"success": False, "result": None, "errors": [str(e)]}


# ============================================================
# Blog Scheduler → WordPress Publisher 연결
# ============================================================

def run_blog_once_wp(cfg: dict, max_count: int = 1, *, driver_id: str = None,
                     status: str = "publish") -> dict:
    """Blog Line → WordPress 발행 (Scheduler run_once_fn 호환).

    Calculator Line의 run_calculator_once()와 동일한 시그니처.
    scheduler.run_scheduler_loop(cfg, run_blog_once_wp)로 직접 연결 가능.

    생성 → 검증 → 기존 publisher.py로 WordPress 발행.
    DB write = 0 (articles 테이블에도 기록하지 않음).

    status: publisher.publish()에 그대로 전달되는 WP post_status("publish"|"draft").
    기본값 "publish"이므로 기존 호출부(main.py::resolve_blog_publish_fn의 자동
    scheduler 경로 — status 인자 없이 호출)는 전혀 영향받지 않는다. CALCMATE-STEP170:
    scripts/run_blog_scheduler.py::cmd_publish()가 이 인자에 명시적으로 "draft"를
    전달해 실제 WP에는 쓰지만 비공개 초안으로만 남기는 TEST-DRAFT 경로를 만든다.

    Returns:
        {"produced": int, "reason": str, "results": list}
    """
    import modules.publisher as publisher
    from modules.config_loader import is_wordpress_ready

    if not is_wordpress_ready(cfg):
        # WordPress 미연결 시 isolated output만 생성
        return run_blog_once(cfg, max_count=max_count, driver_id=driver_id)

    output_dir = _output_dir(cfg)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    produced = 0

    for gc in GOLDEN_10[:max_count]:
        req = BlogScheduleRequest(
            slug=gc.slug, intent=gc.intent,
            title=gc.title, description=gc.description,
        )
        errors = req.validate()
        if errors:
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "VALIDATION_ERROR", "errors": errors})
            continue

        calc = _load_calculator(cfg, gc.slug)
        if not calc:
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "ERROR", "reason": "not_in_db"})
            continue

        # 중복 검사: WordPress에 이미 같은 slug가 있는지 확인 (CALCMATE-STEP172:
        # FAIL-CLOSED — 중복 없음이 실제로 확인(confirmed=True)되지 않으면 발행하지
        # 않는다. "검사 실패했지만 발행 시도"는 더 이상 하지 않는다.)
        dup = _check_wp_duplicate(cfg, gc.slug)
        if not dup.get("confirmed"):
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "DUPLICATE_CHECK_FAILED",
                            "reason": dup.get("error", "unknown")})
            continue
        if dup.get("exists"):
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "SKIP_DUPLICATE",
                            "wp_post_id": dup.get("wp_post_id") or ""})
            continue

        hash_before = _record_hash(cfg, gc.slug, "before")

        try:
            result = auto_generate_blog_all(cfg, calc, save=False, intent=gc.intent,
                                            driver_id=driver_id)
            article = result.get("article_content", "")

            if not article or len(article) < 100:
                results.append({"slug": gc.slug, "intent": gc.intent,
                                "status": "ERROR", "reason": "empty_article"})
                continue

            # 기존 publisher.py로 WordPress 발행
            # STEP125: GOLDEN_10 contract의 slug를 명시적으로 전달 — WordPress가 title
            # 기반으로 slug를 임의 생성하지 않고 의도된 slug를 사용하도록 한다.
            seo = {
                "seo_title": gc.title,
                "seo_description": gc.description,
                "slug": gc.slug,
            }
            post_id = f"blog_{gc.slug}_{gc.intent}"
            pub_result = publisher.publish(post_id, seo, article, {}, cfg, status=status)
            pub_status = pub_result.get("status", "published")

            if pub_status in ("published", "draft"):
                produced += 1
                results.append({
                    "slug": gc.slug, "intent": gc.intent,
                    "status": "PUBLISHED" if pub_status == "published" else "DRAFT",
                    "wp_post_id": pub_result.get("wp_post_id", ""),
                    "wp_permalink": pub_result.get("wp_permalink", ""),
                    "article_len": len(article),
                    # METADATA-05: 이 결과 항목이 이미 article_len 등 generation 결과값을
                    # 추적하고 있으므로, run_blog_once()와 동일하게 generation_metadata도
                    # 추가로 보존한다(publish 관련 필드는 전혀 변경하지 않음).
                    "generation_metadata": result.get("generation_metadata"),
                })
            else:
                results.append({"slug": gc.slug, "intent": gc.intent,
                                "status": "PUBLISH_FAILED",
                                "error": pub_result.get("error", "unknown")})

        except Exception as e:
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "ERROR", "reason": str(e)})

        hash_after = _record_hash(cfg, gc.slug, "after")
        if hash_before and hash_after and hash_before != hash_after:
            results.append({"slug": gc.slug, "intent": gc.intent,
                            "status": "PROTECTION_FAIL",
                            "reason": f"DB changed: {hash_before} -> {hash_after}"})

    summary = {
        "total": len(results), "produced": produced, "results": results,
        "db_write": 0, "wordpress_call": produced, "image_call": 0,
    }
    summary_file = output_dir / "blog_wp_publish_summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return {"produced": produced,
            "reason": "" if produced > 0 else "no_items",
            "results": results}


def _check_wp_duplicate(cfg: dict, slug: str) -> dict:
    """WordPress에 이미 같은 slug의 게시물이 있는지 확인 (READ-ONLY, FAIL-CLOSED).

    CALCMATE-STEP172: 이전에는 조회 실패/예외/비정상 응답을 전부 "중복 없음"(None)으로
    되돌려 호출부가 발행을 강행했다(FAIL-OPEN). 이제는 항상 다음 계약의 dict를
    반환하며, "중복 없음이 실제로 확인되었는지"(confirmed)와 "중복이 존재하는지"
    (exists)를 분리한다 — confirmed=False면 호출부는 반드시 발행을 금지해야 한다.

    또한 조회 파라미터의 slug는 실제 publisher.publish() → _wordpress_api()가
    WP payload["slug"]로 전송하는 값(= 이 함수의 slug 인자, run_blog_once_wp()가
    gc.slug를 그대로 넘긴다)과 정확히 동일해야 한다. 이전에는 f"blog_{slug}"로
    조회해 실제 게시되는 slug(접두사 없음)와 어긋나 진짜 중복을 찾지 못했다.

    반환:
      {"exists": bool, "confirmed": bool, "wp_post_id": str|None,
       "slug": str|None, "error": str|None}

    "중복 없음"으로 확정되는 유일한 경우: HTTP 200 + JSON list + 빈 리스트.
    그 외(모든 non-200, timeout, connection error, JSON decode 실패, list가 아닌
    응답, 함수 내부의 예상 밖 예외 등)는 전부 confirmed=False다.
    """
    wp_url = cfg.get("WORDPRESS_URL", "")
    if not wp_url:
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": "no_wp_url"}

    try:
        import requests
        auth = None
        username = cfg.get("WORDPRESS_USERNAME", "")
        app_password = cfg.get("WORDPRESS_APP_PASSWORD", "")
        if username and app_password:
            auth = (username, app_password)
        resp = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            params={"slug": slug, "per_page": 1},
            auth=auth, timeout=10,
        )
    except Exception as e:
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": f"request_error:{e}"}

    if resp.status_code != 200:
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": f"http_{resp.status_code}"}

    try:
        posts = resp.json()
    except Exception as e:
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": f"decode_error:{e}"}

    if not isinstance(posts, list):
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": "unexpected_response_shape"}

    try:
        if posts:
            return {"exists": True, "confirmed": True,
                    "wp_post_id": posts[0].get("id"), "slug": posts[0].get("slug"),
                    "error": None}
    except Exception as e:
        return {"exists": False, "confirmed": False, "wp_post_id": None,
                "slug": None, "error": f"malformed_post_entry:{e}"}

    return {"exists": False, "confirmed": True, "wp_post_id": None,
            "slug": None, "error": None}
