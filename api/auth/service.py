"""api/auth/service.py — 토큰 검증 + audit 이벤트 기록(인메모리) + 향후 write
endpoint 권한 정책 (STEP 18-Q).

토큰 값을 코드에 하드코딩하지 않는다. 환경변수로만 주입한다:
  CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER
  CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN

두 환경변수가 모두 비어 있으면(로컬 개발 기본 상태) 어떤 토큰도 유효하지
않다 — 즉 기본값은 "인증 불가능"이며 안전한 쪽으로 fail한다.

Audit 이벤트는 파일/DB에 저장하지 않는다(§10). 이번 STEP은 추상화 + 테스트
목적의 인메모리 리스트만 제공하며, pipeline.log 등 보호 파일에는 절대 쓰지
않는다.
"""
import os
from threading import Lock

from api.auth.models import AuditEvent, CurrentUser, Role

_VIEWER_TOKEN_ENV = "CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER"
_ADMIN_TOKEN_ENV = "CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN"


def _resolve_role_for_token(token: str) -> Role | None:
    """토큰 문자열 → Role. 어느 환경변수와도 일치하지 않으면 None(무효 토큰).
    빈 문자열 토큰은 항상 무효(빈 환경변수와 우연히 일치해 인증되는 사고 방지)."""
    if not token:
        return None
    admin_token = os.environ.get(_ADMIN_TOKEN_ENV, "")
    viewer_token = os.environ.get(_VIEWER_TOKEN_ENV, "")
    if admin_token and token == admin_token:
        return Role.ADMIN
    if viewer_token and token == viewer_token:
        return Role.VIEWER
    return None


def authenticate_token(token: str | None) -> CurrentUser:
    """Authorization 헤더에서 추출한 토큰 문자열을 검증해 CurrentUser를 만든다.
    토큰이 없거나 무효하면 익명(authenticated=False)을 반환한다 — 예외를
    던지지 않는다(401/403 판단은 dependencies.py의 몫)."""
    if not token:
        return CurrentUser.anonymous()
    role = _resolve_role_for_token(token)
    if role is None:
        return CurrentUser.anonymous()
    # 사용자 id로 토큰 원문을 쓰지 않는다 — role 기반의 고정 식별자만 사용(§11 토큰 유출 방지).
    actor_id = f"dev-{role.value}"
    return CurrentUser(id=actor_id, role=role, authenticated=True)


# ── Audit(인메모리, 파일/DB 미저장) ──────────────────────────────────────
_audit_lock = Lock()
_audit_events: list[AuditEvent] = []


def record_audit_event(event: AuditEvent) -> None:
    with _audit_lock:
        _audit_events.append(event)


def get_audit_events() -> list[AuditEvent]:
    """테스트/디버깅 전용 조회. 실제 API endpoint로 노출하지 않는다."""
    with _audit_lock:
        return list(_audit_events)


def clear_audit_events() -> None:
    """테스트 격리 전용."""
    with _audit_lock:
        _audit_events.clear()


# ── 향후 Publish/Trash write endpoint 권한 정책(문서화 목적 — 실제 라우트는
#    이번 STEP에서 만들지 않는다. §9) ──────────────────────────────────────
PLANNED_WRITE_ENDPOINT_POLICY = {
    "POST /api/publish/{id}/edit": Role.ADMIN,
    "POST /api/trash/{id}": Role.ADMIN,
    "POST /api/trash/{id}/restore": Role.ADMIN,
}
