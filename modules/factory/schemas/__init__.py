# -*- coding: utf-8 -*-
"""
modules.factory.schemas — Calculator Spec SSoT Schema

Factory의 단일 진실 출처(Single Source of Truth).
모든 계산기 정의가 이 스키마를 따른다.
"""

from .calculator_spec import (
    CalculatorSpec,
    CalculatorTier,
    RiskLevel,
    ComplexityLevel,
    RiskComplexityMatrix,
    InputField,
    OutputField,
    Definition,
    ParameterRef,
    EvidenceRef,
    SemanticsRef,
    GroundTruthRef,
    EngineConfig,
    UIConfig,
    ContentConfig,
    ValidationConfig,
    LegalConfig,
    VersionConfig,
    ReleaseConfig,
    validate_spec,
    spec_to_ui_schema,
)

from .tier_risk_complexity import (
    CalculatorTier as Tier,
    RiskLevel as Risk,
    ComplexityLevel as Complexity,
    get_required_gates,
    evaluate_tier_risk_complexity,
)

__all__ = [
    "CalculatorSpec",
    "CalculatorTier",
    "RiskLevel",
    "ComplexityLevel",
    "RiskComplexityMatrix",
    "InputField",
    "OutputField",
    "Definition",
    "ParameterRef",
    "EvidenceRef",
    "SemanticsRef",
    "GroundTruthRef",
    "EngineConfig",
    "UIConfig",
    "ContentConfig",
    "ValidationConfig",
    "LegalConfig",
    "VersionConfig",
    "ReleaseConfig",
    "validate_spec",
    "spec_to_ui_schema",
    "Tier",
    "Risk",
    "Complexity",
    "get_required_gates",
    "evaluate_tier_risk_complexity",
]