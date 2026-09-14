"""
modules/wp_readonly_client.py — WordPress Production READ-ONLY GET 전용 클라이언트

이 모듈은 GET만 수행한다. POST/PUT/PATCH/DELETE는 절대 구현하지 않는다.

기존 modules/publisher.py:get_post()는 cfg["WORDPRESS_URL"](flat)을 사용하는데,
이 값은 obsolete 로컬 테스트 URL(http://salarymate.test)을 가리키므로
Production(blog.genon.app) 조회에는 사용할 수 없다(CALCMATE-WP-ARTICLE-* 시리즈에서
실측 확인된 사실). 그렇다고 flat WORDPRESS_URL 자체를 바꾸면 modules/publisher.py의
POST/PUT/DELETE 함수 전체와 is_wordpress_ready()에 연쇄 영향을 준다.

따라서 이 모듈은 Production URL을 인자로 명시적으로 받는 독립 경로로 존재하며,
기존 publisher.py/config_loader.py는 전혀 수정하지 않는다.
"""
import base64
import urllib.request
import urllib.error
import urllib.parse
import json

WP_PRODUCTION_URL = "https://blog.genon.app"


def get_wp_post_readonly(post_id, wp_url: str = WP_PRODUCTION_URL,
                          username: str = "", app_password: str = "",
                          timeout: int = 20) -> dict:
    """GET /wp-json/wp/v2/posts/{id}?context=edit. GET 이외의 HTTP method는 사용하지 않는다.

    반환(성공): {"success": True, "http_status": 200, "id", "slug", "status",
                 "date", "modified", "link", "title", "content", "excerpt"}
    반환(실패): {"success": False, "http_status": <code|None>, "error": <str>, "wp_post_id": post_id}
    """
    url = wp_url.rstrip("/") + f"/wp-json/wp/v2/posts/{post_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    if username and app_password:
        token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "http_status": resp.status,
                "id": data.get("id"),
                "slug": data.get("slug", ""),
                "status": data.get("status", ""),
                "date": data.get("date", ""),
                "modified": data.get("modified", ""),
                "link": data.get("link", ""),
                "title": (data.get("title") or {}).get("rendered", ""),
                "content": (data.get("content") or {}).get("rendered", ""),
                "excerpt": (data.get("excerpt") or {}).get("rendered", ""),
            }
    except urllib.error.HTTPError as e:
        return {"success": False, "http_status": e.code, "error": str(e), "wp_post_id": post_id}
    except Exception as e:
        return {"success": False, "http_status": None, "error": str(e), "wp_post_id": post_id}


def list_wp_posts_readonly(wp_url: str = WP_PRODUCTION_URL, username: str = "",
                            app_password: str = "", status: str = "publish",
                            per_page: int = 20, timeout: int = 20) -> dict:
    """GET /wp-json/wp/v2/posts?status=&per_page=&page=&context=edit 전체 페이지 순회.
    GET 이외의 HTTP method는 사용하지 않는다(단건 조회 함수와 동일한 원칙).

    X-WP-TotalPages 응답 헤더 기준으로 마지막 페이지까지 순회한다(get_wp_post_readonly와
    동일한 인증/timeout/에러 처리 패턴을 재사용, 별도 라이브러리 의존성 추가 없음).

    반환(성공): {"success": True, "posts": [{"id","slug","status","title","excerpt",
                 "link","date","date_gmt","modified","modified_gmt"}, ...]}
    반환(실패): {"success": False, "http_status": <code|None>, "error": <str>}
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    if username and app_password:
        token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    posts: list[dict] = []
    page = 1
    while True:
        qs = urllib.parse.urlencode({
            "status": status, "per_page": per_page, "page": page, "context": "edit",
        })
        url = wp_url.rstrip("/") + "/wp-json/wp/v2/posts?" + qs
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                total_pages_hdr = resp.headers.get("X-WP-TotalPages", "1")
        except urllib.error.HTTPError as e:
            if e.code == 400 and page > 1:
                break  # 마지막 페이지 다음 요청은 WP가 400을 반환 — 정상 종료 신호
            return {"success": False, "http_status": e.code, "error": str(e)}
        except Exception as e:
            return {"success": False, "http_status": None, "error": str(e)}

        try:
            data = json.loads(body)
        except Exception as e:
            return {"success": False, "http_status": None, "error": f"invalid_json: {e}"}
        if not isinstance(data, list):
            return {"success": False, "http_status": None, "error": "invalid_json_shape"}
        if not data:
            break

        for p in data:
            try:
                posts.append({
                    "id": p["id"],
                    "slug": p.get("slug", ""),
                    "status": p.get("status", ""),
                    "title": (p.get("title") or {}).get("rendered", ""),
                    "excerpt": (p.get("excerpt") or {}).get("rendered", ""),
                    "link": p.get("link", ""),
                    "date": p.get("date", ""),
                    "date_gmt": p.get("date_gmt", ""),
                    "modified": p.get("modified", ""),
                    "modified_gmt": p.get("modified_gmt", ""),
                })
            except KeyError as e:
                return {"success": False, "http_status": None, "error": f"required_field_missing: {e}"}

        try:
            total_pages = int(total_pages_hdr or 1)
        except Exception:
            total_pages = 1
        if page >= total_pages:
            break
        page += 1

    return {"success": True, "posts": posts}
