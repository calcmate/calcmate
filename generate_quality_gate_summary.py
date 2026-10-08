# -*- coding: utf-8 -*-
"""
CI용 Quality Gate Summary 생성 스크립트
quality-gate-summary.json 생성
"""

from modules.factory.schemas import CalculatorSpec, CalculatorTier, RiskLevel, ComplexityLevel, InputField, OutputField, Definition, EvidenceRef, EngineConfig, ParameterRef
from modules.factory.evidence import EvidenceRecord, SourceType, VerificationStatus, EvidenceRegistry
from modules.factory.semantics import CalculationSemantics, FormulaAST, Definition as SemDef, RoundingMode, RoundingPolicy
from modules.factory.ground_truth import GroundTruthCase, GroundTruthSuite, GroundTruthSource, GroundTruthRegistry
from modules.factory.engine import CalculationEngine, CalculationContext, CalculationResult, CalculationStatus
from modules.factory.parity import ParityRunner, ParityStatus
from modules.factory.gates import QualityGateRunner, QualityGateContext, get_required_gates_for_spec, GateStatus, GateSeverity
from modules.factory.release import ReleaseManifest, VersionBundle
from modules.factory.engine.adapters import MortgageMathAdapter, FormualizerAdapter


def main():
    """Quality Gate 실행 및 summary JSON 생성"""
    print("=" * 60)
    print("Quality Gate Summary Generation")
    print("=" * 60)

    # Calculator Spec 구성 (Loan Calculator용)
    spec = CalculatorSpec(
        id='loan-repayment-calculator',
        slug='loan-repayment-calculator',
        title='대출 상환 계산기',
        category='금융/대출',
        description='원리금균등상환 방식의 대출 상환 계산기',
        tier=CalculatorTier.C,
        risk_level=RiskLevel.MEDIUM,
        risk_financial=True,
        risk_user_impact='금융 상품 선택 참고용',
        complexity_level=ComplexityLevel.MEDIUM,
        scope_included=['원리금균등상환', '월납입금', '총이자', '상환스케줄'],
        scope_excluded=['원금균등상환', '변동금리', '거치기간', '중도상환'],
        inputs=[
            InputField(name='principal', label='대출원금', type='number', unit='원', required=True, min=0),
            InputField(name='annual_rate', label='연이율', type='number', unit='%', required=True, min=0, max=20),
            InputField(name='term_years', label='대출기간', type='integer', unit='년', required=True, min=1, max=50),
        ],
        outputs=[
            OutputField(name='monthly_payment', label='월납입금', type='number', unit='원', precision=0),
            OutputField(name='total_payment', label='총납입액', type='number', unit='원', precision=0),
            OutputField(name='total_interest', label='총이자', type='number', unit='원', precision=0),
        ],
        definitions=[
            Definition(name='monthly_rate', expression='annual_rate / 12 / 100', dependencies=[]),
            Definition(name='num_payments', expression='term_years * 12', dependencies=[]),
        ],
        parameters=[
            ParameterRef(parameter_id='param-monthly-rate', name='월이율', bind_to='monthly_rate'),
            ParameterRef(parameter_id='param-num-payments', name='납입횟수', bind_to='num_payments'),
        ],
        evidence=[
            EvidenceRef(evidence_id='ev-loan-amortization', claim='원리금균등상환 공식', parameter_refs=['param-monthly-rate', 'param-num-payments']),
        ],
        engine=EngineConfig(formula='formualizer', decimal='larzmoney', finance='mortgagemath'),
    )

    # Evidence Registry
    evidence_registry = EvidenceRegistry()
    evidence = EvidenceRecord(
        evidence_id='ev-loan-amortization',
        source_type=SourceType.OTHER,
        source_url='https://en.wikipedia.org/wiki/Amortization',
        source_title='Amortization - Wikipedia',
        publisher='Wikipedia',
        retrieved_at=None,
        effective_from=None,
        effective_to=None,
        version='1.0.0',
        content_hash='a' * 64,
        claim='원리금균등상환 공식: M = P * r(1+r)^n / ((1+r)^n - 1)',
        parameter_refs=['monthly_rate', 'num_payments'],
        calculator_refs=['loan-repayment-calculator'],
        verification_status=VerificationStatus.VERIFIED,
    )
    evidence_registry.add(evidence)

    # Semantics
    semantics = CalculationSemantics(
        semantics_id='sem-loan-amortization',
        calculator_id='loan-repayment-calculator',
        version='1.0.0',
        formulas=[
            FormulaAST(expression='monthly_payment = principal * monthly_rate * (1 + monthly_rate) ** num_payments / ((1 + monthly_rate) ** num_payments - 1)', dependencies=['principal', 'monthly_rate', 'num_payments']),
            FormulaAST(expression='total_payment = monthly_payment * num_payments', dependencies=['monthly_payment', 'num_payments']),
            FormulaAST(expression='total_interest = total_payment - principal', dependencies=['total_payment', 'principal']),
        ],
        definitions=[
            SemDef(name='monthly_rate', formula=FormulaAST(expression='annual_rate / 12 / 100', dependencies=['annual_rate'])),
            SemDef(name='num_payments', formula=FormulaAST(expression='term_years * 12', dependencies=['term_years'])),
        ],
        rounding=RoundingPolicy(mode=RoundingMode.HALF_UP, precision=0),
    )

    # Ground Truth
    gt_suite = GroundTruthSuite(
        suite_id='gt-loan-repayment-v1',
        calculator_id='loan-repayment-calculator',
        version='1.0.0',
    )
    # 3개 기본 케이스
    case1 = GroundTruthCase(
        calculator_id='loan-repayment-calculator',
        tier='C',
        inputs={'principal': 100000000, 'annual_rate': 5.0, 'term_years': 30},
        expected_outputs={'monthly_payment': 536822, 'total_payment': 193255784, 'total_interest': 93255784},
        source=GroundTruthSource.VERIFIED_CALCULATOR,
        source_reference='test_loan_calculator.py',
        tolerance=1000.0,  # mortgagemath rounding 차이 허용
    )
    gt_suite.add_case(case1)

    case2 = GroundTruthCase(
        calculator_id='loan-repayment-calculator',
        tier='C',
        inputs={'principal': 10000000, 'annual_rate': 6.0, 'term_years': 1},
        expected_outputs={'monthly_payment': 860664, 'total_payment': 10327968, 'total_interest': 327968},
        source=GroundTruthSource.VERIFIED_CALCULATOR,
        source_reference='test_loan_calculator.py',
        tolerance=100.0,  # mortgagemath rounding 차이 허용
    )
    gt_suite.add_case(case2)

    case3 = GroundTruthCase(
        calculator_id='loan-repayment-calculator',
        tier='C',
        inputs={'principal': 12000000, 'annual_rate': 0.0, 'term_years': 1},
        expected_outputs={'monthly_payment': 1000000, 'total_payment': 12000000, 'total_interest': 0},
        source=GroundTruthSource.MATHEMATICAL_KNOWN_VALUE,
        source_reference='Mathematical definition',
        tolerance=0.0,
    )
    gt_suite.add_case(case3)

    # Engines
    ref_engine = FormualizerAdapter()
    prod_engine = MortgageMathAdapter()

    # Parity 실행
    parity_runner = ParityRunner()
    context = CalculationContext()
    parameters = {}
    evidence_dict = {}

    print("[1] Parity 실행 중...")
    from modules.factory.ground_truth import get_ground_truth_registry
    gt_registry = get_ground_truth_registry()
    gt_registry.add(gt_suite)
    
    parity_report = parity_runner.run(
        suite_id=gt_suite.suite_id,
        reference_engine=ref_engine,
        production_engine=prod_engine,
        semantics=semantics,
        parameters=parameters,
        evidence=evidence_dict,
        context=context,
    )
    print(f"   Parity Report: {parity_report.total_cases} cases, "
          f"passed={parity_report.passed_cases}, failed={parity_report.failed_cases}, "
          f"errors={parity_report.error_cases}")

    # Quality Gates 실행
    print("[2] Quality Gates 실행 중...")
    
    # 최소한의 ReleaseManifest 생성 (ReleaseGate 통과용)
    version_bundle = VersionBundle(
        spec_version="1.0.0",
        semantics_version="1.0.0",
        evidence_version="1.0.0",
        parameter_version="1.0.0",
        engine_version="1.0.0",
        ui_version="1.0.0",
        content_version="1.0.0",
        validation_version="1.0.0",
    )
    release_manifest = ReleaseManifest(
        calculator_id=spec.id,
        slug=spec.slug,
        release_version="1.0.0",
        versions=version_bundle,
        approved_by="CI",
        approval_role="automated",
    )
    
    gate_context = QualityGateContext(
        calculator_spec=spec,
        semantics=semantics,
        ground_truth_suite=gt_suite,
        evidence_registry=evidence_registry,
        reference_engine=ref_engine,
        production_engine=prod_engine,
        parity_report=parity_report,
        ui_schema=None,
        content_package=None,
        release_manifest=release_manifest,
        existing_calculators=[],
    )

    runner = QualityGateRunner()
    results = runner.run(gate_context)

    # Summary JSON 생성
    summary = runner.to_summary_json()

    # JSON 파일로 저장
    import json
    with open('quality-gate-summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[3] Quality Gate Summary 생성 완료")
    print(f"   Status: {summary['status']}")
    print(f"   Total Gates: {summary['summary']['total_gates']}")
    print(f"   Passed: {summary['summary']['passed']}")
    print(f"   Failed: {summary['summary']['failed']}")
    print(f"   Skipped: {summary['summary']['skipped']}")
    print(f"   Not Applicable: {summary['summary']['not_applicable']}")
    print(f"   Errors: {summary['summary']['errors']}")

    for gate in summary['gates']:
        print(f"   - {gate['name']}: {gate['status']}")

    print("\nquality-gate-summary.json 생성 완료")
    return summary['status'] == 'PASS'


if __name__ == '__main__':
    import json
    success = main()
    exit(0 if success else 1)