# -*- coding: utf-8 -*-
"""
modules.factory.engine.adapters.formualizer_adapter — Formualizer Adapter

CalcMate Engine Contract → formualizer 변환 계층.
Reference Engine 후보로 사용.
"""

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import re
import math

import formualizer as fz

from modules.factory.engine import (
    CalculationEngine,
    CalculationContext,
    CalculationResult,
    CalculationStatus,
    FailureCode,
    CalculationError,
)
from modules.factory.semantics import (
    CalculationSemantics, FormulaAST, Definition, Precondition,
    ExceptionRule, RoundingPolicy, RoundingMode, ReconciliationRule,
    ReconciliationRuleType, TemporalRule, DecisionNode, ParameterBinding,
)


class FormualizerAdapter(CalculationEngine):
    """formualizer를 CalcMate Engine Contract에 맞게 래핑 (Reference Engine용)."""

    @property
    def engine_name(self) -> str:
        return "formualizer"

    @property
    def engine_version(self) -> str:
        return "0.10.1"  # formualizer.__version__ 없음

    def get_supported_features(self) -> list[str]:
        return [
            "formula_parsing",
            "ast_generation",
            "excel_functions",
            "dependency_graph",
            "decimal_precision",
            "financial_functions",
            "workbook_evaluation",
            "definition_evaluation",
            "precondition_checking",
            "rounding_policy",
            "exception_handling",
            "parameter_binding",
        ]

    def _col_to_cell_ref(self, col: int) -> str:
        """숫자 열 번호를 Excel 열 참조로 변환 (1=A, 2=B, ..., 27=AA)."""
        result = ""
        while col > 0:
            col -= 1
            result = chr(65 + (col % 26)) + result
            col //= 26
        return result

    def _apply_rounding_float(self, value: float, policy: RoundingPolicy) -> float:
        """단일 float 값에 RoundingPolicy 적용"""
        if policy.precision < 0:
            return value
        factor = 10 ** policy.precision
        mode = policy.mode
        if mode == RoundingMode.HALF_UP:
            return math.floor(value * factor + 0.5) / factor
        elif mode == RoundingMode.HALF_EVEN:
            return round(value, policy.precision)
        elif mode == RoundingMode.HALF_DOWN:
            return math.floor(value * factor + 0.499999999999) / factor
        elif mode == RoundingMode.UP:
            return math.ceil(value * factor) / factor
        elif mode == RoundingMode.DOWN:
            return math.floor(value * factor) / factor
        elif mode == RoundingMode.CEILING:
            return math.ceil(value * factor) / factor if value >= 0 else math.floor(value * factor) / factor
        elif mode == RoundingMode.FLOOR:
            return math.floor(value * factor) / factor if value >= 0 else math.ceil(value * factor) / factor
        return value

    def _evaluate_preconditions(self, semantics: CalculationSemantics, inputs: dict[str, Any]) -> list[CalculationError]:
        """Precondition 평가"""
        errors = []
        for precond in semantics.preconditions:
            try:
                # Simple expression evaluation for preconditions
                # Replace variable names with values
                expr = precond.expression
                for var_name, value in inputs.items():
                    expr = re.sub(r'\b' + re.escape(var_name) + r'\b', str(value), expr)

                # Evaluate boolean expression (simple eval for basic comparisons)
                try:
                    result = eval(expr, {"__builtins__": {}}, {})
                    if not result:
                        errors.append(CalculationError(
                            code=FailureCode.INVALID_INPUT,
                            user_message="사전 조건 '{}' 실패: {}".format(precond.name, precond.expression),
                            diagnostic="Precondition '{}' failed: {}".format(precond.name, precond.expression),
                            field_name=precond.name,
                        ))
                except Exception as e:
                    errors.append(CalculationError(
                        code=FailureCode.CALCULATION_ERROR,
                        user_message="사전 조건 '{}' 평가 오류: {}".format(precond.name, e),
                        diagnostic="Precondition evaluation error: {}".format(e),
                        field_name=precond.name,
                    ))
            except Exception as e:
                errors.append(CalculationError(
                    code=FailureCode.CALCULATION_ERROR,
                    user_message="사전 조건 '{}' 처리 오류: {}".format(precond.name, e),
                    diagnostic="Precondition processing error: {}".format(e),
                    field_name=precond.name,
                ))
        return errors

    def _apply_exceptions(self, semantics: CalculationSemantics, inputs: dict[str, Any], outputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Exception 규칙 적용"""
        warnings = []
        for exc in semantics.exceptions:
            try:
                expr = exc.condition
                for var_name, value in inputs.items():
                    expr = re.sub(r'\b' + re.escape(var_name) + r'\b', str(value), expr)

                try:
                    if eval(expr, {"__builtins__": {}}, {}):
                        # Exception triggered
                        if exc.action == "use_fallback" and exc.fallback_value is not None:
                            # Find output to apply fallback to
                            for key in outputs:
                                if isinstance(outputs[key], (int, float)):
                                    outputs[key] = float(exc.fallback_value)
                                    warnings.append("Exception '{}' triggered: applied fallback {} to output".format(exc.name, exc.fallback_value))
                                    break
                        elif exc.action == "skip":
                            warnings.append("Exception '{}' triggered: calculation skipped".format(exc.name))
                        elif exc.action == "raise_error":
                            return outputs, ["Exception '{}' triggered: {}".format(exc.name, exc.description or "Exception condition met")]
                except Exception:
                    pass  # Exception condition evaluation failed, ignore
            except Exception:
                pass  # Exception processing failed, ignore
        return outputs, warnings

    def _apply_rounding(self, outputs: dict[str, Any], policy: RoundingPolicy) -> dict[str, Any]:
        """RoundingPolicy 적용"""
        if policy.precision < 0:
            return outputs
        result = {}
        for key, value in outputs.items():
            if isinstance(value, (int, float)):
                result[key] = self._apply_rounding_float(value, policy)
            else:
                result[key] = value
        return result

    def validate_inputs(
        self,
        semantics: CalculationSemantics,
        inputs: dict[str, Any],
    ) -> tuple[bool, list]:
        """입력값 사전 검증 (precondition 포함)."""
        # 기본 formula dependency 검증
        from modules.factory.engine import CalculationError, FailureCode
        errors = []

        for formula in semantics.formulas:
            for dep in formula.dependencies:
                if dep not in inputs:
                    errors.append(CalculationError(
                        code=FailureCode.MISSING_PARAMETER,
                        user_message="수식 '{}'에 필요한 변수 누락: {}".format(formula.expression, dep),
                        diagnostic="Missing variable for formula: {}".format(dep),
                        field_name=dep,
                    ))

        # Precondition 검증
        precond_errors = self._evaluate_preconditions(semantics, inputs)
        errors.extend(precond_errors)

        return len(errors) == 0, errors

    def calculate(
        self,
        semantics: CalculationSemantics,
        inputs: dict[str, Any],
        context: Any,
        parameters: dict[str, Any],
        evidence: dict[str, Any],
    ) -> Any:
        """formualizer로 수식 계산 실행."""
        import time
        start_time = time.perf_counter()

        try:
            # Workbook 생성
            wb = fz.Workbook()
            sheet = wb.sheet("CalcSheet")

            # Parameter binding: in-memory parameters를 inputs에 병합
            merged_inputs = dict(inputs)
            for param in semantics.parameters:
                if param.parameter_id in parameters:
                    merged_inputs[param.semantics_var] = parameters[param.parameter_id]
                elif param.fallback_value is not None:
                    merged_inputs[param.semantics_var] = param.fallback_value

            # Precondition 검증
            precond_errors = self._evaluate_preconditions(semantics, merged_inputs)
            if precond_errors:
                execution_time_ms = (time.perf_counter() - start_time) * 1000
                return CalculationResult(
                    status=CalculationStatus.FAILURE,
                    outputs={},
                    schedule=[],
                    diagnostics=[],
                    parameters_used={k: str(v) for k, v in merged_inputs.items()},
                    evidence_used=[],
                    engine_version=self.engine_version,
                    semantics_version=semantics.version,
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                    errors=precond_errors,
                )

            # Workbook 생성
            wb = fz.Workbook()
            sheet = wb.sheet("CalcSheet")

            # 입력값을 시트에 설정하고 변수명→셀참조 매핑 생성 (1-based indexing)
            row = 1
            col = 1
            var_to_cell = {}
            for name, value in merged_inputs.items():
                sheet.set_value(row, col, value)
                var_to_cell[name] = self._col_to_cell_ref(col) + str(row)
                col += 1

            # 수식에서 변수명을 셀 참조로 치환하는 함수
            def substitute_vars(expr: str) -> str:
                for var_name, cell_ref in var_to_cell.items():
                    expr = re.sub(r'\b' + re.escape(var_name) + r'\b', cell_ref, expr)
                return expr

            outputs = {}
            diagnostics = []

            # definitions 먼저 평가 (중간 계산값) - 의존성 순서대로
            # 정의는 내부 계산용이므로 outputs에 포함하지 않음 (var_to_cell에 셀 참조로 등록)
            for definition in semantics.definitions:
                expr = definition.formula.expression
                expr_substituted = self._substitute_vars_in_expr(expr, var_to_cell)
                sheet.set_formula(row, col, expr_substituted)
                result = wb.evaluate_cell("CalcSheet", row, col)
                if isinstance(result, (int, float)):
                    var_to_cell[definition.name] = self._col_to_cell_ref(col) + str(row)
                elif isinstance(result, Decimal):
                    var_to_cell[definition.name] = self._col_to_cell_ref(col) + str(row)
                else:
                    var_to_cell[definition.name] = self._col_to_cell_ref(col) + str(row)
                diagnostics.append("Definition {}: {} = {} (substituted: {})".format(definition.name, expr, result, expr_substituted))
                col += 1

            # 수식 설정 및 평가
            for formula_ast in semantics.formulas:
                expr = formula_ast.expression
                output_name = "result"
                if "=" in expr:
                    output_name = expr.split("=")[0].strip()
                    expr = expr.split("=", 1)[1].strip()

                expr_substituted = self._substitute_vars_in_expr(expr, var_to_cell)
                sheet.set_formula(row, col, expr_substituted)
                result = wb.evaluate_cell("CalcSheet", row, col)

                if isinstance(result, (int, float)):
                    outputs[output_name] = float(result)
                elif isinstance(result, Decimal):
                    outputs[output_name] = float(result)
                else:
                    outputs[output_name] = result

                diagnostics.append("Evaluated: {} = {} (substituted: {})".format(formula_ast.expression, result, expr_substituted))
                col += 1

            # Exception 처리
            outputs, exception_warnings = self._apply_exceptions(semantics, merged_inputs, outputs)
            diagnostics.extend(exception_warnings)

            # Rounding 적용
            if semantics.rounding and semantics.rounding.precision >= 0:
                outputs = self._apply_rounding(outputs, semantics.rounding)
                diagnostics.append("Applied rounding: {} precision {}".format(semantics.rounding.mode.value, semantics.rounding.precision))

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            return CalculationResult(
                status=CalculationStatus.SUCCESS,
                outputs=outputs,
                schedule=[],
                diagnostics=diagnostics,
                parameters_used={k: str(v) for k, v in merged_inputs.items()},
                evidence_used=[],
                engine_version=self.engine_version,
                semantics_version=semantics.version,
                execution_time_ms=execution_time_ms,
                errors=[],
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return CalculationResult(
                status=CalculationStatus.FAILURE,
                outputs={},
                schedule=[],
                diagnostics=["formualizer error: {}".format(e)],
                parameters_used={},
                evidence_used=[],
                engine_version=self.engine_version,
                semantics_version=semantics.version,
                execution_time_ms=execution_time_ms,
                errors=[CalculationError(
                    code=FailureCode.CALCULATION_ERROR,
                    user_message="수식 계산 중 오류가 발생했습니다",
                    diagnostic=str(e),
                )],
            )

    def _substitute_vars_in_expr(self, expr: str, var_to_cell: dict) -> str:
        for var_name, cell_ref in var_to_cell.items():
            expr = re.sub(r'\b' + re.escape(var_name) + r'\b', cell_ref, expr)
        return expr


# EngineFactory 등록용
def register_formualizer_adapter():
    from modules.factory.engine import EngineFactory
    EngineFactory.register_adapter("formualizer", FormualizerAdapter)


if __name__ == "__main__":
    # 간단 테스트
    adapter = FormualizerAdapter()
    print("Engine: {} v{}".format(adapter.engine_name, adapter.engine_version))
    print("Features: {}".format(adapter.get_supported_features()))

    from modules.factory.semantics import CalculationSemantics, FormulaAST
    from modules.factory.engine import CalculationContext

    sem = CalculationSemantics(
        calculator_id="test-percent",
        version="1.0.0",
        formulas=[
            FormulaAST(expression="result = base_value * percentage / 100", dependencies=["base_value", "percentage"]),
        ],
    )
    ctx = CalculationContext()

    inputs = {
        "base_value": 1000,
        "percentage": 10,
    }

    adapter = FormualizerAdapter()
    valid, errors = adapter.validate_inputs(sem, inputs)
    print("Validation: {}, errors: {}".format(valid, errors))

    result = adapter.calculate(sem, inputs, ctx, {}, {})
    print("Status: {}".format(result.status))
    print("Outputs: {}".format(result.outputs))
    print("Diagnostics: {}".format(result.diagnostics))