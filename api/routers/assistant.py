"""api/routers/assistant.py — AI Assistant(운영비서) 라우터
(CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-ASSISTANT-02).

dashboard.py "🤖 AI Assistant" 탭 이관. 읽기·쓰기 모두 require_admin(파일 내용과 AI 비용을
다루므로 기존 Dashboard 운영 API 정책을 따른다). 보안 경계(경로 검증, 민감 파일 차단,
승인 재검증, 오류 문구 고정)는 api.services.assistant_service가 담당한다.
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.auth.dependencies import require_admin
from api.auth.models import AuditEvent, CurrentUser
from api.auth.service import record_audit_event
from api.dependencies import ok, fail
from api.services import assistant_service as svc

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _audit(user: CurrentUser, action: str, resource_id: str = "", result: str = "success") -> None:
    record_audit_event(AuditEvent(actor_id=user.id, actor_role=user.role.value, action=action,
                                  resource="assistant", resource_id=resource_id, result=result))


def _run(fn, *args):
    try:
        return ok(fn(*args))
    except svc.AssistantPathError as e:
        return fail("PATH_NOT_ALLOWED", str(e))
    except svc.AssistantStateError as e:
        return fail("VALIDATION_ERROR", str(e))


# ── Chat / Models ──────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=svc.MAX_CONTENT_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)


@router.get("/models")
def get_models(user: CurrentUser = Depends(require_admin)):
    return ok(svc.list_models())


@router.post("/chat")
def post_chat(body: ChatRequest, user: CurrentUser = Depends(require_admin)):
    try:
        result = svc.chat(body.model, [m.model_dump() for m in body.messages])
    except svc.AssistantStateError as e:
        return fail("VALIDATION_ERROR", str(e))
    except svc.AssistantAIError as e:
        _audit(user, "assistant_chat", body.model, "failed")
        return fail(e.code, str(e))
    _audit(user, "assistant_chat", body.model)
    return ok(result)


# ── Files ──────────────────────────────────────────────────────────────────
class PathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default=".", max_length=1024)


class ContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=svc.MAX_CONTENT_CHARS)


class WriteRequest(ContentRequest):
    expected_old_sha256: str = Field(min_length=64, max_length=64)


@router.post("/files/list")
def post_files_list(body: PathRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.list_files, body.path)


@router.post("/files/read")
def post_files_read(body: PathRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.read_file, body.path)


@router.post("/files/preview")
def post_files_preview(body: ContentRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.preview_file, body.path, body.content)


@router.post("/files/write")
def post_files_write(body: WriteRequest, user: CurrentUser = Depends(require_admin)):
    res = _run(svc.write_file, body.path, body.content, body.expected_old_sha256)
    _audit(user, "assistant_file_write", body.path, "success" if res.get("success") else "blocked")
    return res


@router.post("/files/create")
def post_files_create(body: ContentRequest, user: CurrentUser = Depends(require_admin)):
    res = _run(svc.create_file, body.path, body.content)
    _audit(user, "assistant_file_create", body.path, "success" if res.get("success") else "blocked")
    return res


# ── Memory / Tasks ─────────────────────────────────────────────────────────
class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rules", "todo", "dev_log"]
    text: str = Field(min_length=1, max_length=5000)


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1)


@router.get("/memory")
def get_memory(user: CurrentUser = Depends(require_admin)):
    return ok(svc.get_memory())


@router.post("/memory")
def post_memory(body: MemoryRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.add_memory, body.kind, body.text)


@router.get("/tasks")
def get_tasks(user: CurrentUser = Depends(require_admin)):
    return ok(svc.get_tasks())


@router.post("/tasks")
def post_task(body: TaskRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.add_task, body.title)


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskStatusRequest, user: CurrentUser = Depends(require_admin)):
    return _run(svc.set_task_status, task_id, body.status)
