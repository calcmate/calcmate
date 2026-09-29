# -*- coding: utf-8 -*-
"""tests/test_nan_infinity_guard.py — STEP 28-136

templates/calculators/assets/components.js의 calculate() 공통 가드가
NaN/Infinity/-Infinity를 정상 결과처럼 화면에 노출하지 않는지 검증한다.

배경: 기존 가드(`!isFinite(num(outputs[CFG.primaryOutput]))`)는 대표 출력
(primaryOutput) 하나만 검사했다. renderResult()는 CFG.outputs 전체(다중 출력)를
화면에 그리므로, primaryOutput이 아닌 다른 출력이 NaN/Infinity가 되면 가드를
통과해 "NaN원"/"∞" 같은 값이 그대로 노출될 수 있었다. STEP 28-136에서
outputs object 전체의 숫자 타입 값을 검사하는 `_hasNonFiniteNumericOutput()`을
추가해 이 간극을 메웠다.

이 테스트는 실제 templates/calculators/assets/components.js 파일(수정된 실물)을
그대로 읽어 Node.js로 실행한다 — Python 재구현이 아니다. formula/registry는
전혀 건드리지 않으며, 이 파일은 순수 계산기 공통 JS의 안전성만 검증한다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_JS = ROOT / "templates" / "calculators" / "assets" / "components.js"

sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")


def _node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _node_available(), reason="Node.js 미설치 환경 — 스킵")


_HARNESS_TEMPLATE = r"""
function makeEl(id) {{
  return {{
    id: id, textContent: '',
    classList: {{ add(){{}}, remove(){{}}, contains(){{return false;}} }},
    style: {{}}, offsetWidth: 0,
    parentNode: {{ insertBefore(){{}} }},
  }};
}}
var els = {{}};
var doc = {{
  getElementById(id) {{ if (!els[id]) els[id] = makeEl(id); return els[id]; }},
  querySelector(sel) {{ return makeEl('btn'); }},
  querySelectorAll(sel) {{ return []; }},
  createElement(tag) {{ return makeEl('created'); }},
}};
var win = {{
  SM_CONFIG: {{
    primaryOutput: {primary_output!r},
    outputs: {output_keys}.map(function(k) {{ return {{key: k, label: k, unit: ''}}; }}),
  }},
  requestAnimationFrame: function() {{}},
}};
global.window = win;
global.document = doc;
global.requestAnimationFrame = function() {{}};

{components_src}

win.computeResult = function(inputs) {{ return {outputs_json}; }};
win.calculate();

var errEl = els['calc-error'];
var blocked = !!(errEl && errEl.textContent && errEl.textContent.length > 0);
var outText = {{}};
{output_keys}.forEach(function(k) {{
  var el = els['out_' + k];
  outText[k] = el ? el.textContent : null;
}});
process.stdout.write(JSON.stringify({{blocked: blocked, outText: outText}}));
"""


def _run_calculate(outputs: dict, primary_output: str, output_keys: list) -> dict:
    """실제 components.js를 Node로 실행해 calculate()의 최종 판정(blocked 여부,
    렌더된 출력 텍스트)을 반환한다."""
    components_src = COMPONENTS_JS.read_text(encoding="utf-8")
    harness = _HARNESS_TEMPLATE.format(
        primary_output=primary_output,
        output_keys=json.dumps(output_keys),
        components_src=components_src,
        outputs_json=json.dumps(outputs, allow_nan=True).replace("NaN", "NaN")
        .replace("Infinity", "Infinity"),
    )
    # JSON은 NaN/Infinity를 표준으로 지원하지 않지만, 이 문자열은 JS 리터럴로 그대로
    # 삽입되므로(JSON.dumps가 아니라 JS 소스 텍스트로 취급) NaN/Infinity 키워드가
    # 유효한 JS 표현식으로 그대로 평가된다.
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with __import__("os").fdopen(fd, "w", encoding="utf-8") as f:
            f.write(harness)
        r = subprocess.run(["node", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
        assert r.returncode == 0, f"Node 실행 오류: {r.stderr}"
        return json.loads(r.stdout.strip())
    finally:
        try:
            __import__("os").unlink(path)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Test 1~4 — NaN / +Infinity / -Infinity 방어, 원인 위치(primary vs secondary)
# ═══════════════════════════════════════════════════════════════════════════

def test_nan_in_secondary_output_is_blocked():
    """primaryOutput은 정상, 보조 출력이 NaN이면 차단되어야 한다(기존 가드의 간극)."""
    result = _run_calculate(
        {"acquisition_tax": 2100000, "registration_tax": float("nan"), "notices": []},
        "acquisition_tax", ["acquisition_tax", "registration_tax"],
    )
    assert result["blocked"] is True
    assert result["outText"]["acquisition_tax"] is None
    assert result["outText"]["registration_tax"] is None


def test_positive_infinity_in_secondary_output_is_blocked():
    result = _run_calculate(
        {"acquisition_tax": 2100000, "registration_tax": float("inf"), "notices": []},
        "acquisition_tax", ["acquisition_tax", "registration_tax"],
    )
    assert result["blocked"] is True


def test_negative_infinity_in_secondary_output_is_blocked():
    result = _run_calculate(
        {"acquisition_tax": 2100000, "registration_tax": float("-inf"), "notices": []},
        "acquisition_tax", ["acquisition_tax", "registration_tax"],
    )
    assert result["blocked"] is True


def test_nan_in_primary_output_is_still_blocked_regression():
    """기존에도 잡히던 primaryOutput NaN 케이스가 이번 변경으로 깨지지 않았는지 확인."""
    result = _run_calculate({"bmi": float("nan"), "notices": []}, "bmi", ["bmi"])
    assert result["blocked"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Test 5~7 — 정상 결과 보존(0 / 유한 소수 / 다중 출력 object 구조)
# ═══════════════════════════════════════════════════════════════════════════

def test_normal_zero_result_not_blocked():
    result = _run_calculate(
        {"acquisition_tax": 0, "registration_tax": 0, "notices": []},
        "acquisition_tax", ["acquisition_tax", "registration_tax"],
    )
    assert result["blocked"] is False
    assert result["outText"]["acquisition_tax"] == "0"
    assert result["outText"]["registration_tax"] == "0"


def test_normal_finite_decimal_not_blocked():
    result = _run_calculate({"bmi": 22.49, "notices": []}, "bmi", ["bmi"])
    assert result["blocked"] is False
    assert result["outText"]["bmi"] is not None


def test_normal_multi_output_object_structure_preserved():
    """여러 숫자 출력이 모두 정상(유한)이면 전부 차단 없이 렌더되고,
    outText의 key 구조(CFG.outputs 순서)가 그대로 유지되어야 한다."""
    result = _run_calculate(
        {"acquisition_tax": 2100000, "registration_tax": 600000, "notices": []},
        "acquisition_tax", ["acquisition_tax", "registration_tax"],
    )
    assert result["blocked"] is False
    assert set(result["outText"].keys()) == {"acquisition_tax", "registration_tax"}
    assert result["outText"]["acquisition_tax"] == "2,100,000"
    assert result["outText"]["registration_tax"] == "600,000"


# ═══════════════════════════════════════════════════════════════════════════
# 실제 계산기 4종 회귀 — 정상 입력 결과가 이번 변경으로 달라지지 않았는지 확인.
# computeResult() 자체(=formula/registry)는 이번 STEP에서 전혀 건드리지 않았으므로,
# 이미 알려진 정답값과의 일치를 재확인하는 순수 회귀 테스트다.
# ═══════════════════════════════════════════════════════════════════════════

def _generate_js_for(slug: str) -> str:
    from modules.config_loader import load_config
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules.app_generator import generate_js

    cfg = load_config()
    repo = CalculatorRepository(get_db_adapter(cfg))
    calc = repo.get_by_slug(slug)
    return generate_js(calc, cfg)


def _run_compute_result(slug: str, inputs: dict) -> dict:
    """실제 generate_js() 전체 번들(components.js 공통 코드 + 계산기별
    computeResult)을, window === globalThis인 실제 브라우저와 동일한 전역
    스코프 구조로 Node에서 실행한다.

    STEP 28-140에서 BMI의 computeResult가 round(x,N)을 components.js의 공유
    helper pyRound()로 위임하게 되면서, computeResult 텍스트만 잘라내 독립
    실행하던 기존 방식(components.js 미로딩)은 `pyRound is not defined`로
    깨진다. pyRound를 이 테스트 안에 별도로 재구현하거나 stub으로 대체하지
    않고, 실제 components.js를 그대로 로드해 진짜 구현이 실행되게 한다 —
    검증 대상(NaN/Infinity 방어, 정상 계산 결과)은 변경하지 않고 실행
    환경만 실제 배포되는 script.js와 동일하게 맞춘다."""
    full_js = _generate_js_for(slug)
    dom_stub = (
        "global.window = global;\n"
        "global.document = {\n"
        "  getElementById: function () { return null; },\n"
        "  querySelector: function () { return null; },\n"
        "  querySelectorAll: function () { return []; },\n"
        "  createElement: function () { return { classList: { add: function () {}, remove: function () {} }, style: {} }; },\n"
        "  addEventListener: function () {},\n"
        "  readyState: 'complete',\n"
        "};\n"
        "global.addEventListener = function () {};\n"
        "global.requestAnimationFrame = function () {};\n"
        "global.localStorage = { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} };\n"
        "global.navigator = { userAgent: 'node-test' };\n"
        "global.location = { pathname: '/test', href: 'http://localhost/test' };\n"
    )
    harness = (
        dom_stub + "\n" + full_js + "\n"
        + f"process.stdout.write(JSON.stringify(window.computeResult({json.dumps(inputs)})));\n"
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with __import__("os").fdopen(fd, "w", encoding="utf-8") as f:
            f.write(harness)
        r = subprocess.run(["node", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
        assert r.returncode == 0, f"Node 실행 오류: {r.stderr}"
        return json.loads(r.stdout.strip())
    finally:
        try:
            __import__("os").unlink(path)
        except Exception:
            pass


def test_regression_bmi_normal_and_boundary():
    """STEP 28-140: round(weight_kg/((height_cm/100)**2), 2)가 이제 pyRound()를
    거쳐 소수점 2자리를 보존한다(이전에는 Math.round(x, 2)가 두 번째 인자를
    무시해 22로 잘렸음 — STEP 28-139에서 확인된 버그, 이번 STEP에서 수정 대상).
    이 STEP의 목적 자체가 이 값을 22 → 22.49로 바로잡는 것이므로, 이 값을
    수정하는 것은 assertion 완화가 아니라 버그 수정 결과를 반영하는 것이다."""
    out = _run_compute_result("bmi-calculator", {"height_cm": 170, "weight_kg": 65})
    assert out["bmi"] == 22.49
    assert _run_compute_result("bmi-calculator", {"height_cm": 0, "weight_kg": 65}) is None


def test_regression_car_tax_normal_and_boundary():
    """STEP 28-193 이후 자동차_취등록세_계산기는 modules/app_generator.py의
    slug 조건부 완전 커스텀 분기로 계산되며, DB에 저장된 input_schema/formula
    (구 스키마: 문자열 car_type/region, 이원 세목)는 실행 시 전혀 참조되지
    않는다 — 이 분기가 슬러그만 보고 자체 로직으로 완전히 대체하기 때문이다.
    따라서 이 회귀 테스트는 실제 코드가 쓰는 새 스키마(car_type/eco_type 숫자
    코드)로 입력하고 새 출력 필드를 검증한다. DB record(Sheets) 자체는 이
    변경으로 건드리지 않는다 — 여전히 구 스키마를 저장하고 있어도 무방하다."""
    out = _run_compute_result("자동차_취등록세_계산기",
                               {"car_type": 1, "car_price": 30000000, "eco_type": 0})
    assert out["acquisition_tax"] == 2100000
    assert out["standard_acquisition_tax"] == 2100000
    assert out["exemption_amount"] == 0
    assert _run_compute_result("자동차_취등록세_계산기",
                                {"car_type": 1, "car_price": -5000000, "eco_type": 0}) is None


def test_regression_jeonse_vs_monthly_normal():
    out = _run_compute_result("jeonse-vs-monthly", {
        "jeonse_deposit": 100000000, "wolse_deposit": 10000000,
        "wolse_amount": 500000, "rate": 5,
    })
    assert out["jeonse_opp_cost"] == 375000
    assert out["wolse_to_jeonse_equiv"] == 130000000
    assert out["monthly_savings"] == 125000


def test_regression_annual_leave_remaining_normal():
    out = _run_compute_result("annual-leave-remaining",
                               {"months_of_service": 13, "used_days": 2})
    assert out["total_days"] == 15
    assert out["remaining_days"] == 13


# ═══════════════════════════════════════════════════════════════════════════
# registry 무변경 확인
# ═══════════════════════════════════════════════════════════════════════════

def test_registry_untouched_by_this_step():
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.stdout.strip() == "", (
        f"이번 STEP은 공통 JS만 수정해야 하는데 registry가 변경됨: {result.stdout}"
    )
