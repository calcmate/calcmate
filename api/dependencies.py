"""api/dependencies.py — 표준 Response 구조 헬퍼.

이번 STEP(18-C)에서는 인증/권한 시스템을 구현하지 않는다.
"""
import uuid
from typing import Any


def new_request_id() -> str:
    return str(uuid.uuid4())


def ok(data: Any = None) -> dict:
    """성공 응답 봉투. data가 없으면 빈 dict를 반환한다."""
    return {
        "success": True,
        "data": data if data is not None else {},
        "error": None,
        "request_id": new_request_id(),
    }


def fail(code: str, message: str) -> dict:
    """실패 응답 봉투."""
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
        "request_id": new_request_id(),
    }
