"""
publisher.py — STEP 11: WordPress REST API 발행

WordPress 미구축 상태에서도 오류 없이 '대기(skip)'로 동작한다.
키명은 WORDPRESS_APP_PASSWORD로 단일화(구 WORDPRESS_PASSWORD 하위호환).
"""
import re
import requests
import mimetypes
import json
from datetime import datetime
from pathlib import Path

from .config_loader import is_wordpress_ready
from .logger import get_logger

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "outputs"
LOG = get_logger()

def _sanitize_filename(name: str) -> str:
    """Windows 파일명 금지 문자를 대체 문자로 치환."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)


def _app_password(cfg: dict) -> str:
    return (
        cfg.get("WORDPRESS_APP_PASSWORD")
        or cfg.get("WORDPRESS_PASSWORD")
        or cfg.get("wordpress", {}).get("app_password")
        or ""
    )


def _wp_auth(cfg: dict) -> tuple:
    """WordPress REST 인증 튜플. 모든 WP REST 호출이 이 헬퍼를 공유."""
    username = (
        cfg.get("WORDPRESS_USERNAME")
        or cfg.get("wordpress", {}).get("username")
        or ""
    )
    return (username, _app_password(cfg))


def upload_media(fpath: Path, cfg: dict) -> dict:
    """WordPress REST API로 미디어 업로드 (Content-Type 자동판별)."""
    if not fpath.exists():
        return {"success": False, "error": "파일 없음"}
    
    mime_type, _ = mimetypes.guess_type(fpath)
    if not mime_type:
        mime_type = "image/webp"
    
    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + "/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f"attachment; filename={fpath.name}",
        "Content-Type": mime_type
    }
    with open(fpath, "rb") as f:
        resp = requests.post(
            url, data=f, headers=headers,
            auth=_wp_auth(cfg),
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "media_id": data["id"], "source_url": data["source_url"]}


def publish(post_id: str, seo_data: dict, html_body: str,
            image_urls: dict, cfg: dict) -> dict:
    """반환: {"wordpress": url, "status": "published"|"skipped_no_wp"}"""
    wp_image_urls = {}
    for kind, fpath in image_urls.items():
        if fpath and fpath != "실패" and not fpath.startswith("http"):
            res = upload_media(Path(fpath), cfg)
            if res["success"]:
                wp_image_urls[kind] = res
            else:
                raise Exception(f"Media upload failed: {res['error']}")
        else:
            wp_image_urls[kind] = {"source_url": fpath}

    if not is_wordpress_ready(cfg):
        LOG.info("WordPress 미구성 — 발행 건너뜀(검수대기)")
        _save_preview(seo_data, html_body, link="")
        return {"wordpress": "", "wp_post_id": "", "wp_permalink": "",
                "wp_status": "skipped", "published_at": datetime.now().isoformat(),
                "status": "skipped_no_wp"}

    res = _wordpress_api(seo_data, html_body, wp_image_urls, cfg)
    res["status"] = "published"
    return res


def update_post(cfg, wp_post_id, title=None, content=None, excerpt=None) -> dict:
    """POST /wp-json/wp/v2/posts/{wp_post_id} — 기존 글 수정.

    None인 필드는 요청에서 아예 제외(미전송) → 해당 필드 수정 안 함.
    빈 문자열("")로 넘어온 필드는 그대로 전송 → 해당 필드를 비우는 의도로 처리한다.
    즉 None(미전송)과 ""(명시적 삭제/비움)를 구분한다.

    WordPress REST API 직접 호출은 이 함수와 _wordpress_api 에만 존재한다
    (dashboard 등 다른 계층은 publisher.update_post 만 호출).

    성공: {"success": True, "wp_post_id", "link", "modified", "status"}
    실패: {"success": False, "error": "..."}

    TODO(동시 수정 감지): 저장 직전 GET /posts/{id}로 현재 modified를 조회하여,
    편집 시작 시점의 modified와 다르면 "다른 곳에서 이미 수정됨" 경고 후 저장 중단
    (낙관적 잠금). 이번 범위 제외.
    """
    if not is_wordpress_ready(cfg):
        return {"success": False, "error": "WordPress 미구성 — 수정할 수 없습니다."}
    if not str(wp_post_id or "").strip():
        return {"success": False, "error": "wp_post_id가 없어 수정할 수 없습니다."}

    # None은 미전송(수정 안 함), ""는 전송(비움) — 구분해서 payload 구성
    payload = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    if excerpt is not None:
        payload["excerpt"] = excerpt
    if not payload:
        return {"success": False, "error": "수정할 필드가 없습니다(title/content/excerpt 모두 None)."}

    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + f"/wp-json/wp/v2/posts/{wp_post_id}"
    try:
        resp = requests.post(
            url, json=payload,
            auth=_wp_auth(cfg),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "wp_post_id": data.get("id", wp_post_id),
            "link": data.get("link", ""),
            "modified": data.get("modified", ""),
            "status": data.get("status", ""),
        }
    except Exception as e:
        LOG.warning("WordPress 글 수정 실패(post_id=%s): %s", wp_post_id, e)
        return {"success": False, "error": str(e)}


def _wp_error(resp) -> str:
    """WP REST 실패 응답 → 에러코드 문자열(운영 원인 파악용)."""
    code = resp.status_code
    if code == 401:
        return "authentication_failed"
    if code == 403:
        return "permission_denied"
    if code == 404:
        return "not_found"
    try:
        txt = resp.text
    except Exception:
        txt = ""
    return f"HTTP {code}: {txt[:200]}"


def get_post(cfg, wp_post_id) -> dict:
    """GET /wp-json/wp/v2/posts/{id} (context=edit). 삭제/수정 전 재조회용.

    성공: {"success": True, "wp_post_id", "status", "title", "link", "modified"}
    실패: {"success": False, "error", "wp_post_id"}
          (error: authentication_failed / permission_denied / not_found / "HTTP {code}: ...")
    """
    if not is_wordpress_ready(cfg):
        return {"success": False, "error": "WordPress 미구성", "wp_post_id": wp_post_id}
    if not str(wp_post_id or "").strip():
        return {"success": False, "error": "wp_post_id가 없습니다.", "wp_post_id": wp_post_id}
    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + f"/wp-json/wp/v2/posts/{wp_post_id}"
    try:
        resp = requests.get(url, params={"context": "edit"}, auth=_wp_auth(cfg), timeout=30)
        if resp.status_code != 200:
            return {"success": False, "error": _wp_error(resp), "wp_post_id": wp_post_id}
        data = resp.json()
        t = data.get("title", {})
        title = (t.get("raw") or t.get("rendered", "")) if isinstance(t, dict) else str(t)
        return {"success": True, "wp_post_id": data.get("id", wp_post_id),
                "status": data.get("status", ""), "title": title,
                "link": data.get("link", ""), "modified": data.get("modified", "")}
    except Exception as e:
        LOG.warning("WordPress 글 조회 실패(post_id=%s): %s", wp_post_id, e)
        return {"success": False, "error": str(e), "wp_post_id": wp_post_id}


def delete_post(cfg, wp_post_id, force=False) -> dict:
    """DELETE /wp-json/wp/v2/posts/{id}. force=False→휴지통(trash), force=True→영구삭제(deleted).

    성공 판정은 HTTP 코드만으로 하지 않는다: status_code in (200, 410)이어도 응답 JSON이
    기대 상태와 다르면 실패 처리한다.
      - force=False 성공: 응답 status == "trash"
      - force=True  성공: 응답 deleted is True  (WP 표준: {"deleted": true, "previous": {...}} —
        status:"deleted" 필드가 아니라 deleted 플래그로 판정)
    force=True는 함수만 제공하고 대시보드 UI에는 노출하지 않는다(4차 복원 대상 제외).

    성공: {"success": True, "wp_post_id", "wp_status", "force"}
    실패: {"success": False, "error"}
    """
    if not is_wordpress_ready(cfg):
        return {"success": False, "error": "WordPress 미구성 — 삭제할 수 없습니다."}
    if not str(wp_post_id or "").strip():
        return {"success": False, "error": "wp_post_id가 없어 삭제할 수 없습니다."}
    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + f"/wp-json/wp/v2/posts/{wp_post_id}"
    try:
        resp = requests.delete(url, params={"force": "true" if force else "false"},
                               auth=_wp_auth(cfg), timeout=30)
        if resp.status_code not in (200, 410):
            return {"success": False, "error": _wp_error(resp)}
        data = resp.json()
        if force:
            if data.get("deleted") is True:
                return {"success": True, "wp_post_id": wp_post_id, "wp_status": "deleted", "force": True}
            return {"success": False,
                    "error": f"unexpected_status: expected=deleted actual={data.get('deleted')!r}"}
        actual = data.get("status", "")
        if actual == "trash":
            return {"success": True, "wp_post_id": wp_post_id, "wp_status": "trash", "force": False}
        return {"success": False, "error": f"unexpected_status: expected=trash actual={actual!r}"}
    except Exception as e:
        LOG.warning("WordPress 글 삭제 실패(post_id=%s, force=%s): %s", wp_post_id, force, e)
        return {"success": False, "error": str(e)}


def restore_post(cfg, wp_post_id) -> dict:
    """휴지통(trash) 글을 발행(publish)으로 복원. POST /posts/{id} {"status":"publish"}.

    복원 전 get_post 재조회 필수(삭제와 동일 원칙):
      - 재조회 실패(not_found/auth/permission) → 그 에러를 그대로 전달.
      - 이미 publish → {success:True, already_restored:True} (POST 미전송, 멱등).
      - trash가 아닌 상태(draft 등) → cannot_restore_from_status 실패.
    성공 판정은 응답 JSON status=="publish" 확인 후에만(3차 원칙 — HTTP 200만으로 판정 금지).
    반환에는 대시보드 history 기록용 title/link 포함.

    성공: {"success": True, "wp_post_id", "wp_status": "publish", "already_restored": bool,
           "title", "link"}
    실패: {"success": False, "error", "wp_post_id"}
    """
    check = get_post(cfg, wp_post_id)
    if not check.get("success"):
        return check  # not_found/auth/permission 등 그대로 전달
    if check.get("status") == "publish":
        return {"success": True, "wp_post_id": wp_post_id, "wp_status": "publish",
                "already_restored": True, "title": check.get("title", ""), "link": check.get("link", "")}
    if check.get("status") != "trash":
        return {"success": False, "error": f"cannot_restore_from_status:{check.get('status')}",
                "wp_post_id": wp_post_id}

    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + f"/wp-json/wp/v2/posts/{wp_post_id}"
    try:
        resp = requests.post(url, json={"status": "publish"}, auth=_wp_auth(cfg), timeout=30)
        if resp.status_code != 200:
            return {"success": False, "error": _wp_error(resp), "wp_post_id": wp_post_id}
        data = resp.json()
        actual = data.get("status", "")
        if actual == "publish":
            return {"success": True, "wp_post_id": wp_post_id, "wp_status": "publish",
                    "already_restored": False,
                    "title": check.get("title", ""),
                    "link": data.get("link", "") or check.get("link", "")}
        return {"success": False, "error": f"unexpected_status: expected=publish actual={actual!r}",
                "wp_post_id": wp_post_id}
    except Exception as e:
        LOG.warning("WordPress 글 복원 실패(post_id=%s): %s", wp_post_id, e)
        return {"success": False, "error": str(e), "wp_post_id": wp_post_id}


def _wordpress_api(seo, html, wp_imgs, cfg) -> dict:
    url = cfg.get("WORDPRESS_URL", "").rstrip("/") + "/wp-json/wp/v2/posts"
    
    thumb_info = wp_imgs.get("thumbnail_url", {})
    body_img_info = wp_imgs.get("body_image_url", {})
    thumb = thumb_info.get("source_url")
    body_img = body_img_info.get("source_url")
    
    # 이미지 생성 실패("실패"/빈값) 시 해당 <img>는 생략
    head_html = (f"<p style='text-align:center;'><img src='{thumb}' "
                 f"alt='{seo.get('alt_thumbnail','')}'/></p><br/>"
                 if thumb and thumb != "실패" else "")
    
    if body_img and body_img != "실패":
        mid = body_img_info.get("media_id")
        block_json = json.dumps({"id": int(mid) if mid else 0})
        body_img_block = (f'<!-- wp:image {block_json} -->\n'
                          f'<figure class="wp-block-image"><img src="{body_img}" alt="{seo.get("alt_body_image","")}"/></figure>\n'
                          f'<!-- /wp:image -->')
        # "계산 원리" 섹션 직후(다음 <h2> 앞)에 단 1회 주입
        m = re.search(r'(<h2[^>]*>계산\s*원리</h2>.*?)(<h2)', html, re.I | re.S)
        if m:
            insert = m.start(2)
            html = html[:insert] + body_img_block + "\n" + html[insert:]
            tail_html = ""
        else:
            tail_html = body_img_block
    else:
        tail_html = ""

    full_content = f"{head_html}{html}{tail_html}"

    payload = {
        "title": seo.get("seo_title", ""),
        "status": "publish",
        "excerpt": seo.get("meta_description") or seo.get("seo_description", ""),
        "content": full_content,
        "featured_media": thumb_info.get("media_id", 0)
    }
    # STEP125: 호출자가 명시적으로 slug를 전달한 경우에만 payload에 포함한다(하위호환 —
    # 기존 호출자(main.py/retry_queue.py)는 slug를 넘기지 않으므로 payload가 그대로 유지됨).
    if seo.get("slug"):
        payload["slug"] = seo["slug"]
    resp = requests.post(
        url, json=payload,
        auth=_wp_auth(cfg),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    link = data.get("link", "")
    _save_preview(seo, html, link=link)
    return {
        "wordpress": link,
        "wp_post_id": data.get("id", ""),
        "wp_permalink": data.get("link", ""),
        "wp_status": data.get("status", ""),
        "published_at": data.get("date") or datetime.now().isoformat(),
    }


def _save_preview(seo, html, link: str) -> Path:
    """발행 미리보기 텍스트 저장 (발행 성공/미구성 공통)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = _sanitize_filename(seo.get('seo_title', 'post'))[:30]
    preview = OUTPUT_DIR / f"{ts}_{safe_title}_발행미리보기.txt"
    preview.write_text(
        f"제목: {seo.get('seo_title','')}\n"
        f"메타설명: {seo.get('meta_description','')}\n"
        f"태그: {seo.get('tags_list','')}\n"
        f"본문 글자수(공백포함): {len(html)}\n"
        f"발행 URL: {link}\n",
        encoding="utf-8"
    )
    return preview
