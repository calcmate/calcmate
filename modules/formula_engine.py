# -*- coding: utf-8 -*-
"""
modules/formula_engine.py — 계산기 수식 실행 엔진 (SalaryMate 확장, 신규)

JSON 기반 수식 정의를 안전하게 실행한다.
보안: 파이썬 eval() 미사용. ast로 파싱 후 화이트리스트 노드/연산자/함수만 평가.

수식 정의 예시:
{
  "calculator_id": "retirement_pay",
  "inputs": {"monthly_salary": "number", "years": "number"},
  "formula": "(monthly_salary / 30) * 30 * years"          # 단일 출력
}
또는 다중 출력:
  "formula": {"severance_pay": "(monthly_salary/30)*30*years"}

데이터 접근은 Repository(CalculatorRepository) 경유. Sheets 직접 접근 없음.
"""
import ast
import json
import operator

# custom compute slugs: _compute_js() 전용 분기 사용, formula 필드 의도적 공백
# validate_formula()에서 formula 검증을 건너뛰고 compute handler 존재만 확인한다.
CUSTOM_COMPUTE_SLUGS: frozenset = frozenset({
    "연말정산_환급액_계산기",
    "육아휴직_급여_계산기",
    "loan-repayment-calculator",
})

from .logger import get_logger

LOG = get_logger()

# 허용 연산자
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
# 허용 함수
_FUNCS = {"min": min, "max": max, "round": round, "abs": abs, "int": int, "float": float}
_MAX_POW = 8   # 거듭제곱 폭주 방지


class FormulaError(Exception):
    pass


def _eval(node, vars: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, vars)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise FormulaError(f"허용되지 않은 상수: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise FormulaError(f"허용되지 않은 연산자: {type(node.op).__name__}")
        left, right = _eval(node.left, vars), _eval(node.right, vars)
        if isinstance(node.op, ast.Pow) and (abs(right) > _MAX_POW):
            raise FormulaError("거듭제곱 지수 한도 초과")
        try:
            return op(left, right)
        except ZeroDivisionError:
            raise FormulaError("0으로 나눌 수 없는 입력값입니다")
    if isinstance(node, ast.UnaryOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise FormulaError("허용되지 않은 단항 연산자")
        return op(_eval(node.operand, vars))
    if isinstance(node, ast.Name):
        if node.id in vars:
            return vars[node.id]
        raise FormulaError(f"미정의 변수: {node.id}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise FormulaError("허용되지 않은 함수 호출")
        return _FUNCS[node.func.id](*[_eval(a, vars) for a in node.args])
    raise FormulaError(f"허용되지 않은 식: {type(node).__name__}")


def _coerce_numbers(inputs: dict) -> dict:
    out = {}
    for k, v in (inputs or {}).items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def _eval_expr(expr: str, inputs: dict):
    tree = ast.parse(str(expr), mode="eval")
    return _eval(tree, inputs)


def execute_formula(formula, inputs: dict, output_schema=None) -> dict:
    """수식 실행. formula는 str(단일) 또는 dict(출력키→식). 반환: {출력키: 값}."""
    vars_ = _coerce_numbers(inputs)
    results = {}
    if isinstance(formula, dict):
        for out_key, expr in formula.items():
            results[out_key] = round(float(_eval_expr(expr, vars_)), 2)
    else:
        # 단일 식 → output_schema 첫 키(없으면 'result')에 매핑
        keys = list((output_schema or {}).keys()) if isinstance(output_schema, dict) else []
        out_key = keys[0] if keys else "result"
        results[out_key] = round(float(_eval_expr(formula, vars_)), 2)
    return results


def validate_formula(formula, inputs_schema=None, slug: str | None = None) -> tuple:
    """수식 안전성/변수 검증. (ok, message). 실제 계산은 더미값(1)으로 시도.

    slug가 CUSTOM_COMPUTE_SLUGS에 포함되면 formula 검증을 건너뛰고
    validate_compute_handler()로 핸들러 존재만 확인한다.
    """
    if slug and slug in CUSTOM_COMPUTE_SLUGS:
        return validate_compute_handler(slug)
    # DB에 JSON 문자열로 저장된 dict 수식을 파싱
    if isinstance(formula, str) and formula.strip().startswith("{"):
        try:
            formula = json.loads(formula)
        except json.JSONDecodeError:
            pass
    try:
        exprs = list(formula.values()) if isinstance(formula, dict) else [formula]
        allowed = set((inputs_schema or {}).keys())
        for expr in exprs:
            tree = ast.parse(str(expr), mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and allowed and node.id not in allowed:
                    # 허용된 내장 함수명(min, max, abs 등)은 변수 검증 대상에서 제외
                    if node.id not in _FUNCS:
                        return False, f"input_schema에 없는 변수: {node.id}"
                if isinstance(node, (ast.Attribute, ast.Subscript, ast.Lambda,
                                     ast.ListComp, ast.comprehension)):
                    return False, f"허용되지 않은 구문: {type(node).__name__}"
        dummy = {k: 1.0 for k in (allowed or [])}
        execute_formula(formula, dummy, inputs_schema if isinstance(inputs_schema, dict) else None)
        return True, "OK"
    except Exception as e:
        return False, str(e)


# ── STEP42: input_schema/output_schema "값" 검증 ──────────────────────────
# STEP41에서 확인된 공백: validate_formula()는 formula가 참조하는 변수명이
# input_schema의 '키'에 있는지만 확인하고, 그 '값'(타입 선언)이 실제로 유효한
# 표현인지는 전혀 검증하지 않았다. 그 결과 App Factory가 GPT 응답을 그대로
# 저장하는 경로에서 값 자리에 숫자 리터럴(예: 0, 0.0)이 들어가도 아무 제지 없이
# calculators 테이블에 저장됐다(bmi-calculator, 연금저축_irp_세액공제_계산기).
#
# 아래 허용 어휘는 새로 만든 것이 아니라 STEP42 §3에서 현재 SQLite 19개
# calculators 행 전수 조사로 실제 사용 중인 값만 추출해 확정했다:
#   평탄형(문자열): "number" | "integer" | "boolean" | "date" | "select:키=라벨,..."
#   dict형(Tier2-B류, military-discharge-date 실측):
#     입력  {"type": <위 스칼라 중 하나 또는 "select">, "label": str, ["options": list]}
#     출력  {"label": str}  (출력 dict 항목엔 "type"이 아예 없는 것이 현재 정상 형태)
_SCALAR_TYPES = {"number", "integer", "boolean", "date"}
_SELECT_PREFIX = "select:"


def _is_valid_select_string(value: str) -> bool:
    """"select:1=매매·교환,2=전세·월세" 형태(콤마로 구분된 key=label 쌍)인지 확인."""
    body = value[len(_SELECT_PREFIX):]
    if not body:
        return False
    for pair in body.split(","):
        if "=" not in pair:
            return False
        key, label = pair.split("=", 1)
        if not key.strip() or not label.strip():
            return False
    return True


def _is_valid_scalar_value(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value in _SCALAR_TYPES:
        return True
    if value.startswith(_SELECT_PREFIX):
        return _is_valid_select_string(value)
    return False


def _is_valid_dict_entry(value: dict, require_type: bool) -> bool:
    label = value.get("label")
    if not isinstance(label, str) or not label.strip():
        return False
    t = value.get("type")
    if t is None:
        return not require_type
    if not isinstance(t, str) or (t not in _SCALAR_TYPES and t != "select"):
        return False
    if t == "select":
        options = value.get("options")
        if not isinstance(options, list) or not options:
            return False
    return True


def _validate_schema_dict(schema, label: str, dict_requires_type: bool) -> tuple:
    if not isinstance(schema, dict) or not schema:
        return False, f"{label}이 비어있거나 dict 형태가 아님: {schema!r}"
    for field_name, value in schema.items():
        if isinstance(value, dict):
            if not _is_valid_dict_entry(value, require_type=dict_requires_type):
                return False, f"{label}.{field_name}: 지원되지 않는 dict 구조({value!r})"
        elif not _is_valid_scalar_value(value):
            return False, (
                f"{label}.{field_name}: 지원되지 않는 값({value!r}) — "
                f"허용값은 {sorted(_SCALAR_TYPES)} 중 하나, 'select:키=라벨,...' 형태, "
                f"또는 {{'type':..., 'label':...}} dict 형태여야 함"
            )
    return True, "OK"


def validate_calculator_schema(input_schema, output_schema) -> tuple:
    """input_schema/output_schema의 각 '값'이 실제로 지원되는 형태인지 검증한다.
    (ok, message) 반환. GPT 재호출 없음 — 저장을 막는 것이 유일한 목적이며
    원본 spec dict는 변경하지 않는다(정규화/자동 수정 없음).

    input_schema는 dict 항목에 "type"이 필수(military-discharge-date류),
    output_schema는 dict 항목에 "type"이 없어도 된다(실측: label만 존재)."""
    if isinstance(input_schema, str):
        try:
            input_schema = json.loads(input_schema) if input_schema else {}
        except Exception:
            return False, f"input_schema JSON 파싱 실패: {input_schema!r}"
    if isinstance(output_schema, str):
        try:
            output_schema = json.loads(output_schema) if output_schema else {}
        except Exception:
            return False, f"output_schema JSON 파싱 실패: {output_schema!r}"

    ok, msg = _validate_schema_dict(input_schema, "input_schema", dict_requires_type=True)
    if not ok:
        return ok, msg
    return _validate_schema_dict(output_schema, "output_schema", dict_requires_type=False)


def validate_compute_handler(slug: str) -> tuple:
    """CUSTOM_COMPUTE_SLUGS의 _compute_js 핸들러 존재 및 정상 생성 확인."""
    try:
        from modules.app_generator import _compute_js, _registry
        reg_entry = dict(_registry().get(slug) or {})
        reg_entry["slug"] = slug
        js = _compute_js(reg_entry)
        if js and len(js) > 100:
            return True, f"OK (custom handler: {slug})"
        return False, f"compute handler 빈 응답: {slug}"
    except Exception as e:
        return False, f"compute handler 오류: {e}"


# ── Contract 검증 지원 ────────────────────────────────────────────

def detect_schema_drift(contract: dict, ai_app: dict) -> dict:
    """Contract 확정 필드명 vs AI 생성 결과 필드명 비교.

    contract: build_contract() 반환 dict — input_fields/output_fields 리스트
    ai_app:   generate_app() 반환 dict — input_schema/output_schema dict
    반환: {
        "drifted": bool,
        "input_changes":  [{"type": "input_missing"|"input_extra",  "contract": str|None, "ai": str|None}],
        "output_changes": [{"type": "output_missing"|"output_extra", "contract": str|None, "ai": str|None}],
        "changes": (input_changes + output_changes 합산),
    }
    """
    contract_inputs = set(contract.get("input_fields") or [])
    contract_outputs = set(contract.get("output_fields") or [])

    raw_in = ai_app.get("input_schema") or {}
    raw_out = ai_app.get("output_schema") or {}
    ai_inputs = set(raw_in.keys()) if isinstance(raw_in, dict) else set()
    ai_outputs = set(raw_out.keys()) if isinstance(raw_out, dict) else set()

    input_changes = []
    for f in sorted(contract_inputs - ai_inputs):
        input_changes.append({"type": "input_missing", "contract": f, "ai": None})
    if contract_inputs:  # Contract에 필드 명세가 있을 때만 extra 감지
        for f in sorted(ai_inputs - contract_inputs):
            input_changes.append({"type": "input_extra", "contract": None, "ai": f})

    output_changes = []
    for f in sorted(contract_outputs - ai_outputs):
        output_changes.append({"type": "output_missing", "contract": f, "ai": None})
    if contract_outputs:  # Contract에 필드 명세가 있을 때만 extra 감지
        for f in sorted(ai_outputs - contract_outputs):
            output_changes.append({"type": "output_extra", "contract": None, "ai": f})

    all_changes = input_changes + output_changes
    return {
        "drifted": bool(all_changes),
        "input_changes": input_changes,
        "output_changes": output_changes,
        "changes": all_changes,
    }


def validate_formula_with_samples(
    formula, input_schema: dict, test_cases: list | None = None
) -> dict:
    """formula 검증 + 샘플 입력값으로 실제 계산 결과 반환.

    formula:      str(단일 식) 또는 dict(출력키 → 식)
    input_schema: {필드명: 타입 문자열 또는 dict} — validate_formula() 전달용
    test_cases:   [{"input": {...}, "expected": {...}}]  Contract에 기록된 검증 케이스

    반환: {
        "valid": bool,
        "message": str,
        "sample_results": [{"input": {}, "output": {}, "expected": {}, "match": bool|None}]
    }
    """
    ok, msg = validate_formula(formula, input_schema)
    result: dict = {"valid": ok, "message": msg, "sample_results": []}
    if ok and test_cases:
        for tc in test_cases:
            inp = dict(tc.get("input") or {})
            expected = tc.get("expected")
            try:
                # output_schema=None: dict formula → 수식 키, str formula → "result"
                output = execute_formula(formula, inp, None)
                result["sample_results"].append({
                    "input": inp,
                    "output": output,
                    "expected": expected,
                    "match": (output == expected) if expected is not None else None,
                })
            except Exception as e:
                result["sample_results"].append({
                    "input": inp, "output": None,
                    "expected": expected, "match": False, "error": str(e),
                })
    return result


# ── Repository 연동 (Sheets 직접 접근 금지) ───────────────────────
def _repo(cfg: dict):
    from adapters.db.factory import get_db_adapter
    from repositories.calculator_repository import CalculatorRepository
    return CalculatorRepository(get_db_adapter(cfg))


def load_formula(cfg: dict, calculator_id: str) -> dict:
    """calculators 시트에서 수식 정의 로드 → {calculator_id, inputs, output_schema, formula}."""
    calc = _repo(cfg).get_by_id(calculator_id)
    if not calc:
        raise FormulaError(f"계산기 없음: {calculator_id}")

    def _pj(v, default):
        if isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(v) if v else default
        except Exception:
            return default
    
    if calculator_id == "육아휴직_급여_계산기":
        # 육아휴직 계산기는 커스텀 로직을 직접 호출하므로, formula 필드를 특별 처리
        return {
            "calculator_id": calculator_id,
            "inputs": _pj(calc.get("input_schema"), {}),
            "output_schema": _pj(calc.get("output_schema"), {}),
            "formula": "modules.parental_leave_calculator.calculate_parental_leave_allowance", # 함수 경로 저장
        }
    return {
        "calculator_id": calculator_id,
        "inputs": _pj(calc.get("input_schema"), {}),
        "output_schema": _pj(calc.get("output_schema"), {}),
        "formula": _pj(calc.get("formula"), calc.get("formula", "")),
    }


def save_formula(cfg: dict, calculator_id: str, formula) -> None:
    """수식을 calculators.formula에 저장(문자열/JSON)."""
    val = formula if isinstance(formula, str) else json.dumps(formula, ensure_ascii=False)
    _repo(cfg).update(calculator_id, {"formula": val})
    LOG.info("수식 저장: %s", calculator_id)
