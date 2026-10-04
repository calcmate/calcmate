# -*- coding: utf-8 -*-
"""tests/test_settings_image_google.py — STEP P2-14: Settings Image-gen AI +
Google 연동 React/FastAPI 이관 검증.

dashboard.py "🎨 블로그 이미지 생성 AI 설정"(3150-3183)/"📊 Google 연동"
(3186-3189)과 동일한 계산/저장 의미를 검증한다. 실제 운영 config.yaml/
secrets.yaml은 이 파일의 어떤 테스트에서도 건드리지 않는다 — ConfigService의
파일 접근을 pytest tmp_path로 만든 임시 config.yaml로 격리한다(기존
test_fastapi_settings_write.py와 동일한 격리 패턴 재사용).
"""
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

VIEWER_TOKEN = "p214-test-viewer-token"
ADMIN_TOKEN = "p214-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """실제 config.yaml을 절대 건드리지 않도록, 임시 디렉터리에 최소 config.yaml을
    만들고 ConfigService가 항상 이 경로를 쓰도록 강제한다. 이번 STEP과 무관한
    다른 키(EXISTING_UNRELATED_KEY 등)도 함께 심어 "다른 키 보존"을 검증한다."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "WORDPRESS_URL: http://existing.test\n"
        "DAILY_AI_BUDGET: 5\n"
        "EXISTING_UNRELATED_KEY: keep-me\n"
        "AI_ROLES:\n"
        "  writer:\n"
        "    provider: openai\n"
        "    model: gpt-4o\n"
        "IMAGE_PROVIDER: gemini\n"
        "MODEL_IMAGE: imagen-3.0-generate-002\n"
        "IMAGE_SIZE: 1024x1024\n"
        "IMAGE_QUALITY: hd\n"
        "GOOGLE_SHEET_ID: existing-sheet-id\n"
        "GOOGLE_DRIVE_ROOT_ID: existing-drive-id\n"
        "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID: existing-placeholder-id\n",
        encoding="utf-8",
    )

    import api.services.config_service as svc_mod

    def _forced_init(self, config_path=None):
        self._config_path = config_path or cfg_path

    monkeypatch.setattr(svc_mod.ConfigService, "__init__", _forced_init)
    return cfg_path


def _client():
    from api.main import app
    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _block_external_calls(monkeypatch):
    """Google/Telegram/WordPress/이미지 생성 등 외부 호출이 이 STEP의 어떤
    경로에서도 발생하지 않아야 한다 — 발생하면 즉시 실패시킨다."""
    import requests

    def _boom(*a, **kw):
        raise AssertionError("Image-gen/Google 설정 저장 경로에서 외부 HTTP 호출이 발생했다")

    for m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, m, _boom)


# ══════════════════════════════════════════════════════════════════════════
# GET /api/settings/image-google
# ══════════════════════════════════════════════════════════════════════════

def test_get_without_auth_returns_401(isolated_config):
    r = _client().get("/api/settings/image-google")
    assert r.status_code == 401


def test_get_as_viewer_returns_403(isolated_config):
    r = _client().get("/api/settings/image-google", headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_get_as_admin_returns_current_values(isolated_config):
    r = _client().get("/api/settings/image-google", headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data == {
        "IMAGE_PROVIDER": "gemini",
        "MODEL_IMAGE": "imagen-3.0-generate-002",
        "IMAGE_SIZE": "1024x1024",
        "IMAGE_QUALITY": "hd",
        "GOOGLE_SHEET_ID": "existing-sheet-id",
        "GOOGLE_DRIVE_ROOT_ID": "existing-drive-id",
        "GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID": "existing-placeholder-id",
    }


def test_get_returns_defaults_when_keys_missing(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("WORDPRESS_URL: http://x.test\n", encoding="utf-8")
    import api.services.config_service as svc_mod
    monkeypatch.setattr(svc_mod.ConfigService, "__init__",
                         lambda self, config_path=None: setattr(self, "_config_path", config_path or cfg_path))
    r = _client().get("/api/settings/image-google", headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["IMAGE_PROVIDER"] == "free_pollinations"
    assert data["MODEL_IMAGE"] == ""
    assert data["IMAGE_SIZE"] == "auto"
    assert data["IMAGE_QUALITY"] == "standard"
    assert data["GOOGLE_SHEET_ID"] == ""


def test_get_response_never_contains_secret_looking_strings(isolated_config):
    r = _client().get("/api/settings/image-google", headers=_auth(ADMIN_TOKEN))
    text = r.text.lower()
    for forbidden in ("password", "passwd", "api_key", "apikey", "token", "secret", "credential"):
        assert forbidden not in text, f"응답에 '{forbidden}' 포함됨"


def test_get_response_never_contains_credential_masking_object(isolated_config):
    r = _client().get("/api/settings/image-google", headers=_auth(ADMIN_TOKEN))
    assert "configured" not in r.text  # secret 필드 마스킹 패턴({"configured": bool})이 없어야 함(해당 없음 확인)


# ══════════════════════════════════════════════════════════════════════════
# PATCH 인증
# ══════════════════════════════════════════════════════════════════════════

def test_patch_without_auth_returns_401(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"})
    assert r.status_code == 401
    assert "existing" in isolated_config.read_text(encoding="utf-8")  # 미변경


def test_patch_as_viewer_returns_403(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403
    assert "existing" in isolated_config.read_text(encoding="utf-8")


def test_patch_as_admin_returns_200(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# 입력 검증
# ══════════════════════════════════════════════════════════════════════════

def test_patch_unknown_field_returns_422(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"not_a_real_field": "x"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_patch_invalid_image_provider_returns_422(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_provider": "not-a-real-provider"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_patch_invalid_image_size_returns_422(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_size": "999x999"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_patch_invalid_image_quality_returns_422(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_quality": "ultra"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_patch_valid_enum_values_accepted(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google",
                         json={"image_provider": "openai", "image_size": "1792x1024", "image_quality": "hd"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["IMAGE_PROVIDER"] == "openai"
    assert data["IMAGE_SIZE"] == "1792x1024"
    assert data["IMAGE_QUALITY"] == "hd"


def test_patch_google_ids_accept_free_text(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google",
                         json={"google_sheet_id": "new-sheet-id-123"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["GOOGLE_SHEET_ID"] == "new-sheet-id-123"


def test_patch_explicit_empty_string_clears_value(isolated_config, monkeypatch):
    """비-secret 필드이므로 빈 문자열을 명시적으로 보내면 실제로 비운다
    (GeneralSettingsUpdate의 falsy-필터링과 다른 의미론, 모듈 docstring 참고)."""
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"google_sheet_id": ""},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert r.json()["data"]["GOOGLE_SHEET_ID"] == ""


def test_patch_omitted_field_leaves_value_unchanged(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(ADMIN_TOKEN))
    data = r.json()["data"]
    assert data["GOOGLE_SHEET_ID"] == "existing-sheet-id"  # 안 보낸 필드는 그대로


# ══════════════════════════════════════════════════════════════════════════
# config 보존성(§7) — 대상 7개 외 다른 키/섹션 완전 보존
# ══════════════════════════════════════════════════════════════════════════

def test_patch_preserves_unrelated_keys_and_sections(isolated_config, monkeypatch):
    _block_external_calls(monkeypatch)
    before = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))

    r = _client().patch("/api/settings/image-google",
                         json={"image_provider": "openai", "google_sheet_id": "changed-id"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200

    after = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert after["WORDPRESS_URL"] == before["WORDPRESS_URL"]
    assert after["DAILY_AI_BUDGET"] == before["DAILY_AI_BUDGET"]
    assert after["EXISTING_UNRELATED_KEY"] == before["EXISTING_UNRELATED_KEY"]
    assert after["AI_ROLES"] == before["AI_ROLES"]
    # 대상 필드만 변경됨
    assert after["IMAGE_PROVIDER"] == "openai"
    assert after["GOOGLE_SHEET_ID"] == "changed-id"
    # 나머지 대상 필드(변경 안 보낸)는 그대로
    assert after["MODEL_IMAGE"] == before["MODEL_IMAGE"]
    assert after["IMAGE_SIZE"] == before["IMAGE_SIZE"]


def test_patch_does_not_touch_secrets_yaml_path(isolated_config, monkeypatch, tmp_path):
    """이 7개는 secret이 아니므로 save_secrets_flat() 등 secrets.yaml 관련
    함수를 전혀 호출하지 않는다 — secrets.yaml이 아예 생성되지 않아야 한다."""
    _block_external_calls(monkeypatch)
    secrets_path = tmp_path / "secrets.yaml"
    assert not secrets_path.exists()
    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert not secrets_path.exists()


# ══════════════════════════════════════════════════════════════════════════
# atomic write / rollback(§11)
# ══════════════════════════════════════════════════════════════════════════

def test_patch_write_failure_leaves_original_config_intact(isolated_config, monkeypatch):
    """_atomic_write()가 임시파일 write 단계에서 실패하면 원본 config.yaml은
    전혀 변경되지 않아야 한다(임시파일→rename 패턴이므로 rename 이전에 실패하면
    원본은 그대로 남는다)."""
    _block_external_calls(monkeypatch)
    before = isolated_config.read_text(encoding="utf-8")

    from api.services.config_service import ConfigService

    def _boom_write(self, text):
        raise OSError("simulated disk full")
    monkeypatch.setattr(ConfigService, "_atomic_write", _boom_write)

    with pytest.raises(OSError):
        _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(ADMIN_TOKEN))

    after = isolated_config.read_text(encoding="utf-8")
    assert after == before


def test_patch_uses_existing_atomic_write_temp_file_rename_pattern(isolated_config, monkeypatch):
    """새 저장 메커니즘을 만들지 않았는지 — ConfigService._atomic_write가
    실제로 호출되는지(재사용 여부) 확인한다."""
    _block_external_calls(monkeypatch)
    from api.services.config_service import ConfigService
    calls = []
    original = ConfigService._atomic_write

    def _spy(self, text):
        calls.append(text)
        return original(self, text)
    monkeypatch.setattr(ConfigService, "_atomic_write", _spy)

    r = _client().patch("/api/settings/image-google", json={"image_provider": "openai"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    assert len(calls) == 1


# ══════════════════════════════════════════════════════════════════════════
# 동시성(§8)
# ══════════════════════════════════════════════════════════════════════════

def test_concurrent_patches_do_not_corrupt_config_file(isolated_config, monkeypatch):
    """두 요청이 거의 동시에 저장되어도 최종 파일은 항상 유효한 YAML이어야
    하고(손상 없음), 부분 쓰기(잘린/깨진 내용)는 절대 없어야 한다. 재사용하는
    기존 _atomic_write()(임시파일→rename)는 두 요청이 완전히 같은 순간에
    경합하면 Windows에서 둘 중 하나가 PermissionError로 실패할 수 있다(같은
    "config.yaml.tmp" 경로를 공유하기 때문 — STEP 4-F부터 있던 기존 동작이며
    이 STEP에서 새로 만들지 않았다). 이 STEP이 보장해야 하는 것은 "파일이
    손상되지 않는다"이지 "두 요청 모두 반드시 200이어야 한다"가 아니다 —
    실패하는 쪽은 rename 이전에 예외가 발생하므로 원본 파일은 항상 온전하게
    남는다(§3의 "저장 실패 시 기존 config 보존"과 일치)."""
    _block_external_calls(monkeypatch)

    results = []
    errors = []

    def _run(provider):
        try:
            r = _client().patch("/api/settings/image-google", json={"image_provider": provider},
                                 headers=_auth(ADMIN_TOKEN))
            results.append(r.status_code)
        except Exception as e:  # noqa: BLE001 — 아래에서 원인을 검증하기 위해 수집
            errors.append(e)

    threads = [threading.Thread(target=_run, args=(p,)) for p in ("openai", "gemini")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) + len(errors) == 2  # 두 스레드 모두 실제로 완료됨(유실 없음)
    assert all(code == 200 for code in results)  # 성공한 요청은 전부 정상 응답
    for e in errors:
        assert isinstance(e, PermissionError)  # 실패한다면 오직 이 알려진 원인으로만

    final_text = isolated_config.read_text(encoding="utf-8")
    final = yaml.safe_load(final_text)  # 파싱 자체가 성공 = YAML 손상 없음
    assert final["IMAGE_PROVIDER"] in ("openai", "gemini")  # 둘 중 하나로 일관(부분 쓰기 없음)
    assert final["WORDPRESS_URL"] == "http://existing.test"  # 다른 키도 그대로


# ══════════════════════════════════════════════════════════════════════════
# 외부 호출 없음(§9, AST/static + mock 이중 확인)
# ══════════════════════════════════════════════════════════════════════════

def _source_body_without_docstring(fn):
    import ast
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(fn))  # 클래스 메서드는 들여쓰기된 채로 반환되므로 dedent 필요
    tree = ast.parse(source)
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant) and isinstance(func.body[0].value.value, str)):
        func.body = func.body[1:]
    return ast.unparse(func)


def test_service_source_has_no_external_call_or_write_elsewhere():
    from api.services import config_service
    for fn in (config_service.ConfigService.get_image_google_settings,
               config_service.ConfigService.patch_image_google_settings):
        source = _source_body_without_docstring(fn)
        for forbidden in ("requests.", "gspread", "telegram_ops", "publisher", "image_generator",
                          "save_secrets_flat"):
            assert forbidden not in source, f"{fn.__name__}가 외부 호출/범위 밖 기능({forbidden})을 참조함"


def test_patch_did_not_call_requests_at_all(isolated_config, monkeypatch):
    """mock으로 이중 확인: requests의 모든 메서드를 호출 즉시 실패하는 함수로
    바꿔둔 상태에서 PATCH가 정상 200을 반환해야 한다(=requests를 전혀
    호출하지 않았다는 뜻)."""
    _block_external_calls(monkeypatch)
    r = _client().patch("/api/settings/image-google",
                         json={"image_provider": "gemini", "google_sheet_id": "x"},
                         headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 기존 완료 STEP(4-F general) 무변경 확인 + route 확인
# ══════════════════════════════════════════════════════════════════════════

def test_general_settings_endpoint_still_works_unmodified(isolated_config):
    """P2-14가 GeneralSettingsUpdate/patch_general_settings()를 건드리지
    않았는지 회귀 확인 — general 조회가 여전히 정상 동작해야 한다."""
    r = _client().get("/api/settings/general")
    assert r.status_code == 200
    assert r.json()["data"]["WORDPRESS_URL"] == "http://existing.test"


def test_image_google_routes_exist_before_dynamic_section_route():
    from _route_utils import collect_routes
    from api.main import app
    routes = collect_routes(app)
    paths_methods = {(r.path, m) for r in routes for m in r.methods if "image-google" in r.path}
    assert paths_methods == {
        ("/api/settings/image-google", "GET"),
        ("/api/settings/image-google", "PATCH"),
    }
