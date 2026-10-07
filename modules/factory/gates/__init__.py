# -*- coding: utf-8 -*-
"""
modules.factory.gates — Quality Gate Framework

12개 게이트 계층화. Critical FAIL 시 HOLD. 자동 수정 금지.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class GateStatus(str, Enum):
    """게이트 실행 결과 상태."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GateSeverity(str, Enum):
    """게이트 중요도."""
    CRITICAL = "CRITICAL"   # 실패 시 HOLD
    HIGH = "HIGH"           # 실패 시 경고, 진행 가능
    MEDIUM = "MEDIUM"       # 정보성
    LOW = "LOW"             # 권장사항


@dataclass
class GateResult:
    """단일 게이트 실행 결과."""
    gate_id: str
    name: str
    severity: GateSeverity
    status: GateStatus
    diagnostics: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # evidence_id 리스트
    metadata: dict[str, Any] = field(default_factory=dict)
    executed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def is_critical_fail(self) -> bool:
        return self.severity == GateSeverity.CRITICAL and self.status == GateStatus.FAIL

    def to_dict(self) -> dict:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "severity": self.severity.value,
            "status": self.status.value,
            "diagnostics": self.diagnostics,
            "evidence": self.evidence,
            "metadata": self.metadata,
            "executed_at": self.executed_at,
            "is_critical_fail": self.is_critical_fail(),
        }


@dataclass
class QualityGateContext:
    """게이트 실행 컨텍스트."""
    calculator_spec: Any = None  # CalculatorSpec
    semantics: Any = None        # CalculationSemantics
    ground_truth_suite: Any = None  # GroundTruthSuite
    evidence_registry: Any = None   # EvidenceRegistry
    reference_engine: Any = None    # CalculationEngine
    production_engine: Any = None   # CalculationEngine
    parity_report: Any = None       # ParityReport
    ui_schema: Any = None           # UI Schema
    content_package: Any = None     # ContentPackage
    release_manifest: Any = None    # ReleaseManifest
    existing_calculators: list = field(default_factory=list)  # 회귀 테스트용


class QualityGate(ABC):
    """품질 게이트 추상 베이스 클래스."""

    def __init__(self, gate_id: str, name: str, severity: GateSeverity = GateSeverity.CRITICAL):
        self.gate_id = gate_id
        self.name = name
        self.severity = severity

    @abstractmethod
    def execute(self, context: QualityGateContext) -> GateResult:
        """게이트 실행."""
        pass

    def is_applicable(self, context: QualityGateContext) -> bool:
        """이 게이트가 현재 컨텍스트에 적용 가능한지 확인."""
        return True


class SpecGate(QualityGate):
    """Spec Gate — Calculator Spec 완전성/유효성 검증."""
    def __init__(self):
        super().__init__("SpecGate", "Calculator Spec Validation", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        from modules.factory.schemas import validate_spec
        spec = context.calculator_spec
        if not spec:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["CalculatorSpec not provided"])

        valid, errors = validate_spec(spec)
        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if valid else GateStatus.FAIL,
            diagnostics=errors,
        )


class EvidenceGate(QualityGate):
    """Evidence Gate — 증거 자료 존재/유효성/만료 검증."""
    def __init__(self):
        super().__init__("EvidenceGate", "Evidence Validation", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        from modules.factory.evidence import validate_evidence, VerificationStatus
        evidence_registry = context.evidence_registry
        spec = context.calculator_spec

        if not evidence_registry or not spec:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["EvidenceRegistry or CalculatorSpec not provided"])

        errors = []
        for ev_ref in spec.evidence:
            evidence = evidence_registry.get(ev_ref.evidence_id)
            if not evidence:
                errors.append(f"Evidence not found: {ev_ref.evidence_id}")
                continue

            valid, ev_errors = validate_evidence(evidence)
            if not valid:
                errors.extend([f"{evidence.evidence_id}: {e}" for e in ev_errors])

            if evidence.verification_status == VerificationStatus.STALE:
                errors.append(f"Evidence stale: {evidence.evidence_id}")
            elif evidence.verification_status == VerificationStatus.CONFLICT:
                errors.append(f"Evidence conflict: {evidence.evidence_id}")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class SemanticsGate(QualityGate):
    """Semantics Gate — Calculation Semantics 완결성/순환참조 검증."""
    def __init__(self):
        super().__init__("SemanticsGate", "Calculation Semantics Validation", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        from modules.factory.semantics import validate_semantics
        semantics = context.semantics
        if not semantics:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["CalculationSemantics not provided"])

        valid, errors = validate_semantics(semantics)
        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if valid else GateStatus.FAIL,
            diagnostics=errors,
        )


class GroundTruthGate(QualityGate):
    """Ground Truth Gate — 모든 케이스 통과 (tolerance 내)."""
    def __init__(self):
        super().__init__("GroundTruthGate", "Ground Truth Validation", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        from modules.factory.ground_truth import validate_ground_truth_case
        suite = context.ground_truth_suite
        if not suite:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.SKIPPED,
                              diagnostics=["GroundTruthSuite not provided"])

        errors = []
        for case in suite.cases:
            valid, case_errors = validate_ground_truth_case(case)
            if not valid:
                errors.extend([f"{case.id}: {e}" for e in case_errors])

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class ReferenceParityGate(QualityGate):
    """Reference Parity Gate — Reference ≡ Production (tolerance 내)."""
    def __init__(self):
        super().__init__("ReferenceParityGate", "Reference-Production Parity", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        parity_report = context.parity_report
        if not parity_report:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.SKIPPED,
                              diagnostics=["ParityReport not provided"])

        if parity_report.overall_status().value == "PASS":
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.PASS)

        diagnostics = [f"Parity check failed: {parity_report.failed_cases} cases failed"]
        for case in parity_report.case_results:
            if case.status.value == "FAIL":
                for comp in case.comparisons:
                    if not comp.passed:
                        diagnostics.append(f"  {comp.field_name}: ref={comp.reference_value} vs prod={comp.production_value} (diff={comp.difference})")

        return GateResult(
            self.gate_id, self.name, self.severity, GateStatus.FAIL,
            diagnostics=diagnostics,
        )


class NumericGate(QualityGate):
    """Numeric Gate — 정밀도/반올림/정산 정책 준수."""
    def __init__(self):
        super().__init__("NumericGate", "Numeric Policy Compliance", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        semantics = context.semantics
        if not semantics:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.SKIPPED,
                              diagnostics=["CalculationSemantics not provided"])

        errors = []
        # 반올림 정책 확인
        if not semantics.rounding.apply_to and semantics.rounding.precision < 0:
            errors.append("Invalid rounding precision")

        # 정산 규칙 확인
        for rule in semantics.reconciliation:
            if rule.rule_type.value == "LAST_PERIOD_ADJUST" and not rule.target_variable:
                errors.append(f"Reconciliation rule missing target_variable: {rule.rule_type.value}")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class InputValidationGate(QualityGate):
    """Input Validation Gate — 입력 스키마 검증, 범위 체크."""
    def __init__(self):
        super().__init__("InputValidationGate", "Input Validation", GateSeverity.HIGH)

    def execute(self, context: QualityGateContext) -> GateResult:
        spec = context.calculator_spec
        if not spec:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["CalculatorSpec not provided"])

        errors = []
        for inp in spec.inputs:
            if inp.type in ("number", "integer") and inp.min is not None and inp.max is not None:
                if inp.min > inp.max:
                    errors.append(f"Input '{inp.name}': min > max")
            if inp.type == "select" and inp.enum and len(inp.enum) == 0:
                errors.append(f"Input '{inp.name}': empty enum")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class UIGate(QualityGate):
    """UI Gate — Default/Custom 렌더링 동작, 접근성."""
    def __init__(self):
        super().__init__("UIGate", "UI Rendering Validation", GateSeverity.HIGH)

    def execute(self, context: QualityGateContext) -> GateResult:
        ui_schema = context.ui_schema
        if not ui_schema:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.SKIPPED,
                              diagnostics=["UI Schema not provided"])

        errors = []
        if "inputs" not in ui_schema:
            errors.append("UI schema missing 'inputs'")
        else:
            for inp in ui_schema["inputs"]:
                if "name" not in inp or "label" not in inp:
                    errors.append(f"UI input missing name/label: {inp}")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class ContentConsistencyGate(QualityGate):
    """Content Consistency Gate — Engine 결과 = 콘텐츠 내 숫자."""
    def __init__(self):
        super().__init__("ContentConsistencyGate", "Content-Engine Consistency", GateSeverity.HIGH)

    def execute(self, context: QualityGateContext) -> GateResult:
        content_package = context.content_package
        # 실제 구현에서는 content_package의 숫자들을 engine 결과와 비교
        # MVP에서는 구조만 검증
        if not content_package:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.SKIPPED,
                              diagnostics=["ContentPackage not provided"])

        errors = []
        required_fields = ["title", "description", "formula_explanation", "worked_example"]
        for field in required_fields:
            if not getattr(content_package, field, None):
                errors.append(f"ContentPackage missing required field: {field}")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class LegalGate(QualityGate):
    """Legal Gate — 법령 준수, 승인 필요 여부 (R/R+ 필수)."""
    def __init__(self):
        super().__init__("LegalGate", "Legal Compliance", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        spec = context.calculator_spec
        if not spec:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["CalculatorSpec not provided"])

        # Tier R이거나 Risk High/Critical인 경우만 엄격 적용
        from modules.factory.schemas import CalculatorTier, RiskLevel
        if spec.tier != CalculatorTier.R and spec.risk_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.NOT_APPLICABLE)

        errors = []
        if spec.legal.approval_required and not spec.release:
            errors.append("Legal approval required but no ReleaseManifest")
        if spec.legal.approval_required and spec.release and not spec.release.approved_by:
            errors.append("ReleaseManifest missing approved_by")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class RegressionGate(QualityGate):
    """Regression Gate — 기존 계산기 대비 회귀 없음."""
    def __init__(self):
        super().__init__("RegressionGate", "Regression Test", GateSeverity.HIGH)

    def execute(self, context: QualityGateContext) -> GateResult:
        existing = context.existing_calculators
        if not existing:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.NOT_APPLICABLE)

        errors = []
        # 실제로는 기존 계산기 결과와 비교
        # MVP에서는 구조만 검증
        for calc in existing:
            if not calc.get("formula"):
                errors.append(f"Existing calculator missing formula: {calc.get('slug', 'unknown')}")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


class ReleaseGate(QualityGate):
    """Release Gate — Manifest 완전성, 버전 일관성."""
    def __init__(self):
        super().__init__("ReleaseGate", "Release Manifest Validation", GateSeverity.CRITICAL)

    def execute(self, context: QualityGateContext) -> GateResult:
        manifest = context.release_manifest
        if not manifest:
            return GateResult(self.gate_id, self.name, self.severity, GateStatus.FAIL,
                              diagnostics=["ReleaseManifest not provided"])

        errors = []
        required_versions = [
            "spec_version", "semantics_version", "evidence_version",
            "parameter_version", "engine_version", "ui_version",
            "content_version", "validation_version", "release_version"
        ]
        for v in required_versions:
            if not getattr(manifest, v, None):
                errors.append(f"Missing version: {v}")

        if not manifest.calculator_id:
            errors.append("Missing calculator_id")
        if not manifest.released_at:
            errors.append("Missing released_at")
        if not manifest.approved_by:
            errors.append("Missing approved_by")

        return GateResult(
            self.gate_id, self.name, self.severity,
            GateStatus.PASS if not errors else GateStatus.FAIL,
            diagnostics=errors,
        )


# 게이트 레지스트리
GATE_REGISTRY: dict[str, type[QualityGate]] = {
    "SpecGate": SpecGate,
    "EvidenceGate": EvidenceGate,
    "SemanticsGate": SemanticsGate,
    "GroundTruthGate": GroundTruthGate,
    "ReferenceParityGate": ReferenceParityGate,
    "NumericGate": NumericGate,
    "InputValidationGate": InputValidationGate,
    "UIGate": UIGate,
    "ContentConsistencyGate": ContentConsistencyGate,
    "LegalGate": LegalGate,
    "RegressionGate": RegressionGate,
    "ReleaseGate": ReleaseGate,
}


class QualityGateRunner:
    """품질 게이트 실행기 — 순차 실행, Critical FAIL 시 중단."""

    def __init__(self, gate_ids: list[str] | None = None):
        self.gate_ids = gate_ids or list(GATE_REGISTRY.keys())
        self._results: list[GateResult] = []

    def run(self, context: QualityGateContext) -> list[GateResult]:
        """모든 게이트 순차 실행. Critical FAIL 시 즉시 중단 (HOLD)."""
        self._results = []

        for gate_id in self.gate_ids:
            gate_class = GATE_REGISTRY.get(gate_id)
            if not gate_class:
                result = GateResult(gate_id, f"Unknown Gate: {gate_id}",
                                    GateSeverity.CRITICAL, GateStatus.ERROR,
                                    diagnostics=[f"Gate class not registered: {gate_id}"])
                self._results.append(result)
                break

            gate = gate_class()
            if not gate.is_applicable(context):
                result = GateResult(gate.gate_id, gate.name, gate.severity, GateStatus.NOT_APPLICABLE)
                self._results.append(result)
                continue

            try:
                result = gate.execute(context)
            except Exception as e:
                result = GateResult(gate.gate_id, gate.name, gate.severity, GateStatus.ERROR,
                                    diagnostics=[f"Gate execution error: {e}"])

            self._results.append(result)

            # Critical FAIL 시 즉시 중단
            if result.is_critical_fail():
                break

        return self._results

    def has_critical_fail(self) -> bool:
        return any(r.is_critical_fail() for r in self._results)

    def get_results(self) -> list[GateResult]:
        return self._results

    def to_dict(self) -> dict:
        return {
            "total_gates": len(self._results),
            "passed": sum(1 for r in self._results if r.status == GateStatus.PASS),
            "failed": sum(1 for r in self._results if r.status == GateStatus.FAIL),
            "skipped": sum(1 for r in self._results if r.status == GateStatus.SKIPPED),
            "not_applicable": sum(1 for r in self._results if r.status == GateStatus.NOT_APPLICABLE),
            "errors": sum(1 for r in self._results if r.status == GateStatus.ERROR),
            "critical_failures": sum(1 for r in self._results if r.is_critical_fail()),
            "hold_required": self.has_critical_fail(),
            "results": [r.to_dict() for r in self._results],
        }


def get_required_gates_for_spec(spec: Any) -> list[str]:
    """CalculatorSpec의 tier/risk/complexity에 따른 필수 게이트 목록 반환."""
    from modules.factory.schemas import RiskComplexityMatrix, CalculatorTier, RiskLevel, ComplexityLevel
    return RiskComplexityMatrix.get_required_gates(spec.tier, spec.risk_level, spec.complexity_level)