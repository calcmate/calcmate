# -*- coding: utf-8 -*-
"""
modules.factory.tests — Factory MVP Isolated Tests

기존 CalcMate 테스트와 분리된 Factory 핵심 테스트.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal

from modules.factory.schemas import (
    CalculatorSpec, CalculatorTier, RiskLevel, ComplexityLevel,
    InputField, OutputField, Definition, ParameterRef, EvidenceRef,
    EngineConfig, validate_spec, spec_to_ui_schema,
    RiskComplexityMatrix,
)
from modules.factory.evidence import (
    EvidenceRecord, SourceType, VerificationStatus,
    EvidenceRegistry, validate_evidence,
)
from modules.factory.semantics import (
    CalculationSemantics, FormulaAST, Definition as SemDef,
    RoundingMode, RoundingPolicy, validate_semantics,
)
from modules.factory.ground_truth import (
    GroundTruthCase, GroundTruthSuite, GroundTruthSource,
    GroundTruthRegistry, validate_ground_truth_case,
)
from modules.factory.engine import (
    CalculationEngine, CalculationContext, CalculationResult,
    CalculationStatus, FailureCode, EngineConfig as EngineProtocolConfig, EngineFactory,
)
from modules.factory.parity import (
    ParityRunner, ParityStatus, run_parity_test,
    compare_values, GroundTruthSuite,
)
from modules.factory.gates import (
    QualityGateRunner, QualityGateContext, GateStatus, GateSeverity,
    SpecGate, EvidenceGate, SemanticsGate, GroundTruthGate,
    ReferenceParityGate, NumericGate, InputValidationGate,
    UIGate, ContentConsistencyGate, LegalGate, RegressionGate, ReleaseGate,
    get_required_gates_for_spec,
)
from modules.factory.ui import (
    UIField, UISchema, spec_to_ui_schema, BUILTIN_CUSTOM_RENDERERS,
)
from modules.factory.content import (
    ContentPackage, ContentFactory, WorkedExample,
)
from modules.factory.release import (
    ReleaseManifest, VersionBundle, ReleaseManifestValidator,
    ReleaseRegistry, create_release_manifest,
)


# ===== Fixtures =====

@pytest.fixture
def sample_spec():
    """테스트용 CalculatorSpec 생성."""
    return CalculatorSpec(
        id="test-calc-001",
        slug="test-calculator",
        title="테스트 계산기",
        category="테스트",
        description="테스트용 계산기",
        tier=CalculatorTier.C,
        risk_level=RiskLevel.MEDIUM,
        risk_financial=True,
        complexity_level=ComplexityLevel.MEDIUM,
        inputs=[
            InputField(name="principal", label="원금", type="number", unit="원", required=True, min=0),
            InputField(name="rate", label="금리", type="number", unit="%", required=True, min=0, max=100),
            InputField(name="months", label="기간", type="integer", unit="개월", required=True, min=1),
        ],
        outputs=[
            OutputField(name="monthly_payment", label="월납입금", type="number", unit="원", precision=0),
            OutputField(name="total_interest", label="총이자", type="number", unit="원", precision=0),
        ],
        definitions=[
            Definition(name="monthly_rate", expression="rate / 12 / 100", dependencies=[]),
        ],
        parameters=[
            ParameterRef(parameter_id="param-rate", name="연이율", bind_to="monthly_rate"),
        ],
        evidence=[
            EvidenceRef(evidence_id="ev-001", claim="대출 금리 계산 공식", parameter_refs=["param-rate"]),
        ],
        engine=EngineConfig(formula="formualizer", decimal="larzmoney", finance="mortgagemath"),
    )


@pytest.fixture
def sample_evidence():
    """테스트용 EvidenceRecord 생성."""
    return EvidenceRecord(
        evidence_id="ev-001",
        source_type=SourceType.REGULATION,
        source_url="https://example.com/regulation",
        source_title="대출 금리 고시",
        publisher="금융위원회",
        retrieved_at=datetime.utcnow(),
        effective_from=date(2024, 1, 1),
        effective_to=None,
        version="1.0.0",
        content_hash="a" * 64,
        claim="대출 금리 계산 시 연이율을 월이율로 변환",
        parameter_refs=["param-rate"],
        calculator_refs=["test-calc-001"],
        verification_status=VerificationStatus.VERIFIED,
    )


@pytest.fixture
def sample_semantics():
    """테스트용 CalculationSemantics 생성."""
    return CalculationSemantics(
        semantics_id="sem-001",
        calculator_id="test-calc-001",
        version="1.0.0",
        formulas=[
            FormulaAST(expression="monthly_payment = principal * monthly_rate * (1 + monthly_rate)^months / ((1 + monthly_rate)^months - 1)"),
        ],
        definitions=[
            SemDef(name="monthly_rate", formula=FormulaAST(expression="rate / 12 / 100")),
        ],
        rounding=RoundingPolicy(mode=RoundingMode.HALF_UP, precision=0),
    )


@pytest.fixture
def sample_ground_truth_suite():
    """테스트용 GroundTruthSuite 생성."""
    suite = GroundTruthSuite(
        suite_id="gt-001",
        calculator_id="test-calc-001",
        version="1.0.0",
    )
    suite.add_case(GroundTruthCase(
        calculator_id="test-calc-001",
        tier="C",
        inputs={"principal": 100000000, "rate": 5.0, "months": 360},
        expected_outputs={"monthly_payment": 536822, "total_interest": 93255920},
        source=GroundTruthSource.OFFICIAL_EXAMPLE,
        source_reference="금융감독원 대출 계산 예시",
        tolerance=1.0,
    ))
    return suite


# ===== Schema Tests =====

class TestCalculatorSpec:
    def test_valid_spec_passes(self, sample_spec):
        valid, errors = validate_spec(sample_spec)
        assert valid, f"Validation failed: {errors}"

    def test_invalid_spec_fails(self):
        spec = CalculatorSpec(slug="", title="")  # 필수 필드 누락
        valid, errors = validate_spec(spec)
        assert not valid
        assert any("slug is required" in e for e in errors)
        assert any("title is required" in e for e in errors)

    def test_duplicate_input_names_fail(self, sample_spec):
        sample_spec.inputs.append(InputField(name="principal", label="원금2", type="number"))
        valid, errors = validate_spec(sample_spec)
        assert not valid
        assert any("duplicate input field name" in e for e in errors)

    def test_select_requires_enum(self, sample_spec):
        sample_spec.inputs.append(InputField(name="type", label="유형", type="select", enum=[]))
        valid, errors = validate_spec(sample_spec)
        assert not valid
        assert any("select type input" in e and "requires enum" in e for e in errors)

    def test_tier_auto_upgrade_on_high_risk(self):
        spec = CalculatorSpec(
            slug="test", title="Test", category="Test",
            tier=CalculatorTier.S, risk_level=RiskLevel.HIGH,
        )
        assert spec.tier == CalculatorTier.R  # 자동 승격

    def test_spec_to_ui_schema(self, sample_spec):
        ui_schema = spec_to_ui_schema(sample_spec)
        assert ui_schema.calculator_id == sample_spec.id
        assert len(ui_schema.inputs) == 3
        assert ui_schema.inputs[0].name == "principal"
        assert ui_schema.custom_renderer is None


class TestTierRiskComplexity:
    def test_risk_low_complexity_low_is_tier_s(self):
        tier = RiskComplexityMatrix.determine_tier(RiskLevel.LOW, ComplexityLevel.LOW)
        assert tier == CalculatorTier.S

    def test_risk_high_complexity_high_is_tier_r(self):
        tier = RiskComplexityMatrix.determine_tier(RiskLevel.HIGH, ComplexityLevel.HIGH)
        assert tier == CalculatorTier.R

    def test_risk_critical_is_tier_r(self):
        tier = RiskComplexityMatrix.determine_tier(RiskLevel.CRITICAL, ComplexityLevel.LOW)
        assert tier == CalculatorTier.R

    def test_required_gates_includes_legal_for_tier_r(self, sample_spec):
        sample_spec.tier = CalculatorTier.R
        gates = get_required_gates_for_spec(sample_spec)
        assert "LegalGate" in gates
        assert "ReleaseGate" in gates


# ===== Evidence Tests =====

class TestEvidenceRecord:
    def test_valid_evidence_passes(self, sample_evidence):
        valid, errors = validate_evidence(sample_evidence)
        assert valid, f"Validation failed: {errors}"

    def test_missing_source_url_fails(self, sample_evidence):
        sample_evidence.source_url = ""
        valid, errors = validate_evidence(sample_evidence)
        assert not valid
        assert any("source_url is required" in e for e in errors)

    def test_invalid_content_hash_fails(self, sample_evidence):
        sample_evidence.content_hash = "short"
        valid, errors = validate_evidence(sample_evidence)
        assert not valid
        assert any("64-char SHA256" in e for e in errors)

    def test_effective_to_before_from_fails(self, sample_evidence):
        sample_evidence.effective_to = date(2023, 1, 1)
        valid, errors = validate_evidence(sample_evidence)
        assert not valid
        assert any("effective_to cannot be before" in e for e in errors)

    def test_is_effective_on(self, sample_evidence):
        assert sample_evidence.is_effective_on(date(2024, 6, 15))
        assert not sample_evidence.is_effective_on(date(2023, 12, 31))

    def test_to_prov_json(self, sample_evidence):
        prov = sample_evidence.to_prov_json()
        assert "entity" in prov
        assert f"evidence:{sample_evidence.evidence_id}" in prov["entity"]


class TestEvidenceRegistry:
    def test_add_get_update_delete(self, sample_evidence):
        registry = EvidenceRegistry()
        registry.add(sample_evidence)
        assert registry.get(sample_evidence.evidence_id) == sample_evidence

        sample_evidence.claim = "Updated claim"
        registry.update(sample_evidence)
        assert registry.get(sample_evidence.evidence_id).claim == "Updated claim"

        assert registry.delete(sample_evidence.evidence_id)
        assert registry.get(sample_evidence.evidence_id) is None

    def test_find_by_parameter(self, sample_evidence):
        registry = EvidenceRegistry()
        registry.add(sample_evidence)
        results = registry.find_by_parameter("param-rate")
        assert len(results) == 1

    def test_find_effective_on(self, sample_evidence):
        registry = EvidenceRegistry()
        registry.add(sample_evidence)
        results = registry.find_effective_on(date(2024, 6, 15))
        assert len(results) == 1
        results = registry.find_effective_on(date(2023, 1, 1))
        assert len(results) == 0


# ===== Semantics Tests =====

class TestCalculationSemantics:
    def test_valid_semantics_passes(self, sample_semantics):
        valid, errors = validate_semantics(sample_semantics)
        assert valid, f"Validation failed: {errors}"

    def test_missing_calculator_id_fails(self):
        sem = CalculationSemantics(semantics_id="sem-001", calculator_id="")
        valid, errors = validate_semantics(sem)
        assert not valid
        assert any("calculator_id is required" in e for e in errors)

    def test_undefined_definition_dependency_fails(self):
        sem = CalculationSemantics(
            semantics_id="sem-001", calculator_id="test",
            definitions=[SemDef(name="a", formula=FormulaAST(expression="1"), dependencies=["unknown"])],
        )
        valid, errors = validate_semantics(sem)
        assert not valid
        assert any("references unknown definition" in e for e in errors)

    def test_get_formula_definition(self, sample_semantics):
        formula = sample_semantics.get_formula("monthly_payment")
        assert formula is not None

    def test_topological_order(self, sample_semantics):
        order = sample_semantics.topological_order()
        assert isinstance(order, list)


# ===== Ground Truth Tests =====

class TestGroundTruthCase:
    def test_valid_case_passes(self, sample_ground_truth_suite):
        case = sample_ground_truth_suite.cases[0]
        valid, errors = validate_ground_truth_case(case)
        assert valid, f"Validation failed: {errors}"

    def test_missing_inputs_fails(self):
        case = GroundTruthCase(calculator_id="test", inputs={}, expected_outputs={"a": 1})
        valid, errors = validate_ground_truth_case(case)
        assert not valid
        assert any("inputs is required" in e for e in errors)

    def test_ai_generated_precision_warning(self):
        case = GroundTruthCase(
            calculator_id="test",
            inputs={"a": 1},
            expected_outputs={"result": 1.12345678901234567890},  # 의심스러운 정밀도
            source=GroundTruthSource.BENCHMARK,
        )
        valid, errors = validate_ground_truth_case(case)
        assert not valid
        assert any("suspiciously precise" in e for e in errors)


class TestGroundTruthRegistry:
    def test_add_get_by_calculator(self, sample_ground_truth_suite):
        registry = GroundTruthRegistry()
        registry.add(sample_ground_truth_suite)
        results = registry.get_by_calculator("test-calc-001")
        assert len(results) == 1


# ===== Engine Tests =====

class TestCalculationEngineProtocol:
    def test_engine_interface_exists(self):
        # 추상 클래스이므로 직접 인스턴스화 불가
        assert hasattr(CalculationEngine, 'calculate')
        assert hasattr(CalculationEngine, 'validate_inputs')
        assert hasattr(CalculationEngine, 'get_supported_features')

    def test_calculation_result_structure(self):
        result = CalculationResult(
            status=CalculationStatus.SUCCESS,
            outputs={"payment": 1000},
            engine_version="1.0.0",
            semantics_version="1.0.0",
        )
        assert result.is_success()
        assert result.get_error_codes() == []

    def test_calculation_error_codes(self):
        assert FailureCode.INVALID_INPUT
        assert FailureCode.NO_VALID_RATE
        assert FailureCode.DATE_OUT_OF_RANGE


# ===== Parity Tests =====

class TestParityComparison:
    def test_compare_equal_numbers(self):
        comp = compare_values(100.0, 100.0, 1e-9, "test")
        assert comp.passed
        assert comp.difference == 0.0

    def test_compare_within_tolerance(self):
        comp = compare_values(100.0, 100.0000001, 1e-6, "test")
        assert comp.passed

    def test_compare_outside_tolerance(self):
        comp = compare_values(100.0, 101.0, 1e-6, "test")
        assert not comp.passed
        assert comp.difference == 1.0

    def test_compare_none_values(self):
        comp = compare_values(None, None, 1e-9, "test")
        assert comp.passed
        comp = compare_values(100, None, 1e-9, "test")
        assert not comp.passed

    def test_compare_strings(self):
        comp = compare_values("hello", "hello", 1e-9, "test")
        assert comp.passed
        comp = compare_values("hello", "world", 1e-9, "test")
        assert not comp.passed

    def test_relative_diff_calculation(self):
        comp = compare_values(100.0, 101.0, 1e-9, "test")
        assert comp.relative_diff == 0.01


class TestParityRunner:
    def test_parity_runner_creation(self):
        runner = ParityRunner()
        assert runner is not None


# ===== Quality Gate Tests =====

class TestQualityGates:
    def test_spec_gate_passes_valid_spec(self, sample_spec):
        gate = SpecGate()
        context = QualityGateContext(calculator_spec=sample_spec)
        result = gate.execute(context)
        assert result.status == GateStatus.PASS

    def test_spec_gate_fails_invalid_spec(self):
        gate = SpecGate()
        context = QualityGateContext(calculator_spec=CalculatorSpec(slug="", title=""))
        result = gate.execute(context)
        assert result.status == GateStatus.FAIL

    def test_gate_runner_critical_fail_stops(self, sample_spec, sample_evidence, sample_semantics):
        runner = QualityGateRunner(["SpecGate", "EvidenceGate"])
        ev_registry = EvidenceRegistry()
        # sample_evidence를 추가하지 않음 -> EvidenceGate가 FAIL (CRITICAL)
        context = QualityGateContext(
            calculator_spec=sample_spec,
            evidence_registry=ev_registry,
        )
        results = runner.run(context)
        assert runner.has_critical_fail()
        assert results[1].status == GateStatus.FAIL
        assert results[1].severity == GateSeverity.CRITICAL

    def test_required_gates_for_spec(self, sample_spec):
        gates = get_required_gates_for_spec(sample_spec)
        assert "SpecGate" in gates
        assert "EvidenceGate" in gates
        assert "GroundTruthGate" in gates
        assert "ReferenceParityGate" in gates


# ===== UI Schema Tests =====

class TestUISchema:
    def test_spec_to_ui_schema(self, sample_spec):
        ui_schema = spec_to_ui_schema(sample_spec)
        assert isinstance(ui_schema, UISchema)
        assert len(ui_schema.inputs) == 3

    def test_ui_field_form_engine_config(self):
        field = UIField(name="test", label="Test", type="number", unit="원", required=True, min=0, max=100)
        config = field.to_form_engine_config()
        assert config["type"] == "NumberInput"
        assert config["min"] == 0
        assert config["max"] == 100

    def test_custom_renderer_mapping(self):
        assert "loan-schedule" in BUILTIN_CUSTOM_RENDERERS
        assert "tax-bracket" in BUILTIN_CUSTOM_RENDERERS


# ===== Content Tests =====

class TestContentPackage:
    def test_content_package_creation(self, sample_spec):
        factory = ContentFactory()
        engine_result = {
            "outputs": {"monthly_payment": 536822, "total_interest": 93255920},
            "schedule": [{"period": 1, "payment": 536822, "principal": 100000, "interest": 436822, "balance": 99900000}],
        }
        package = factory.generate(sample_spec, engine_result)
        assert isinstance(package, ContentPackage)
        assert package.calculator_id == sample_spec.id
        assert package.engine_driven is True
        assert package.title == sample_spec.title

    def test_content_package_to_dict(self, sample_spec):
        factory = ContentFactory()
        package = factory.generate(sample_spec, {"outputs": {}})
        d = package.to_dict()
        assert d["calculator_id"] == sample_spec.id
        assert "seo_metadata" in d


# ===== Release Manifest Tests =====

class TestReleaseManifest:
    def test_version_bundle_bump(self):
        vb = VersionBundle(spec_version="1.0.0")
        vb2 = vb.bump("spec_version", "minor")
        assert vb2.spec_version == "1.1.0"
        assert vb2.semantics_version == "0.1.0"  # 다른 것 변경 안 됨

    def test_release_manifest_validation(self):
        manifest = ReleaseManifest(
            calculator_id="test-001",
            slug="test-calculator",
            release_version="1.0.0",
            approved_by="reviewer",
            approval_role="legal_reviewer",
        )
        valid, errors = ReleaseManifestValidator.validate(manifest)
        # versions가 기본값이라 모두 0.1.0 -> valid
        assert valid

    def test_invalid_semver_fails(self):
        manifest = ReleaseManifest(
            calculator_id="test", slug="test", release_version="invalid",
            approved_by="a", approval_role="legal_reviewer",
        )
        valid, errors = ReleaseManifestValidator.validate(manifest)
        assert not valid
        assert any("Invalid release_version format" in e for e in errors)

    def test_create_release_manifest(self, sample_spec, sample_semantics, sample_ground_truth_suite):
        manifest = create_release_manifest(
            calculator_id="test-001",
            slug="test-calculator",
            spec=sample_spec,
            semantics=sample_semantics,
            evidence_registry=None,
            ground_truth_suite=sample_ground_truth_suite,
            engine=None,
            ui_schema=None,
            content_package=None,
            parity_report_ref="parity-001",
            approved_by="reviewer",
            approval_role="legal_reviewer",
        )
        assert manifest.calculator_id == "test-001"
        assert manifest.release_version == "0.1.0"
        assert manifest.approved_by == "reviewer"


# ===== Integration Test =====

class TestFactoryIntegration:
    def test_full_factory_flow(self, sample_spec, sample_evidence, sample_semantics, sample_ground_truth_suite):
        """Factory 전체 흐름 테스트: Spec → Evidence → Semantics → Ground Truth → UI → Content → Release"""
        # 1. Spec 검증
        valid, errors = validate_spec(sample_spec)
        assert valid

        # 2. Evidence 등록
        evidence_registry = EvidenceRegistry()
        evidence_registry.add(sample_evidence)

        # 3. Semantics 검증
        valid, errors = validate_semantics(sample_semantics)
        assert valid

        # 4. Ground Truth 검증
        valid, errors = validate_ground_truth_case(sample_ground_truth_suite.cases[0])
        assert valid

        # 5. UI Schema 생성
        ui_schema = spec_to_ui_schema(sample_spec)
        assert len(ui_schema.inputs) == 3

        # 6. Content 생성
        factory = ContentFactory()
        package = factory.generate(sample_spec, {"outputs": {"monthly_payment": 536822}})
        assert package.engine_driven

        # 7. Release Manifest 생성
        manifest = create_release_manifest(
            calculator_id=sample_spec.id,
            slug=sample_spec.slug,
            spec=sample_spec,
            semantics=sample_semantics,
            evidence_registry=evidence_registry,
            ground_truth_suite=sample_ground_truth_suite,
            engine=None, ui_schema=None, content_package=package,
            parity_report_ref="parity-001",
            approved_by="reviewer", approval_role="legal_reviewer",
        )
        valid, errors = ReleaseManifestValidator.validate(manifest)
        assert valid

        print("✅ Full Factory Integration Test PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])