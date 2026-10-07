# -*- coding: utf-8 -*-
"""
modules.factory.ui — Default UI Schema

Calculator Spec → Input Schema → Default React Renderer (bghcore/form-engine)
Custom Renderer 허용 (loan schedule, tax bracket 등) — 계산 로직 포함 금지.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class UIField:
    """UI 필드 정의 — Spec InputField에서 변환."""
    name: str
    label: str
    type: str  # "text" | "number" | "integer" | "boolean" | "date" | "select" | "textarea" | "email" | "tel"
    unit: str | None = None
    required: bool = True
    min: float | int | None = None
    max: float | int | None = None
    step: float | int | None = None
    enum: list[dict[str, str]] | None = None  # [{"value": "opt1", "label": "Option 1"}, ...]
    default: Any = None
    placeholder: str | None = None
    help: str | None = None
    validation: dict[str, Any] | None = None  # 추가 검증 규칙
    conditional: dict[str, Any] | None = None  # 조건부 표시 로직

    def to_form_engine_config(self) -> dict:
        """bghcore/form-engine 필드 설정으로 변환."""
        config = {
            "type": self._map_type(),
            "label": self.label,
            "required": self.required,
            "help": self.help,
        }
        if self.min is not None:
            config["min"] = self.min
        if self.max is not None:
            config["max"] = self.max
        if self.step is not None:
            config["step"] = self.step
        if self.enum:
            config["options"] = self.enum
        if self.default is not None:
            config["default"] = self.default
        if self.placeholder:
            config["placeholder"] = self.placeholder
        if self.validation:
            config["validate"] = self.validation
        if self.conditional:
            config["visibleWhen"] = self.conditional
        return config

    def _map_type(self) -> str:
        """Factory 타입 → form-engine 타입 매핑."""
        mapping = {
            "text": "Textbox",
            "number": "NumberInput",
            "integer": "NumberInput",
            "boolean": "Toggle",
            "date": "DatePicker",
            "select": "Dropdown",
            "textarea": "Textarea",
            "email": "EmailInput",
            "tel": "TelInput",
        }
        return mapping.get(self.type, "Textbox")


@dataclass
class UISchema:
    """전체 UI 스키마 — Default Renderer가 이 스키마로 폼 렌더링."""
    calculator_id: str
    slug: str
    title: str
    description: str | None = None
    inputs: list[UIField] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)  # 출력 표시용
    custom_renderer: str | None = None  # 예: "loan-schedule", "tax-bracket"
    layout: dict[str, Any] = field(default_factory=dict)  # 레이아웃 설정

    def to_form_engine_config(self) -> dict:
        """bghcore/form-engine IFormConfig로 변환."""
        field_configs = {}
        for inp in self.inputs:
            field_configs[inp.name] = inp.to_form_engine_config()

        return {
            "fields": field_configs,
            "layout": self.layout,
            "customRenderer": self.custom_renderer,
        }


def spec_to_ui_schema(spec: Any) -> UISchema:
    """CalculatorSpec → UISchema 변환."""
    from modules.factory.schemas import InputField, OutputField

    inputs = []
    for inp in spec.inputs:
        # enum 변환: 문자열 리스트 → {value, label} 리스트
        enum = None
        if inp.enum:
            enum = [{"value": v, "label": v} for v in inp.enum]

        ui_field = UIField(
            name=inp.name,
            label=inp.label,
            type=inp.type,
            unit=inp.unit,
            required=inp.required,
            min=inp.min,
            max=inp.max,
            enum=enum,
            default=inp.default,
            help=inp.help,
            validation=inp.validation,
        )
        inputs.append(ui_field)

    outputs = []
    for out in spec.outputs:
        outputs.append({
            "name": out.name,
            "label": out.label,
            "type": out.type,
            "unit": out.unit,
            "description": out.description,
            "precision": out.precision,
        })

    return UISchema(
        calculator_id=spec.id,
        slug=spec.slug,
        title=spec.title,
        description=spec.description,
        inputs=inputs,
        outputs=outputs,
        custom_renderer=spec.ui.custom_renderer,
        layout=spec.ui.__dict__.get("layout", {}),
    )


# Custom Renderer 인터페이스 (구현은 별도 패키지)
class CustomRendererProtocol:
    """
    Custom Renderer 인터페이스.

    Engine
      ↓
    structured result (typed output)
      ↓
    Custom Renderer (React component)

    원칙: Custom Renderer에 계산 로직 금지.
    """

    @staticmethod
    def render(result: dict, schema: UISchema) -> Any:
        """
        계산 결과와 UI 스키마를 받아 React 요소 반환.
        실제 구현은 React 컴포넌트에서 수행.
        """
        raise NotImplementedError


# 내장 Custom Renderer 타입 (확장 가능)
BUILTIN_CUSTOM_RENDERERS = {
    "loan-schedule": "LoanScheduleRenderer",      # 상환 스케줄 테이블 + 차트
    "tax-bracket": "TaxBracketRenderer",          # 세율 구간 시각화
    "timeline": "TimelineRenderer",               # 기간별 변화 타임라인
    "chart": "ChartRenderer",                     # 일반 차트
    "comparison": "ComparisonRenderer",           # 시나리오 비교
    "simulation": "SimulationRenderer",           # 시뮬레이션 결과
}

def get_custom_renderer(renderer_name: str) -> str | None:
    """내장 Custom Renderer 컴포넌트 이름 반환."""
    return BUILTIN_CUSTOM_RENDERERS.get(renderer_name)