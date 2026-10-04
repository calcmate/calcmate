"""api/routers/workspace.py — AI Workspace 라우터
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-WORKSPACE-02).

dashboard.py "💬 AI Workspace" 탭 이관. /api/assistant/*(AI Assistant)와 별도 namespace.
전부 require_admin. 보안 경계는 api.services.workspace_service가 담당한다.
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import AuditEvent, CurrentUser
from api.auth.service import record_audit_event
from api.dependencies import ok, fail
from api.services import workspace_service as svc

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _audit(user: CurrentUser, action: str, resource_id: str, result: str) -> None:
    record_audit_event(AuditEvent(actor_id=user.id, actor_role=user.role.value, action=action,
                                  resource="workspace", resource_id=resource_id, result=result))


def _run(fn, *args):
    try:
        return ok(fn(*args))
    except svc.WorkspaceError as e:
        return fail(e.code, str(e))


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=svc.MAX_CONTENT_CHARS)


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str | None = Field(default=None, max_length=1024)
    repo: Literal["sites", "calculators", "articles", "templates"] | None = None
    structure: bool = False


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    context: ContextSelection = Field(default_factory=ContextSelection)


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=svc.MAX_CONTENT_CHARS)
    overwrite: bool = False


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=svc.MAX_CONTENT_CHARS)


class WriteRequest(ContentRequest):
    expected_old_sha256: str = Field(min_length=64, max_length=64)


@router.get("/models")
def get_models(user: CurrentUser = Depends(require_admin)):
    return ok(svc.list_roles())


@router.get("/context/files")
def get_context_files(user: CurrentUser = Depends(require_admin)):
    return ok(svc.list_context_files())


@router.post("/chat")
def post_chat(body: ChatRequest, user: CurrentUser = Depends(require_admin)):
    c = body.context
    res = _run(svc.chat, body.role, [m.model_dump() for m in body.messages], c.file, c.repo, c.structure)
    _audit(user, "workspace_chat", body.role, "success" if res.get("success") else "failed")
    return res


@router.post("/files/sandbox")
def post_sandbox(body: SandboxRequest, user: CurrentUser = Depends(require_admin)):
    res = _run(svc.save_sandbox, body.name, body.content, body.overwrite)
    _audit(user, "workspace_sandbox_save", body.name, "success" if res.get("success") else "blocked")
    return res


@router.post("/files/preview")
def post_preview(body: ContentRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.preview_project_file, body.path, body.content)


@router.post("/files/write")
def post_write(body: WriteRequest, user: CurrentUser = Depends(require_admin)):
    res = _run(svc.write_project_file, body.path, body.content, body.expected_old_sha256)
    _audit(user, "workspace_file_write", body.path, "success" if res.get("success") else "blocked")
    return res


@router.post("/files/create")
def post_create(body: ContentRequest, user: CurrentUser = Depends(require_admin)):
    res = _run(svc.create_project_file, body.path, body.content)
    _audit(user, "workspace_file_create", body.path, "success" if res.get("success") else "blocked")
    return res
