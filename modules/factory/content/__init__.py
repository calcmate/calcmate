# -*- coding: utf-8 -*-
"""
modules.factory.content — Engine-Driven Content Package

Calculator Spec + Engine + Ground Truth + Evidence
       ↓
Content Factory (Template Engine)
       ↓
Title, Description, How-to-use, Formula Explanation,
Worked Example, FAQ, Limitations, Disclaimer, SEO Metadata

LLM이 숫자를 임의 생성하지 않는다.
Engine Result → Template → Published Text
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class ContentPackage:
    """콘텐츠 패키지 — 발행용 완성된 콘텐츠."""
    calculator_id: str
    slug: str
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # 필수 필드
    title: str = ""
    description: str = ""
    how_to_use: str = ""
    formula_explanation: str = ""
    worked_example: str = ""
    faq: list[dict[str, str]] = field(default_factory=list)  # [{"q": "...", "a": "..."}]
    limitations: str = ""
    disclaimer: str = ""
    seo_metadata: dict[str, str] = field(default_factory=dict)  # title, description, keywords, og:...

    # 엔진 기반 생성 메타데이터
    engine_driven: bool = True
    engine_result_ref: str | None = None  # 계산 결과 참조
    template_pack: str = "default"
    generated_by: str = "factory"  # factory | manual | hybrid

    def to_dict(self) -> dict:
        return {
            "calculator_id": self.calculator_id,
            "slug": self.slug,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "description": self.description,
            "how_to_use": self.how_to_use,
            "formula_explanation": self.formula_explanation,
            "worked_example": self.worked_example,
            "faq": self.faq,
            "limitations": self.limitations,
            "disclaimer": self.disclaimer,
            "seo_metadata": self.seo_metadata,
            "engine_driven": self.engine_driven,
            "engine_result_ref": self.engine_result_ref,
            "template_pack": self.template_pack,
            "generated_by": self.generated_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentPackage":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkedExample:
    """작동 예시 — Engine 결과 기반."""
    title: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    schedule: list[dict[str, Any]] | None = None
    explanation: str = ""


@dataclass
class ContentTemplate:
    """콘텐츠 템플릿 — Jinja2 호환."""
    name: str
    template: str  # Jinja2 템플릿 문자열
    required_fields: list[str] = field(default_factory=list)


# 기본 템플릿 팩
DEFAULT_TEMPLATES = {
    "calculator_page": ContentTemplate(
        name="calculator_page",
        required_fields=["title", "description", "how_to_use", "formula_explanation",
                         "worked_example", "faq", "limitations", "disclaimer"],
        template="""# {{ title }}

{{ description }}

## 사용 방법
{{ how_to_use }}

## 계산 공식
{{ formula_explanation }}

## 계산 예시
{{ worked_example }}

## 자주 묻는 질문
{% for item in faq %}
**Q: {{ item.q }}**
A: {{ item.a }}

{% endfor %}

## 제한사항
{{ limitations }}

## 면책 조항
{{ disclaimer }}
""",
    ),
    "seo_meta": ContentTemplate(
        name="seo_meta",
        required_fields=["title", "description", "keywords"],
        template="""<title>{{ seo_metadata.title }}</title>
<meta name="description" content="{{ seo_metadata.description }}">
<meta name="keywords" content="{{ seo_metadata.keywords }}">
<meta property="og:title" content="{{ seo_metadata.og_title }}">
<meta property="og:description" content="{{ seo_metadata.og_description }}">
""",
    ),
}


class ContentFactory:
    """
    콘텐츠 팩토리 — Engine 결과를 템플릿에 주입해 콘텐츠 생성.
    LLM은 템플릿 작성/문장 개선에만 사용, 숫자 생성 금지.
    """

    def __init__(self, template_pack: str = "default"):
        self.template_pack = template_pack
        self.templates = DEFAULT_TEMPLATES.copy()

    def register_template(self, template: ContentTemplate) -> None:
        self.templates[template.name] = template

    def generate(
        self,
        spec: Any,  # CalculatorSpec
        engine_result: dict,  # CalculationResult.outputs + schedule
        evidence_summary: list[dict] | None = None,
        ground_truth_cases: list[dict] | None = None,
    ) -> ContentPackage:
        """
        엔진 결과로부터 콘텐츠 패키지 생성.

        Args:
            spec: CalculatorSpec
            engine_result: {"outputs": {...}, "schedule": [...], "diagnostics": [...]}
            evidence_summary: 증거 요약 리스트
            ground_truth_cases: Ground Truth 케이스 요약
        """
        # 1. 공식 설명 생성 (Spec의 formulas/definitions 기반)
        formula_explanation = self._generate_formula_explanation(spec, engine_result)

        # 2. 작동 예시 생성 (Ground Truth 첫 번째 케이스 또는 엔진 결과)
        worked_example = self._generate_worked_example(spec, engine_result, ground_truth_cases)

        # 3. 사용 방법 생성 (입력 필드 기반)
        how_to_use = self._generate_how_to_use(spec)

        # 4. FAQ 생성 (기존 FAQ + 엔진 결과 기반 자동 생성)
        faq = self._generate_faq(spec, engine_result)

        # 5. 제한사항 생성
        limitations = self._generate_limitations(spec, engine_result)

        # 6. 면책 조항 생성 (Legal config 기반)
        disclaimer = self._generate_disclaimer(spec)

        # 7. SEO 메타데이터 생성
        seo_metadata = self._generate_seo_metadata(spec, engine_result)

        package = ContentPackage(
            calculator_id=spec.id,
            slug=spec.slug,
            title=spec.title,
            description=spec.description or "",
            how_to_use=how_to_use,
            formula_explanation=formula_explanation,
            worked_example=worked_example,
            faq=faq,
            limitations=limitations,
            disclaimer=disclaimer,
            seo_metadata=seo_metadata,
            engine_driven=True,
            engine_result_ref=f"engine_result_{spec.id}_{datetime.utcnow().timestamp()}",
        )
        return package

    def _generate_formula_explanation(self, spec: Any, engine_result: dict) -> str:
        """공식 설명 생성 — Spec의 definitions와 semantics에서."""
        lines = []
        if spec.definitions:
            lines.append("### 중간 계산값")
            for d in spec.definitions:
                lines.append(f"- **{d.name}**: {d.description or d.expression}")

        # formulas와 rounding은 semantics에 있음
        semantics = getattr(spec, 'semantics', None)
        if semantics and semantics.formulas:
            lines.append("\n### 최종 계산 공식")
            for f in semantics.formulas:
                lines.append(f"- `{f.expression}`")

        if semantics and semantics.rounding and semantics.rounding.mode:
            lines.append(f"\n**반올림**: {semantics.rounding.mode.value} (소수점 {semantics.rounding.precision}자리)")

        if semantics and semantics.reconciliation:
            lines.append("\n**정산 규칙**:")
            for r in semantics.reconciliation:
                lines.append(f"- {r.rule_type.value}: {r.target_variable} ({r.description or ''})")

        return "\n".join(lines) if lines else "단순 산술 계산으로 이루어집니다."

    def _generate_worked_example(
        self, spec: Any, engine_result: dict, ground_truth_cases: list[dict] | None
    ) -> str:
        """작동 예시 생성 — Engine 결과 또는 Ground Truth 기반."""
        # Ground Truth 첫 번째 케이스 우선 사용
        example_inputs = None
        example_outputs = None

        if ground_truth_cases:
            example_inputs = ground_truth_cases[0].get("inputs", {})
            example_outputs = ground_truth_cases[0].get("expected_outputs", {})
        elif engine_result.get("outputs"):
            example_inputs = {}  # 실제로는 별도 저장 필요
            example_outputs = engine_result["outputs"]

        if not example_outputs:
            return "작동 예시를 생성할 데이터가 없습니다."

        lines = ["### 입력값"]
        for k, v in (example_inputs or {}).items():
            lines.append(f"- **{k}**: {v}")

        lines.append("\n### 계산 결과")
        for k, v in example_outputs.items():
            lines.append(f"- **{k}**: {v}")

        if engine_result.get("schedule"):
            lines.append("\n### 상환 스케줄 (일부)")
            for i, row in enumerate(engine_result["schedule"][:3]):
                lines.append(f"{i+1}. {row}")
            if len(engine_result["schedule"]) > 3:
                lines.append(f"... 외 {len(engine_result['schedule']) - 3}개 회차")

        return "\n".join(lines)

    def _generate_how_to_use(self, spec: Any) -> str:
        """사용 방법 생성 — 입력 필드 기반."""
        lines = ["1. 아래 입력란에 필요한 값을 입력하세요."]
        for inp in spec.inputs:
            unit_str = f" ({inp.unit})" if inp.unit else ""
            req_str = " (필수)" if inp.required else " (선택)"
            lines.append(f"2. **{inp.label}**{unit_str}{req_str}: {inp.help or '값을 입력하세요'}")
        lines.append("3. '계산하기' 버튼을 누르면 결과가 표시됩니다.")
        return "\n".join(lines)

    def _generate_faq(self, spec: Any, engine_result: dict) -> list[dict[str, str]]:
        """FAQ 생성 — 기존 FAQ + 엔진 결과 기반."""
        faq = []

        # 기존 FAQ가 있으면 포함 (spec에 저장된 경우)
        # 실제로는 spec.faq 또는 별도 저장소에서 로드

        # 자동 생성 FAQ
        semantics = getattr(spec, 'semantics', None)
        rounding_mode = semantics.rounding.mode.value if semantics and semantics.rounding else 'HALF_UP'
        faq.extend([
            {"q": "이 계산기의 정확도는 어떻게 보장되나요?",
             "a": "공식 예제와 검증된 수치를 기준으로 Ground Truth 테스트를 통과한 계산기입니다. Reference Engine과 Production Engine 간의 패리티 검증을 통해 정확성을 검증합니다."},
            {"q": "반올림으로 인한 오차는 어떻게 처리하나요?",
             "a": f"반올림 정책은 {rounding_mode}을 사용하며, 마지막 회차 보정을 통해 최종 잔액이 정확히 0이 되도록 정산합니다."},
        ])

        # 입력 필드별 FAQ
        for inp in spec.inputs:
            if inp.help:
                faq.append({"q": f"{inp.label}은(는) 무엇을 의미하나요?", "a": inp.help})

        return faq

    def _generate_limitations(self, spec: Any, engine_result: dict) -> str:
        """제한사항 생성."""
        lines = []

        # Tier별 기본 제한사항
        from modules.factory.schemas import CalculatorTier
        if spec.tier == CalculatorTier.S:
            lines.append("단순 참고용 계산기이며, 법적 효력은 없습니다.")
        elif spec.tier == CalculatorTier.C:
            lines.append("상업적 참고용이며, 실제 계약 시 금융기관의 정확한 계산과 다를 수 있습니다.")
        elif spec.tier == CalculatorTier.R:
            lines.append("법령 기반 계산기이나, 개별 사안에 따라 예외가 적용될 수 있습니다. 정확한 기준은 관할기관에 문의하세요.")

        # Scope excluded
        if spec.scope_excluded:
            lines.append("\n**계산 제외 사항**:")
            for item in spec.scope_excluded:
                lines.append(f"- {item}")

        # 파라미터 유효기간
        if spec.parameters:
            lines.append("\n**적용 기준일**: 이 계산기는 특정 기준일의 파라미터를 사용합니다. 기준일 이후 법령/요율 변경 시 결과가 달라질 수 있습니다.")

        return "\n".join(lines) if lines else "특별한 제한사항은 없습니다."

    def _generate_disclaimer(self, spec: Any) -> str:
        """면책 조항 생성 — Legal config 기반."""
        if spec.legal.regulatory_refs:
            authority = ", ".join(spec.legal.regulatory_refs)
            return (f"본 계산기는 {authority} 등 관련 법령을 기준으로 작성되었습니다. "
                    f"정확한 세부 기준은 관할기관에 확인하시기 바랍니다. "
                    f"본 계산 결과는 참고용이며 법적 효력을 가지지 않습니다.")
        return ("본 계산기의 결과는 참고용으로만 활용하시고, "
                "정확한 기준은 관할기관에 문의하시기 바랍니다. "
                "본 계산 결과는 법적 효력을 가지지 않습니다.")

    def _generate_seo_metadata(self, spec: Any, engine_result: dict) -> dict[str, str]:
        """SEO 메타데이터 생성."""
        title = f"{spec.title} | CalcMate"
        description = spec.description or f"{spec.title}를 온라인으로 간편하게 계산하세요."
        keywords = f"{spec.title}, 계산기, {spec.category}, 온라인 계산"

        return {
            "title": title,
            "description": description[:160],
            "keywords": keywords,
            "og_title": title,
            "og_description": description[:160],
            "og_type": "website",
        }

    def render_markdown(self, package: ContentPackage) -> str:
        """ContentPackage → Markdown 렌더링."""
        template = self.templates.get("calculator_page")
        if not template:
            return ""

        # 간단한 템플릿 렌더링 (실제로는 Jinja2 사용)
        md = template.template
        replacements = {
            "{{ title }}": package.title,
            "{{ description }}": package.description,
            "{{ how_to_use }}": package.how_to_use,
            "{{ formula_explanation }}": package.formula_explanation,
            "{{ worked_example }}": package.worked_example,
            "{{ limitations }}": package.limitations,
            "{{ disclaimer }}": package.disclaimer,
        }
        for k, v in replacements.items():
            md = md.replace(k, v)

        # FAQ 반복문 수동 처리
        faq_html = ""
        for item in package.faq:
            faq_html += f"**Q: {item.get('q', '')}**\nA: {item.get('a', '')}\n\n"
        md = md.replace("{% for item in faq %}\n**Q: {{ item.q }}**\nA: {{ item.a }}\n\n{% endfor %}", faq_html)

        return md