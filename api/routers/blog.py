"""api/routers/blog.py — 실제 운영 Blog(calcmate.kr) 조회 라우터 (STEP 18-X).

조회 전용(GET만). "articles" DB 기반 Publish/Trash(api/routers/publish.py)와는
완전히 별개의 데이터 소스(_site/blog/*)를 읽는다 — 이 라우터는 articles DB를
전혀 참조하지 않는다.
"""
from fastapi import APIRouter

from api.dependencies import ok
from api.services import blog_service

router = APIRouter(prefix="/api/blog", tags=["blog"])


@router.get("")
def get_blog_posts():
    return ok(blog_service.list_blog_posts())
