# -*- coding: utf-8 -*-
"""tests/test_sites_create.py — STEP P2-06: Site Management Create/Import
React/FastAPI 이관 검증.

dashboard.py "➕ 사이트 추가"/"🧙 새 사이트 마법사"/"⬆️ Import"(dashboard.py:1037-
1070, 1168-1343)와 동일한 실행 의미를 검증한다. 실제 운영 DB/secrets.yaml은 이
파일의 어떤 테스트에서도 건드리지 않는다 — 전부 isolated tmp_path(가짜 DB_ADAPTER
=sqlite, 가짜 config/secrets.yaml)에서만 실행한다. 실제 site_wizard.create_site()
자체는 (rollback/concurrency 검증 목적으로) 이 파일의 일부 테스트에서 진짜로
호출되지만, 대상은 항상 tmp_path이지 실제 프로젝트 데이터가 아니다.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
import yaml
from fastapi.testclient import TestClient

VIEWER_TOKEN = "sites-create-test-viewer-token"
ADMIN_TOKEN = "sites-create-test-admin-token"


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch):
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_VIEWER", VIEWER_TOKEN)
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    from api.auth.service import clear_audit_events
    clear_audit_events()
    yield
    clear_audit_events()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _client():
    from api.main import app
    return TestClient(app)


def _isolated_cfg(tmp_path):
    """실제 프로젝트 DB/secrets.yaml과 완전히 분리된 cfg. DB_ADAPTER를 명시적으로
    "sqlite"로 지정한다 — get_db_adapter()의 기본값은 "sheets"이므로, 이를
    빠뜨리면 실제 Google Sheets를 건드릴 위험이 있다(운영 데이터 보호 원칙)."""
    return {"_root": str(tmp_path), "DB_ADAPTER": "sqlite", "SQLITE_PATH": "data/blog_auto.db"}


def _mock_isolated(monkeypatch, tmp_path):
    cfg = _isolated_cfg(tmp_path)
    monkeypatch.setattr("api.services.site_service.load_config", lambda: dict(cfg))
    return cfg


VALID_PAYLOAD = {
    "type_label": "계산기",  # needs_wp=False — WordPress 자격증명 없이도 성공 가능
    "site_name": "테스트 계산기 사이트",
    "domain": "calc-test.example.com",
}


# ══════════════════════════════════════════════════════════════════════════
# Create — 인증
# ══════════════════════════════════════════════════════════════════════════

def test_create_without_auth_returns_401():
    r = _client().post("/api/sites", json=VALID_PAYLOAD)
    assert r.status_code == 401


def test_create_as_viewer_returns_403():
    r = _client().post("/api/sites", json=VALID_PAYLOAD, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_create_as_admin_returns_200(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites", json=VALID_PAYLOAD, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["site_name"] == "테스트 계산기 사이트"
    assert body["data"]["domain"] == "calc-test.example.com"
    assert body["data"]["site_id"]  # 자동 생성된 site_id가 채워져 있어야 함


def test_create_invalid_payload_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites", json={"type_label": "존재하지않는유형", "site_name": "x", "domain": "x.com"},
                        headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_create_missing_required_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites", json={"type_label": "계산기", "domain": "x.com"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_create_extra_field_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    payload = dict(VALID_PAYLOAD, unexpected_field="x")
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# Create — 중복 검증(기존 _validate_site() 그대로 재사용)
# ══════════════════════════════════════════════════════════════════════════

def test_create_duplicate_domain_returns_validation_error(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r1 = _client().post("/api/sites", json=VALID_PAYLOAD, headers=_auth(ADMIN_TOKEN))
    assert r1.status_code == 200 and r1.json()["success"] is True

    dup = dict(VALID_PAYLOAD, site_name="다른이름")  # 도메인만 동일
    r2 = _client().post("/api/sites", json=dup, headers=_auth(ADMIN_TOKEN))
    assert r2.status_code == 200
    body = r2.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "도메인" in body["error"]["message"]


def test_create_duplicate_site_name_returns_validation_error(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r1 = _client().post("/api/sites", json=VALID_PAYLOAD, headers=_auth(ADMIN_TOKEN))
    assert r1.status_code == 200 and r1.json()["success"] is True

    dup = dict(VALID_PAYLOAD, domain="different-domain.example.com")  # 이름만 동일
    r2 = _client().post("/api/sites", json=dup, headers=_auth(ADMIN_TOKEN))
    body = r2.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "사이트명" in body["error"]["message"]


def test_create_wordpress_type_without_credentials_fails_like_original(monkeypatch, tmp_path):
    """needs_wp=True인 유형(예: 사용자정의)에 WordPress ID/App Password가 없으면
    원본 _validate_site()와 동일하게 실패해야 한다."""
    _mock_isolated(monkeypatch, tmp_path)
    payload = {"type_label": "사용자정의", "site_name": "블로그사이트", "domain": "blog-test.example.com",
               "wp_url": "http://wp.example.com"}
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "WordPress" in body["error"]["message"]


# ══════════════════════════════════════════════════════════════════════════
# Create — wordpress_configured / platforms / secret 미노출
# ══════════════════════════════════════════════════════════════════════════

def test_create_with_full_wordpress_credentials_sets_configured_true(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    payload = {
        "type_label": "사용자정의", "site_name": "WP사이트", "domain": "wp-test.example.com",
        "wp_url": "http://wp.example.com", "wp_user": "admin", "wp_app_password": "fake-app-password-1234",
        "platforms": ["WordPress"],
    }
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is True
    assert body["data"]["wordpress_configured"] is True
    assert body["data"]["platforms"] == ["WordPress"]


def test_create_without_wordpress_sets_configured_false(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites", json=VALID_PAYLOAD, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["wordpress_configured"] is False


def test_create_response_never_contains_secret_values(monkeypatch, tmp_path):
    payload = {
        "type_label": "사용자정의", "site_name": "시크릿체크사이트", "domain": "secretcheck.example.com",
        "wp_url": "http://real-wp.example", "wp_user": "realuser999", "wp_app_password": "super-secret-app-password-abc",
        "platforms": ["WordPress"],
    }
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    body_text = r.text
    for forbidden in (
        "realuser999", "super-secret-app-password-abc", "real-wp.example",
        "password", "passwd", "app_password", "api_key", "apikey", "token",
        "access_token", "refresh_token", "client_secret", "private_key",
    ):
        assert forbidden not in body_text, f"응답에 민감할 수 있는 문자열 '{forbidden}'이 포함됨"

    # secrets.yaml 자체(실제 파일 내용)에도 rollback 관련 로직이 값 자체를 로그로
    # 남기지 않는지 확인 — 이 테스트는 응답만 검사하면 충분하다(secrets.yaml
    # 자체에 값이 있는 것은 정상이며, 문제는 그것이 API 응답에 노출되는지 여부).


# ══════════════════════════════════════════════════════════════════════════
# Rollback — 실제 secrets.yaml write 성공 + DB write 실패 재현(isolated)
# ══════════════════════════════════════════════════════════════════════════

def test_rollback_removes_orphan_wp_profile_when_db_save_fails(monkeypatch, tmp_path):
    """P2-05에서 확인된 위험 재현: save_wp_profile()(secrets.yaml)은 성공하지만
    SiteRepository.save()(DB)가 실패하는 경우, 이번 STEP 이전에는 secrets.yaml에
    고아 wordpress_profiles 항목이 남았다. 이제는 롤백되어 남지 않아야 한다."""
    cfg = _mock_isolated(monkeypatch, tmp_path)

    from repositories.site_repository import SiteRepository

    def _boom_save(self, row):
        raise RuntimeError("시뮬레이션된 DB 저장 실패")
    monkeypatch.setattr(SiteRepository, "save", _boom_save)

    payload = {
        "type_label": "사용자정의", "site_name": "롤백테스트사이트", "domain": "rollback-test.example.com",
        "wp_url": "http://wp.example.com", "wp_user": "admin", "wp_app_password": "fake-pw-rollback",
    }
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"

    # secrets.yaml에 고아 profile이 남아있지 않아야 한다.
    secrets_path = Path(cfg["_root"]) / "config" / "secrets.yaml"
    assert secrets_path.exists(), "secrets.yaml 자체는 save_wp_profile() 호출로 생성되었어야 함"
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("wordpress_profiles", {}) == {}, "DB 저장 실패 후 고아 wordpress_profiles가 남아있음"


def test_rollback_restores_previous_profile_value_on_db_failure(monkeypatch, tmp_path):
    """기존에 동일 profile_id가 이미 존재하던 경우(예: 이전 사이트가 같은 슬러그를
    사용), DB 저장 실패 시 원래 값으로 복원되어야 한다(값을 잃지 않아야 함)."""
    cfg = _mock_isolated(monkeypatch, tmp_path)
    secrets_path = Path(cfg["_root"]) / "config" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(yaml.dump({
        "wordpress_profiles": {
            "wp_기존사이트": {"url": "http://original.example.com", "username": "originaluser", "app_password": "original-pw"}
        }
    }, allow_unicode=True), encoding="utf-8")

    from repositories.site_repository import SiteRepository

    def _boom_save(self, row):
        raise RuntimeError("시뮬레이션된 DB 저장 실패")
    monkeypatch.setattr(SiteRepository, "save", _boom_save)

    # site_name의 slug가 기존 profile_id("wp_기존사이트")와 충돌하도록 동일한 이름 사용.
    payload = {
        "type_label": "사용자정의", "site_name": "기존사이트", "domain": "collision-test.example.com",
        "wp_url": "http://new-attempt.example.com", "wp_user": "newuser", "wp_app_password": "new-pw",
    }
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    assert r.json()["success"] is False

    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    restored = data.get("wordpress_profiles", {}).get("wp_기존사이트", {})
    assert restored.get("url") == "http://original.example.com"
    assert restored.get("username") == "originaluser"
    assert restored.get("app_password") == "original-pw"


def test_reverse_failure_order_is_structurally_impossible(monkeypatch, tmp_path):
    """P2-05에서 확인된 대로, create_site()는 secrets 저장을 항상 DB 저장보다
    먼저 시도하고, secrets 저장이 실패하면 즉시 반환한다 — 따라서 "DB 성공 →
    secrets 실패" 순서는 구조적으로 발생할 수 없다. save_wp_profile()을 실패
    시키고 DB save()가 호출되지 않았음을 실제로 증명한다."""
    _mock_isolated(monkeypatch, tmp_path)

    from repositories.site_repository import SiteRepository

    save_called = {"n": 0}
    original_save = SiteRepository.save

    def _spy_save(self, row):
        save_called["n"] += 1
        return original_save(self, row)

    def _boom_wp_profile(self, *a, **k):
        raise RuntimeError("시뮬레이션된 secrets.yaml 저장 실패")

    monkeypatch.setattr(SiteRepository, "save", _spy_save)
    monkeypatch.setattr(SiteRepository, "save_wp_profile", _boom_wp_profile)

    payload = {
        "type_label": "사용자정의", "site_name": "실패순서테스트", "domain": "order-test.example.com",
        "wp_url": "http://wp.example.com", "wp_user": "admin", "wp_app_password": "fake-pw",
    }
    r = _client().post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN))
    assert r.json()["success"] is False
    assert save_called["n"] == 0, "secrets 저장 실패 시 DB save()가 호출되면 안 된다"


# ══════════════════════════════════════════════════════════════════════════
# 동시성 — 실제 in-process lock으로 직렬화 검증(isolated tmp DB)
# ══════════════════════════════════════════════════════════════════════════

def test_concurrent_create_same_domain_only_one_succeeds(monkeypatch, tmp_path):
    """동일 도메인으로 실제 threading을 이용해 2개 요청을 동시에 실행해도, 최종
    DB에는 정확히 1개의 row만 생성되어야 한다(TOCTOU 레이스 해결 증명)."""
    _mock_isolated(monkeypatch, tmp_path)
    client = _client()
    payload = {"type_label": "계산기", "site_name": "동시생성테스트", "domain": "concurrent-test.example.com"}

    results = []

    def _call():
        results.append(client.post("/api/sites", json=payload, headers=_auth(ADMIN_TOKEN)))

    threads = [threading.Thread(target=_call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    successes = [r for r in results if r.json()["success"] is True]
    failures = [r for r in results if r.json()["success"] is False]
    assert len(successes) == 1, f"정확히 1건만 성공해야 하는데 {len(successes)}건 성공함"
    assert len(failures) == 1
    assert failures[0].json()["error"]["code"] == "VALIDATION_ERROR"

    # 실제 DB에도 정확히 1개 row만 있는지 재확인.
    from repositories.site_repository import SiteRepository
    from adapters.db.factory import get_db_adapter
    cfg = _isolated_cfg(tmp_path)
    repo = SiteRepository(get_db_adapter(cfg), cfg)
    matching = [r for r in repo.get_all() if r.get("domain") == "concurrent-test.example.com"]
    assert len(matching) == 1


# ══════════════════════════════════════════════════════════════════════════
# Import
# ══════════════════════════════════════════════════════════════════════════

def test_import_without_auth_returns_401():
    r = _client().post("/api/sites/import", json={"rows": []})
    assert r.status_code == 401


def test_import_as_viewer_returns_403():
    r = _client().post("/api/sites/import", json={"rows": []}, headers=_auth(VIEWER_TOKEN))
    assert r.status_code == 403


def test_import_all_valid_rows_succeed(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    rows = [
        {"site_name": "임포트1", "domain": "import1.example.com", "site_type": "calculator"},
        {"site_name": "임포트2", "domain": "import2.example.com", "site_type": "calculator"},
    ]
    r = _client().post("/api/sites/import", json={"rows": rows}, headers=_auth(ADMIN_TOKEN))
    body = r.json()
    assert body["success"] is True
    assert body["data"] == {"total": 2, "success": 2, "failed": 0, "errors": []}


def test_import_mixed_success_and_failure(monkeypatch, tmp_path):
    """row 1 성공, row 2 실패(중복 도메인), row 3 성공 — 부분 실패가 전체를
    중단시키지 않는 원본 동작을 그대로 재현."""
    _mock_isolated(monkeypatch, tmp_path)
    rows = [
        {"site_name": "성공1", "domain": "mixed1.example.com", "site_type": "calculator"},
        {"site_name": "성공1", "domain": "mixed-dup.example.com", "site_type": "calculator"},  # 이름 중복
        {"site_name": "성공2", "domain": "mixed2.example.com", "site_type": "calculator"},
    ]
    r = _client().post("/api/sites/import", json={"rows": rows}, headers=_auth(ADMIN_TOKEN))
    body = r.json()["data"]
    assert body["total"] == 3
    assert body["success"] == 2
    assert body["failed"] == 1
    assert len(body["errors"]) == 1


def test_import_wordpress_type_always_fails_like_original(monkeypatch, tmp_path):
    """원본과 동일하게 Import는 wp_user/wp_app_password를 항상 빈 문자열로
    보내므로, needs_wp=True 유형은 항상 실패해야 한다(알려진 제약, 수정 대상 아님)."""
    _mock_isolated(monkeypatch, tmp_path)
    rows = [{"site_name": "WP임포트", "domain": "wpimport.example.com",
              "site_type": "custom", "wordpress_url": "http://wp.example.com"}]
    r = _client().post("/api/sites/import", json={"rows": rows}, headers=_auth(ADMIN_TOKEN))
    body = r.json()["data"]
    assert body["success"] == 0
    assert body["failed"] == 1
    assert "WordPress" in body["errors"][0]


def test_import_empty_rows_returns_zero_totals(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/import", json={"rows": []}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"] == {"total": 0, "success": 0, "failed": 0, "errors": []}


def test_import_malformed_row_missing_fields_counted_as_failure(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    rows = [{}]  # site_name/domain 전부 없음
    r = _client().post("/api/sites/import", json={"rows": rows}, headers=_auth(ADMIN_TOKEN))
    body = r.json()["data"]
    assert body["success"] == 0
    assert body["failed"] == 1


def test_import_extra_field_in_request_returns_422(monkeypatch, tmp_path):
    _mock_isolated(monkeypatch, tmp_path)
    r = _client().post("/api/sites/import", json={"rows": [], "unexpected": "x"}, headers=_auth(ADMIN_TOKEN))
    assert r.status_code == 422


def test_import_never_reads_secret_fields_from_row(monkeypatch, tmp_path):
    """Import row에 wordpress_username/wordpress_app_password가 포함되어 있어도
    site_service.import_sites()는 이를 읽지 않는다(원본과 동일 — 항상 빈 문자열
    고정)."""
    cfg = _mock_isolated(monkeypatch, tmp_path)
    rows = [{
        "site_name": "계산기임포트시크릿", "domain": "calcimport-secret.example.com",
        "site_type": "calculator",
        "wordpress_username": "should-not-be-used", "wordpress_app_password": "should-not-be-used-either",
    }]
    r = _client().post("/api/sites/import", json={"rows": rows}, headers=_auth(ADMIN_TOKEN))
    assert r.json()["data"]["success"] == 1
    # calculator 유형은 needs_wp=False라 애초에 secrets.yaml을 건드리지 않는다.
    secrets_path = Path(cfg["_root"]) / "config" / "secrets.yaml"
    if secrets_path.exists():
        content = secrets_path.read_text(encoding="utf-8")
        assert "should-not-be-used" not in content


# ══════════════════════════════════════════════════════════════════════════
# 구조 검증 — lock 재사용 확인(전역 Scheduler lock을 재사용하지 않음)
# ══════════════════════════════════════════════════════════════════════════

def test_service_uses_its_own_lock_not_scheduler_lock():
    import inspect
    from api.services import site_service
    source = inspect.getsource(site_service)
    assert "threading.Lock" in source
    assert "modules.scheduler" not in source
    assert "_acquire_lock" not in source  # Scheduler의 파일 lock 함수를 재사용하지 않음


def test_only_expected_write_routes_exist_under_sites():
    """STEP P2-07에서 PUT /api/sites/{site_id}와 POST 2개(Override 저장/초기화)가,
    STEP P2-08에서 POST 4개(Activate/Deactivate/Archive/Restore)가, STEP
    P2-09에서 DELETE 1개(Hard Delete)와 POST 1개(Clone)가 require_admin()
    뒤에서 정당하게 추가되었다."""
    from _route_utils import write_routes
    from api.main import app
    assert set(write_routes(app, prefix="/api/sites")) == {
        ("/api/sites", "POST"),
        ("/api/sites/import", "POST"),
        # SITE-PAGE-DEPLOYMENT-02: 사이트 공통 페이지 미리보기/로컬 저장/배포(require_admin)
        ("/api/sites/pages/preview", "POST"),
        ("/api/sites/pages/save", "POST"),
        ("/api/sites/pages/deploy", "POST"),
        ("/api/sites/rebuild", "POST"),  # GAP-03 전체 정적 사이트 재빌드(require_admin)
        ("/api/sites/{site_id}", "PUT"),
        ("/api/sites/{site_id}/override", "POST"),
        ("/api/sites/{site_id}/override/reset", "POST"),
        ("/api/sites/{site_id}/activate", "POST"),
        ("/api/sites/{site_id}/deactivate", "POST"),
        ("/api/sites/{site_id}/archive", "POST"),
        ("/api/sites/{site_id}/restore", "POST"),
        ("/api/sites/{site_id}", "DELETE"),
        ("/api/sites/{site_id}/clone", "POST"),
    }
