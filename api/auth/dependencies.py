"""api/auth/dependencies.py — FastAPI Depends 체인 (STEP 18-Q).

get_current_user()      → 인증 실패해도 예외를 던지지 않고 익명 CurrentUser 반환.
require_authenticated() → 인증 안 됨(401 Unauthorized).
require_admin()         → 인증은 됐지만 admin이 아님(403 Forbidden).

이 파일은 토큰 값이나 Authorization 헤더 원문을 절대 로그로 남기지 않는다
(§11 token leakage 금지 — logging/print 호출이 이 파일에 존재하지 않는다).

이번 STEP에서는 어떤 기존 GET route에도 이 dependency들을 연결하지 않는다(§7).
새로 추가하는 것은 /api/auth/me, /api/auth/admin-check 2개 GET 진단 endpoint뿐이며,
기존 write endpoint(PATCH /api/scheduler/blog/config, POST .../run-once)에도
이번 STEP에서는 연결하지 않는다(§8 — feasibility 검토만, 실제 연결은 후속 STEP).

── STEP V1-OPS-03: 로컬 전용 무인증 모드 ──────────────────────────────────
CALCMATE_DASHBOARD_LOCAL_MODE 환경변수가 명시적으로 truthy일 때만
get_current_user()가 토큰 검사를 건너뛰고 고정 admin CurrentUser를 반환한다.
기본값(환경변수 미설정)은 기존 동작 100% 그대로다 — require_authenticated()/
require_admin()/authenticate_token()/CurrentUser/Role 등 기존 인증 구조는
한 줄도 바꾸지 않았다. 외부/운영 배포 환경에서 이 환경변수를 설정하지 않으면
기존 보호가 그대로 유지된다. 나중에 인증을 다시 강제하려면 이 환경변수를
제거하기만 하면 된다(코드 변경 불필요).
"""
import os

from fastapi import Depends, HTTPException, Request

from api.auth.models import CurrentUser, Role
from api.auth.service import authenticate_token

_LOCAL_MODE_ENV = "CALCMATE_DASHBOARD_LOCAL_MODE"


def _is_local_mode() -> bool:
    return os.environ.get(_LOCAL_MODE_ENV, "").strip().lower() in ("1", "true", "yes")


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def get_current_user(request: Request) -> CurrentUser:
    """예외를 던지지 않는다 — 인증 실패는 익명 사용자로 표현한다.
    이 함수 자체를 GET 조회 라우트에 붙여도 기존 동작을 깨지 않는다(선택적 사용).

    CALCMATE_DASHBOARD_LOCAL_MODE가 설정된 경우에만 토큰 검사를 건너뛴다."""
    if _is_local_mode():
        return CurrentUser(id="local-admin", role=Role.ADMIN, authenticated=True)
    token = _extract_bearer_token(request)
    return authenticate_token(token)


def require_authenticated(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_admin(user: CurrentUser = Depends(require_authenticated)) -> CurrentUser:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user
