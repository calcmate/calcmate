# -*- coding: utf-8 -*-
"""tests/test_live_health_check.py

STEP83: modules/calculator_3way_sync.run_live_health_check() 회귀 테스트.

STEP82에서 결정된 "B. Live 독립 검증 유지"를 구현한 신규 진입점에 대한
테스트다. 이 함수는 run_calc_webapp_once()/run_three_way_anomaly_check_safely()/
Dashboard/Scheduler 어디에도 연결되어 있지 않다 — 이 파일은 그 독립성과
함수 자체의 동작만 검증한다.

기존 compare_local_site_vs_live()/normalize_live_compare_bytes()/
classify_three_way()/compare_calculators_three_way()는 이 파일에서 전혀
수정하지 않는다. 실제 네트워크 요청은 하지 않는다 — requests.get을 항상
mock으로 대체한다. 실제 SQLite/Sheets/_site/queue/Telegram도 전혀
건드리지 않는다.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_3way_sync import (
    run_live_health_check,
    LIVE_MATCH,
    LIVE_MATCH_NORMALIZED,
    LIVE_DEPLOYED_DRIFT,
    LIVE_UNAVAILABLE,
)


class _StubRepo:
    def __init__(self, rows):
        self._rows = rows

    def get_all(self):
        return self._rows


def _mock_response(status_code=200, content=b"", url="https://calcmate.kr/x/", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.url = url
    resp.headers = headers if headers is not None else {}
    return resp


def _write_local(tmp_path: Path, slug: str, content: bytes):
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_bytes(content)


# ── A. 전체 Health Check(slugs=None) → SQLite 전체 대상 수집 ──────────

def test_a_full_health_check_collects_all_targets(tmp_path):
    rows = [{"slug": "calc-a"}, {"slug": "calc-b"}, {"slug": "calc-c"}, {"slug": "calc-d"}]
    for r in rows:
        _write_local(tmp_path, r["slug"], b"<html>same</html>")

    with patch("requests.get", return_value=_mock_response(200, b"<html>same</html>")):
        result = run_live_health_check({}, slugs=None, site_dir=tmp_path,
                                        sqlite_repo=_StubRepo(rows))

    assert result["status"] == "ok"
    assert len(result["results"]) == 4
    assert {r["slug"] for r in result["results"]} == {"calc-a", "calc-b", "calc-c", "calc-d"}
    assert result["counts"].get(LIVE_MATCH) == 4


# ── B. 특정 slug만 검사 ────────────────────────────────────────────────

def test_b_specific_slug_only(tmp_path):
    _write_local(tmp_path, "annual-leave-remaining", b"<html>x</html>")
    _write_local(tmp_path, "other-calc", b"<html>y</html>")

    with patch("requests.get", return_value=_mock_response(200, b"<html>x</html>")):
        result = run_live_health_check({}, slugs=["annual-leave-remaining"], site_dir=tmp_path)

    assert len(result["results"]) == 1
    assert result["results"][0]["slug"] == "annual-leave-remaining"


# ── C. MATCH_NORMALIZED(CRLF vs LF) ───────────────────────────────────

def test_c_match_normalized(tmp_path):
    _write_local(tmp_path, "calc-c", b"<html>\r\n<body>x</body>\r\n</html>")

    with patch("requests.get", return_value=_mock_response(200, b"<html>\n<body>x</body>\n</html>")):
        result = run_live_health_check({}, slugs=["calc-c"], site_dir=tmp_path)

    assert result["results"][0]["status"] == LIVE_MATCH_NORMALIZED
    assert result["counts"].get(LIVE_MATCH_NORMALIZED) == 1


# ── D. 실제 DRIFT ──────────────────────────────────────────────────────

def test_d_deployed_live_drift(tmp_path):
    _write_local(tmp_path, "calc-d", b"<html>\r\n<body>local version</body>\r\n</html>")

    with patch("requests.get", return_value=_mock_response(200, b"<html>\n<body>DIFFERENT</body>\n</html>")):
        result = run_live_health_check({}, slugs=["calc-d"], site_dir=tmp_path)

    assert result["results"][0]["status"] == LIVE_DEPLOYED_DRIFT
    assert result["counts"].get(LIVE_DEPLOYED_DRIFT) == 1


# ── E. LIVE_UNAVAILABLE(HTTP 실패) ────────────────────────────────────

def test_e_live_unavailable_on_http_failure(tmp_path):
    _write_local(tmp_path, "calc-e", b"<html>x</html>")

    with patch("requests.get", return_value=_mock_response(500, b"err")):
        result = run_live_health_check({}, slugs=["calc-e"], site_dir=tmp_path)

    assert result["results"][0]["status"] == LIVE_UNAVAILABLE
    assert result["results"][0]["error_type"] == "http_5xx"
    assert result["counts"].get(LIVE_UNAVAILABLE) == 1


# ── F. 개별 실패 격리 ──────────────────────────────────────────────────

def test_f_individual_failure_does_not_stop_batch(tmp_path):
    _write_local(tmp_path, "calc-match", b"<html>same</html>")
    _write_local(tmp_path, "calc-fail", b"<html>x</html>")
    _write_local(tmp_path, "calc-match2", b"<html>same2</html>")

    def _side_effect(url, timeout=10.0, allow_redirects=True):
        if "calc-fail" in url:
            raise ConnectionError("network down")
        if "calc-match2" in url:
            return _mock_response(200, b"<html>same2</html>", url)
        return _mock_response(200, b"<html>same</html>", url)

    with patch("requests.get", side_effect=_side_effect):
        result = run_live_health_check(
            {}, slugs=["calc-match", "calc-fail", "calc-match2"], site_dir=tmp_path)

    assert result["status"] == "ok"
    by_slug = {r["slug"]: r["status"] for r in result["results"]}
    assert by_slug["calc-match"] == LIVE_MATCH
    assert by_slug["calc-fail"] == LIVE_UNAVAILABLE
    assert by_slug["calc-match2"] == LIVE_MATCH
    assert len(result["results"]) == 3  # 전부 수집됨, 하나 실패해도 중단되지 않음


def test_f2_unexpected_internal_exception_is_isolated_per_slug(tmp_path):
    """compare_local_site_vs_live 자체가 예기치 않게 예외를 던져도(가정: 버그)
    나머지 slug 처리는 계속되고 해당 slug만 LIVE_UNAVAILABLE로 기록된다."""
    _write_local(tmp_path, "calc-ok", b"<html>x</html>")
    _write_local(tmp_path, "calc-boom", b"<html>y</html>")

    def _side_effect(slug, local_path, timeout=10.0):
        if slug == "calc-boom":
            raise RuntimeError("simulated internal bug")
        return {"status": LIVE_MATCH, "requested_url": "u", "final_url": "u",
                "local_sha256": "a", "live_sha256": "a", "http_status": 200, "error_type": None}

    with patch("modules.calculator_3way_sync.compare_local_site_vs_live", side_effect=_side_effect):
        result = run_live_health_check({}, slugs=["calc-ok", "calc-boom"], site_dir=tmp_path)

    by_slug = {r["slug"]: r for r in result["results"]}
    assert by_slug["calc-ok"]["status"] == LIVE_MATCH
    assert by_slug["calc-boom"]["status"] == LIVE_UNAVAILABLE
    assert by_slug["calc-boom"]["error_type"] == "internal_error"
    assert result["status"] == "ok"


# ── G. no-write ────────────────────────────────────────────────────────

def test_g_no_write_anywhere(tmp_path):
    slug = "calc-g"
    _write_local(tmp_path, slug, b"<html>content</html>")
    local_file = tmp_path / slug / "index.html"
    before = local_file.read_bytes()

    with patch("requests.get", return_value=_mock_response(200, b"<html>content</html>")):
        run_live_health_check({}, slugs=[slug], site_dir=tmp_path)

    assert local_file.read_bytes() == before  # local _site 파일 무변경
    # sqlite_repo가 주입되지 않아도(slugs 지정 시) SQLite에 전혀 접근하지 않음을
    # 구조적으로 보장 — sqlite_repo 인자가 아예 사용되지 않는 코드 경로다.


def test_g2_sqlite_repo_is_read_only_get_all_call_only(tmp_path):
    """slugs=None일 때도 sqlite_repo.get_all()만 호출하고 다른 메서드는
    호출하지 않는다(쓰기 메서드가 아예 없는 스텁으로 증명)."""
    rows = [{"slug": "calc-g2"}]
    _write_local(tmp_path, "calc-g2", b"<html>x</html>")
    repo = _StubRepo(rows)  # get_all()만 존재 — insert/update/delete 없음
    with patch("requests.get", return_value=_mock_response(200, b"<html>x</html>")):
        result = run_live_health_check({}, slugs=None, site_dir=tmp_path, sqlite_repo=repo)
    assert result["status"] == "ok"


# ── H. Telegram 미연결 ─────────────────────────────────────────────────

def test_h_no_telegram_call(tmp_path):
    _write_local(tmp_path, "calc-h", b"<html>x</html>")
    with patch("requests.get", return_value=_mock_response(200, b"<html>x</html>")), \
         patch("modules.telegram_ops.notify_level") as mock_notify:
        run_live_health_check({}, slugs=["calc-h"], site_dir=tmp_path)
    mock_notify.assert_not_called()


def test_h2_does_not_call_notify_three_way_anomalies(tmp_path):
    _write_local(tmp_path, "calc-h2", b"<html>x</html>")
    with patch("requests.get", return_value=_mock_response(200, b"<html>x</html>")), \
         patch("modules.calculator_3way_sync.notify_three_way_anomalies") as mock_notify_3way:
        run_live_health_check({}, slugs=["calc-h2"], site_dir=tmp_path)
    mock_notify_3way.assert_not_called()


# ── I. 기존 3-Way 자동 체인과의 독립성 ─────────────────────────────────

def test_i_does_not_touch_three_way_classification_pipeline(tmp_path):
    """run_live_health_check()는 compare_calculators_three_way()/
    classify_three_way()/run_three_way_anomaly_check_safely()를 전혀
    호출하지 않는다 — 기존 3-Way 자동 체인과 완전히 독립적이다."""
    _write_local(tmp_path, "calc-i", b"<html>x</html>")
    with patch("requests.get", return_value=_mock_response(200, b"<html>x</html>")), \
         patch("modules.calculator_3way_sync.compare_calculators_three_way") as mock_three_way, \
         patch("modules.calculator_3way_sync.classify_three_way") as mock_classify, \
         patch("modules.calculator_3way_sync.run_three_way_anomaly_check_safely") as mock_safe_entry:
        run_live_health_check({}, slugs=["calc-i"], site_dir=tmp_path)

    mock_three_way.assert_not_called()
    mock_classify.assert_not_called()
    mock_safe_entry.assert_not_called()
