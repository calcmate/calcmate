# -*- coding: utf-8 -*-
"""
modules.factory.semantics — Calculation Semantics Model

Formula Engine과 별도 계층.
법률 규칙, 시행일, 예외, 요율 선택, 반올림, 마지막 회차 보정 등
'계산의 의미'를 표현한다.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class RoundingMode(str, Enum):
    """반올림 모드."""
    HALF_UP = "HALF_UP"           # 4사5입 (기본)
    HALF_EVEN = "HALF_EVEN"       # 은행가 반올림
    HALF_DOWN = "HALF_DOWN"       # 5사6입
    UP = "UP"                     # 올림
    DOWN = "DOWN"                 # 내림
    CEILING = "CEILING"           # 양의 무한대 방향
    FLOOR = "FLOOR"               # 음의 무한대 방향


class ReconciliationRuleType(str, Enum):
    """정산/보정 규칙 유형."""
    LAST_PERIOD_ADJUST = "LAST_PERIOD_ADJUST"  # 마지막 회차 보정 (잔액 0 맞춤)
    ROUNDING_CORRECTION = "ROUNDING_CORRECTION"  # 반올림 누적 오차 보정
    INTEREST_ROUNDING = "INTEREST_ROUNDING"      # 이자 반올림 규칙


@dataclass
class FormulaAST:
    """Formualizer 호환 Formula AST (간단 표현)."""
    expression: str  # 원본 표현식
    ast_json: dict | None = None  # 파싱된 AST (Formualizer format)
    dependencies: list[str] = field(default_factory=list)  # 참조 변수명


@dataclass
class Definition:
    """중간 계산값 정의."""
    name: str
    formula: FormulaAST
    description: str | None = None
    dependencies: list[str] = field(default_factory=list)  # 다른 definition 이름


@dataclass
class Precondition:
    """실행 전 선행 조건."""
    name: str
    expression: str  # boolean 표현식 (zerotime DSL 또는 Formualizer boolean)
    description: str | None = None
    severity: str = "error"  # error | warning | info


@dataclass
class DecisionNode:
    """조건 분기 노드 (Decision Tree)."""
    node_id: str
    condition: str  # boolean 표현식
    then_branch: list[str] = field(default_factory=list)  # 다음 node_id 또는 action
    else_branch: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass
class RuleRef:
    """Rule Engine (gorules/zen JDM) 참조."""
    rule_id: str
    rule_version: str
    input_bindings: dict[str, str] = field(default_factory=dict)  # semantics 변수 → rule 입력
    output_bindings: dict[str, str] = field(default_factory=dict)  # rule 출력 → semantics 변수


@dataclass
class ParameterBinding:
    """Time-Aware Parameter 바인딩."""
    parameter_id: str
    semantics_var: str  # semantics 내부에서 쓸 변수명
    target_date: date | None = None  # 평가 기준일 (None = 현재)
    tax_year: int | None = None
    fallback_value: Any = None  # 파라미터 없을 때 기본값


@dataclass
class ExceptionRule:
    """예외 처리 규칙."""
    name: str
    condition: str  # boolean 표현식
    action: Literal["skip", "use_fallback", "raise_error", "use_alternative"] = "raise_error"
    fallback_value: Any = None
    alternative_formula: FormulaAST | None = None
    description: str | None = None


@dataclass
class TemporalRule:
    """시간 인식 규칙 (zerotime DSL)."""
    name: str
    dsl: str  # zerotime AtomicRule DSL 문자열
    description: str | None = None
    applies_to: list[str] = field(default_factory=list)  # 적용 대상 변수/파라미터


@dataclass
class RoundingPolicy:
    """반올림 정책."""
    mode: RoundingMode = RoundingMode.HALF_UP
    precision: int = 2  # 소수점 자리수
    apply_to: list[str] = field(default_factory=list)  # 적용 대상 변수명 (빈 리스트 = 전체)


@dataclass
class ReconciliationRule:
    """정산/보정 규칙."""
    rule_type: ReconciliationRuleType
    target_variable: str
    description: str | None = None
    config: dict[str, Any] = field(default_factory=dict)  # 규칙별 추가 설정


@dataclass
class CalculationSemantics:
    """
    계산 의미론 — 하나의 계산기가 '어떻게 계산되는지'를 완결적으로 표현.

    Formula Engine 내부 로직이 아님. 의미론 계층에서 Formula/Rule/Parameter/Temporal을 조합.
    """

    semantics_id: str = field(default_factory=lambda: str(uuid4()))
    calculator_id: str = ""
    version: str = "1.0.0"

    # 구성 요소
    formulas: list[FormulaAST] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    preconditions: list[Precondition] = field(default_factory=list)
    decision_tree: list[DecisionNode] = field(default_factory=list)
    rules: list[RuleRef] = field(default_factory=list)
    parameters: list[ParameterBinding] = field(default_factory=list)
    exceptions: list[ExceptionRule] = field(default_factory=list)
    temporal_logic: list[TemporalRule] = field(default_factory=list)
    rounding: RoundingPolicy = field(default_factory=RoundingPolicy)
    reconciliation: list[ReconciliationRule] = field(default_factory=list)

    # 메타데이터
    description: str = ""
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    updated_at: str = field(default_factory=lambda: date.today().isoformat())

    def get_formula(self, name: str) -> FormulaAST | None:
        for f in self.formulas:
            if f.expression.startswith(f"{name}=") or f.expression.startswith(f"{name} ="):
                return f
        return None

    def get_definition(self, name: str) -> Definition | None:
        for d in self.definitions:
            if d.name == name:
                return d
        return None

    def get_parameter_binding(self, param_id: str) -> ParameterBinding | None:
        for p in self.parameters:
            if p.parameter_id == param_id:
                return p
        return None

    def get_rule_ref(self, rule_id: str) -> RuleRef | None:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        return None

    def topological_order(self) -> list[str]:
        """정의/수식의 위상 정렬 순서 반환 (Formualizer dependency graph 위임)."""
        # 실제로는 Formualizer의 dependency graph를 사용
        # 여기서는 간단히 이름 순서 반환 (구현 시 Formualizer 연계)
        all_names = [d.name for d in self.definitions] + [f.expression.split("=")[0].strip() for f in self.formulas]
        return all_names

    def to_dict(self) -> dict:
        return {
            "semantics_id": self.semantics_id,
            "calculator_id": self.calculator_id,
            "version": self.version,
            "formulas": [{"expression": f.expression, "ast_json": f.ast_json, "dependencies": f.dependencies} for f in self.formulas],
            "definitions": [{"name": d.name, "formula": d.formula.expression, "description": d.description, "dependencies": d.dependencies} for d in self.definitions],
            "preconditions": [{"name": p.name, "expression": p.expression, "description": p.description, "severity": p.severity} for p in self.preconditions],
            "decision_tree": [{"node_id": n.node_id, "condition": n.condition, "then_branch": n.then_branch, "else_branch": n.else_branch, "description": n.description} for n in self.decision_tree],
            "rules": [{"rule_id": r.rule_id, "rule_version": r.rule_version, "input_bindings": r.input_bindings, "output_bindings": r.output_bindings} for r in self.rules],
            "parameters": [{"parameter_id": p.parameter_id, "semantics_var": p.semantics_var, "target_date": p.target_date.isoformat() if p.target_date else None, "tax_year": p.tax_year, "fallback_value": p.fallback_value} for p in self.parameters],
            "exceptions": [{"name": e.name, "condition": e.condition, "action": e.action, "fallback_value": e.fallback_value, "description": e.description} for e in self.exceptions],
            "temporal_logic": [{"name": t.name, "dsl": t.dsl, "description": t.description, "applies_to": t.applies_to} for t in self.temporal_logic],
            "rounding": {"mode": self.rounding.mode.value, "precision": self.rounding.precision, "apply_to": self.rounding.apply_to},
            "reconciliation": [{"rule_type": r.rule_type.value, "target_variable": r.target_variable, "description": r.description, "config": r.config} for r in self.reconciliation],
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalculationSemantics":
        sem = cls(
            semantics_id=data.get("semantics_id", str(uuid4())),
            calculator_id=data.get("calculator_id", ""),
            version=data.get("version", "1.0.0"),
            formulas=[FormulaAST(**f) for f in data.get("formulas", [])],
            definitions=[Definition(
                name=d["name"],
                formula=FormulaAST(expression=d["formula"]),
                description=d.get("description"),
                dependencies=d.get("dependencies", []),
            ) for d in data.get("definitions", [])],
            preconditions=[Precondition(**p) for p in data.get("preconditions", [])],
            decision_tree=[DecisionNode(**n) for n in data.get("decision_tree", [])],
            rules=[RuleRef(**r) for r in data.get("rules", [])],
            parameters=[ParameterBinding(
                parameter_id=p["parameter_id"],
                semantics_var=p["semantics_var"],
                target_date=date.fromisoformat(p["target_date"]) if p.get("target_date") else None,
                tax_year=p.get("tax_year"),
                fallback_value=p.get("fallback_value"),
            ) for p in data.get("parameters", [])],
            exceptions=[ExceptionRule(**e) for e in data.get("exceptions", [])],
            temporal_logic=[TemporalRule(**t) for t in data.get("temporal_logic", [])],
            rounding=RoundingPolicy(
                mode=RoundingMode(data.get("rounding", {}).get("mode", "HALF_UP")),
                precision=data.get("rounding", {}).get("precision", 2),
                apply_to=data.get("rounding", {}).get("apply_to", []),
            ),
            reconciliation=[ReconciliationRule(
                rule_type=ReconciliationRuleType(r["rule_type"]),
                target_variable=r["target_variable"],
                description=r.get("description"),
                config=r.get("config", {}),
            ) for r in data.get("reconciliation", [])],
            description=data.get("description", ""),
            created_at=data.get("created_at", date.today().isoformat()),
            updated_at=data.get("updated_at", date.today().isoformat()),
        )
        return sem


def validate_semantics(semantics: CalculationSemantics) -> tuple[bool, list[str]]:
    """Calculation Semantics 유효성 검증."""
    errors = []

    if not semantics.calculator_id:
        errors.append("calculator_id is required")

    # Definition 순환 참조 체크
    def_names = {d.name for d in semantics.definitions}
    for d in semantics.definitions:
        for dep in d.dependencies:
            if dep not in def_names:
                errors.append(f"definition '{d.name}' references unknown definition '{dep}'")

    # Parameter 바인딩 검증
    param_ids = {p.parameter_id for p in semantics.parameters}
    for p in semantics.parameters:
        if p.semantics_var in def_names:
            pass  # 정의된 변수에 바인딩됨
        elif p.fallback_value is None:
            errors.append(f"parameter '{p.parameter_id}' binds to '{p.semantics_var}' but no fallback")

    # Decision Tree 노드 존재 체크
    node_ids = {n.node_id for n in semantics.decision_tree}
    for n in semantics.decision_tree:
        for branch in n.then_branch + n.else_branch:
            if branch not in node_ids and not branch.startswith("action:"):
                errors.append(f"decision node '{n.node_id}' references unknown branch '{branch}'")

    # Rule 참조 검증 (실제 Rule Engine 연계 시 검증)
    for r in semantics.rules:
        if not r.rule_id:
            errors.append("rule_ref missing rule_id")

    return len(errors) == 0, errors