"""tests/test_config_wp_target.py — CALCMATE-WP-ENDPOINT-FIX-IMPLEMENT-01

load_config(wp_target=...) / _apply_wp_target() / worker_manager._build_worker_cfg()
검증. 실제 config/secrets 파일은 읽지 않고 tmp_path에 만든 가짜 config만 사용한다.
네트워크 호출 없음(requests/socket 차단 fixture 사용).
"""
import inspect
from urllib.parse import urlparse

import pytest
import yaml

import modules.config_loader as config_loader
from modules.config_loader import ConfigError, load_config

LOCAL_URL = "http://local-wp.test"
LOCAL_USER = "local-user"
LOCAL_PW = "LOCAL-PW-should-not-leak"
PROD_URL = "https://prod-wp.invalid"
PROD_USER = "prod-user"
PROD_PW = "PROD-PW-should-not-leak"
API_KEY = "sk-FAKE-API-KEY-should-not-leak"

MODELS = {k: "fake-model" for k in config_loader.REQUIRED_MODELS}


def _write_cfg(tmp_path, wordpress=..., extra_secrets=None):
    cfg = {
        **MODELS,
        "WORDPRESS_URL": LOCAL_URL,
        "WORDPRESS_USERNAME": LOCAL_USER,
        "WRITER_PROVIDER": "openai",
        "BLOG_SCHEDULE": {"enabled": False, "mode": "draft"},
    }
    secrets = {"WORDPRESS_APP_PASSWORD": LOCAL_PW, "OPENAI_API_KEY": API_KEY}
    if wordpress is ...:
        wordpress = {"url": PROD_URL, "username": PROD_USER, "app_password": PROD_PW}
    if wordpress is not None:
        secrets["wordpress"] = wordpress
    secrets.update(extra_secrets or {})
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (tmp_path / "secrets.yaml").write_text(yaml.safe_dump(secrets, allow_unicode=True), encoding="utf-8")
    return str(tmp_path / "config.yaml")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import requests
    import socket

    def _boom(*a, **kw):
        raise AssertionError("네트워크 호출 발생")

    for m in ("get", "post", "put", "patch", "delete", "request"):
        monkeypatch.setattr(requests, m, _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


def _assert_local(cfg):
    assert cfg["WORDPRESS_URL"] == LOCAL_URL
    assert cfg["WORDPRESS_USERNAME"] == LOCAL_USER
    assert cfg["WORDPRESS_APP_PASSWORD"] == LOCAL_PW
    assert "_wp_target" not in cfg


# ── Test 1/2: local 기본 동작 유지 ─────────────────────────────────────────

def test_1_load_config_default_is_local_even_if_env_says_production(tmp_path, monkeypatch):
    monkeypatch.setenv("CALCMATE_WP_TARGET", "production")
    _assert_local(load_config(_write_cfg(tmp_path)))


def test_1b_config_loader_source_does_not_read_wp_target_env():
    src = inspect.getsource(config_loader)
    assert "CALCMATE_WP_TARGET" not in src


def test_2_explicit_local_keeps_local(tmp_path):
    _assert_local(load_config(_write_cfg(tmp_path), wp_target="local"))


# ── Test 3: production = nested 세트 3개 동시 적용 ──────────────────────────

def test_3_production_applies_full_credential_set(tmp_path):
    path = _write_cfg(tmp_path, extra_secrets={"WORDPRESS_PASSWORD": "LEGACY-PW"})
    cfg = load_config(path, wp_target="production")
    assert cfg["WORDPRESS_URL"] == PROD_URL
    assert cfg["WORDPRESS_USERNAME"] == PROD_USER
    assert cfg["WORDPRESS_APP_PASSWORD"] == PROD_PW
    assert "WORDPRESS_PASSWORD" not in cfg
    assert cfg["_wp_target"] == "production"
    # production URL + local credential 조합이 없는지
    assert LOCAL_PW not in (cfg["WORDPRESS_APP_PASSWORD"], cfg.get("WORDPRESS_PASSWORD"))
    assert cfg["WORDPRESS_USERNAME"] != LOCAL_USER


def test_3b_publisher_and_dup_check_resolve_same_production_set(tmp_path):
    """publisher._wp_auth()(flat 우선)와 _check_wp_duplicate가 읽는 flat 키가
    모두 production 세트인지 — 실제 호출 없이 인증 튜플만 확인."""
    import modules.publisher as publisher
    cfg = load_config(_write_cfg(tmp_path), wp_target="production")
    assert publisher._wp_auth(cfg) == (PROD_USER, PROD_PW)


# ── Test 4~7: 불완전한 production 세트 → ConfigError ─────────────────────────

@pytest.mark.parametrize("missing", ["url", "username", "app_password"])
def test_4_5_6_production_missing_field_raises(tmp_path, missing):
    wp = {"url": PROD_URL, "username": PROD_USER, "app_password": PROD_PW}
    wp[missing] = ""
    with pytest.raises(ConfigError) as ei:
        load_config(_write_cfg(tmp_path, wordpress=wp), wp_target="production")
    assert missing in str(ei.value)


@pytest.mark.parametrize("missing", ["url", "username", "app_password"])
def test_4_5_6b_production_absent_key_raises(tmp_path, missing):
    wp = {"url": PROD_URL, "username": PROD_USER, "app_password": PROD_PW}
    del wp[missing]
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, wordpress=wp), wp_target="production")


def test_7_production_without_wordpress_section_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, wordpress=None), wp_target="production")


# ── Test 8: 허용되지 않는 target → ConfigError(fallback 없음) ────────────────

@pytest.mark.parametrize("target", ["prod", "staging", "test", "foo", "Production", ""])
def test_8_unknown_target_raises(tmp_path, target):
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path), wp_target=target)


# ── Test 9: 예외 메시지에 secret 값 없음 ─────────────────────────────────────

def test_9_error_messages_do_not_leak_secrets(tmp_path):
    msgs = []
    for wp in ({"url": PROD_URL, "username": PROD_USER, "app_password": ""},
               {"url": "", "username": PROD_USER, "app_password": PROD_PW},
               {"url": PROD_URL, "username": "", "app_password": PROD_PW}):
        with pytest.raises(ConfigError) as ei:
            load_config(_write_cfg(tmp_path, wordpress=wp), wp_target="production")
        msgs.append(str(ei.value))
    with pytest.raises(ConfigError) as ei:
        load_config(_write_cfg(tmp_path), wp_target="prod")
    msgs.append(str(ei.value))
    for m in msgs:
        for secret in (PROD_PW, LOCAL_PW, API_KEY, PROD_URL, PROD_USER, LOCAL_USER, "prod-wp.invalid"):
            assert secret not in m


# ── Test 10: Worker cfg = 전체 runtime cfg ────────────────────────────────────

@pytest.fixture
def worker_cfg_loader(tmp_path, monkeypatch):
    """_build_worker_cfg()가 호출하는 load_config를 tmp config 경로로 고정한다
    (wp_target 인자는 그대로 전달 — worker가 넘긴 값을 검증하기 위함)."""
    path = _write_cfg(tmp_path)
    real = config_loader.load_config
    calls = []

    def _fake(p=None, *, wp_target=None):
        calls.append(wp_target)
        return real(path, wp_target=wp_target)

    monkeypatch.setattr(config_loader, "load_config", _fake)
    return calls


def _assert_full_worker_cfg(cfg):
    for k in ("BLOG_SCHEDULE", "WORDPRESS_URL", "WORDPRESS_USERNAME",
              "WORDPRESS_APP_PASSWORD", "_root", "scheduler_line", "WRITER_PROVIDER"):
        assert k in cfg and cfg[k] not in (None, ""), k
    assert all(cfg.get(m) for m in config_loader.REQUIRED_MODELS)
    assert cfg["scheduler_line"] == "blog"
    assert isinstance(cfg["BLOG_SCHEDULE"], dict)   # 중첩 구조 유지(안쪽 dict만 넘기던 이전 버그 방지)
    assert cfg.get("OPENAI_API_KEY")                 # secrets 병합됨(값은 출력하지 않음)


def test_10_worker_cfg_default_local_is_full_runtime_cfg(worker_cfg_loader, monkeypatch):
    from api.services.worker_manager import _build_worker_cfg
    monkeypatch.delenv("CALCMATE_WP_TARGET", raising=False)
    cfg = _build_worker_cfg()
    _assert_full_worker_cfg(cfg)
    assert worker_cfg_loader == ["local"]
    assert urlparse(cfg["WORDPRESS_URL"]).hostname == "local-wp.test"


def test_10b_worker_cfg_production_uses_production_set(worker_cfg_loader, monkeypatch):
    from api.services.worker_manager import _build_worker_cfg
    monkeypatch.setenv("CALCMATE_WP_TARGET", "production")
    cfg = _build_worker_cfg()
    _assert_full_worker_cfg(cfg)
    assert worker_cfg_loader == ["production"]
    assert urlparse(cfg["WORDPRESS_URL"]).hostname == "prod-wp.invalid"
    assert cfg["WORDPRESS_USERNAME"] == PROD_USER
    assert cfg["WORDPRESS_APP_PASSWORD"] == PROD_PW


def test_10c_worker_cfg_unknown_env_target_fails_closed(worker_cfg_loader, monkeypatch):
    from api.services.worker_manager import _build_worker_cfg
    monkeypatch.setenv("CALCMATE_WP_TARGET", "staging")
    with pytest.raises(ConfigError):
        _build_worker_cfg()


def test_10d_worker_log_contains_hostname_only(worker_cfg_loader, monkeypatch, caplog):
    import logging
    from api.services.worker_manager import _build_worker_cfg
    monkeypatch.setenv("CALCMATE_WP_TARGET", "production")
    with caplog.at_level(logging.INFO, logger="worker"):
        _build_worker_cfg()
    text = caplog.text
    assert "prod-wp.invalid" in text
    for secret in (PROD_PW, LOCAL_PW, API_KEY, PROD_USER):
        assert secret not in text


def test_10e_worker_threads_use_build_worker_cfg_not_section_only():
    """두 worker 경로 모두 공용 helper를 쓰고, BLOG_SCHEDULE 섹션만 넘기던
    이전 코드가 남아 있지 않은지(정적 확인)."""
    import api.services.worker_manager as wm
    for fn in (wm.WorkerManager._run_blog_scheduler, wm.WorkerManager._run_oneoff_scheduler):
        src = inspect.getsource(fn)
        assert "_build_worker_cfg()" in src
        assert 'get_section("BLOG_SCHEDULE")' not in src
