# -*- coding: utf-8 -*-
"""
modules.factory.engine.adapters.mortgagemath_adapter — MortgageMath Adapter
 
CalcMate Engine Contract → mortgagemath 변환 계층.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import mortgagemath as mm

from modules.factory.engine import (
    CalculationEngine,
    CalculationContext,
    CalculationResult,
    CalculationStatus,
    FailureCode,
    CalculationError,
)
from modules.factory.semantics import CalculationSemantics


class MortgageMathAdapter(CalculationEngine):
    """mortgagemath를 CalcMate Engine Contract에 맞게 래핑."""

    @property
    def engine_name(self) -> str:
        return "mortgagemath"

    @property
    def engine_version(self) -> str:
        return mm.__version__

    def get_supported_features(self) -> list[str]:
        return [
            "amortization",
            "variable_rate",
            "interest_only",
            "recast",
            "payment_frequency",
            "compounding",
            "rounding_modes",
            "cent_precision",
        ]

    def validate_inputs(
        self,
        semantics: CalculationSemantics,
        inputs: dict[str, Any],
    ) -> tuple[bool, list[CalculationError]]:
        """입력값 사전 검증."""
        errors = []

        # 필수 입력 확인 (CalcMate 표준 형식 지원)
        # term_months 또는 term_years 중 하나는 있어야 함
        has_term_months = "term_months" in inputs
        has_term_years = "term_years" in inputs
        
        required = ["principal", "annual_rate"]
        for field in required:
            if field not in inputs:
                errors.append(CalculationError(
                    code=FailureCode.MISSING_PARAMETER,
                    user_message=f"필수 입력값 누락: {field}",
                    diagnostic=f"Missing required input: {field}",
                    field_name=field,
                ))
        
        if not has_term_months and not has_term_years:
            errors.append(CalculationError(
                code=FailureCode.MISSING_PARAMETER,
                user_message="대출 기간 필수 (term_months 또는 term_years)",
                diagnostic="Missing term_months or term_years",
                field_name="term_months",
            ))

        # 값 타입/범위 검증
        try:
            principal = Decimal(str(inputs.get("principal", 0)))
            if principal <= 0:
                errors.append(CalculationError(
                    code=FailureCode.INVALID_INPUT,
                    user_message="원금은 0보다 커야 합니다",
                    diagnostic="principal must be positive",
                    field_name="principal",
                ))
        except Exception:
            errors.append(CalculationError(
                code=FailureCode.INVALID_INPUT,
                user_message="원금은 숫자여야 합니다",
                diagnostic="principal must be a valid number",
                field_name="principal",
            ))

        try:
            rate = Decimal(str(inputs.get("annual_rate", 0)))
            # annual_rate를 percentage(5 for 5%)로 받음 (CalcMate 표준)
            if rate < 0 or rate > 100:
                errors.append(CalculationError(
                    code=FailureCode.INVALID_INPUT,
                    user_message="연이율은 0~100 사이여야 합니다 (예: 5.0 = 5%)",
                    diagnostic="annual_rate must be between 0 and 100",
                    field_name="annual_rate",
                ))
        except Exception:
            errors.append(CalculationError(
                code=FailureCode.INVALID_INPUT,
                user_message="연이율은 숫자여야 합니다",
                diagnostic="annual_rate must be a valid number",
                field_name="annual_rate",
            ))

        # term_months 또는 term_years 검증
        if has_term_months:
            try:
                term = int(inputs.get("term_months", 0))
                if term <= 0:
                    errors.append(CalculationError(
                        code=FailureCode.INVALID_INPUT,
                        user_message="대출 기간은 1개월 이상이어야 합니다",
                        diagnostic="term_months must be positive",
                        field_name="term_months",
                    ))
            except Exception:
                errors.append(CalculationError(
                    code=FailureCode.INVALID_INPUT,
                    user_message="대출 기간은 정수여야 합니다",
                    diagnostic="term_months must be an integer",
                    field_name="term_months",
                ))
        elif has_term_years:
            try:
                term = int(inputs.get("term_years", 0))
                if term <= 0:
                    errors.append(CalculationError(
                        code=FailureCode.INVALID_INPUT,
                        user_message="대출 기간은 1년 이상이어야 합니다",
                        diagnostic="term_years must be positive",
                        field_name="term_years",
                    ))
            except Exception:
                errors.append(CalculationError(
                    code=FailureCode.INVALID_INPUT,
                    user_message="대출 기간은 정수여야 합니다",
                    diagnostic="term_years must be an integer",
                    field_name="term_years",
                ))

        return len(errors) == 0, errors

    def calculate(
        self,
        semantics: CalculationSemantics,
        inputs: dict[str, Any],
        context: CalculationContext,
        parameters: dict[str, Any],
        evidence: dict[str, Any],
    ) -> CalculationResult:
        """mortgagemath로 대출 상환 계산 실행."""
        import time
        start_time = time.perf_counter()

        try:
            # 입력 파싱 (CalcMate 표준 형식 지원)
            principal = Decimal(str(inputs["principal"]))
            annual_rate = Decimal(str(inputs["annual_rate"]))
            
            # term_months 또는 term_years 처리
            if "term_months" in inputs:
                term_months = int(inputs["term_months"])
            elif "term_years" in inputs:
                term_months = int(inputs["term_years"]) * 12
            else:
                raise ValueError("term_months 또는 term_years 필요")

            # annual_rate를 percentage(5 for 5%)로 받음 - mortgagemath도 percentage 사용
            annual_rate_decimal = annual_rate

            # 선택적 입력 (기본값 사용)
            payment_frequency_str = inputs.get("payment_frequency", "monthly").lower()
            compounding_str = inputs.get("compounding", "monthly").lower()
            currency_unit_str = inputs.get("currency_unit", "0.01")
            day_count_str = inputs.get("day_count", "30/360")
            payment_rounding_str = inputs.get("payment_rounding", "ROUND_HALF_UP")
            interest_rounding_str = inputs.get("interest_rounding", "ROUND_HALF_UP")
            balance_tracking_str = inputs.get("balance_tracking", "ROUND_EACH")
            interest_only_months = int(inputs.get("interest_only_months", 0))
            fee_per_period = Decimal(str(inputs.get("fee_per_period", "0")))

            # Enum 매핑
            payment_frequency = self._map_payment_frequency(payment_frequency_str)
            compounding = self._map_compounding(compounding_str)
            currency_unit = Decimal(currency_unit_str)
            day_count = self._map_day_count(day_count_str)
            payment_rounding = self._map_payment_rounding(payment_rounding_str)
            interest_rounding = self._map_payment_rounding(interest_rounding_str)
            balance_tracking = self._map_balance_tracking(balance_tracking_str)

            # LoanParams 생성
            loan_params = mm.LoanParams(
                principal=principal,
                annual_rate=annual_rate_decimal,
                term_months=term_months,
                compounding=compounding,
                payment_frequency=payment_frequency,
                currency_unit=currency_unit,
                day_count=day_count,
                payment_rounding=payment_rounding,
                interest_rounding=interest_rounding,
                balance_tracking=balance_tracking,
                interest_only_months=interest_only_months,
                fee_per_period=fee_per_period,
            )

            # 월납입금 계산
            payment = mm.periodic_payment(loan_params)

            # 상환 스케줄 생성
            schedule_raw = mm.amortization_schedule(loan_params)

            # 스케줄 변환 (첫 번째 행은 0번 초기값이므로 제외)
            schedule = []
            for inst in schedule_raw[1:]:  # row 0은 초기값
                schedule.append({
                    "period": inst.number,
                    "payment": float(inst.payment),
                    "principal": float(inst.principal),
                    "interest": float(inst.interest),
                    "balance": float(inst.balance),
                    "fee": float(inst.fee),
                    "total_interest": float(inst.total_interest),
                })

            # 총 이자 계산 (마지막 행의 total_interest)
            total_interest = float(schedule_raw[-1].total_interest) if schedule_raw else 0.0
            
            # 총 납입액 = 월납입금 * 상환횟수 (원금+이자 모두 포함)
            total_payment = float(payment * term_months)

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            return CalculationResult(
                status=CalculationStatus.SUCCESS,
                outputs={
                    "monthly_payment": float(payment),
                    "total_interest": total_interest,
                    "total_payment": total_payment,
                },
                schedule=schedule,
                diagnostics=[
                    f"mortgagemath {mm.__version__} calculation completed",
                    f"currency_unit: {currency_unit}",
                    f"compounding: {compounding_str}",
                    f"payment_frequency: {payment_frequency_str}",
                ],
                parameters_used={
                    "principal": str(principal),
                    "annual_rate": str(annual_rate),
                    "term_months": str(term_months),
                },
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
                diagnostics=[f"mortgagemath error: {e}"],
                parameters_used={},
                evidence_used=[],
                engine_version=self.engine_version,
                semantics_version=semantics.version,
                execution_time_ms=execution_time_ms,
                errors=[CalculationError(
                    code=FailureCode.CALCULATION_ERROR,
                    user_message="대출 계산 중 오류가 발생했습니다",
                    diagnostic=str(e),
                )],
            )

    # Enum 매핑 헬퍼 메서드들
    def _map_payment_frequency(self, value: str) -> mm.PaymentFrequency:
        mapping = {
            "monthly": mm.PaymentFrequency.MONTHLY,
            "semi_monthly": mm.PaymentFrequency.SEMI_MONTHLY,
            "biweekly": mm.PaymentFrequency.BIWEEKLY,
            "weekly": mm.PaymentFrequency.WEEKLY,
            "quarterly": mm.PaymentFrequency.QUARTERLY,
            "annual": mm.PaymentFrequency.ANNUAL,
        }
        return mapping.get(value, mm.PaymentFrequency.MONTHLY)

    def _map_compounding(self, value: str) -> mm.Compounding:
        mapping = {
            "monthly": mm.Compounding.MONTHLY,
            "semi_annual": mm.Compounding.SEMI_ANNUAL,
            "annual": mm.Compounding.ANNUAL,
        }
        return mapping.get(value, mm.Compounding.MONTHLY)

    def _map_day_count(self, value: str) -> mm.DayCount:
        mapping = {
            "30/360": mm.DayCount.THIRTY_360,
            "actual/360": mm.DayCount.ACTUAL_360,
        }
        return mapping.get(value, mm.DayCount.THIRTY_360)

    def _map_payment_rounding(self, value: str) -> mm.PaymentRounding:
        mapping = {
            "round_up": mm.PaymentRounding.ROUND_UP,
            "round_down": mm.PaymentRounding.ROUND_DOWN,
            "round_half_up": mm.PaymentRounding.ROUND_HALF_UP,
            "round_half_even": mm.PaymentRounding.ROUND_HALF_EVEN,
        }
        return mapping.get(value.upper(), mm.PaymentRounding.ROUND_HALF_UP)

    def _map_balance_tracking(self, value: str) -> mm.BalanceTracking:
        mapping = {
            "round_each": mm.BalanceTracking.ROUND_EACH,
            "carry_precision": mm.BalanceTracking.CARRY_PRECISION,
        }
        return mapping.get(value.lower(), mm.BalanceTracking.ROUND_EACH)


# EngineFactory 등록용
def register_mortgagemath_adapter():
    from modules.factory.engine import EngineFactory
    EngineFactory.register_adapter("mortgagemath", MortgageMathAdapter)


if __name__ == "__main__":
    # 간단 테스트
    adapter = MortgageMathAdapter()
    print(f"Engine: {adapter.engine_name} v{adapter.engine_version}")
    print(f"Features: {adapter.get_supported_features()}")

    from modules.factory.semantics import CalculationSemantics
    sem = CalculationSemantics(calculator_id="test", version="1.0.0")
    ctx = CalculationContext()

    # 테스트 입력
    inputs = {
        "principal": "300000000",
        "annual_rate": "0.05",
        "term_months": "360",
    }

    valid, errors = adapter.validate_inputs(sem, inputs)
    print(f"Validation: {valid}, errors: {errors}")

    result = adapter.calculate(sem, inputs, ctx, {}, {})
    print(f"Status: {result.status}")
    print(f"Outputs: {result.outputs}")
    print(f"Schedule rows: {len(result.schedule)}")
    if result.schedule:
        print(f"First: {result.schedule[0]}")
        print(f"Last: {result.schedule[-1]}")