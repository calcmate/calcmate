# -*- coding: utf-8 -*-
"""
modules.factory.schemas.tier_risk_complexity — Tier / Risk × Complexity 평가

계산기 등급(Tier)과 위험도×복잡도 매트릭스로 필수 게이트 결정.
"""

from .calculator_spec import (
    CalculatorTier,
    RiskLevel,
    ComplexityLevel,
    RiskComplexityMatrix,
)


def evaluate_tier_risk_complexity(
    tier: CalculatorTier | str,
    risk: RiskLevel | str,
    complexity: ComplexityLevel | str,
) -> dict:
    """Tier + Risk + Complexity 종합 평가 결과 반환."""
    t = CalculatorTier(tier) if isinstance(tier, str) else tier
    r = RiskLevel(risk) if isinstance(risk, str) else risk
    c = ComplexityLevel(complexity) if isinstance(complexity, str) else complexity

    derived_tier = RiskComplexityMatrix.determine_tier(r, c)
    gates = RiskComplexityMatrix.get_required_gates(t, r, c)
    approval = RiskComplexityMatrix.requires_human_approval(t, r)

    return {
        "input_tier": t.value,
        "derived_tier": derived_tier.value,
        "tier_match": t == derived_tier,
        "risk": r.value,
        "complexity": c.value,
        "required_gates": gates,
        "human_approval_required": approval,
        "gate_count": len(gates),
    }


def get_required_gates(
    tier: CalculatorTier | str,
    risk: RiskLevel | str,
    complexity: ComplexityLevel | str,
) -> list[str]:
    """필수 게이트 목록 반환."""
    t = CalculatorTier(tier) if isinstance(tier, str) else tier
    r = RiskLevel(risk) if isinstance(risk, str) else risk
    c = ComplexityLevel(complexity) if isinstance(complexity, str) else complexity
    return RiskComplexityMatrix.get_required_gates(t, r, c)