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
