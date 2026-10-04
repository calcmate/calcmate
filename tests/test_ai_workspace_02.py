# -*- coding: utf-8 -*-
"""tests/test_ai_workspace_02.py — CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-WORKSPACE-02.

dashboard.py "💬 AI Workspace" 이관(/api/workspace/*)과 HTTP 보안 경계 검증.

격리: modules.ai_workspace._root / modules.ai_assistant.ROOT(공용 경로 검증 기준)를 tmp 루트로
바꿔 운영 저장소·운영 data/workspace를 건드리지 않는다. provider는 ai_roles.build_provider를
mock해 실제 ai_workspace.chat → ai_roles.make_provider 경로를 그대로 타게 하고(실제 호출 0),
BudgetTracker도 mock한다.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

VIEWER = "aw02-viewer-token"
ADMIN = "aw02-admin-token"
SECRET = "sk-live-WORKSPACESECRET0123456789"


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
    from modules import ai_assistant as AS, ai_workspace as WS, ai_roles as R
    from api.services import workspace_service as S
    root = (tmp_path / "root")
    files = {
        "main.py": "print('main')\n",
        "modules/app_factory.py": "# af\n",
        "config/config.yaml": "SITE_URL: https://calcmate.kr\n",
        "config/secrets.yaml": f"OPENAI_API_KEY: {SECRET}\n",
        "credentials.json": f"{{\"k\": \"{SECRET}\"}}",
        "token.json": f"{{\"t\": \"{SECRET}\"}}",
        "secret.txt": SECRET,
        "api_key.txt": SECRET,
        "notes/apikey.md": SECRET,
        "foo/token.txt": SECRET,
        "foo/secret.yaml": SECRET,
        "foo/credentials.json": SECRET,
        "secrets/x.yaml": SECRET,
        ".env": f"K={SECRET}\n",
        ".env.local": f"K={SECRET}\n",
        ".env.production": f"K={SECRET}\n",
        "foo/.env.production": f"K={SECRET}\n",
        ".git/config": "[core]\n",
        "data/workspace/_site/index.html": "<html>site</html>",
        "data/workspace/_site/sitemap.xml": "<urlset/>",
        "data/workspace/existing.html": "<p>old</p>",
        "data/workspace/backups/old.bak": "bak",
        "docs/readme.md": "readme\n",
    }
    for rel, c in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8")
    root = root.resolve()
    monkeypatch.setattr(AS, "ROOT", root)
    monkeypatch.setattr(WS, "_root", lambda: root)

    state = {"calls": [], "providers": [], "budget": [], "reply": ("워크스페이스 응답", 77), "raise": None,
             "build_raise": None, "cfg": {"OPENAI_API_KEY": SECRET, "SITE_URL": "https://calcmate.kr"},
             "rows": {"sites": [{"site_id": "s1", "site_name": "A", "wp_app_password": SECRET, "api_token": SECRET,
                                 "github_token": SECRET, "client_secret": SECRET, "openai_api_key": SECRET,
                                 "ApiKey": SECRET, "Authorization": SECRET, "refresh_token": SECRET,
                                 "credential_ref": SECRET, "wordpress_url": "https://wp.test"}]}}

    class _P:
        def chat(self, system, user, model, max_tokens=4000, json_mode=False):
            state["calls"].append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
            if state["raise"]:
                raise state["raise"]
            return state["reply"]

    def _build(provider_name, cfg):
        state["providers"].append(provider_name)
        if state["build_raise"]:
            raise state["build_raise"]
        return _P()

    class _Budget:
        def __init__(self, cfg):
            pass

        def record(self, model, tokens=0, **kw):
            state["budget"].append((model, tokens))

    monkeypatch.setattr(R, "build_provider", _build)
    monkeypatch.setattr(WS, "BudgetTracker", _Budget)
    monkeypatch.setattr(WS, "query_repo", lambda cfg, which: list(state["rows"].get(which, [{"id": i} for i in range(30)])))
    monkeypatch.setattr(S, "load_config", lambda *a, **k: dict(state["cfg"]))
    state["root"] = root
    return state


def _client():
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _h(t=ADMIN):
    return {"Authorization": f"Bearer {t}"}


def _post(path, body, token=ADMIN):
    return _client().post(path, headers=_h(token), json=body)


def _chat(content="안녕", role="orchestrator", context=None, messages=None):
    return _post("/api/workspace/chat", {"role": role, "messages": messages or [{"role": "user", "content": content}],
                                         "context": context or {}})


ROUTES = [
    ("get", "/api/workspace/models", None), ("get", "/api/workspace/context/files", None),
    ("post", "/api/workspace/chat", {"role": "orchestrator", "messages": [{"role": "user", "content": "x"}]}),
    ("post", "/api/workspace/files/sandbox", {"name": "a.html", "content": "x"}),
    ("post", "/api/workspace/files/preview", {"path": "docs/readme.md", "content": "x"}),
    ("post", "/api/workspace/files/write", {"path": "docs/readme.md", "content": "x", "expected_old_sha256": "0" * 64}),
    ("post", "/api/workspace/files/create", {"path": "docs/new.md", "content": "x"}),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_unauthenticated_401(method, path, body):
    r = getattr(_client(), method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_viewer_403_no_ai_no_write(method, path, body, ws):
    r = getattr(_client(), method)(path, headers=_h(VIEWER), **({"json": body} if body is not None else {}))
    assert r.status_code == 403
    assert ws["calls"] == [] and not (ws["root"] / "docs/new.md").exists() and not (ws["root"] / "data/workspace/a.html").exists()


# ── Roles / Chat ───────────────────────────────────────────────────────────

def test_models_roles_and_defaults(ws):
    d = _client().get("/api/workspace/models", headers=_h()).json()["data"]
    assert [(r["id"], r["label"]) for r in d["roles"]] == [("orchestrator", "총괄 (GPT)"), ("code", "코드 (Claude)"), ("research", "리서치 (Gemini)")]
    assert [(r["provider"], r["model"]) for r in d["roles"]] == [("openai", "gpt-4o"), ("claude", "claude-sonnet-4-6"), ("gemini", "gemini-2.5-flash")]
    assert d["repos"] == ["sites", "calculators", "articles", "templates"]
    assert SECRET not in str(d)


def test_models_reflect_ai_roles_setting(ws):
    ws["cfg"]["AI_ROLES"] = {"code": {"provider": "openai", "model": "gpt-4o-mini"}}
    d = _client().get("/api/workspace/models", headers=_h()).json()["data"]
    assert d["roles"][1]["provider"] == "openai" and d["roles"][1]["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("role,provider,model", [("orchestrator", "openai", "gpt-4o"), ("code", "claude", "claude-sonnet-4-6"),
                                                 ("research", "gemini", "gemini-2.5-flash")])
def test_chat_routes_through_ai_roles_and_records_budget(ws, role, provider, model):
    d = _chat(role=role).json()["data"]
    assert d == {"reply": "워크스페이스 응답", "model": model, "tokens": 77}
    assert ws["providers"] == [provider] and ws["calls"][0]["max_tokens"] == 2500
    assert "SalaryMate 운영센터의 AI 어시스턴트" in ws["calls"][0]["system"]
    assert ws["budget"] == [(model, 77)]


def test_chat_ai_roles_override_is_used(ws):
    ws["cfg"]["AI_ROLES"] = {"code": {"provider": "gemini", "model": "gemini-2.5-pro"}}
    d = _chat(role="code").json()["data"]
    assert ws["providers"] == ["gemini"] and d["model"] == "gemini-2.5-pro"


def test_chat_invalid_role_and_messages(ws):
    assert _chat(role="writer").json()["error"]["code"] == "VALIDATION_ERROR"
    assert _chat(content="   ").json()["error"]["code"] == "VALIDATION_ERROR"
    r = _chat(messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _post("/api/workspace/chat", {"role": "code", "messages": [{"role": "user", "content": "x"}],
                                         "context": "raw context string"}).status_code == 422
    assert _post("/api/workspace/chat", {"role": "code", "provider": "openrouter",
                                         "messages": [{"role": "user", "content": "x"}]}).status_code == 422
    assert ws["calls"] == []


def test_chat_recent_12_messages(ws):
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m-{i:02d}"} for i in range(19)]
    msgs.append({"role": "user", "content": "m-final"})
    _chat(messages=msgs)
    convo = ws["calls"][0]["user"]
    assert "m-final" in convo and "m-08" in convo and "m-07" not in convo


def test_chat_error_sanitized(ws, caplog):
    ws["raise"] = RuntimeError(f"boom {SECRET} C:\\Users\\x\\secrets.yaml Traceback")
    with caplog.at_level(logging.DEBUG):
        r = _chat()
    assert r.json()["error"]["code"] == "AI_REQUEST_FAILED"
    assert SECRET not in r.text and "secrets.yaml" not in r.text and "Traceback" not in r.text
    assert SECRET not in caplog.text and ws["budget"] == []
    ws["raise"] = None
    ws["build_raise"] = KeyError("CLAUDE_API_KEY")
    r2 = _chat(role="code")
    assert r2.json()["error"]["code"] == "AI_NOT_CONFIGURED" and "CLAUDE_API_KEY" not in r2.text


# ── Context ────────────────────────────────────────────────────────────────

def test_context_files_list_excludes_sensitive(ws):
    files = _client().get("/api/workspace/context/files", headers=_h()).json()["data"]["files"]
    assert "main.py" in files and "docs/readme.md" in files and "config/config.yaml" in files
    for bad in ("config/secrets.yaml", "credentials.json", "token.json", "secret.txt", "api_key.txt", "notes/apikey.md",
                "foo/token.txt", "foo/secret.yaml", "foo/credentials.json", "secrets/x.yaml", "data/workspace/backups/old.bak"):
        assert bad not in files, bad


def test_file_context_attached(ws):
    _chat("분석해", context={"file": "main.py"})
    assert "# 파일: main.py\nprint('main')" in ws["calls"][0]["user"]


def test_repo_context_20_rows_and_sensitive_columns_removed(ws):
    _chat(context={"repo": "calculators"})
    convo = ws["calls"][0]["user"]
    assert "# calculators 데이터(최대 20행)" in convo and "'id': 19" in convo and "'id': 20" not in convo
    ws["calls"].clear()
    _chat(context={"repo": "sites"})
    convo = ws["calls"][0]["user"]
    assert "'site_name': 'A'" in convo and "https://wp.test" in convo and SECRET not in convo
    for col in ("wp_app_password", "api_token", "github_token", "client_secret", "openai_api_key", "ApiKey",
                "Authorization", "refresh_token", "credential_ref"):
        assert col not in convo, col


def test_structure_context(ws):
    _chat(context={"structure": True})
    assert "# 프로젝트 구조\n{" in ws["calls"][0]["user"]


def test_context_limited_to_8000_chars(ws):
    (ws["root"] / "docs/big.md").write_text("x" * 20000, encoding="utf-8")
    from api.services import workspace_service as S
    ctx = S.build_context(file="docs/big.md", structure=True)
    assert len(ctx) == 8000


def test_context_failure_uses_placeholder_not_raw_error(ws, monkeypatch):
    from modules import ai_workspace as WS
    monkeypatch.setattr(WS, "query_repo", lambda cfg, which: (_ for _ in ()).throw(RuntimeError(f"db down {SECRET}")))
    _chat(context={"repo": "sites"})
    convo = ws["calls"][0]["user"]
    assert "(컨텍스트 일부를 불러오지 못했습니다)" in convo and "db down" not in convo and SECRET not in convo


# ── 보안 매트릭스 ──────────────────────────────────────────────────────────

MATRIX = ["../x.txt", "..\\x.txt", "../config/secrets.yaml", "C:\\secret", "c:/secret", "/etc/passwd",
          "\\\\server\\share", "//server/share/x", "file.txt:secret", ".git/config", ".env", ".env.local",
          ".env.production", "foo/.env.production", "config/secrets.yaml", "credentials.json", "token.json",
          "secret.txt", "api_key.txt", "notes/apikey.md", "foo/token.txt", "foo/secret.yaml", "secrets/x.yaml",
          "data/workspace/backups/old.bak"]


@pytest.mark.parametrize("path", MATRIX)
def test_attach_read_blocked_without_ai_call(ws, path):
    r = _chat(context={"file": path})
    assert r.json()["error"]["code"] == "FILE_NOT_ALLOWED"
    assert ws["calls"] == [] and SECRET not in r.text and "secrets.yaml" not in r.json()["error"]["message"]


@pytest.mark.parametrize("path", MATRIX + ["data/workspace/_site/index.html", "data/workspace/_site/sitemap.xml",
                                           "data/workspace/_site/new.html"])
def test_preview_write_create_blocked(ws, path):
    for ep, body in (("preview", {"path": path, "content": "x"}), ("create", {"path": path, "content": "x"}),
                     ("write", {"path": path, "content": "x", "expected_old_sha256": "0" * 64})):
        r = _post(f"/api/workspace/files/{ep}", body)
        assert r.json()["error"]["code"] == "FILE_NOT_ALLOWED", (ep, path)
    assert (ws["root"] / "data/workspace/_site/index.html").read_text(encoding="utf-8") == "<html>site</html>"
    assert (ws["root"] / "config/secrets.yaml").read_text(encoding="utf-8").endswith(f"{SECRET}\n")


@pytest.mark.parametrize("name", [".env", ".env.local", "secret.txt", "my_token.json", "credentials.json", "api_key.txt",
                                  "_site", "backups", "..", "."])
def test_sandbox_blocked_names(ws, name):
    r = _post("/api/workspace/files/sandbox", {"name": name, "content": "x"})
    assert r.json()["error"]["code"] == "FILE_NOT_ALLOWED", name
    assert not (ws["root"] / "data/workspace" / name).is_file()


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


def _make_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return r.returncode == 0 and link.exists()


def _escape_checks(ws, prefix, outside):
    r = _chat(context={"file": f"{prefix}/leak.txt"})
    assert r.json()["error"]["code"] == "FILE_NOT_ALLOWED" and ws["calls"] == [] and SECRET not in r.text
    for ep, body in (("preview", {"path": f"{prefix}/leak.txt", "content": "x"}),
                     ("create", {"path": f"{prefix}/new.txt", "content": "x"}),
                     ("write", {"path": f"{prefix}/leak.txt", "content": "x", "expected_old_sha256": "0" * 64})):
        assert _post(f"/api/workspace/files/{ep}", body).json()["error"]["code"] == "FILE_NOT_ALLOWED", ep
    assert not (outside / "new.txt").exists() and (outside / "leak.txt").read_text(encoding="utf-8") == SECRET


def test_symlink_escape_blocked(ws, tmp_path):
    outside = tmp_path / "outside_sym"
    outside.mkdir()
    (outside / "leak.txt").write_text(SECRET, encoding="utf-8")
    if not _make_link(ws["root"] / "docs" / "sym", outside):
        pytest.skip("symlink 생성 불가")
    _escape_checks(ws, "docs/sym", outside)


def test_junction_escape_blocked(ws, tmp_path):
    outside = tmp_path / "outside_junc"
    outside.mkdir()
    (outside / "leak.txt").write_text(SECRET, encoding="utf-8")
    if not _make_junction(ws["root"] / "docs" / "junc", outside):
        pytest.skip("junction 생성 불가(Windows 전용)")
    _escape_checks(ws, "docs/junc", outside)


def test_link_inside_root_to_site_dir_cannot_write(ws):
    if not _make_link(ws["root"] / "docs" / "sitelink", ws["root"] / "data/workspace/_site"):
        pytest.skip("symlink/junction 생성 불가")
    r = _post("/api/workspace/files/create", {"path": "docs/sitelink/evil.html", "content": "x"})
    assert r.json()["error"]["code"] == "FILE_NOT_ALLOWED"
    assert not (ws["root"] / "data/workspace/_site/evil.html").exists()


# ── 저장 ───────────────────────────────────────────────────────────────────

def test_sandbox_new_save_and_overwrite_requires_confirm_with_backup(ws):
    r = _post("/api/workspace/files/sandbox", {"name": "gen page.html", "content": "<p>new</p>"}).json()
    assert r["data"] == {"path": "data/workspace/gen_page.html", "saved": True, "overwritten": False, "backup": None}
    assert (ws["root"] / "data/workspace/gen_page.html").read_text(encoding="utf-8") == "<p>new</p>"
    c = _post("/api/workspace/files/sandbox", {"name": "existing.html", "content": "<p>v2</p>"})
    assert c.json()["error"]["code"] == "FILE_CONFLICT"
    assert (ws["root"] / "data/workspace/existing.html").read_text(encoding="utf-8") == "<p>old</p>"
    o = _post("/api/workspace/files/sandbox", {"name": "existing.html", "content": "<p>v2</p>", "overwrite": True}).json()["data"]
    assert o["overwritten"] is True and o["backup"].startswith("data/workspace/backups/existing.html.")
    assert (ws["root"] / o["backup"]).read_text(encoding="utf-8") == "<p>old</p>"
    assert (ws["root"] / "data/workspace/existing.html").read_text(encoding="utf-8") == "<p>v2</p>"


def test_sandbox_empty_content_rejected(ws):
    assert _post("/api/workspace/files/sandbox", {"name": "a.txt", "content": "  "}).json()["error"]["code"] == "VALIDATION_ERROR"


def test_project_preview_then_write_with_sha_and_backup(ws):
    pv = _post("/api/workspace/files/preview", {"path": "docs/readme.md", "content": "updated"}).json()["data"]
    assert pv["exists"] is True and pv["old"] == "readme\n" and len(pv["old_sha256"]) == 64
    assert (ws["root"] / "docs/readme.md").read_text(encoding="utf-8") == "readme\n"      # preview는 변경 없음
    r = _post("/api/workspace/files/write", {"path": "docs/readme.md", "content": "updated",
                                            "expected_old_sha256": pv["old_sha256"]}).json()
    assert r["success"] is True and r["data"]["backed_up"] is True and str(ws["root"]) not in str(r)
    assert (ws["root"] / "docs/readme.md").read_text(encoding="utf-8") == "updated"
    baks = list((ws["root"] / "data/workspace/backups").glob("readme.md.*.bak"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == "readme\n"


def test_project_write_sha_mismatch_is_conflict(ws):
    pv = _post("/api/workspace/files/preview", {"path": "docs/readme.md", "content": "A"}).json()["data"]
    (ws["root"] / "docs/readme.md").write_text("changed", encoding="utf-8")
    r = _post("/api/workspace/files/write", {"path": "docs/readme.md", "content": "A", "expected_old_sha256": pv["old_sha256"]})
    assert r.json()["error"]["code"] == "FILE_CONFLICT"
    assert (ws["root"] / "docs/readme.md").read_text(encoding="utf-8") == "changed"


def test_project_write_requires_existing_and_sha(ws):
    assert _post("/api/workspace/files/write", {"path": "docs/none.md", "content": "x", "expected_old_sha256": "a" * 64}).json()["error"]["code"] == "FILE_CONFLICT"
    assert _post("/api/workspace/files/write", {"path": "docs/readme.md", "content": "x"}).status_code == 422


def test_project_create_and_existing_rejected(ws):
    r = _post("/api/workspace/files/create", {"path": "docs/sub/new.md", "content": "made"}).json()
    assert r["success"] is True and (ws["root"] / "docs/sub/new.md").read_text(encoding="utf-8") == "made"
    r2 = _post("/api/workspace/files/create", {"path": "docs/readme.md", "content": "x"})
    assert r2.json()["error"]["code"] == "FILE_CONFLICT"
    assert (ws["root"] / "docs/readme.md").read_text(encoding="utf-8") == "readme\n"


def test_client_cannot_choose_backup_path(ws):
    assert _post("/api/workspace/files/write", {"path": "docs/readme.md", "content": "x", "expected_old_sha256": "a" * 64,
                                                "backup_path": "docs/steal.bak"}).status_code == 422
    assert _post("/api/workspace/files/create", {"path": "data/workspace/backups/injected.bak", "content": "x"}).json()["error"]["code"] == "FILE_NOT_ALLOWED"
    assert _post("/api/workspace/files/create", {"path": "data/assistant/backups/injected.bak", "content": "x"}).json()["error"]["code"] == "FILE_NOT_ALLOWED"


def test_dashboard_module_contract_unchanged():
    import inspect
    from modules import ai_workspace as WS
    assert list(inspect.signature(WS.chat).parameters) == ["cfg", "role", "messages", "context"]
    assert WS.SAFE_EXT == {".py", ".md", ".yaml", ".yml", ".bat", ".txt", ".json"}
