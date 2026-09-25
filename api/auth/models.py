"""api/auth/models.py — CurrentUser / Role / AuditEvent 데이터 구조 (STEP 18-Q).

전부 순수 데이터 클래스다. DB/파일에 저장하지 않는다(§10 — audit 저장소는
이번 STEP에서 실제로 만들지 않고 추상화만 제공한다).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    ADMIN = "admin"


@dataclass(frozen=True)
class CurrentUser:
    """요청을 보낸 주체. authenticated=False면 id/role은 의미가 없다(익명)."""
    id: str
    role: Role | None
    authenticated: bool

    @staticmethod
    def anonymous() -> "CurrentUser":
        return CurrentUser(id="anonymous", role=None, authenticated=False)


@dataclass(frozen=True)
class AuditEvent:
    """향후 Publish/Trash 등 관리 작업 추적을 위한 최소 이벤트 구조.

    중요: 토큰 원문(raw token)은 어떤 필드에도 담지 않는다(§11 token leakage 금지).
    이번 STEP에서는 실제 작업을 기록하지 않는다 — 구조 + 테스트만 제공한다.
    """
    actor_id: str
    actor_role: str
    action: str
    resource: str
    resource_id: str
    result: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
