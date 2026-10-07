# -*- coding: utf-8 -*-
"""
modules.factory.ground_truth — Ground Truth Model

독립 검증의 핵심. AI가 생성한 테스트 데이터 사용 금지.
공식 예제/표/계산 사례/수학적 known value만 허용.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class GroundTruthSource(str, Enum):
    """Ground Truth 출처 — 우선순위 순."""
    OFFICIAL_EXAMPLE = "OFFICIAL_EXAMPLE"         # 공식 예제 (법령 예시, 매뉴얼 예제)
    OFFICIAL_TABLE = "OFFICIAL_TABLE"             # 공식 표 (요율표, 구간표)
    VERIFIED_CALCULATOR = "VERIFIED_CALCULATOR"   # 검증된 기존 계산기 (독립 구현)
    MATHEMATICAL_KNOWN_VALUE = "MATHEMATICAL_KNOWN_VALUE"  # 수학적 known value
    BENCHMARK = "BENCHMARK"                       # 신뢰 가능한 benchmark (납세자연맹 등)


@dataclass
class GroundTruthCase:
    """단일 Ground Truth 테스트 케이스."""
    id: str = field(default_factory=lambda: str(uuid4()))
    calculator_id: str = ""
    tier: str = "C"  # S | C | R
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    source: GroundTruthSource = GroundTruthSource.BENCHMARK
    source_reference: str = ""  # 출처 상세 (URL, 문서명, 페이지 등)
    tolerance: float = 1e-9  # 허용 오차 (절대값)
    effective_date: date = field(default_factory=date.today)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "calculator_id": self.calculator_id,
            "tier": self.tier,
            "inputs": self.inputs,
            "expected_outputs": self.expected_outputs,
            "source": self.source.value,
            "source_reference": self.source_reference,
            "tolerance": self.tolerance,
            "effective_date": self.effective_date.isoformat(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GroundTruthCase":
        return cls(
            id=data.get("id", str(uuid4())),
            calculator_id=data.get("calculator_id", ""),
            tier=data.get("tier", "C"),
            inputs=data.get("inputs", {}),
            expected_outputs=data.get("expected_outputs", {}),
            source=GroundTruthSource(data.get("source", "BENCHMARK")),
            source_reference=data.get("source_reference", ""),
            tolerance=data.get("tolerance", 1e-9),
            effective_date=date.fromisoformat(data["effective_date"])
                if data.get("effective_date") else date.today(),
            notes=data.get("notes", ""),
        )


@dataclass
class GroundTruthSuite:
    """계산기별 Ground Truth 스위트."""
    suite_id: str = field(default_factory=lambda: str(uuid4()))
    calculator_id: str = ""
    version: str = "1.0.0"
    cases: list[GroundTruthCase] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    updated_at: str = field(default_factory=lambda: date.today().isoformat())

    def add_case(self, case: GroundTruthCase) -> None:
        case.calculator_id = self.calculator_id
        self.cases.append(case)

    def get_case(self, case_id: str) -> GroundTruthCase | None:
        for c in self.cases:
            if c.id == case_id:
                return c
        return None

    def filter_by_tier(self, tier: str) -> list[GroundTruthCase]:
        return [c for c in self.cases if c.tier == tier]

    def filter_by_source(self, source: GroundTruthSource) -> list[GroundTruthCase]:
        return [c for c in self.cases if c.source == source]

    def to_dict(self) -> dict:
        return {
            "suite_id": self.suite_id,
            "calculator_id": self.calculator_id,
            "version": self.version,
            "cases": [c.to_dict() for c in self.cases],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GroundTruthSuite":
        suite = cls(
            suite_id=data.get("suite_id", str(uuid4())),
            calculator_id=data.get("calculator_id", ""),
            version=data.get("version", "1.0.0"),
            cases=[GroundTruthCase.from_dict(c) for c in data.get("cases", [])],
            created_at=data.get("created_at", date.today().isoformat()),
            updated_at=data.get("updated_at", date.today().isoformat()),
        )
        return suite


class GroundTruthRegistry:
    """Ground Truth 스위트 저장소 (MVP: 인메모리)."""

    def __init__(self):
        self._store: dict[str, GroundTruthSuite] = {}

    def add(self, suite: GroundTruthSuite) -> GroundTruthSuite:
        if suite.suite_id in self._store:
            raise ValueError(f"Suite already exists: {suite.suite_id}")
        self._store[suite.suite_id] = suite
        return suite

    def get(self, suite_id: str) -> GroundTruthSuite | None:
        return self._store.get(suite_id)

    def get_by_calculator(self, calculator_id: str) -> list[GroundTruthSuite]:
        return [s for s in self._store.values() if s.calculator_id == calculator_id]

    def update(self, suite: GroundTruthSuite) -> GroundTruthSuite:
        if suite.suite_id not in self._store:
            raise KeyError(f"Suite not found: {suite.suite_id}")
        self._store[suite.suite_id] = suite
        return suite

    def delete(self, suite_id: str) -> bool:
        if suite_id in self._store:
            del self._store[suite_id]
            return True
        return False

    def all(self) -> list[GroundTruthSuite]:
        return list(self._store.values())


_global_gt_registry: GroundTruthRegistry | None = None


def get_ground_truth_registry() -> GroundTruthRegistry:
    global _global_gt_registry
    if _global_gt_registry is None:
        _global_gt_registry = GroundTruthRegistry()
    return _global_gt_registry


def validate_ground_truth_case(case: GroundTruthCase) -> tuple[bool, list[str]]:
    """Ground Truth 케이스 유효성 검증."""
    errors = []

    if not case.calculator_id:
        errors.append("calculator_id is required")
    if not case.inputs:
        errors.append("inputs is required")
    if not case.expected_outputs:
        errors.append("expected_outputs is required")
    if case.tolerance < 0:
        errors.append("tolerance must be non-negative")
    if case.source == GroundTruthSource.BENCHMARK and not case.source_reference:
        errors.append("BENCHMARK source requires source_reference")

    # AI 생성 데이터 금지 검증 (휴리스틱)
    # expected_outputs에 비현실적으로 정교한 값이 있으면 경고
    for key, value in case.expected_outputs.items():
        if isinstance(value, float):
            # 소수점 10자리 이상이면 AI 생성 의심
            str_val = repr(value)
            if len(str_val) > 15 and "e" not in str_val.lower():
                errors.append(f"output '{key}' has suspiciously precise value (possible AI-generated): {value}")

    return len(errors) == 0, errors