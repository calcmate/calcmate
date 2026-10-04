# -*- coding: utf-8 -*-
"""tests/test_calculator_live_status.py

STEP78: modules/calculator_3way_sync.build_live_url()/
compare_local_site_vs_live()/attach_live_status_to_three_way() 회귀 테스트.

STEP77에서 조사한 대로 실제 공개 URL(https://calcmate.kr/<slug>/)과 local
_site를 READ-ONLY로 비교하는 신규 코드에 대한 테스트다. 기존 7개
classification/classify_three_way()/두 pairwise detector는 이 파일에서
전혀 건드리지 않는다.

실제 네트워크 요청은 하지 않는다 — requests.get을 항상 mock으로 대체한다.
실제 SQLite/Sheets/_site/queue/Telegram도 전혀 건드리지 않는다.
"""
import sys
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.calculator_3way_sync import (
    build_live_url,
    compare_local_site_vs_live,
    attach_live_status_to_three_way,
    run_three_way_anomaly_check_safely,
    normalize_live_compare_bytes,
    notify_three_way_anomalies,
    LIVE_MATCH,
    LIVE_MATCH_NORMALIZED,
    LIVE_DEPLOYED_DRIFT,
    LIVE_UNAVAILABLE,
    CLASSIFICATION_MATCH,
    CLASSIFICATION_BACKUP_DRIFT,
    SEVERITY_INFO,
    SEVERITY_WARN,
)


def _mock_response(status_code=200, content=b"", url="https://calcmate.kr/x/", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.url = url
    resp.headers = headers if headers is not None else {}
    return resp


# ── URL 헬퍼: 순수 함수 확인 ─────────────────────────────────────────

def test_00_build_live_url_is_pure_and_correct():
    assert build_live_url("annual-leave-remaining") == "https://calcmate.kr/annual-leave-remaining/"
    assert build_live_url("military-discharge-date") == "https://calcmate.kr/military-discharge-date/"
    # 순수 함수 — 같은 입력에 항상 같은 출력, 부작용 없음(네트워크/DB/파일 접근 없음)
    assert build_live_url("x") == build_live_url("x")


# ── A. Live MATCH ────────────────────────────────────────────────────

def test_a_live_match(tmp_path):
    html = b"<html><body>same content</body></html>"
    local_file = tmp_path / "index.html"
    local_file.write_bytes(html)

    with patch("requests.get", return_value=_mock_response(200, html, "https://calcmate.kr/calc-a/")):
        result = compare_local_site_vs_live("calc-a", local_file)

    assert result["status"] == LIVE_MATCH
    assert result["local_sha256"] == result["live_sha256"]
    assert result["http_status"] == 200
    assert result["error_type"] is None
    assert result["requested_url"] == "https://calcmate.kr/calc-a/"


# ── B. Live DRIFT ────────────────────────────────────────────────────

def test_b_live_drift(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>local version</html>")

    with patch("requests.get", return_value=_mock_response(200, b"<html>DIFFERENT live version</html>",
                                                             "https://calcmate.kr/calc-b/")):
        result = compare_local_site_vs_live("calc-b", local_file)

    assert result["status"] == LIVE_DEPLOYED_DRIFT
    assert result["local_sha256"] != result["live_sha256"]
    assert result["http_status"] == 200


# ── C. HTTP 404 ──────────────────────────────────────────────────────

def test_c_http_404_is_live_unavailable(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", return_value=_mock_response(404, b"not found", "https://calcmate.kr/calc-c/")):
        result = compare_local_site_vs_live("calc-c", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_4xx"
    assert result["http_status"] == 404
    assert result["live_sha256"] is None
    assert result["local_sha256"] is not None  # local은 이미 읽었으므로 채워짐


# ── D. HTTP 500 ──────────────────────────────────────────────────────

def test_d_http_500_is_live_unavailable(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", return_value=_mock_response(500, b"server error", "https://calcmate.kr/calc-d/")):
        result = compare_local_site_vs_live("calc-d", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_5xx"
    assert result["http_status"] == 500


# ── E. timeout ───────────────────────────────────────────────────────

def test_e_timeout_is_live_unavailable(tmp_path):
    import requests
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")):
        result = compare_local_site_vs_live("calc-e", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "timeout"
    assert result["http_status"] is None
    assert result["live_sha256"] is None


def test_e2_connection_error_is_live_unavailable(tmp_path):
    import requests
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        result = compare_local_site_vs_live("calc-e2", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "connection_failure"


def test_e3_dns_failure_is_classified_distinctly(tmp_path):
    import requests
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError(
            "Failed to resolve 'calcmate.kr' ([Errno -2] Name or service not known)")):
        result = compare_local_site_vs_live("calc-e3", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "dns_failure"


# ── F. redirect → 최종 body 사용 ─────────────────────────────────────

def test_f_redirect_final_body_used_for_match(tmp_path):
    html = b"<html>redirected content</html>"
    local_file = tmp_path / "index.html"
    local_file.write_bytes(html)

    # requests는 allow_redirects=True일 때 resp.url을 최종 URL로 채운다 —
    # 여기서는 그 동작을 mock으로 재현한다(요청 URL과 최종 URL이 다름).
    mock_resp = _mock_response(200, html, final_url := "https://calcmate.kr/calc-f/")
    with patch("requests.get", return_value=mock_resp) as mock_get:
        result = compare_local_site_vs_live("calc-f", local_file)

    assert result["status"] == LIVE_MATCH
    assert result["final_url"] == final_url
    assert result["requested_url"] == build_live_url("calc-f")
    # allow_redirects=True로 호출됐는지 확인(리다이렉트를 따라가도록 요청)
    _, kwargs = mock_get.call_args
    assert kwargs.get("allow_redirects") is True


# ── G. 기존 3-Way classification 독립성 ──────────────────────────────

def test_g_existing_classification_untouched_by_live_status(tmp_path):
    site_dir = tmp_path / "_site"
    site_dir.mkdir()
    slug = "calc-g"
    (site_dir / slug).mkdir()
    html = b"<html>content</html>"
    (site_dir / slug / "index.html").write_bytes(html)

    three_way_out = {
        "total": 1,
        "results": [{"slug": slug, "calculator_id": "id-g",
                     "classification": CLASSIFICATION_BACKUP_DRIFT, "severity": SEVERITY_WARN}],
        "counts": {CLASSIFICATION_BACKUP_DRIFT: 1},
        "deployed_result_source": "local_site_artifact",
    }
    original = {k: dict(v) if isinstance(v, dict) else v for k, v in three_way_out["results"][0].items()}

    with patch("requests.get", return_value=_mock_response(200, html, build_live_url(slug))):
        new_out = attach_live_status_to_three_way(three_way_out, site_dir=site_dir)

    # 원본은 전혀 변경되지 않았어야 한다.
    assert three_way_out["results"][0] == original
    assert "live_status" not in three_way_out["results"][0]

    # 새 결과는 classification/severity가 그대로이고 live_status만 추가됨.
    new_entry = new_out["results"][0]
    assert new_entry["classification"] == CLASSIFICATION_BACKUP_DRIFT
    assert new_entry["severity"] == SEVERITY_WARN
    assert new_entry["live_status"]["status"] == LIVE_MATCH


def test_g2_live_drift_does_not_change_classification():
    """Live가 DRIFT여도 기존 classification(MATCH 등)은 절대 자동 변경되지 않는다."""
    three_way_out = {
        "total": 1,
        "results": [{"slug": "calc-g2", "calculator_id": "id-g2",
                     "classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO}],
        "counts": {CLASSIFICATION_MATCH: 1},
    }
    with patch("modules.calculator_3way_sync.compare_local_site_vs_live",
               return_value={"status": LIVE_DEPLOYED_DRIFT, "requested_url": "u", "final_url": "u",
                             "local_sha256": "a", "live_sha256": "b", "http_status": 200, "error_type": None}):
        new_out = attach_live_status_to_three_way(three_way_out, site_dir=Path("."))
    entry = new_out["results"][0]
    assert entry["classification"] == CLASSIFICATION_MATCH  # 그대로
    assert entry["severity"] == SEVERITY_INFO  # 그대로
    assert entry["live_status"]["status"] == LIVE_DEPLOYED_DRIFT  # 독립 축


# ── H. 예외 격리(운영 함수 안전성) ────────────────────────────────────

def test_h1_single_slug_live_exception_does_not_break_batch():
    """한 slug의 Live 검증이 내부에서 예기치 않게 터져도 나머지 slug 처리와
    detector 결과는 훼손되지 않는다."""
    three_way_out = {
        "total": 2,
        "results": [
            {"slug": "calc-ok", "calculator_id": "id-ok",
             "classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO},
            {"slug": "calc-boom", "calculator_id": "id-boom",
             "classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO},
        ],
        "counts": {CLASSIFICATION_MATCH: 2},
    }

    def _side_effect(slug, local_path, timeout=10.0):
        if slug == "calc-boom":
            raise RuntimeError("simulated internal bug")
        return {"status": LIVE_MATCH, "requested_url": "u", "final_url": "u",
                "local_sha256": "a", "live_sha256": "a", "http_status": 200, "error_type": None}

    with patch("modules.calculator_3way_sync.compare_local_site_vs_live", side_effect=_side_effect):
        new_out = attach_live_status_to_three_way(three_way_out, site_dir=Path("."))

    by_slug = {r["slug"]: r for r in new_out["results"]}
    assert by_slug["calc-ok"]["live_status"]["status"] == LIVE_MATCH
    assert by_slug["calc-boom"]["live_status"]["status"] == LIVE_UNAVAILABLE
    assert by_slug["calc-boom"]["live_status"]["error_type"] == "internal_error"
    # 기존 classification은 예외와 무관하게 그대로 유지됨.
    assert by_slug["calc-boom"]["classification"] == CLASSIFICATION_MATCH


def test_h2_run_three_way_anomaly_check_safely_unaffected_by_live_helpers():
    """STEP78의 Live 검증 코드는 STEP76의 안전 진입점(run_three_way_anomaly_check_safely)에
    아직 연결되지 않았으므로, Live 관련 코드에 문제가 있어도 기존 3-way
    안전 진입점 동작에는 전혀 영향이 없어야 한다(구조적 독립성 확인)."""
    with patch("modules.calculator_3way_sync.compare_calculators_sqlite_vs_sheets",
               return_value={"results": []}), \
         patch("modules.calculator_site_sync.compare_calculators_sqlite_vs_site",
               return_value={"results": []}), \
         patch("modules.calculator_3way_sync.compare_local_site_vs_live",
               side_effect=RuntimeError("should never be called from here")):
        result = run_three_way_anomaly_check_safely({}, run_id="test-run")

    assert result["status"] == "ok"  # Live 헬퍼가 아예 호출되지 않으므로 영향 없음


# ══════════════════════════════════════════════════════════════════
# STEP80: MATCH_NORMALIZED(CRLF→LF 정규화) 최소 구현 회귀 테스트
# ══════════════════════════════════════════════════════════════════

def test_normalize_live_compare_bytes_only_does_crlf_to_lf():
    """순수 함수 — CRLF→LF 치환만 한다. strip/공백제거/기타 변형은 하지 않는다."""
    assert normalize_live_compare_bytes(b"a\r\nb") == b"a\nb"
    assert normalize_live_compare_bytes(b"a\nb") == b"a\nb"  # 이미 LF면 무변화
    assert normalize_live_compare_bytes(b"  a  \r\n  b  ") == b"  a  \n  b  "  # 공백은 건드리지 않음
    assert normalize_live_compare_bytes(b"") == b""


# ── A. Raw MATCH ─────────────────────────────────────────────────────

def test_a2_raw_match_short_circuits_before_normalization(tmp_path):
    html = b"<html>identical</html>"
    local_file = tmp_path / "index.html"
    local_file.write_bytes(html)

    with patch("requests.get", return_value=_mock_response(200, html, "https://calcmate.kr/a2/")):
        result = compare_local_site_vs_live("a2", local_file)

    assert result["status"] == LIVE_MATCH
    assert "normalization" not in result  # raw MATCH에는 정규화 metadata 없음


# ── B. local=CRLF, live=LF → MATCH_NORMALIZED ────────────────────────

def test_b_crlf_local_lf_live_is_match_normalized(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>\r\n<body>x</body>\r\n</html>")
    live_body = b"<html>\n<body>x</body>\n</html>"

    with patch("requests.get", return_value=_mock_response(200, live_body, "https://calcmate.kr/b/")):
        result = compare_local_site_vs_live("b", local_file)

    assert result["status"] == LIVE_MATCH_NORMALIZED
    assert result["normalization"] == "crlf_to_lf"
    assert result["local_sha256_normalized"] == result["live_sha256_normalized"]
    assert result["local_sha256"] != result["live_sha256"]  # raw는 여전히 다름


# ── C. local=LF, live=CRLF → MATCH_NORMALIZED(반대 방향도 동일하게 처리) ──

def test_c_lf_local_crlf_live_is_match_normalized(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>\n<body>y</body>\n</html>")
    live_body = b"<html>\r\n<body>y</body>\r\n</html>"

    with patch("requests.get", return_value=_mock_response(200, live_body, "https://calcmate.kr/c/")):
        result = compare_local_site_vs_live("c", local_file)

    assert result["status"] == LIVE_MATCH_NORMALIZED
    assert result["normalization"] == "crlf_to_lf"


# ── D. 정규화 후에도 실제 콘텐츠 차이 → DEPLOYED_LIVE_DRIFT ───────────

def test_d_real_content_difference_after_normalization_is_drift(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>\r\n<body>local version</body>\r\n</html>")
    live_body = b"<html>\n<body>COMPLETELY DIFFERENT</body>\n</html>"

    with patch("requests.get", return_value=_mock_response(200, live_body, "https://calcmate.kr/d/")):
        result = compare_local_site_vs_live("d", local_file)

    assert result["status"] == LIVE_DEPLOYED_DRIFT
    assert "normalization" not in result  # DRIFT에는 정규화 metadata 없음(스펙 그대로)


# ── E/F/G. HTTP 실패는 정규화 로직 이전에 이미 LIVE_UNAVAILABLE(회귀 재확인) ──

def test_e_http_404_still_live_unavailable_with_normalization_added(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")
    with patch("requests.get", return_value=_mock_response(404, b"nf", "https://calcmate.kr/e/")):
        result = compare_local_site_vs_live("e", local_file)
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_4xx"


def test_f_http_500_still_live_unavailable_with_normalization_added(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")
    with patch("requests.get", return_value=_mock_response(500, b"err", "https://calcmate.kr/f/")):
        result = compare_local_site_vs_live("f", local_file)
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_5xx"


def test_g_timeout_still_live_unavailable_with_normalization_added(tmp_path):
    import requests
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")
    with patch("requests.get", side_effect=requests.exceptions.Timeout("t")):
        result = compare_local_site_vs_live("g", local_file)
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "timeout"


# ── H. 기존 3-Way classification 독립성(MATCH_NORMALIZED 포함해도 불변) ──

def test_h3_three_way_classification_unaffected_by_match_normalized(tmp_path):
    site_dir = tmp_path / "_site"
    site_dir.mkdir()
    slug = "calc-h3"
    (site_dir / slug).mkdir()
    local_html = b"<html>\r\n<body>content</body>\r\n</html>"
    (site_dir / slug / "index.html").write_bytes(local_html)
    live_html = b"<html>\n<body>content</body>\n</html>"  # CRLF만 다름

    three_way_out = {
        "total": 1,
        "results": [{"slug": slug, "calculator_id": "id-h3",
                     "classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO}],
        "counts": {CLASSIFICATION_MATCH: 1},
    }

    with patch("requests.get", return_value=_mock_response(200, live_html, build_live_url(slug))):
        new_out = attach_live_status_to_three_way(three_way_out, site_dir=site_dir)

    entry = new_out["results"][0]
    assert entry["classification"] == CLASSIFICATION_MATCH  # 그대로(불변)
    assert entry["severity"] == SEVERITY_INFO  # 그대로(불변)
    assert entry["live_status"]["status"] == LIVE_MATCH_NORMALIZED  # 독립 축


# ── I. metadata 확인 ─────────────────────────────────────────────────

def test_i_match_normalized_metadata_shape(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"a\r\nb")
    with patch("requests.get", return_value=_mock_response(200, b"a\nb", "https://calcmate.kr/i/")):
        result = compare_local_site_vs_live("i", local_file)

    assert result["status"] == LIVE_MATCH_NORMALIZED
    assert result["normalization"] == "crlf_to_lf"
    assert "local_sha256_normalized" in result
    assert "live_sha256_normalized" in result
    assert "local_sha256" in result and "live_sha256" in result  # raw hash도 그대로 유지
    # HTML 본문 자체는 절대 포함되지 않는다.
    for v in result.values():
        assert v != b"a\r\nb" and v != b"a\nb"


# ── J. MATCH_NORMALIZED는 Telegram 알림 대상이 아니다 ─────────────────

def test_j_match_normalized_never_triggers_telegram():
    """live_status는 notify_three_way_anomalies()가 참조하는 classification
    체계와 완전히 분리돼 있으므로, MATCH_NORMALIZED가 섞여 있어도 기존 4개
    classification 기준(BACKUP_DRIFT 등)이 아니면 Telegram이 호출되지 않는다."""
    entry_with_live_normalized = dict(
        slug="calc-j", calculator_id="id-j",
        classification=CLASSIFICATION_MATCH, severity=SEVERITY_INFO,
        live_status={"status": LIVE_MATCH_NORMALIZED, "normalization": "crlf_to_lf"})
    three_way_out = {"results": [entry_with_live_normalized], "counts": {CLASSIFICATION_MATCH: 1},
                      "deployed_result_source": "local_site_artifact"}

    with patch("modules.telegram_ops.notify_level") as mock_notify:
        notifications = notify_three_way_anomalies({}, three_way_out)

    mock_notify.assert_not_called()
    assert notifications == []


# ══════════════════════════════════════════════════════════════════
# STEP86: local 파일이 없어도 Live HTTP GET을 실제로 수행하도록 개선한
# compare_local_site_vs_live()의 회귀 테스트(Case A~F).
#
# STEP85에서 확인된 문제: local _site 파일이 없으면 기존 코드가 Live HTTP
# GET을 아예 실행하지 않고 즉시 LIVE_UNAVAILABLE/local_file_missing으로
# 조기 반환했다 — 그 결과 실제 Live 상태(진짜 제거됨/여전히 노출/캐시
# 오탐 등)를 절대 확인할 수 없었다. 이 섹션은 그 맹점이 제거되었는지와,
# local 존재 여부가 독립 metadata(local_artifact_exists)로만 기록되는지,
# 기존 3-Way classification에는 전혀 영향이 없는지를 검증한다.
# ══════════════════════════════════════════════════════════════════

# ── Case A. local 존재 + Live 200(일치) → 기존 정상 판정 유지 ─────────

def test_step86_case_a_local_exists_live_match_unaffected(tmp_path):
    html = b"<html>same</html>"
    local_file = tmp_path / "index.html"
    local_file.write_bytes(html)

    with patch("requests.get", return_value=_mock_response(200, html, "https://calcmate.kr/case-a/")):
        result = compare_local_site_vs_live("case-a", local_file)

    assert result["status"] == LIVE_MATCH
    assert result["local_artifact_exists"] is True
    assert result["http_status"] == 200
    assert result["error_type"] is None


# ── Case B. local 존재 + Live 404 → 기존 Live 상태 유지 ────────────────

def test_step86_case_b_local_exists_live_404_unaffected(tmp_path):
    local_file = tmp_path / "index.html"
    local_file.write_bytes(b"<html>x</html>")

    with patch("requests.get", return_value=_mock_response(404, b"nf", "https://calcmate.kr/case-b/")):
        result = compare_local_site_vs_live("case-b", local_file)

    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_4xx"
    assert result["local_artifact_exists"] is True
    assert result["local_sha256"] is not None  # local은 이미 읽었으므로 채워짐


# ── Case C. local 없음 + Live 404 → 실제 Live GET이 수행됨을 검증 ──────

def test_step86_case_c_local_missing_live_404_get_actually_performed(tmp_path):
    missing_path = tmp_path / "does-not-exist" / "index.html"
    assert not missing_path.exists()

    with patch("requests.get", return_value=_mock_response(404, b"nf", "https://calcmate.kr/case-c/")) as mock_get:
        result = compare_local_site_vs_live("case-c", missing_path)

    mock_get.assert_called_once()  # 조기 반환 없이 실제로 GET이 호출됨
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "http_4xx"  # local_file_missing이 아니라 실제 HTTP 원인으로 기록
    assert result["local_artifact_exists"] is False
    assert result["local_sha256"] is None
    assert result["http_status"] == 404


# ── Case D. local 없음 + Live 200 → 실제 200이 그대로 관측됨 ───────────

def test_step86_case_d_local_missing_live_200_is_observed(tmp_path):
    missing_path = tmp_path / "does-not-exist" / "index.html"
    live_body = b"<html>still live content</html>"

    with patch("requests.get", return_value=_mock_response(
            200, live_body, "https://calcmate.kr/case-d/",
            headers={"Age": "105276", "CF-Cache-Status": "DYNAMIC"})) as mock_get:
        result = compare_local_site_vs_live("case-d", missing_path)

    mock_get.assert_called_once()
    # 콘텐츠 비교 기준(local)이 없어 MATCH 판정은 못하지만, 실제 HTTP 200과
    # live_sha256/캐시 헤더는 그대로 관측되어야 한다(STEP85의 "200인데 왜
    # 안 보이나"를 다음에는 즉시 진단할 수 있어야 하므로).
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "local_file_missing"
    assert result["local_artifact_exists"] is False
    assert result["http_status"] == 200
    assert result["live_sha256"] is not None
    assert result["local_sha256"] is None
    assert result["age"] == "105276"
    assert result["cf_cache_status"] == "DYNAMIC"


# ── Case E. local 없음 + timeout/네트워크 오류 → LIVE_UNAVAILABLE ──────

def test_step86_case_e_local_missing_network_error_is_live_unavailable(tmp_path):
    import requests
    missing_path = tmp_path / "does-not-exist" / "index.html"

    with patch("requests.get", side_effect=requests.exceptions.Timeout("timed out")) as mock_get:
        result = compare_local_site_vs_live("case-e", missing_path)

    mock_get.assert_called_once()
    assert result["status"] == LIVE_UNAVAILABLE
    assert result["error_type"] == "timeout"
    assert result["local_artifact_exists"] is False
    assert result["local_sha256"] is None
    assert result["http_status"] is None


# ── Case F. local 없음 + Live 404 상황에서도 기존 3-Way classification은
#            절대 변경되지 않는다 ──────────────────────────────────────

def test_step86_case_f_three_way_classification_unaffected_when_local_missing():
    slug = "case-f"
    three_way_out = {
        "total": 1,
        "results": [{"slug": slug, "calculator_id": "id-case-f",
                     "classification": CLASSIFICATION_MATCH, "severity": SEVERITY_INFO}],
        "counts": {CLASSIFICATION_MATCH: 1},
    }
    original = {k: dict(v) if isinstance(v, dict) else v for k, v in three_way_out["results"][0].items()}

    with patch("modules.calculator_3way_sync.compare_local_site_vs_live",
               return_value={"status": LIVE_UNAVAILABLE, "requested_url": "u", "final_url": "u",
                             "local_sha256": None, "live_sha256": None, "http_status": 404,
                             "error_type": "http_4xx", "local_artifact_exists": False}):
        new_out = attach_live_status_to_three_way(three_way_out, site_dir=Path("."))

    # 원본은 전혀 변경되지 않았어야 한다.
    assert three_way_out["results"][0] == original
    # classification/severity는 그대로, live_status만 독립적으로 추가됨.
    entry = new_out["results"][0]
    assert entry["classification"] == CLASSIFICATION_MATCH
    assert entry["severity"] == SEVERITY_INFO
    assert entry["live_status"]["status"] == LIVE_UNAVAILABLE
    assert entry["live_status"]["local_artifact_exists"] is False
