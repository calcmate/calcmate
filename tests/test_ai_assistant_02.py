# -*- coding: utf-8 -*-
"""tests/test_ai_assistant_02.py — CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-ASSISTANT-02.

dashboard.py "🤖 AI Assistant" 이관(Chat/Models/Files/Memory/Tasks)과 HTTP 보안 경계 검증.

격리: modules.ai_assistant.ROOT/_ASSIST_DIR를 tmp 루트로 바꿔 운영 저장소·운영
data/assistant(memory/tasks/backups)를 건드리지 않는다. AI provider(build_provider)와
BudgetTracker는 mock — 실제 OpenAI/Claude/Gemini/OpenRouter 호출 0.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER = "aa02-viewer-token"
ADMIN = "aa02-admin-token"
SECRET = "sk-live-SECRETKEYVALUE0123456789"
CONFIG_MARKER = "INTERNAL_CONFIG_MARKER_DO_NOT_SEND"


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture(autouse=True)
def ws(monkeypatch, tmp_path):
    """tmp 워크스페이스 + mock provider/budget. 운영 경로/외부 AI 차단."""
    # 아래에서 modules.logger.BudgetTracker를 가짜로 바꾸기 전에 api.main(→ cost_service)을 먼저
    # import한다. 패치 중에 처음 import되면 cost_service의 module-level
    # `from modules.logger import BudgetTracker`가 가짜를 붙잡아, 뒤에 도는 test_cost_monitor가 실패한다.
    import api.main  # noqa: F401
    from modules import ai_assistant as AS
    import modules.logger as L
    from api.services import assistant_service as S
    root = tmp_path / "root"
    files = {
        "modules/app_factory.py": "# app factory code\nprint('af')\n",
        "modules/calculator_reviewer.py": "# reviewer\n",
        "config/config.yaml": f"SITE_URL: https://calcmate.kr\nINTERNAL: {CONFIG_MARKER}\n",
        "config/secrets.yaml": f"OPENAI_API_KEY: {SECRET}\n",
        ".env": f"OPENAI_API_KEY={SECRET}\n",
        ".env.local": "X=1\n",
        "deploy/prod.env": "X=1\n",
        "credentials.json": "{\"private_key\": \"x\"}\n",
        "data/api_token.txt": "tok\n",
        "notes/my_secret_plan.md": "s\n",
        ".git/config": "[remote]\n",
        "data/assistant/backups/old.txt.bak": "bak\n",
        "data/assistant/memory.json": "{\"rules\": [], \"todo\": [], \"dev_log\": []}",
        "data/assistant/tasks.json": "[]",
        "data/logs/pipeline.log": f"[INFO] ok\n[ERROR] provider failed key={SECRET}\n[ERROR] Bearer abcdefghijklmnop\n",
        "data/workspace/example.txt": "hello\n",
        "docs/readme.md": "readme\n",
        "templates/calculators/calculator_v1.html": "<html></html>\n",
    }
    for rel, c in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8")
    monkeypatch.setattr(AS, "ROOT", root.resolve())
    monkeypatch.setattr(AS, "_ASSIST_DIR", root.resolve() / "data" / "assistant")

    state = {"calls": [], "budget": [], "reply": ("분석 결과입니다.", 42), "raise": None}

    class _FakeProvider:
        def chat(self, system, user, model, max_tokens=4000, json_mode=False):
            state["calls"].append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
            if state["raise"]:
                raise state["raise"]
            return state["reply"]

    def _build(provider_name, cfg):
        state.setdefault("providers", []).append(provider_name)
        if state.get("build_raise"):
            raise state["build_raise"]
        return _FakeProvider()

    class _Budget:
        def __init__(self, cfg):
            pass

        def record(self, model, tokens=0, **kw):
            state["budget"].append((model, tokens))

    monkeypatch.setattr(AS, "build_provider", _build)
    monkeypatch.setattr(L, "BudgetTracker", _Budget)
    monkeypatch.setattr(S, "load_config", lambda *a, **k: {"OPENAI_API_KEY": SECRET, "SITE_URL": "https://calcmate.kr",
                                                           "SITE_NAME": "CalcMate", "ADSENSE_MODE": "pre"})
    state["root"] = root.resolve()
    return state


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(t=ADMIN):
    return {"Authorization": f"Bearer {t}"}


def _post(path, body=None, token=ADMIN):
    return _client().post(path, headers=_h(token), json=body if body is not None else {})


GPT = "GPT (CEO/전략)"

ROUTES = [
    ("get", "/api/assistant/models", None), ("post", "/api/assistant/chat", {"model": GPT, "messages": [{"role": "user", "content": "x"}]}),
    ("post", "/api/assistant/files/list", {"path": "."}), ("post", "/api/assistant/files/read", {"path": "docs/readme.md"}),
    ("post", "/api/assistant/files/preview", {"path": "docs/readme.md", "content": "x"}),
    ("post", "/api/assistant/files/write", {"path": "docs/readme.md", "content": "x", "expected_old_sha256": "0" * 64}),
    ("post", "/api/assistant/files/create", {"path": "docs/new.md", "content": "x"}),
    ("get", "/api/assistant/memory", None), ("post", "/api/assistant/memory", {"kind": "rules", "text": "x"}),
    ("get", "/api/assistant/tasks", None), ("post", "/api/assistant/tasks", {"title": "x"}),
    ("patch", "/api/assistant/tasks/1", {"status": "Running"}),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_unauthenticated_401(method, path, body):
    r = getattr(_client(), method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_viewer_403_and_no_side_effect(method, path, body, ws):
    r = getattr(_client(), method)(path, headers=_h(VIEWER), **({"json": body} if body is not None else {}))
    assert r.status_code == 403
    assert ws["calls"] == [] and not (ws["root"] / "docs/new.md").exists()


# ── Models / Chat ──────────────────────────────────────────────────────────

def test_models_whitelist_and_quick_questions():
    d = _client().get("/api/assistant/models", headers=_h()).json()["data"]
    assert [m["label"] for m in d["models"]] == ["GPT (CEO/전략)", "Claude (편집장/코드)", "Gemini (실무팀/분석)"]
    assert d["default"] == GPT
    assert d["quick_questions"] == ["현재 프로젝트 분석해", "App Factory 분석해", "문제점 찾아", "개선안 제안해"]


def test_chat_success_uses_existing_mapping_and_records_budget(ws):
    r = _post("/api/assistant/chat", {"model": "Claude (편집장/코드)", "messages": [{"role": "user", "content": "문제점 찾아"}]})
    d = r.json()["data"]
    assert d == {"reply": "분석 결과입니다.", "model": "claude-sonnet-4-6", "tokens": 42}
    assert ws["providers"] == ["claude"] and ws["calls"][0]["model"] == "claude-sonnet-4-6"
    assert ws["calls"][0]["max_tokens"] == 2500 and "운영비서" in ws["calls"][0]["system"]
    assert ws["budget"] == [("claude-sonnet-4-6", 42)]


def test_chat_unknown_model_rejected_without_ai_call(ws):
    r = _post("/api/assistant/chat", {"model": "evil-model", "messages": [{"role": "user", "content": "x"}]})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR" and ws["calls"] == []


def test_chat_client_cannot_pass_provider_or_endpoint(ws):
    r = _post("/api/assistant/chat", {"model": GPT, "provider": "openrouter", "api_base": "http://evil",
                                      "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 422 and ws["calls"] == []


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": "   "}],
    [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
    [],
])
def test_chat_empty_or_invalid_messages(ws, messages):
    r = _post("/api/assistant/chat", {"model": GPT, "messages": messages})
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert ws["calls"] == []


def test_chat_only_recent_10_messages_sent(ws):
    msgs = []
    for i in range(15):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i:02d}"})
    msgs.append({"role": "user", "content": "msg-final"})
    _post("/api/assistant/chat", {"model": GPT, "messages": msgs})
    convo = ws["calls"][0]["user"]
    assert "msg-final" in convo and "msg-06" in convo and "msg-05" not in convo and "msg-00" not in convo


def test_chat_context_is_safe(ws):
    """config 언급 시에도 config.yaml 전체/secrets는 보내지 않고 공개 allowlist만, 로그 비밀값은 마스킹."""
    _post("/api/assistant/chat", {"model": GPT, "messages": [{"role": "user", "content": "config 확인하고 app factory 분석해"}]})
    convo = ws["calls"][0]["user"]
    assert "[프로젝트 구조]" in convo and "[최근 오류]" in convo
    assert "[참고 파일 modules/app_factory.py]" in convo
    assert "SITE_URL: https://calcmate.kr" in convo and "ADSENSE_MODE: pre" in convo
    assert CONFIG_MARKER not in convo and SECRET not in convo and "abcdefghijklmnop" not in convo
    assert "[REDACTED]" in convo


def test_chat_provider_error_is_sanitized_and_not_logged(ws, caplog):
    ws["raise"] = RuntimeError(f"401 Unauthorized key={SECRET} at C:\\Users\\x\\secrets.yaml")
    with caplog.at_level(logging.DEBUG):
        r = _post("/api/assistant/chat", {"model": GPT, "messages": [{"role": "user", "content": "x"}]})
    e = r.json()["error"]
    assert e["code"] == "AI_REQUEST_FAILED" and e["message"] == "AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요."
    assert SECRET not in r.text and "secrets.yaml" not in r.text and "Traceback" not in r.text
    assert SECRET not in caplog.text
    assert ws["budget"] == []


def test_chat_missing_api_key_is_fixed_message(ws):
    ws["build_raise"] = KeyError("OPENAI_API_KEY")
    r = _post("/api/assistant/chat", {"model": GPT, "messages": [{"role": "user", "content": "x"}]})
    assert r.json()["error"]["code"] == "AI_NOT_CONFIGURED" and "OPENAI_API_KEY" not in r.text


# ── 경로 보안 ──────────────────────────────────────────────────────────────

BLOCKED = [
    "../secrets.yaml", "..\\secrets.yaml", "modules/../config/secrets.yaml", "..", "../../etc/passwd",
    "C:\\Windows\\win.ini", "c:/windows/win.ini", "/etc/passwd", "\\etc\\passwd",
    "\\\\server\\share\\x.txt", "//server/share/x.txt", "docs/readme.md:stream",
    ".git/config", ".GIT/config", ".env", ".env.local", "deploy/prod.env",
    "config/secrets.yaml", "CONFIG/SECRETS.YAML", "credentials.json", "data/api_token.txt",
    "notes/my_secret_plan.md", "data/assistant/backups/old.txt.bak", "data/assistant/backups",
    " docs/readme.md", "",
]


@pytest.mark.parametrize("path", BLOCKED)
def test_read_blocked(path):
    r = _post("/api/assistant/files/read", {"path": path})
    assert r.json()["success"] is False and r.json()["error"]["code"] == "PATH_NOT_ALLOWED"
    assert SECRET not in r.text


@pytest.mark.parametrize("path", BLOCKED)
def test_write_preview_create_blocked(path, ws):
    for ep, body in (("preview", {"path": path, "content": "x"}), ("create", {"path": path, "content": "x"}),
                     ("write", {"path": path, "content": "x", "expected_old_sha256": "0" * 64})):
        r = _post(f"/api/assistant/files/{ep}", body)
        if r.status_code == 422:   # 빈 경로 등은 스키마에서 거부
            continue
        assert r.json()["error"]["code"] == "PATH_NOT_ALLOWED", (ep, path)
    assert (ws["root"] / "config/secrets.yaml").read_text(encoding="utf-8") == f"OPENAI_API_KEY: {SECRET}\n"
    assert (ws["root"] / ".env").read_text(encoding="utf-8").startswith("OPENAI_API_KEY=")


@pytest.mark.parametrize("path", [".git", "config/../.git", "data/assistant/backups", "../"])
def test_list_blocked(path):
    assert _post("/api/assistant/files/list", {"path": path}).json()["error"]["code"] == "PATH_NOT_ALLOWED"


def _make_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(str(target), str(link), target_is_directory=target.is_dir())
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and target.is_dir():
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return r.returncode == 0 and link.exists()
    return False


def test_symlink_or_junction_escape_blocked(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text(SECRET, encoding="utf-8")
    if not _make_link(ws["root"] / "docs" / "escape", outside):
        pytest.skip("symlink/junction 생성 불가 환경")
    for ep, body in (("read", {"path": "docs/escape/leak.txt"}), ("list", {"path": "docs/escape"}),
                     ("create", {"path": "docs/escape/new.txt", "content": "x"})):
        r = _post(f"/api/assistant/files/{ep}", body)
        assert r.json()["error"]["code"] == "PATH_NOT_ALLOWED", ep
        assert SECRET not in r.text
    assert not (outside / "new.txt").exists()


def test_symlink_inside_root_to_secret_blocked(ws):
    if not _make_link(ws["root"] / "docs" / "cfg", ws["root"] / "config"):
        pytest.skip("symlink/junction 생성 불가 환경")
    r = _post("/api/assistant/files/read", {"path": "docs/cfg/secrets.yaml"})
    assert r.json()["error"]["code"] == "PATH_NOT_ALLOWED" and SECRET not in r.text


def test_list_root_hides_sensitive_entries():
    d = _post("/api/assistant/files/list", {"path": "."}).json()["data"]
    names = {i["name"] for i in d["items"]}
    assert {"modules", "docs", "data", "config"} <= names
    assert not names & {".git", ".env", ".env.local", "credentials.json"}
    cfg = _post("/api/assistant/files/list", {"path": "config"}).json()["data"]
    assert [i["name"] for i in cfg["items"]] == ["config.yaml"]
    assist = _post("/api/assistant/files/list", {"path": "data/assistant"}).json()["data"]
    assert "backups" not in {i["name"] for i in assist["items"]}


# ── Files ──────────────────────────────────────────────────────────────────

def test_read_safe_file_with_limit():
    d = _post("/api/assistant/files/read", {"path": "modules/app_factory.py"}).json()["data"]
    assert d["path"] == "modules/app_factory.py" and "app factory code" in d["content"]


def test_preview_existing_and_new(ws):
    d = _post("/api/assistant/files/preview", {"path": "data/workspace/example.txt", "content": "new!"}).json()["data"]
    assert d["exists"] is True and d["old"] == "hello\n" and d["old_len"] == 6 and d["new_len"] == 4 and len(d["old_sha256"]) == 64
    n = _post("/api/assistant/files/preview", {"path": "data/workspace/brand_new.txt", "content": "abc"}).json()["data"]
    assert n["exists"] is False and n["old_sha256"] is None
    assert not (ws["root"] / "data/workspace/brand_new.txt").exists()


def test_write_existing_with_server_revalidation_and_backup(ws):
    pv = _post("/api/assistant/files/preview", {"path": "data/workspace/example.txt", "content": "updated"}).json()["data"]
    r = _post("/api/assistant/files/write", {"path": "data/workspace/example.txt", "content": "updated",
                                            "expected_old_sha256": pv["old_sha256"]}).json()
    assert r["success"] is True and r["data"]["backed_up"] is True
    assert (ws["root"] / "data/workspace/example.txt").read_text(encoding="utf-8") == "updated"
    baks = list((ws["root"] / "data/assistant/backups").glob("example.txt.*.bak"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == "hello\n"
    assert str(ws["root"]) not in str(r)


def test_write_rejected_when_file_changed_after_preview(ws):
    pv = _post("/api/assistant/files/preview", {"path": "data/workspace/example.txt", "content": "A"}).json()["data"]
    (ws["root"] / "data/workspace/example.txt").write_text("changed by someone", encoding="utf-8")
    r = _post("/api/assistant/files/write", {"path": "data/workspace/example.txt", "content": "A",
                                            "expected_old_sha256": pv["old_sha256"]})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (ws["root"] / "data/workspace/example.txt").read_text(encoding="utf-8") == "changed by someone"


def test_write_nonexistent_rejected():
    r = _post("/api/assistant/files/write", {"path": "data/workspace/none.txt", "content": "x", "expected_old_sha256": "a" * 64})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_new_and_reject_existing(ws):
    r = _post("/api/assistant/files/create", {"path": "data/workspace/sub/new.txt", "content": "made"}).json()
    assert r["success"] is True and (ws["root"] / "data/workspace/sub/new.txt").read_text(encoding="utf-8") == "made"
    r2 = _post("/api/assistant/files/create", {"path": "data/workspace/example.txt", "content": "x"})
    assert r2.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (ws["root"] / "data/workspace/example.txt").read_text(encoding="utf-8") == "hello\n"


def test_client_cannot_specify_backup_path(ws):
    r = _post("/api/assistant/files/write", {"path": "data/workspace/example.txt", "content": "x",
                                            "expected_old_sha256": "a" * 64, "backup_path": "docs/steal.bak"})
    assert r.status_code == 422
    r2 = _post("/api/assistant/files/create", {"path": "data/assistant/backups/injected.bak", "content": "x"})
    assert r2.json()["error"]["code"] == "PATH_NOT_ALLOWED"
    assert not (ws["root"] / "data/assistant/backups/injected.bak").exists()


# ── Memory ─────────────────────────────────────────────────────────────────

def test_memory_read_and_add_each_kind(ws):
    assert _client().get("/api/assistant/memory", headers=_h()).json()["data"] == {"rules": [], "todo": [], "dev_log": []}
    for kind in ("rules", "todo", "dev_log"):
        d = _post("/api/assistant/memory", {"kind": kind, "text": f"{kind} item"}).json()["data"]
        assert d[kind][-1]["text"] == f"{kind} item"
    assert "rules item" in (ws["root"] / "data/assistant/memory.json").read_text(encoding="utf-8")


def test_memory_path_cannot_be_overridden_and_invalid_kind(ws):
    assert _post("/api/assistant/memory", {"kind": "rules", "text": "x", "path": "docs/m.json"}).status_code == 422
    assert _post("/api/assistant/memory", {"kind": "secrets", "text": "x"}).status_code == 422
    assert not (ws["root"] / "docs/m.json").exists()


# ── Tasks ──────────────────────────────────────────────────────────────────

def test_task_create_list_and_status_change(ws):
    t = _post("/api/assistant/tasks", {"title": "점검하기"}).json()["data"]
    tid = t["task"]["id"]
    assert t["task"]["status"] == "Pending" and t["statuses"] == ["Pending", "Running", "Completed", "Failed"]
    lst = _client().get("/api/assistant/tasks", headers=_h()).json()["data"]["tasks"]
    assert lst[-1]["title"] == "점검하기"
    d = _client().patch(f"/api/assistant/tasks/{tid}", headers=_h(), json={"status": "Completed"}).json()["data"]
    assert d["tasks"][-1]["status"] == "Completed"


def test_task_invalid_status_and_unknown_id(ws):
    tid = _post("/api/assistant/tasks", {"title": "x"}).json()["data"]["task"]["id"]
    r = _client().patch(f"/api/assistant/tasks/{tid}", headers=_h(), json={"status": "Deleted"})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r2 = _client().patch("/api/assistant/tasks/nope", headers=_h(), json={"status": "Running"})
    assert r2.json()["error"]["code"] == "VALIDATION_ERROR"


def test_task_path_cannot_be_overridden(ws):
    assert _post("/api/assistant/tasks", {"title": "x", "path": "docs/t.json"}).status_code == 422
    assert not (ws["root"] / "docs/t.json").exists()


def test_dashboard_default_chat_behavior_unchanged(monkeypatch):
    """modules.ai_assistant.chat()의 기존 호출(context 미지정)은 _context_for()를 그대로 쓴다."""
    from modules import ai_assistant as AS
    seen = {}
    monkeypatch.setattr(AS, "_context_for", lambda t: seen.setdefault("ctx", f"CTX:{t}"))

    class _P:
        def chat(self, system, user, model, max_tokens=4000):
            seen["user"] = user
            return "ok", 1
    monkeypatch.setattr(AS, "build_provider", lambda n, c: _P())
    AS.chat({}, GPT, [{"role": "user", "content": "hi"}])
    assert seen["ctx"] == "CTX:hi" and "CTX:hi" in seen["user"]
