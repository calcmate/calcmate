# -*- coding: utf-8 -*-
"""
modules.factory.engine — Engine Protocol

Production Engine과 Reference Engine을 위한 공통 프로토콜.
어댑터 패턴으로 실제 OSS(Formualizer, mortgagemath, numpy-financial 등) 연결.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


def _empty_dict() -> dict:
    return {}


def _empty_list() -> list:
    return []


class CalculationStatus(str, Enum):
    """계산 실행 상태."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"  # 일부 출력만 계산됨


class FailureCode(str, Enum):
    """Factory 공통 실패 코드."""
    INVALID_INPUT = "INVALID_INPUT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    UNSUPPORTED_CASE = "UNSUPPORTED_CASE"
    NO_VALID_RATE = "NO_VALID_RATE"
    DATE_OUT_OF_RANGE = "DATE_OUT_OF_RANGE"
    CALCULATION_ERROR = "CALCULATION_ERROR"
    OVERFLOW = "OVERFLOW"
    ROUNDING_ERROR = "ROUNDING_ERROR"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass
class CalculationError:
    """계산 오류 상세."""
    code: FailureCode
    user_message: str  # 사용자 표시용
    diagnostic: str    # 내부 진단용
    field_name: str | None = None
    context: dict[str, Any] = field(default_factory=_empty_dict)


@dataclass
class CalculationContext:
    """계산 실행 컨텍스트."""
    target_date: date = field(default_factory=date.today)
    tax_year: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    scenario_id: str | None = None  # 시나리오 식별자
    metadata: dict[str, Any] = field(default_factory=_empty_dict)


@dataclass
class CalculationResult:
    """계산 결과 표준 구조."""
    status: CalculationStatus
    outputs: dict[str, Any] = field(default_factory=_empty_dict)
    schedule: list[dict[str, Any]] = field(default_factory=_empty_list)  # 상환스케줄 등
    diagnostics: list[str] = field(default_factory=_empty_list)
    parameters_used: dict[str, Any] = field(default_factory=_empty_dict)
    evidence_used: list[str] = field(default_factory=_empty_list)  # evidence_id 리스트
    engine_version: str = ""
    semantics_version: str = ""
    execution_time_ms: float = 0.0
    errors: list[CalculationError] = field(default_factory=_empty_list)

    def is_success(self) -> bool:
        return self.status == CalculationStatus.SUCCESS

    def get_error_codes(self) -> list[FailureCode]:
        return [e.code for e in self.errors]

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "outputs": self.outputs,
            "schedule": self.schedule,
            "diagnostics": self.diagnostics,
            "parameters_used": self.parameters_used,
            "evidence_used": self.evidence_used,
            "engine_version": self.engine_version,
            "semantics_version": self.semantics_version,
            "execution_time_ms": self.execution_time_ms,
            "errors": [
                {
                    "code": e.code.value,
                    "user_message": e.user_message,
                    "diagnostic": e.diagnostic,
                    "field": e.field_name,
                    "context": e.context,
                }
                for e in self.errors
            ],
        }


class CalculationEngine(ABC):
    """
    계산 엔진 추상 베이스 클래스.
    Production Engine과 Reference Engine이 모두 이 인터페이스를 구현.
    """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """엔진 식별자 (예: 'formualizer', 'mortgagemath', 'numpy-financial')."""
        pass

    @property
    @abstractmethod
    def engine_version(self) -> str:
        """엔진 버전."""
        pass

    @abstractmethod
    def calculate(
        self,
        semantics: "CalculationSemantics",  # forward ref
        inputs: dict[str, Any],
        context: CalculationContext,
        parameters: dict[str, Any],
        evidence: dict[str, Any],
    ) -> CalculationResult:
        """
        계산 실행.

        Args:
            semantics: 계산 의미론 (Formula/Rule/Parameter/Temporal/Rounding/Reconciliation)
            inputs: 사용자 입력값
            context: 계산 컨텍스트 (target_date, tax_year 등)
            parameters: 바인딩된 파라미터 값들 (parameter_id -> value)
            evidence: 관련 증거 자료 (evidence_id -> EvidenceRecord)

        Returns:
            CalculationResult: 표준 결과 구조
        """
        pass

    @abstractmethod
    def validate_inputs(
        self,
        semantics: "CalculationSemantics",
        inputs: dict[str, Any],
    ) -> tuple[bool, list[CalculationError]]:
        """입력값 사전 검증."""
        pass

    @abstractmethod
    def get_supported_features(self) -> list[str]:
        """지원하는 기능 목록 (예: ['amortization', 'variable_rate', 'grace_period'])."""
        pass


# 실제 어댑터는 별도 파일에서 구현 (FormualizerAdapter, MortgageMathAdapter 등)
# MVP에서는 프로토콜과 기본 구현만 제공


@dataclass
class EngineConfig:
    """엔진 설정."""
    engine_type: str = "production"  # production | reference
    adapter_name: str = ""
    config: dict[str, Any] = field(default_factory=_empty_dict)


class EngineFactory:
    """엔진 인스턴스 생성 팩토리."""

    _adapters: dict[str, type] = {}

    @classmethod
    def register_adapter(cls, name: str, adapter_class: type) -> None:
        """어댑터 클래스 등록."""
        cls._adapters[name] = adapter_class

    @classmethod
    def create_engine(cls, config: EngineConfig) -> CalculationEngine:
        """설정에 따라 엔진 인스턴스 생성."""
        adapter_class = cls._adapters.get(config.adapter_name)
        if not adapter_class:
            raise ValueError(f"Unknown adapter: {config.adapter_name}")
        return adapter_class(config.config)

    @classmethod
    def list_adapters(cls) -> list[str]:
        return list(cls._adapters.keys())