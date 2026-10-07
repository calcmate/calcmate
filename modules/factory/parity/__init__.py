# -*- coding: utf-8 -*-
"""
modules.factory.parity — Parity Test Runner

Ground Truth → Reference Engine → Production Engine → Compare → Tolerance → PASS/FAIL
Reference와 Production이 동일한 코드에서 생성되지 않았는지 검증.
실패 시 자동 수정 금지 → HOLD.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from modules.factory.engine import CalculationEngine, CalculationResult, CalculationContext, CalculationStatus
from modules.factory.ground_truth import GroundTruthCase, GroundTruthSuite, get_ground_truth_registry


class ParityStatus(str, Enum):
    """패리티 테스트 결과 상태."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class ParityComparison:
    """단일 출력 필드에 대한 비교 결과."""
    field_name: str
    reference_value: Any
    production_value: Any
    tolerance: float
    passed: bool
    difference: float | None = None
    relative_diff: float | None = None

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "reference_value": self.reference_value,
            "production_value": self.production_value,
            "tolerance": self.tolerance,
            "passed": self.passed,
            "difference": self.difference,
            "relative_diff": self.relative_diff,
        }


@dataclass
class CaseParityResult:
    """단일 Ground Truth 케이스에 대한 패리티 결과."""
    case_id: str
    status: ParityStatus
    comparisons: list[ParityComparison] = field(default_factory=list)
    reference_result: CalculationResult | None = None
    production_result: CalculationResult | None = None
    error_message: str | None = None

    def all_passed(self) -> bool:
        return all(c.passed for c in self.comparisons)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "reference_success": self.reference_result.is_success() if self.reference_result else False,
            "production_success": self.production_result.is_success() if self.production_result else False,
            "error_message": self.error_message,
        }


@dataclass
class ParityReport:
    """전체 패리티 테스트 리포트."""
    report_id: str = field(default_factory=lambda: str(uuid4()))
    calculator_id: str = ""
    suite_id: str = ""
    reference_engine: str = ""
    production_engine: str = ""
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    skipped_cases: int = 0
    error_cases: int = 0
    case_results: list[CaseParityResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: date.today().isoformat())

    def overall_status(self) -> ParityStatus:
        if self.failed_cases > 0 or self.error_cases > 0:
            return ParityStatus.FAIL
        if self.passed_cases == self.total_cases:
            return ParityStatus.PASS
        return ParityStatus.SKIPPED

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "calculator_id": self.calculator_id,
            "suite_id": self.suite_id,
            "reference_engine": self.reference_engine,
            "production_engine": self.production_engine,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "skipped_cases": self.skipped_cases,
            "error_cases": self.error_cases,
            "overall_status": self.overall_status().value,
            "case_results": [r.to_dict() for r in self.case_results],
            "created_at": self.created_at,
        }


def compare_values(
    ref_val: Any,
    prod_val: Any,
    tolerance: float,
    field_name: str = "",
) -> ParityComparison:
    """두 값 비교 (숫자/문자열/불린/None 지원)."""
    # None 처리
    if ref_val is None and prod_val is None:
        return ParityComparison(field_name, ref_val, prod_val, tolerance, True, 0.0, 0.0)
    if ref_val is None or prod_val is None:
        return ParityComparison(field_name, ref_val, prod_val, tolerance, False)

    # 불린
    if isinstance(ref_val, bool) or isinstance(prod_val, bool):
        passed = bool(ref_val) == bool(prod_val)
        return ParityComparison(field_name, ref_val, prod_val, tolerance, passed)

    # 문자열
    if isinstance(ref_val, str) or isinstance(prod_val, str):
        passed = str(ref_val) == str(prod_val)
        return ParityComparison(field_name, ref_val, prod_val, tolerance, passed)

    # 숫자 비교
    try:
        ref_f = float(ref_val)
        prod_f = float(prod_val)
        diff = abs(ref_f - prod_f)
        rel_diff = diff / max(abs(ref_f), 1e-12) if ref_f != 0 else diff
        passed = diff <= tolerance
        return ParityComparison(
            field_name, ref_val, prod_val, tolerance, passed, diff, rel_diff
        )
    except (TypeError, ValueError):
        # 비교 불가 타입
        passed = ref_val == prod_val
        return ParityComparison(field_name, ref_val, prod_val, tolerance, passed)


def run_parity_test(
    suite: GroundTruthSuite,
    reference_engine: CalculationEngine,
    production_engine: CalculationEngine,
    semantics: "CalculationSemantics",
    parameters: dict[str, Any],
    evidence: dict[str, Any],
    context: CalculationContext | None = None,
    default_tolerance: float = 1e-9,
) -> ParityReport:
    """
    Ground Truth 스위트에 대해 Reference/Production 엔진 패리티 테스트 실행.

    Args:
        suite: Ground Truth 스위트
        reference_engine: Reference Engine 인스턴스
        production_engine: Production Engine 인스턴스
        semantics: 계산 의미론
        parameters: 바인딩된 파라미터 값들
        evidence: 증거 자료
        context: 계산 컨텍스트
        default_tolerance: 기본 허용 오차

    Returns:
        ParityReport: 전체 테스트 결과
    """
    if context is None:
        context = CalculationContext()

    report = ParityReport(
        calculator_id=suite.calculator_id,
        suite_id=suite.suite_id,
        reference_engine=reference_engine.engine_name,
        production_engine=production_engine.engine_name,
        total_cases=len(suite.cases),
    )

    for case in suite.cases:
        case_tolerance = case.tolerance if case.tolerance > 0 else default_tolerance
        case_result = CaseParityResult(case_id=case.id, status=ParityStatus.PASS)

        try:
            # Reference Engine 실행
            ref_result = reference_engine.calculate(
                semantics, case.inputs, context, parameters, evidence
            )
            case_result.reference_result = ref_result

            # Production Engine 실행
            prod_result = production_engine.calculate(
                semantics, case.inputs, context, parameters, evidence
            )
            case_result.production_result = prod_result

            # 양쪽 모두 성공해야 비교 가능
            if not ref_result.is_success() or not prod_result.is_success():
                case_result.status = ParityStatus.ERROR
                case_result.error_message = (
                    f"Reference success: {ref_result.is_success()}, "
                    f"Production success: {prod_result.is_success()}"
                )
                report.error_cases += 1
                report.case_results.append(case_result)
                continue

            # 출력 필드별 비교
            all_fields = set(ref_result.outputs.keys()) | set(prod_result.outputs.keys())
            all_passed = True

            for field_name in all_fields:
                ref_val = ref_result.outputs.get(field_name)
                prod_val = prod_result.outputs.get(field_name)
                expected_val = case.expected_outputs.get(field_name)

                # Ground Truth 기대값이 있으면 그걸 기준으로, 없으면 Reference를 기준으로
                if expected_val is not None:
                    comparison = compare_values(expected_val, prod_val, case_tolerance, field_name)
                    if not comparison.passed:
                        all_passed = False
                else:
                    comparison = compare_values(ref_val, prod_val, case_tolerance, field_name)
                    if not comparison.passed:
                        all_passed = False

                case_result.comparisons.append(comparison)

            # Schedule 비교 (있는 경우)
            if ref_result.schedule and prod_result.schedule:
                if len(ref_result.schedule) != len(prod_result.schedule):
                    all_passed = False
                    case_result.comparisons.append(ParityComparison(
                        "schedule_length",
                        len(ref_result.schedule),
                        len(prod_result.schedule),
                        0, False
                    ))
                else:
                    for i, (ref_row, prod_row) in enumerate(zip(ref_result.schedule, prod_result.schedule)):
                        for key in set(ref_row.keys()) | set(prod_row.keys()):
                            comparison = compare_values(
                                ref_row.get(key), prod_row.get(key), case_tolerance, f"schedule[{i}].{key}"
                            )
                            if not comparison.passed:
                                all_passed = False
                            case_result.comparisons.append(comparison)

            case_result.status = ParityStatus.PASS if all_passed else ParityStatus.FAIL
            if all_passed:
                report.passed_cases += 1
            else:
                report.failed_cases += 1

        except Exception as e:
            case_result.status = ParityStatus.ERROR
            case_result.error_message = str(e)
            report.error_cases += 1

        report.case_results.append(case_result)

    return report


class ParityRunner:
    """패리티 테스트 실행기 — 상태 관리 및 리포트 저장."""

    def __init__(self):
        self._reports: dict[str, ParityReport] = {}

    def run(
        self,
        suite_id: str,
        reference_engine: CalculationEngine,
        production_engine: CalculationEngine,
        semantics: "CalculationSemantics",
        parameters: dict[str, Any],
        evidence: dict[str, Any],
        context: CalculationContext | None = None,
    ) -> ParityReport:
        """스위트 전체 패리티 테스트 실행."""
        gt_registry = get_ground_truth_registry()
        suite = gt_registry.get(suite_id)
        if not suite:
            raise ValueError(f"Ground Truth suite not found: {suite_id}")

        report = run_parity_test(
            suite, reference_engine, production_engine,
            semantics, parameters, evidence, context
        )
        self._reports[report.report_id] = report
        return report

    def get_report(self, report_id: str) -> ParityReport | None:
        return self._reports.get(report_id)

    def list_reports(self) -> list[ParityReport]:
        return list(self._reports.values())

    def check_parity_pass(self, report: ParityReport) -> bool:
        """패리티 통과 여부 확인 — FAIL 시 HOLD."""
        return report.overall_status() == ParityStatus.PASS


_global_parity_runner: ParityRunner | None = None


def get_parity_runner() -> ParityRunner:
    global _global_parity_runner
    if _global_parity_runner is None:
        _global_parity_runner = ParityRunner()
    return _global_parity_runner