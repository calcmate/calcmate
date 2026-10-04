# -*- coding: utf-8 -*-
"""tests/test_html_js_completeness_guard.py — P0-1: HTML/JS 생성 완결성 검증 가드.

배경: React Dashboard 실제 수동 생성 E2E에서 modules.app_factory.generate_app()의
"code"(HTML) 단계가 _chat(...,"code",...,max_tokens=4000) 토큰 한도 부근에서 잘려,
</html> 없이 <script> 중간에서 끊긴 HTML이 save_app()까지 그대로 저장되는 사례가
실측 확인됐다(연금저축·IRP 세액공제 계산기, 자동차 취등록세 계산기 — 실제 운영
DB의 app_templates.html_template에서 직접 확인). 이 파일은:

  1) modules.review_center.validate_html_js_completeness()의 단위 동작을
     실제 관측된 두 실패 패턴(태그 자체가 끊긴 경우 / 태그는 닫혔지만 내부
     template literal만 미종료인 경우)으로 검증하고,
  2) api.services.calculator_service.submit_calculator_generation()이 실제로
     이 게이트를 Formula Hard Gate 직후·save_app() 호출 직전에 통과시키는지
     React가 호출하는 바로 그 POST /api/calculators/generate 경로로 확인한다.

안전 설계(기존 tests/test_step_4h5_calculator_generate.py 관례 그대로 재사용):
실제 AI 호출 없음(_chat만 결정적 mock), 실제 DB/Registry 접근 없음(fake만 사용),
save_app()은 spy로 감싸 호출 여부만 확인(실제 파일 없음 이중 확인은 파일 끝의
test_real_registry_and_config_unchanged_by_this_test_file()이 담당).
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
from fastapi.testclient import TestClient

from modules.review_center import validate_html_js_completeness

_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOKEN = "html-guard-test-admin-token"


def _registry_snapshot():
    import subprocess
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout


_BEFORE_REGISTRY_SNAPSHOT = _registry_snapshot()


# ══════════════════════════════════════════════════════════════════════════
# 실제 프로젝트 정상 계산기 구조를 그대로 반영한 fixture
# (실 운영 DB의 annual-leave-remaining 계산기 HTML과 동일한 골격: DOCTYPE,
#  <html lang="ko">, 단일 인라인 <script>, input+button, </script></body></html>)
# ══════════════════════════════════════════════════════════════════════════
GOOD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>연차 잔여일 계산기</title></head>
<body>
<div class="calculator">
  <input id="years_of_service" type="number">
  <input id="used_days" type="number">
  <button onclick="calculate()">계산하기</button>
  <div id="result"></div>
</div>
<script>
  function calculate() {
    const years = parseFloat(document.getElementById('years_of_service').value) || 0;
    const used = parseFloat(document.getElementById('used_days').value) || 0;
    const total = 15 + Math.min(Math.max(0, Math.floor((years - 1) / 2)), 10);
    const remaining = total - used;
    document.getElementById('result').innerHTML = `잔여일: ${remaining}일`;
  }
</script>
</body>
</html>"""

# 실제 관측된 실패 패턴 1: 태그 자체가 끊김(</html> 없음, </script> 없음)
# — 연금저축·IRP 세액공제 계산기 / 자동차 취등록세 계산기에서 실측된 형태를
# 그대로 재현(끝부분이 문장 중간에서 끊기고 닫는 태그가 전혀 없음).
TRUNCATED_MID_SCRIPT_HTML = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>연금저축·IRP 세액공제 계산기</title></head>
<body>
<div class="calculator">
  <input id="pension_contribution" type="number">
  <input id="irp_contribution" type="number">
  <input id="annual_income" type="number">
  <button onclick="calculate()">세액공제 계산하기</button>
  <div id="result_area"></div>
</div>
<script>
  function calculate() {
    const pension = parseFloat(document.getElementById('pension_contribution').value) || 0;
    const irp = parseFloat(document.getElementById('irp_contribution').value) || 0;
    const income = parseFloat(document.getElementById('annual_income').value) || 0;
    const totalContribution = pension + irp;
    const incomeLimit = 0.12 * income;
    const maxLimit = 7000000;
    const deductibleAmount = Math.min(maxLimit, totalContribution, incomeLimit);
    const estimatedTaxCredit = 0.15 * deductibleAmount;
    let limitReason = '';
    if (deductibleAmount === maxLimit) {
      limitReason = '연간 <strong>700만 원 한도</strong>가 적용되었습니다.';
    } else if (incomeLimit > 0 && deductibleAmount === incomeLimit) {
      limitReason = '<strong>연소득의 12%</strong> 한도가 적용되었습니다.';
    } else {
      limitReason = '납입액 전액이 공제 대상입니다.';
    }
    const detail = `
      총 납입액: <strong>${totalContribution.toLocaleString()}원</strong> (연금저축 ${pension.toLocaleString()}원 + IRP ${irp.toLocaleString()}원)<br>
      공제 한도: 700만원 / 연소득"""

# 실제 관측된 실패 패턴 2(합성 재현): <script>/</script> 태그 자체는 정상 종료됐지만
# 내부 template literal(백틱)이 닫히지 않은 경우 — 위 truncation과 원인은 동일
# (AI 응답이 template literal 한가운데서 끊김)이나 결과 형태가 다르므로 별도 검증.
UNCLOSED_TEMPLATE_LITERAL_HTML = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>합성 테스트 계산기</title></head>
<body>
<div class="calculator">
  <input id="a" type="number">
  <button onclick="calculate()">계산</button>
  <div id="result"></div>
</div>
<script>
  function calculate() {
    const a = parseFloat(document.getElementById('a').value) || 0;
    const detail = `
      총액: ${a}원
    document.getElementById('result').innerHTML = detail;
  }
</script>
</body>
</html>"""

MISSING_CLOSING_HTML_TAG = GOOD_HTML.replace("</html>", "")

EMPTY_HTML = ""


# ══════════════════════════════════════════════════════════════════════════
# 단위 테스트 — validate_html_js_completeness() 자체
# ══════════════════════════════════════════════════════════════════════════

class TestValidateHtmlJsCompleteness:
    def test_normal_html_passes(self):
        ok, msg, steps = validate_html_js_completeness(GOOD_HTML)
        assert ok is True, msg
        assert all(s["passed"] or s["skipped"] for s in steps)

    def test_empty_html_fails(self):
        ok, msg, steps = validate_html_js_completeness(EMPTY_HTML)
        assert ok is False
        assert "비어" in msg

    def test_missing_closing_html_tag_fails(self):
        ok, msg, steps = validate_html_js_completeness(MISSING_CLOSING_HTML_TAG)
        assert ok is False
        step3 = next(s for s in steps if s["step"] == 3)
        assert step3["passed"] is False

    def test_truncated_mid_script_fails(self):
        """실제 관측된 실패 패턴 1(태그 자체 끊김) 회귀 고정."""
        ok, msg, steps = validate_html_js_completeness(TRUNCATED_MID_SCRIPT_HTML)
        assert ok is False
        step3 = next(s for s in steps if s["step"] == 3)  # </html> 닫힘
        step4 = next(s for s in steps if s["step"] == 4)  # script 태그 균형
        assert step3["passed"] is False
        assert step4["passed"] is False

    def test_unclosed_template_literal_fails_even_with_balanced_script_tags(self):
        """실제 관측된 실패 패턴 2(template literal만 미종료) 회귀 고정 —
        <script>/</script> 태그 자체는 정상이어도 FAIL해야 한다(STEP 6 핵심 요구)."""
        ok, msg, steps = validate_html_js_completeness(UNCLOSED_TEMPLATE_LITERAL_HTML)
        step4 = next(s for s in steps if s["step"] == 4)
        assert step4["passed"] is True  # 태그 자체는 균형(이 케이스의 핵심)
        assert ok is False  # 그럼에도 전체는 FAIL이어야 함
        step5 = next(s for s in steps if s["step"] == 5)  # 백틱 휴리스틱
        step7 = next(s for s in steps if s["step"] == 7)  # node --check
        assert step5["passed"] is False
        assert step7["passed"] is False
        assert "template literal" in step5["detail"] or "Unexpected end of input" in step7["detail"]

    def test_missing_input_or_button_fails(self):
        no_button = GOOD_HTML.replace('<button onclick="calculate()">계산하기</button>', "")
        ok, msg, steps = validate_html_js_completeness(no_button)
        step6 = next(s for s in steps if s["step"] == 6)
        assert step6["passed"] is False
        assert ok is False

    def test_json_ld_and_external_script_blocks_do_not_cause_false_positive(self):
        """P0-2 실 E2E에서 실측 발견된 회귀: 실제 배포 중인 annual-leave-remaining
        계산기(app_generator.generate_calculator() 산출물)는 <script type=
        "application/ld+json">(SEO 구조화 데이터) 3개 + 외부 <script src=...>
        (Google Analytics)를 포함하는데, 이를 실제 JS 블록과 그대로 이어붙여
        node --check하면 JSON의 콜론(:)이 "Unexpected token ':'"으로 오탐 FAIL
        됐었다. 정상적으로 배포되어 실제 계산이 되는 HTML이 이 이유로 차단되면
        안 된다."""
        html = (
            '<!DOCTYPE html><html lang="ko"><head><title>t</title>'
            '<script async src="https://www.googletagmanager.com/gtag/js?id=X"></script>'
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"WebApplication","name":"t"}'
            '</script>'
            '</head><body>'
            '<input id="a"><button onclick="c()">계산</button>'
            '<script>function c(){ return 1; }</script>'
            '</body></html>'
        )
        ok, msg, steps = validate_html_js_completeness(html)
        assert ok is True, msg
        step7 = next(s for s in steps if s["step"] == 7)
        assert step7["passed"] is True, step7["detail"]

    def test_js_syntax_error_unrelated_to_template_literal_fails(self):
        broken_js_html = GOOD_HTML.replace(
            "const total = 15", "const total == 15 +++"
        )
        ok, msg, steps = validate_html_js_completeness(broken_js_html)
        step7 = next(s for s in steps if s["step"] == 7)
        assert step7["passed"] is False
        assert ok is False


# ══════════════════════════════════════════════════════════════════════════
# 통합 테스트 — 실제 React가 호출하는 POST /api/calculators/generate 경로
# (안전 격리: _chat만 mock, DB/Registry는 fake, save_app은 spy)
# ══════════════════════════════════════════════════════════════════════════

def _make_chat_mock(code_response_html, calls_list):
    def mock(cfg, role, system, user, max_tokens=1200):
        calls_list.append(role)
        if role == "orchestrator":
            return (
                '{"calculator_type":"general","input_schema":{"a":"number"},'
                '"output_schema":{"result":"number"},"formula":"a","labels":{"a":"입력값","result":"결과"}}',
                "gpt-4o", 100,
            )
        if role == "code":
            return (code_response_html, "claude-sonnet-4-6", 4000)
        if role == "writer":
            return ('{"seo_title":"T","seo_desc":"D","faq":[],"blog_draft":""}', "gpt-4o", 100)
        raise AssertionError(f"예상치 못한 role 호출: {role}")
    return mock


class _FakeDb:
    def delete(self, table, id_):
        pass


def _make_fake_calc_repo(shared_rows):
    class _Repo:
        def __init__(self, db):
            self.db = db
        def get_all(self):
            return [dict(r) for r in shared_rows.values()]
        def save(self, data):
            _id = f"calc_{len(shared_rows) + 1}"
            row = dict(data); row["id"] = _id
            shared_rows[_id] = row
            return _id
        def delete(self, id_):
            shared_rows.pop(id_, None)
    return _Repo


class _FakeTplRepo:
    def __init__(self, db):
        self.db = db
    def save(self, data):
        return "tpl_1"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _run_generate_via_real_endpoint(code_response_html, monkeypatch):
    """React가 실제로 호출하는 POST /api/calculators/generate를 FastAPI
    TestClient로 호출. generate_app()/save_app()은 실제 코드 그대로 실행하되
    _chat만 결정적 mock, DB/Registry는 fake — save_app이 호출되면 안 되는
    케이스에서 실제로 호출 여부를 spy로 확인한다."""
    import os
    monkeypatch.setenv("CALCMATE_DASHBOARD_AUTH_TOKEN_ADMIN", ADMIN_TOKEN)
    monkeypatch.delenv("CALCMATE_DASHBOARD_LOCAL_MODE", raising=False)

    import modules.app_factory as af
    shared_rows = {}
    save_app_calls = []
    real_save_app = af.save_app

    def _spy_save_app(cfg, app, site_id="", slug=None):
        save_app_calls.append({"name": app.get("name")})
        return real_save_app(cfg, app, site_id=site_id, slug=slug)

    calls = []
    monkeypatch.setattr(af, "get_db_adapter", lambda cfg: _FakeDb())
    # IRP-23: app_templates 저장은 get_template_storage_adapter(cfg)를 거치므로
    # (SQLite-원본/Sheets-백업 전용, get_db_adapter와 별개 함수) 동일하게 대역 처리한다.
    monkeypatch.setattr(af, "get_template_storage_adapter", lambda cfg: _FakeDb())
    monkeypatch.setattr(af, "CalculatorRepository", _make_fake_calc_repo(shared_rows))
    monkeypatch.setattr(af, "TemplateRepository", _FakeTplRepo)
    monkeypatch.setattr("modules.registry_loader.load_registry_v3", lambda force=True: {})
    monkeypatch.setattr("modules.registry_loader.add_auto_entry", lambda *a, **k: None)
    monkeypatch.setattr("modules.registry_loader.remove_auto_entry", lambda *a, **k: True)
    monkeypatch.setattr(af, "_write_registry_v3", lambda *a, **k: None)
    monkeypatch.setattr(af, "_write_calculator_index", lambda *a, **k: None)
    monkeypatch.setattr(af, "_save_contract_instance", lambda *a, **k: None)
    monkeypatch.setattr(af, "save_af_checklist", lambda *a, **k: None)
    monkeypatch.setattr(af, "_chat", _make_chat_mock(code_response_html, calls))
    monkeypatch.setattr(af, "save_app", _spy_save_app)
    monkeypatch.setattr("modules.config_loader.load_config", lambda *a, **k: {})

    import api.services.generation_job_store as job_store_module
    job_store_module._store = None
    from api.main import app
    client = TestClient(app)

    r = client.post(
        "/api/calculators/generate",
        json={"name": "가드테스트계산기", "category": "노무/급여", "description": "테스트", "tier": 2},
        headers=_auth(ADMIN_TOKEN),
    )
    job_id = r.json()["data"]["job_id"]
    deadline = time.time() + 10
    job = None
    while time.time() < deadline:
        jr = client.get(f"/api/calculators/generate/{job_id}", headers=_auth(ADMIN_TOKEN))
        job = jr.json()["data"]
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    if job_store_module._store is not None:
        job_store_module._store.shutdown(wait=True)
        job_store_module._store = None

    return job, save_app_calls, shared_rows


class TestSaveBlockedOnIncompleteHtml:
    def test_truncated_html_blocks_save_via_real_endpoint(self, monkeypatch):
        """STEP 6 핵심 회귀: 실제 관측된 truncation 패턴이 React 호출 endpoint를
        통해서도 저장 직전에 차단되는지 확인."""
        job, save_app_calls, shared_rows = _run_generate_via_real_endpoint(
            TRUNCATED_MID_SCRIPT_HTML, monkeypatch)
        assert job["status"] == "failed"
        assert "HTML/JS 완결성 검증 실패" in job["error"]
        assert save_app_calls == [], "완결성 검증 실패 시 save_app()이 호출되면 안 된다"
        assert shared_rows == {}, "DB(fake)에 row가 생성되면 안 된다"

    def test_unclosed_template_literal_blocks_save_via_real_endpoint(self, monkeypatch):
        job, save_app_calls, shared_rows = _run_generate_via_real_endpoint(
            UNCLOSED_TEMPLATE_LITERAL_HTML, monkeypatch)
        assert job["status"] == "failed"
        assert "HTML/JS 완결성 검증 실패" in job["error"]
        assert save_app_calls == []
        assert shared_rows == {}

    def test_complete_html_still_succeeds_via_real_endpoint(self, monkeypatch):
        """완결된 정상 HTML은 기존과 동일하게 저장까지 정상 진행되어야 한다
        (이 게이트가 정상 케이스를 억지로 막지 않는지 확인)."""
        job, save_app_calls, shared_rows = _run_generate_via_real_endpoint(
            GOOD_HTML, monkeypatch)
        assert job["status"] == "succeeded", job.get("error")
        assert len(save_app_calls) == 1
        assert len(shared_rows) == 1


# ══════════════════════════════════════════════════════════════════════════
# 기존 Registry/Config 무손상 확인(기존 관례 그대로)
# ══════════════════════════════════════════════════════════════════════════

def test_real_registry_and_config_unchanged_by_this_test_file():
    after_registry = _registry_snapshot()
    assert after_registry == _BEFORE_REGISTRY_SNAPSHOT, (
        f"운영 Registry가 변경됨:\nbefore={_BEFORE_REGISTRY_SNAPSHOT!r}\nafter={after_registry!r}"
    )
