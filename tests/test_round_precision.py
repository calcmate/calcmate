# -*- coding: utf-8 -*-
"""tests/test_round_precision.py — STEP 28-140

modules/app_generator.py::_to_js()가 Python round(x, N)(자릿수 반올림)을
JS Math.round(x, N)으로 그대로 옮겨 두 번째 인자(N)가 조용히 무시되던 버그
(STEP 28-139에서 확정: bmi-calculator 실제 표시값이 22.49 대신 22가 됨)를
수정한 결과를 검증한다.

수정 내용:
  - templates/calculators/assets/components.js에 공통 helper pyRound(value, digits)
    추가. Math.round(x * 10**N) / 10**N 방식은 채택하지 않음 — 1.005 같은 값에서
    이진 부동소수점 곱셈 오차로 잘못된 결과가 나오는 것으로 알려진 문제가 있음.
    대신 지수 표기 문자열 변환("1.005e2")으로 소수점을 옮겨 다시 파싱한다.
  - modules/app_generator.py::_to_js()는 round(x, N)(2-인자, 괄호 중첩까지 고려한
    실제 스캔)만 pyRound(x, N)으로 바꾼다. round(x)(1-인자)는 그대로 Math.round(x)로
    변환되어 기존 동작이 완전히 보존된다.

이 테스트는 실제 파일(components.js, _to_js())을 그대로 사용한다 — Python
재구현이 아니다.
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

from modules.app_generator import _to_js  # noqa: E402


def _node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _node_available(), reason="Node.js 미설치 환경 — 스킵")


# ═══════════════════════════════════════════════════════════════════════════
# A. _to_js() 변환 자체 검증 (Python, Node 불필요)
# ═══════════════════════════════════════════════════════════════════════════

def test_single_arg_round_maps_to_math_round():
    """round(x)(1-인자)는 기존과 동일하게 Math.round(x)로 변환되어야 한다."""
    assert _to_js("round(22.49)") == "Math.round(22.49)"


def test_two_arg_round_maps_to_pyround():
    assert _to_js("round(x, 2)") == "pyRound(x, 2)"


def test_nested_parentheses_expression_handled_correctly():
    """BMI 실제 formula와 동일한 중첩 괄호 표현이 정확히 pyRound로 변환되는지."""
    expr = "round(weight_kg / ((height_cm / 100) ** 2), 2)"
    assert _to_js(expr) == "pyRound(weight_kg / ((height_cm / 100) ** 2), 2)"


def test_round_nested_inside_other_function():
    """round(...)가 다른 함수(min)의 인자로 중첩되어도 top-level 콤마만 정확히 인식."""
    assert _to_js("min(round(a,2), round(b,2))") == "Math.min(pyRound(a,2), pyRound(b,2))"


def test_mixed_one_and_two_arg_round_in_same_expression():
    assert _to_js("round(a) + round(b, 3)") == "Math.round(a) + pyRound(b, 3)"


def test_similarly_named_functions_not_matched():
    """round와 이름이 겹치는 다른 식별자(not_round, xround)는 건드리지 않는다."""
    assert _to_js("not_round(x, 2)") == "not_round(x, 2)"
    assert _to_js("xround(x, 2)") == "xround(x, 2)"


def test_other_js_func_mappings_unaffected():
    """min/max/abs/int/float 매핑과 // 처리는 이번 변경과 무관하게 그대로 동작."""
    assert _to_js("min(a, b)") == "Math.min(a, b)"
    assert _to_js("max(a, b)") == "Math.max(a, b)"
    assert _to_js("abs(a)") == "Math.abs(a)"
    assert _to_js("int(a)") == "Math.trunc(a)"
    assert _to_js("float(a)") == "Number(a)"
    assert _to_js("a // 2") == "Math.floor(a / 2)"


# ═══════════════════════════════════════════════════════════════════════════
# B. 실제 pyRound() 실행(Node, 실제 components.js 파일 그대로 사용)
# ═══════════════════════════════════════════════════════════════════════════

def _run_pyround(value, digits) -> float:
    src = COMPONENTS_JS.read_text(encoding="utf-8")
    harness = (
        _dom_stub()
        + src
        + f"\nprocess.stdout.write(JSON.stringify(window.pyRound({json.dumps(value)}, {json.dumps(digits)})));\n"
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        import os
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(harness)
        r = subprocess.run(["node", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
        assert r.returncode == 0, f"Node 실행 오류: {r.stderr}"
        return json.loads(r.stdout.strip())
    finally:
        try:
            import os
            os.unlink(path)
        except Exception:
            pass


@pytest.mark.parametrize("value,digits,expected", [
    (22.49, 2, 22.49),
    (1.2345, 2, 1.23),
    (123.4567, 3, 123.457),
    (-1.2345, 2, -1.23),
    (0, 2, 0),
])
def test_pyround_matches_python_round(value, digits, expected):
    got = _run_pyround(value, digits)
    assert abs(got - expected) < 1e-9, f"pyRound({value}, {digits}) = {got}, expected {expected}"


def test_pyround_1005_floating_point_boundary_case():
    """정책 명시: 1.005는 이진 부동소수점으로 정확히 표현되지 않아 순수
    곱셈 방식(Math.round(x*100)/100)에서는 1.01이 아니라 1이 되는 것으로
    잘 알려진 문제가 있다. pyRound()는 지수 표기 문자열 변환으로 이를
    올바르게 1.01로 처리한다(Python round(1.005, 2)도 부동소수점 표현상
    1.0049999999999999...에 가깝게 저장되어 실제로는 1.0을 반환하지만,
    이 프로젝트에서는 "10진 리터럴 그대로 반올림"을 pyRound()의 명시적
    정책으로 채택한다 — Python과 완전히 동일한 이진 표현 재현을 목표로
    하지 않음)."""
    got = _run_pyround(1.005, 2)
    assert got == 1.01, f"1.005 경계값 처리 실패: got {got}, expected 1.01"


def test_pyround_single_arg_default_zero_digits():
    """digits 인자를 생략하면 정수로 반올림(기존 round(x) 동작과 동일한 결과)."""
    got = _run_pyround(22.49, 0)
    assert got == 22


# ═══════════════════════════════════════════════════════════════════════════
# C. 실제 계산기(BMI) 회귀 — 실제 generate_js() 전체 번들을 Node로 실행
# ═══════════════════════════════════════════════════════════════════════════

def _dom_stub() -> str:
    return (
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


def _generate_js_for(slug: str) -> str:
    from modules.config_loader import load_config
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules.app_generator import generate_js

    cfg = load_config()
    repo = CalculatorRepository(get_db_adapter(cfg))
    calc = repo.get_by_slug(slug)
    return generate_js(calc, cfg)


def _run_compute_result(slug: str, inputs: dict):
    harness = (
        _dom_stub() + "\n" + _generate_js_for(slug) + "\n"
        + f"process.stdout.write(JSON.stringify(window.computeResult({json.dumps(inputs)})));\n"
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        import os
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(harness)
        r = subprocess.run(["node", path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
        assert r.returncode == 0, f"Node 실행 오류: {r.stderr}"
        return json.loads(r.stdout.strip()) if r.stdout.strip() != "null" else None
    finally:
        try:
            import os
            os.unlink(path)
        except Exception:
            pass


def test_bmi_real_compute_result_170_65_is_22_49():
    out = _run_compute_result("bmi-calculator", {"height_cm": 170, "weight_kg": 65})
    assert out["bmi"] == 22.49


def test_bmi_validation_guard_unaffected():
    """이번 STEP은 round(x,N) 정밀도만 다루며 validation 로직은 건드리지 않는다."""
    assert _run_compute_result("bmi-calculator", {"height_cm": 0, "weight_kg": 65}) is None
    assert _run_compute_result("bmi-calculator", {"height_cm": 49, "weight_kg": 65}) is None
    out = _run_compute_result("bmi-calculator", {"height_cm": 50, "weight_kg": 65})
    assert out is not None and out["bmi"] == 260.0


# ═══════════════════════════════════════════════════════════════════════════
# D. round(x,N) 미사용 계산기 — 생성 JS(_compute_js) 무변경 확인(DB 전수)
# ═══════════════════════════════════════════════════════════════════════════

def test_round_unused_calculators_unaffected():
    """DB의 모든 계산기 중 bmi-calculator를 제외한 전부는 formula에
    round(x,N) 2-인자 호출이 없어야 하며(STEP 28-139에서 확인된 사실),
    실제 _compute_js() 생성 결과에 pyRound가 등장하지 않아야 한다 —
    즉 이번 변경이 이들에게는 완전한 no-op임을 실제 생성 결과로 확인한다.

    자동차_취등록세_계산기는 예외다(STEP 28-193/196): slug 조건부 완전
    커스텀 분기에서 원(₩) 단위 반올림 오차 제거를 위해 pyRound를 정당하게
    사용하는 두 번째 사례이며(BMI와 마찬가지로 formula 필드 기반이 아니라
    코드 분기 기반), "BMI만 pyRound를 쓴다"는 이 테스트의 전제가 STEP
    28-139 시점의 관찰(당시 사실)이었을 뿐 설계상 불변식이 아니었음이
    STEP 28-194에서 확인됐다. 다른 계산기에 대한 보호는 그대로 유지한다."""
    from modules.config_loader import load_config
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    from modules.app_generator import _compute_js

    cfg = load_config()
    repo = CalculatorRepository(get_db_adapter(cfg))
    all_calcs = repo.get_all()

    checked = 0
    for calc in all_calcs:
        slug = calc.get("slug", "")
        if slug in ("bmi-calculator", "자동차_취등록세_계산기"):
            continue
        js = _compute_js(calc)
        assert "pyRound" not in js, f"{slug}의 생성 JS에 예상치 못한 pyRound 등장: {js[:200]}"
        checked += 1
    assert checked >= 15, f"검사 대상 계산기가 예상보다 적음: {checked}건"


# ═══════════════════════════════════════════════════════════════════════════
# registry 무변경 확인
# ═══════════════════════════════════════════════════════════════════════════

def test_registry_untouched_by_this_step():
    result = subprocess.run(
        ["git", "status", "--short", "--", "docs/registry_auto.yaml", "docs/registry"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.stdout.strip() == "", (
        f"이번 STEP은 round(x,N) 정밀도만 다뤄야 하는데 registry가 변경됨: {result.stdout}"
    )
