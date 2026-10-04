"""tests/conftest.py — pytest 설정 및 캐시 정리"""
import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 테스트 로그가 운영 로그(data/logs/pipeline.log)에 섞이지 않도록, 테스트 프로세스에서만
# modules.logger.get_logger()가 붙이는 운영 FileHandler를 떼어낸다(콘솔/caplog 출력은
# pytest가 그대로 캡처). 다른 모듈이 get_logger를 import하기 전에 적용되어야 하므로
# conftest import 시점에 설치하고, pytest_unconfigure에서 원래 함수로 되돌린다.
import modules.logger as _modules_logger

_PROD_LOG_FILE = (_modules_logger.BASE / "logs" / "pipeline.log").resolve()
_original_get_logger = _modules_logger.get_logger


def _detach_prod_log_handlers(logger):
    for handler in list(logger.handlers):
        if (isinstance(handler, logging.FileHandler)
                and Path(handler.baseFilename).resolve() == _PROD_LOG_FILE):
            logger.removeHandler(handler)
            handler.close()


def _test_isolated_get_logger(name: str = "pipeline"):
    logger = _original_get_logger(name)
    _detach_prod_log_handlers(logger)
    return logger


for _existing in list(logging.Logger.manager.loggerDict.values()):
    if isinstance(_existing, logging.Logger):
        _detach_prod_log_handlers(_existing)
_modules_logger.get_logger = _test_isolated_get_logger


def _clear_law_ssot():
    """law_ssot 캐시 초기화."""
    try:
        from modules.law_ssot import clear_ssot_cache
        clear_ssot_cache()
    except Exception:
        pass


# conftest import 시점 (테스트 수집 이전)
_clear_law_ssot()


def pytest_runtest_setup(item):
    """각 테스트 실행 전 law_ssot 캐시 초기화 (collection 이후, 테스트 실행 직전)."""
    _clear_law_ssot()


def pytest_sessionstart(session):
    """테스트 세션 시작 시 추가 캐시 초기화 + 운영 상태 fingerprint 기록."""
    _clear_law_ssot()
    _assert_test_root_isolation()
    session.config._calcmate_prod_fingerprint = _production_fingerprint()


def _assert_test_root_isolation():
    """CALCMATE-TEST-ISOLATION-FIX-01: 운영 config를 거친 _root가 이 테스트 프로젝트 root인지
    세션 시작 시 확인한다. 아니면(복사본/worktree에서 실제 저장소를 가리키는 상태) 즉시 중단."""
    if _config_loader.merge_secrets is not _test_root_merge_secrets:
        pytest.exit("CALCMATE: _root 격리(merge_secrets wrapper)가 설치되지 않았습니다.", returncode=3)
    if _CONFIGURED_ROOT is None:
        return
    effective = _resolve(_config_loader.merge_secrets({"_root": str(_CONFIGURED_ROOT)},
                                                      str(_PROD_CONFIG_FILE)).get("_root"))
    if effective != _REPO_ROOT:
        pytest.exit(f"CALCMATE: 테스트 cfg의 _root가 테스트 프로젝트 root가 아닙니다 "
                    f"({effective} != {_REPO_ROOT}) — 실제 저장소 접근 위험으로 중단합니다.", returncode=3)


def pytest_sessionfinish(session, exitstatus):
    """세션 종료 시 운영 상태 fingerprint를 다시 계산해, 달라졌으면 세션을 실패로
    만든다(누수를 숨기지 않고 즉시 드러낸다). 테스트와 동시에 돌고 있는 운영
    프로세스(FastAPI worker, 블로그배포 등)가 같은 파일을 바꿨을 수도 있으므로
    변경 항목을 그대로 출력한다."""
    before = getattr(session.config, "_calcmate_prod_fingerprint", None)
    if before is None:
        return
    after = _production_fingerprint()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        session.config._calcmate_prod_changed = changed
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    changed = getattr(terminalreporter.config, "_calcmate_prod_changed", None)
    if changed:
        terminalreporter.section("CALCMATE PRODUCTION STATE CHANGED", sep="!", red=True, bold=True)
        for key in changed:
            terminalreporter.write_line(f"changed: {key}")


# ══════════════════════════════════════════════════════════════════════════
# 운영 환경 격리 (CALCMATE-TELEGRAM-ISOLATION-FIX-01)
# ══════════════════════════════════════════════════════════════════════════
# 개발 PC에는 CALCMATE_DASHBOARD_LOCAL_MODE가 Windows 사용자 환경변수로 상시
# 설정되어 있어, 401/403을 기대하는 테스트가 인증을 건너뛰고 실제 서비스(운영
# SQLite/Google Sheets/WP/Telegram/AI)까지 도달할 수 있었다(2026-10-03 sites row
# 누수 사고). 아래 autouse fixture가 모든 테스트에서 운영 접근을 막는다. 막힌
# 접근은 조용히 우회시키지 않고 ProductionAccessBlocked로 실패시킨다.
import builtins
import hashlib
import io
import ipaddress
import os
import socket
import sqlite3
from urllib.parse import unquote, urlparse

_DATA_DIR = (_REPO_ROOT / "data").resolve()
# 운영 config 디렉터리 전체(config.yaml/secrets.yaml 및 그 .tmp 원자적 쓰기 파일 포함)를
# 쓰기 금지 대상으로 본다 — tmp_path 기반 테스트 config는 이 디렉터리 밖이다.
_PROD_CONFIG_DIR = (_REPO_ROOT / "config").resolve()
_FINGERPRINT_FILES = (
    "data/blog_auto.db", "data/cache/dashboard_cache.db", "data/workspace/calculators.db",
    "data/calcmate.db", "data/calculators.db", "config/config.yaml", "config/secrets.yaml",
    "data/logs/budget.json",          # CALCMATE-TEST-ISOLATION-FIX-01
)
_FINGERPRINT_DIRS = ("data/workspace/_site", "docs/registry",
                     "data/outputs")  # CALCMATE-TEST-ISOLATION-FIX-01
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
_SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")

_real_sqlite_connect = sqlite3.connect
_real_socket_connect = socket.socket.connect
_real_socket_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo
_real_open = builtins.open
_real_io_open = io.open
_real_os_replace = os.replace
_real_os_rename = os.rename

# 현재 테스트에서 차단된 운영 접근 기록. 앱 코드가 예외를 삼켜도(예: DualAdapter의
# SQLite fallback) teardown에서 테스트를 실패시켜 누수 시도를 드러낸다.
BLOCKED_ATTEMPTS: list = []


class ProductionAccessBlocked(RuntimeError):
    """테스트가 운영 리소스(운영 DB/Sheets/외부 네트워크/운영 config)에 접근하려 함."""

    def __init__(self, message: str):
        super().__init__(message)
        BLOCKED_ATTEMPTS.append(message)


def _file_digest(path: Path) -> str:
    if not path.exists():
        return "absent"
    h = hashlib.sha256()
    with _real_open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_digest(path: Path) -> str:
    if not path.exists():
        return "absent"
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(path)}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
    return h.hexdigest()


def _production_fingerprint() -> dict:
    fp = {rel: _file_digest(_REPO_ROOT / rel) for rel in _FINGERPRINT_FILES}
    fp.update({rel + "/": _dir_digest(_REPO_ROOT / rel) for rel in _FINGERPRINT_DIRS})
    return fp


def _resolve(path_like) -> Path | None:
    try:
        return Path(os.fspath(path_like)).resolve()
    except (TypeError, ValueError, OSError):
        return None


# ── CALCMATE-TEST-ISOLATION-FIX-01 (TEST-FIX-02): config의 절대 _root 격리 ─────────────
# config/config.yaml의 _root는 실제 저장소 절대경로다. 복사본/worktree에서 테스트하면
# load_config()가 그 값을 그대로 돌려줘 dashboard_cache·SQLiteAdapter·Sheets adapter 등
# _root 기반 경로가 전부 실제 저장소를 가리켰다. load_config()는 여러 모듈이 이름으로
# import하므로 함수 자체 대신, load_config()가 호출 시점에 전역으로 찾는 merge_secrets()를
# 감싼다 — 운영 config 파일(이 테스트 프로젝트의 config/config.yaml)에서 읽은 _root만
# 테스트 프로젝트 root로 바꾸고, 다른 경로의 config나 직접 만든 cfg dict는 건드리지 않는다.
import modules.config_loader as _config_loader

_PROD_CONFIG_FILE = (_PROD_CONFIG_DIR / "config.yaml").resolve()
_original_merge_secrets = _config_loader.merge_secrets


def _read_configured_root() -> Path | None:
    """운영 config.yaml에 적힌 _root 원본값(읽기 전용)."""
    try:
        import yaml
        with _real_open(_PROD_CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return _resolve(raw["_root"]) if raw.get("_root") else None
    except Exception:
        return None


_CONFIGURED_ROOT = _read_configured_root()
# 복사본 실행이면 config가 가리키는 다른 저장소의 data/도 운영 데이터로 보고 SQLite 쓰기를 막는다.
_PROD_DATA_DIRS = tuple({_DATA_DIR} | ({(_CONFIGURED_ROOT / "data").resolve()} if _CONFIGURED_ROOT else set()))


def _test_root_merge_secrets(cfg, config_path=None):
    merged = _original_merge_secrets(cfg, config_path)
    target = _resolve(config_path) if config_path else _PROD_CONFIG_FILE
    if target == _PROD_CONFIG_FILE and isinstance(merged, dict) and merged.get("_root"):
        if _resolve(merged["_root"]) != _REPO_ROOT:
            merged["_root"] = str(_REPO_ROOT)
    return merged


_config_loader.merge_secrets = _test_root_merge_secrets


def _is_production_sqlite(path: Path) -> bool:
    return path.suffix.lower() in _SQLITE_SUFFIXES and any(
        path == d or d in path.parents for d in _PROD_DATA_DIRS)


# ── CALCMATE-TEST-ISOLATION-FIX-01 (TEST-FIX-01): BudgetTracker 저장 위치 격리 ──────────
# BudgetTracker는 modules.logger.BASE/logs/budget.json에 고정 저장한다. logger.BASE 전체를
# 바꾸면 pipeline.log 등 다른 경로까지 바뀌므로, 운영 budget.json을 가리키는 인스턴스의
# _save()만 테스트별 임시 파일로 돌린다. record()의 계산/집계/반환과 _save() 자체는 그대로
# 실행된다. 같은 테스트 안에서 기록 후 다시 읽는 경우를 위해, 임시 파일이 생긴 뒤의
# _load()는 임시 파일을 읽는다(그 전에는 운영 파일을 읽기만 한다).
_PROD_BUDGET_FILE = (_modules_logger.BASE / "logs" / "budget.json").resolve()
_real_budget_save = _modules_logger.BudgetTracker._save
_real_budget_load = _modules_logger.BudgetTracker._load
_ISOLATED = {"budget": None, "outputs": None}


def _isolated_budget_save(self):
    iso = _ISOLATED["budget"]
    if iso is not None and _resolve(self.path) == _PROD_BUDGET_FILE:
        original = self.path
        iso.parent.mkdir(parents=True, exist_ok=True)
        self.path = iso
        try:
            return _real_budget_save(self)
        finally:
            self.path = original
    return _real_budget_save(self)


def _isolated_budget_load(self):
    iso = _ISOLATED["budget"]
    if iso is not None and iso.exists() and _resolve(self.path) == _PROD_BUDGET_FILE:
        original = self.path
        self.path = iso
        try:
            return _real_budget_load(self)
        finally:
            self.path = original
    return _real_budget_load(self)


def _guarded_sqlite_connect(database, *args, **kwargs):
    uri = kwargs.get("uri", False)
    target, read_only = database, False
    if isinstance(database, str) and uri and database.startswith("file:"):
        parsed = urlparse(database)
        target = unquote(parsed.path or database[len("file:"):].split("?", 1)[0])
        read_only = "mode=ro" in (parsed.query or "")
    if isinstance(target, (str, os.PathLike)) and str(target) not in ("", ":memory:"):
        resolved = _resolve(target)
        if resolved is not None and _is_production_sqlite(resolved) and not read_only:
            raise ProductionAccessBlocked(
                f"운영 SQLite 쓰기 연결 차단: {resolved} (테스트는 tmp_path 또는 mode=ro만 허용)")
    return _real_sqlite_connect(database, *args, **kwargs)


def _host_is_loopback(host) -> bool:
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _check_address(address):
    if isinstance(address, (str, bytes)):  # AF_UNIX
        return
    if isinstance(address, tuple) and address and not _host_is_loopback(address[0]):
        raise ProductionAccessBlocked(f"외부 네트워크 연결 차단: {address[0]}:{address[1] if len(address) > 1 else ''}")


def _guarded_socket_connect(self, address):
    _check_address(address)
    return _real_socket_connect(self, address)


def _guarded_socket_connect_ex(self, address):
    _check_address(address)
    return _real_socket_connect_ex(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    _check_address(address)
    return _real_create_connection(address, *args, **kwargs)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _host_is_loopback(host):
        raise ProductionAccessBlocked(f"외부 호스트 이름 조회 차단: {host}")
    return _real_getaddrinfo(host, *args, **kwargs)


def _is_production_config(path_like) -> bool:
    resolved = _resolve(path_like)
    return resolved is not None and _PROD_CONFIG_DIR in resolved.parents


def _guarded_open(file, mode="r", *args, **kwargs):
    if isinstance(file, (str, bytes, os.PathLike)) and any(c in str(mode) for c in "wax+") \
            and _is_production_config(file):
        raise ProductionAccessBlocked(f"운영 config 쓰기 차단: {file}")
    return _real_io_open(file, mode, *args, **kwargs)


def _guarded_os_replace(src, dst, *args, **kwargs):
    if _is_production_config(dst):
        raise ProductionAccessBlocked(f"운영 config 교체 차단: {dst}")
    return _real_os_replace(src, dst, *args, **kwargs)


def _guarded_os_rename(src, dst, *args, **kwargs):
    if _is_production_config(dst):
        raise ProductionAccessBlocked(f"운영 config 교체 차단: {dst}")
    return _real_os_rename(src, dst, *args, **kwargs)


def _blocked(what):
    def _raise(*_a, **_k):
        raise ProductionAccessBlocked(f"{what} 차단(테스트에서 실제 Google Sheets 사용 금지)")
    return _raise


# 테스트 중 시도된 Telegram 전송 기록(실제 전송 없음). 토큰/Chat ID 값은 저장하지 않는다.
TELEGRAM_ATTEMPTS: list = []


def _recording_send_telegram(cfg, message):
    TELEGRAM_ATTEMPTS.append({"message": message,
                              "has_token": bool((cfg or {}).get("TELEGRAM_BOT_TOKEN")),
                              "has_chat_id": bool((cfg or {}).get("TELEGRAM_CHAT_ID"))})


# HARDEN-01: api.main의 Host guard는 127.0.0.1:8000 / localhost:8000만 허용한다.
# TestClient 기본 base_url(http://testserver)을 운영과 같은 http://127.0.0.1:8000으로
# 바꿔 기존 API 테스트가 실제 allowlist를 그대로 통과하게 한다(allowlist에 테스트용
# Host를 추가하지 않는다). base_url을 명시한 테스트는 그 값을 그대로 쓴다.
_TESTCLIENT_ORIG_INIT = None


def _local_testclient_init(self, app, base_url="http://127.0.0.1:8000", *args, **kwargs):
    _TESTCLIENT_ORIG_INIT(self, app, base_url, *args, **kwargs)


@pytest.fixture(autouse=True)
def _block_production_access(monkeypatch, tmp_path_factory):
    """모든 테스트에 적용되는 운영 접근 차단. LOCAL_MODE를 검증하는 테스트는 테스트
    안에서 monkeypatch.setenv로 다시 켤 수 있다(이 fixture가 먼저 실행된다)."""
    # 0. CALCMATE-TEST-ISOLATION-FIX-01: 테스트별 임시 디렉터리(테스트 자신의 tmp_path와 분리).
    #    budget.json 기록과 발행 미리보기(publisher.OUTPUT_DIR)를 이 아래로 돌린다.
    iso_dir = tmp_path_factory.mktemp("calcmate_isolation")
    _ISOLATED["budget"] = iso_dir / "budget.json"
    _ISOLATED["outputs"] = iso_dir / "outputs"
    monkeypatch.setattr(_modules_logger.BudgetTracker, "_save", _isolated_budget_save)
    monkeypatch.setattr(_modules_logger.BudgetTracker, "_load", _isolated_budget_load)
    import modules.publisher as publisher
    monkeypatch.setattr(publisher, "OUTPUT_DIR", _ISOLATED["outputs"])
    # A. 로컬 무인증 모드 해제 — get_current_user()가 요청마다 읽으므로 즉시 적용된다.
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)
    # B. 운영 SQLite 쓰기 연결 차단
    monkeypatch.setattr(sqlite3, "connect", _guarded_sqlite_connect)
    # C. Google Sheets 연결 차단
    import gspread
    import adapters.db.sheets_adapter as sheets_adapter
    monkeypatch.setattr(sheets_adapter.SheetsAdapter, "_connect", _blocked("SheetsAdapter._connect"))
    for name in ("authorize", "service_account", "service_account_from_dict", "oauth"):
        if hasattr(gspread, name):
            monkeypatch.setattr(gspread, name, _blocked(f"gspread.{name}"))
    # D. 외부 네트워크 차단(loopback만 허용 — TestClient는 소켓을 쓰지 않는다)
    monkeypatch.setattr(socket.socket, "connect", _guarded_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_socket_connect_ex)
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
    # E. Telegram — 실제 전송 대신 기록만(모든 telegram_notifier.send* 가 이 함수를 거친다)
    import modules.telegram_notifier as telegram_notifier
    TELEGRAM_ATTEMPTS.clear()
    monkeypatch.setattr(telegram_notifier, "_send_telegram", _recording_send_telegram)
    # F. 운영 config.yaml / secrets.yaml 쓰기 차단(tmp_path config는 허용).
    #    pathlib.Path.open/write_text는 io.open을 쓰므로 둘 다 막는다.
    monkeypatch.setattr(builtins, "open", _guarded_open)
    monkeypatch.setattr(io, "open", _guarded_open)
    monkeypatch.setattr(os, "replace", _guarded_os_replace)
    monkeypatch.setattr(os, "rename", _guarded_os_rename)
    # G. HARDEN-01: TestClient 기본 Host를 127.0.0.1:8000으로(위 _local_testclient_init 참고)
    global _TESTCLIENT_ORIG_INIT
    from starlette.testclient import TestClient as _StarletteTestClient
    if _TESTCLIENT_ORIG_INIT is None:
        _TESTCLIENT_ORIG_INIT = _StarletteTestClient.__init__
    monkeypatch.setattr(_StarletteTestClient, "__init__", _local_testclient_init)
    BLOCKED_ATTEMPTS.clear()
    yield
    _ISOLATED["budget"] = None
    _ISOLATED["outputs"] = None
    attempts = list(BLOCKED_ATTEMPTS)
    BLOCKED_ATTEMPTS.clear()
    if attempts:
        pytest.fail("운영 접근 시도가 차단되었습니다(테스트 격리 누락):\n- " + "\n- ".join(attempts[:10]),
                    pytrace=False)


def pytest_configure(config):
    """테스트 설정 단계에서 캐시 초기화 (fallback)."""
    _clear_law_ssot()


def pytest_unconfigure(config):
    """테스트 종료 시 운영 로그 격리용 get_logger 대체와 _root 격리용 merge_secrets 대체를
    원래 함수로 되돌린다."""
    _modules_logger.get_logger = _original_get_logger
    _config_loader.merge_secrets = _original_merge_secrets


@pytest.fixture(scope="session", autouse=True)
def _clear_law_ssot_cache_session():
    """세션 종료 시 캐시 정리."""
    yield
    try:
        from modules.law_ssot import clear_ssot_cache
        clear_ssot_cache()
    except Exception:
        pass