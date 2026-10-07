# -*- coding: utf-8 -*-
"""
modules.factory.schemas.calculator_spec — Calculator Spec SSoT

Factory의 단일 진실 출처.
Tier S/C/R + Risk × Complexity 2축으로 검증 수준 결정.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4


class CalculatorTier(str, Enum):
    """계산기 등급 — 문서량/검증 수준 결정."""
    S = "S"  # Simple: BMI, 단위변환, 단순 날짜계산
    C = "C"  # Commercial: 대출, 예금, 연금, 보험
    R = "R"  # Regulatory: 세금, 4대보험, 노무, 법정급여


class RiskLevel(str, Enum):
    """위험도 — 금전/법적 영향 크기."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComplexityLevel(str, Enum):
    """복잡도 — 계산 로직/분기/파라미터 수."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskComplexityMatrix:
    """Risk × Complexity 매트릭스로 등급/게이트 결정."""

    @staticmethod
    def determine_tier(risk: RiskLevel, complexity: ComplexityLevel) -> CalculatorTier:
        """Risk × Complexity → Tier 결정."""
        if risk == RiskLevel.CRITICAL or (risk == RiskLevel.HIGH and complexity in (ComplexityLevel.MEDIUM, ComplexityLevel.HIGH)):
            return CalculatorTier.R
        if risk == RiskLevel.HIGH and complexity == ComplexityLevel.LOW:
            return CalculatorTier.R
        if risk in (RiskLevel.MEDIUM, RiskLevel.HIGH) and complexity in (ComplexityLevel.MEDIUM, ComplexityLevel.HIGH):
            return CalculatorTier.C
        if risk == RiskLevel.LOW and complexity == ComplexityLevel.LOW:
            return CalculatorTier.S
        return CalculatorTier.C  # 기본값

    @staticmethod
    def get_required_gates(tier: CalculatorTier, risk: RiskLevel, complexity: ComplexityLevel) -> list[str]:
        """Tier + Risk + Complexity 조합으로 필수 게이트 결정."""
        gates = [
            "SpecGate",
            "EvidenceGate",
            "SemanticsGate",
            "GroundTruthGate",
            "ReferenceParityGate",
            "NumericGate",
            "InputValidationGate",
            "UIGate",
            "ContentConsistencyGate",
        ]
        if tier == CalculatorTier.R or risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            gates.extend(["LegalGate", "RegressionGate"])
        if tier in (CalculatorTier.C, CalculatorTier.R):
            gates.append("ReleaseGate")
        return gates

    @staticmethod
    def requires_human_approval(tier: CalculatorTier, risk: RiskLevel) -> bool:
        """Human Approval 필수 여부."""
        return tier == CalculatorTier.R or risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)


@dataclass
class InputField:
    """입력 필드 정의."""
    name: str
    label: str
    type: Literal["number", "integer", "boolean", "date", "select", "text"]
    unit: str | None = None
    required: bool = True
    min: float | int | None = None
    max: float | int | None = None
    enum: list[str] | None = None
    default: Any = None
    help: str | None = None
    validation: dict | None = None  # 추가 검증 규칙

    def to_ui_schema(self) -> dict:
        """Default UI Schema 변환."""
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "unit": self.unit,
            "required": self.required,
            "min": self.min,
            "max": self.max,
            "enum": self.enum,
            "default": self.default,
            "help": self.help,
            "validation": self.validation,
        }


@dataclass
class OutputField:
    """출력 필드 정의."""
    name: str
    label: str
    type: Literal["number", "integer", "boolean", "date", "string", "object", "array"]
    unit: str | None = None
    description: str | None = None
    precision: int | None = None  # 표시 정밀도 (소수점 자리수)

    def to_ui_schema(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "unit": self.unit,
            "description": self.description,
            "precision": self.precision,
        }


@dataclass
class Definition:
    """계산 의미론의 중간 정의(중간 계산값)."""
    name: str
    expression: str  # Formualizer 호환 AST 또는 표현식 문자열
    description: str | None = None
    dependencies: list[str] = field(default_factory=list)  # 다른 definition 이름들


@dataclass
class ParameterRef:
    """Time-Aware Parameter 참조."""
    parameter_id: str
    name: str
    bind_to: str  # semantics 내부 변수명
    required: bool = True
    default_value: Any = None


@dataclass
class EvidenceRef:
    """Evidence 참조."""
    evidence_id: str
    claim: str
    parameter_refs: list[str] = field(default_factory=list)


@dataclass
class SemanticsRef:
    """Calculation Semantics 참조."""
    semantics_id: str
    version: str


@dataclass
class GroundTruthRef:
    """Ground Truth Suite 참조."""
    suite_id: str
    version: str


@dataclass
class EngineConfig:
    """엔진 설정 — 어떤 OSS 어댑터를 쓸지 지정."""
    formula: str = "formualizer"  # formualizer | custom
    decimal: str = "larzmoney"    # larzmoney | finprecise
    finance: str = "mortgagemath" # mortgagemath | numpy-financial | finprecise
    temporal: str = "zerotime"    # zerotime | pytemporal
    rule: str = "zen"             # zen | form-engine
    # 참고: 실제 OSS 설치 전 adapter로만 연결


@dataclass
class UIConfig:
    """UI 설정."""
    default_renderer: str = "form-engine"  # form-engine | rjsf
    custom_renderer: str | None = None     # 예: "loan-schedule", "tax-bracket"


@dataclass
class ContentConfig:
    """콘텐츠 설정."""
    template_pack: str = "default"
    engine_driven: bool = True


@dataclass
class ValidationConfig:
    """검증 설정."""
    gates: list[str] = field(default_factory=list)
    failure_contract: list[str] = field(default_factory=list)


@dataclass
class LegalConfig:
    """법적 설정."""
    approval_required: bool = False
    regulatory_refs: list[str] = field(default_factory=list)


@dataclass
class VersionConfig:
    """8개 하위 버전 + 상위 release_version."""
    spec: str = "0.1.0"
    semantics: str = "0.1.0"
    evidence: str = "0.1.0"
    parameter: str = "0.1.0"
    engine: str = "0.1.0"
    ui: str = "0.1.0"
    content: str = "0.1.0"
    validation: str = "0.1.0"
    release: str = "0.1.0"  # 상위 SemVer


@dataclass
class ReleaseConfig:
    """Release Manifest 설정."""
    calculator_id: str
    released_at: datetime | None = None
    approved_by: str | None = None
    parity_report_ref: str | None = None


@dataclass
class CalculatorSpec:
    """Calculator Spec SSoT — 모든 계산기의 단일 진실 출처."""

    # Identity
    id: str = field(default_factory=lambda: str(uuid4()))
    slug: str = ""
    title: str = ""
    category: str = ""
    description: str = ""
    tier: CalculatorTier = CalculatorTier.C

    # Risk × Complexity
    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_regulatory: bool = False
    risk_financial: bool = False
    risk_user_impact: str = ""
    complexity_level: ComplexityLevel = ComplexityLevel.MEDIUM

    # Scope
    scope_included: list[str] = field(default_factory=list)
    scope_excluded: list[str] = field(default_factory=list)

    # Core definitions
    inputs: list[InputField] = field(default_factory=list)
    outputs: list[OutputField] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    parameters: list[ParameterRef] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)

    # References
    semantics: SemanticsRef | None = None
    ground_truth: GroundTruthRef | None = None

    # Engine / UI / Content / Validation / Legal
    engine: EngineConfig = field(default_factory=EngineConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    content: ContentConfig = field(default_factory=ContentConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    legal: LegalConfig = field(default_factory=LegalConfig)

    # Versioning
    version: VersionConfig = field(default_factory=VersionConfig)
    release: ReleaseConfig | None = None

    def __post_init__(self):
        if self.tier == CalculatorTier.S and self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            # Tier S인데 Risk High면 Tier R로 승격
            self.tier = CalculatorTier.R

        # 필수 게이트 자동 채우기
        if not self.validation.gates:
            self.validation.gates = RiskComplexityMatrix.get_required_gates(
                self.tier, self.risk_level, self.complexity_level
            )
        # Legal 승인 필요 여부 자동 설정
        self.legal.approval_required = RiskComplexityMatrix.requires_human_approval(
            self.tier, self.risk_level
        )

    def to_dict(self) -> dict:
        """직렬화용 dict 변환."""
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "tier": self.tier.value,
            "risk": {
                "level": self.risk_level.value,
                "regulatory": self.risk_regulatory,
                "financial": self.risk_financial,
                "user_impact": self.risk_user_impact,
            },
            "complexity": self.complexity_level.value,
            "scope": {
                "included": self.scope_included,
                "excluded": self.scope_excluded,
            },
            "inputs": [i.__dict__ for i in self.inputs],
            "outputs": [o.__dict__ for o in self.outputs],
            "definitions": [d.__dict__ for d in self.definitions],
            "parameters": [p.__dict__ for p in self.parameters],
            "evidence": [e.__dict__ for e in self.evidence],
            "semantics": self.semantics.__dict__ if self.semantics else None,
            "ground_truth": self.ground_truth.__dict__ if self.ground_truth else None,
            "engine": self.engine.__dict__,
            "ui": self.ui.__dict__,
            "content": self.content.__dict__,
            "validation": self.validation.__dict__,
            "legal": self.legal.__dict__,
            "version": self.version.__dict__,
            "release": self.release.__dict__ if self.release else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalculatorSpec":
        """dict에서 복원."""
        # Enum 변환
        tier = CalculatorTier(data.get("tier", "C"))
        risk_level = RiskLevel(data.get("risk", {}).get("level", "MEDIUM"))
        complexity_level = ComplexityLevel(data.get("complexity", "MEDIUM"))

        spec = cls(
            id=data.get("id", str(uuid4())),
            slug=data.get("slug", ""),
            title=data.get("title", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            tier=tier,
            risk_level=risk_level,
            risk_regulatory=data.get("risk", {}).get("regulatory", False),
            risk_financial=data.get("risk", {}).get("financial", False),
            risk_user_impact=data.get("risk", {}).get("user_impact", ""),
            complexity_level=complexity_level,
            scope_included=data.get("scope", {}).get("included", []),
            scope_excluded=data.get("scope", {}).get("excluded", []),
            inputs=[InputField(**i) for i in data.get("inputs", [])],
            outputs=[OutputField(**o) for o in data.get("outputs", [])],
            definitions=[Definition(**d) for d in data.get("definitions", [])],
            parameters=[ParameterRef(**p) for p in data.get("parameters", [])],
            evidence=[EvidenceRef(**e) for e in data.get("evidence", [])],
            engine=EngineConfig(**data.get("engine", {})),
            ui=UIConfig(**data.get("ui", {})),
            content=ContentConfig(**data.get("content", {})),
            validation=ValidationConfig(**data.get("validation", {})),
            legal=LegalConfig(**data.get("legal", {})),
            version=VersionConfig(**data.get("version", {})),
        )

        # References 복원
        if data.get("semantics"):
            spec.semantics = SemanticsRef(**data["semantics"])
        if data.get("ground_truth"):
            spec.ground_truth = GroundTruthRef(**data["ground_truth"])
        if data.get("release"):
            spec.release = ReleaseConfig(**data["release"])

        return spec


def validate_spec(spec: CalculatorSpec) -> tuple[bool, list[str]]:
    """Calculator Spec 유효성 검증."""
    errors = []

    if not spec.slug:
        errors.append("slug is required")
    if not spec.title:
        errors.append("title is required")
    if not spec.category:
        errors.append("category is required")

    # Input/Output 필수
    if not spec.inputs:
        errors.append("at least one input field is required")
    if not spec.outputs:
        errors.append("at least one output field is required")

    # Input 필드 검증
    input_names = set()
    for inp in spec.inputs:
        if inp.name in input_names:
            errors.append(f"duplicate input field name: {inp.name}")
        input_names.add(inp.name)
        if inp.type == "select" and not inp.enum:
            errors.append(f"select type input '{inp.name}' requires enum values")

    # Output 필드 검증
    output_names = set()
    for out in spec.outputs:
        if out.name in output_names:
            errors.append(f"duplicate output field name: {out.name}")
        output_names.add(out.name)

    # Definition 순환 참조 간단 체크
    def_names = {d.name for d in spec.definitions}
    for d in spec.definitions:
        for dep in d.dependencies:
            if dep not in def_names:
                errors.append(f"definition '{d.name}' references unknown definition '{dep}'")

    # Parameter 바인딩 검증
    param_ids = {p.parameter_id for p in spec.parameters}
    for p in spec.parameters:
        if p.bind_to not in def_names and p.bind_to not in input_names:
            errors.append(f"parameter '{p.name}' binds to unknown variable '{p.bind_to}'")

    # Evidence 참조 검증
    evidence_ids = {e.evidence_id for e in spec.evidence}
    for e in spec.evidence:
        for pref in e.parameter_refs:
            if pref not in param_ids:
                errors.append(f"evidence '{e.evidence_id}' references unknown parameter '{pref}'")

    return len(errors) == 0, errors


def spec_to_ui_schema(spec: CalculatorSpec) -> dict:
    """Calculator Spec → Default UI Schema 변환."""
    return {
        "calculator_id": spec.id,
        "slug": spec.slug,
        "title": spec.title,
        "description": spec.description,
        "inputs": [i.to_ui_schema() for i in spec.inputs],
        "outputs": [o.to_ui_schema() for o in spec.outputs],
        "custom_renderer": spec.ui.custom_renderer,
    }