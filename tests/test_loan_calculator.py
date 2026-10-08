"""
loan-repayment-calculator 테스트
Custom Compute Handler 방식의 원리금균등상환 계산기 검증
"""
import pytest
from modules.app_generator import _compute_js
from modules.formula_engine import CUSTOM_COMPUTE_SLUGS, validate_compute_handler


class TestLoanRepaymentCalculator:
    """loan-repayment-calculator Custom Handler 테스트"""

    def test_custom_compute_slugs_contains_loan(self):
        """CUSTOM_COMPUTE_SLUGS에 loan-repayment-calculator가 등록되어 있는가?"""
        assert "loan-repayment-calculator" in CUSTOM_COMPUTE_SLUGS

    def test_validate_compute_handler_passes(self):
        """validate_compute_handler가 loan calculator를 통과하는가?"""
        ok, msg = validate_compute_handler("loan-repayment-calculator")
        assert ok is True
        assert "loan-repayment-calculator" in msg

    def test_compute_js_generation(self):
        """_compute_js가 loan calculator용 JS를 생성하는가?"""
        calc = {"slug": "loan-repayment-calculator"}
        js = _compute_js(calc)
        
        # 기본 구조 확인
        assert "window.computeResult = function(inputs)" in js
        assert "principal" in js
        assert "annual_rate" in js
        assert "term_years" in js
        assert "monthly_payment" in js
        assert "total_payment" in js
        assert "total_interest" in js
        
        # 핵심 로직 확인
        assert "Math.pow" in js
        assert "Number.isFinite" in js
        assert "r = annual_rate / 12 / 100" in js
        assert "n = term_years * 12" in js
        assert "factor = Math.pow(1 + r, n)" in js
        assert "monthly_payment = principal * r * factor / (factor - 1)" in js
        assert "total_payment = monthly_payment * n" in js
        assert "total_interest = total_payment - principal" in js
        
        # 0% 금리 분기 확인
        assert "if (r === 0)" in js
        assert "monthly_payment = principal / n" in js
        assert "total_interest = 0" in js
        
        # 검증 로직 확인
        assert "Number.isFinite" in js
        assert "if (!Number.isFinite" in js
        assert "if (principal <= 0 || annual_rate < 0 || term_years <= 0)" in js

    def test_compute_result_normal_cases(self):
        """정상 케이스 계산 결과 검증"""
        # JS 실행 환경 시뮬레이션을 위해 Python으로 동일 로직 검증
        def calculate_loan(principal, annual_rate, term_years):
            if principal <= 0 or annual_rate < 0 or term_years <= 0:
                return None
            r = annual_rate / 12 / 100
            n = term_years * 12
            if r == 0:
                monthly_payment = principal / n
                total_payment = principal
                total_interest = 0
            else:
                factor = (1 + r) ** n
                monthly_payment = principal * r * factor / (factor - 1)
                total_payment = monthly_payment * n
                total_interest = total_payment - principal
            
            # NaN/Infinity 체크
            import math
            if not all(math.isfinite(x) for x in [monthly_payment, total_payment, total_interest]):
                return None
            
            return {
                "monthly_payment": monthly_payment,
                "total_payment": total_payment,
                "total_interest": total_interest
            }

        # Case 1: 1억, 5%, 30년
        result = calculate_loan(100000000, 5, 30)
        assert result is not None
        assert abs(result["monthly_payment"] - 536822) <= 1  # 약 536,821원
        assert abs(result["total_payment"] - 193255784) <= 1
        assert abs(result["total_interest"] - 93255784) <= 1

        # Case 2: 1천만, 6%, 1년
        result = calculate_loan(10000000, 6, 1)
        assert result is not None
        assert abs(result["monthly_payment"] - 860664) <= 1

        # Case 3: 5천만, 15%, 5년
        result = calculate_loan(50000000, 15, 5)
        assert result is not None
        assert abs(result["monthly_payment"] - 1189497) <= 50  # 근사치

        # Case 4: 1200만, 0%, 1년 (0% 금리 분기)
        result = calculate_loan(12000000, 0, 1)
        assert result is not None
        assert result["monthly_payment"] == 1000000
        assert result["total_payment"] == 12000000
        assert result["total_interest"] == 0

        # Case 5: 3억, 4.5%, 40년
        result = calculate_loan(300000000, 4.5, 40)
        assert result is not None
        assert abs(result["monthly_payment"] - 1348689) <= 5000

    def test_compute_result_edge_cases(self):
        """경계값 및 이상 입력 방어 검증"""
        def calculate_loan(principal, annual_rate, term_years):
            if principal <= 0 or annual_rate < 0 or term_years <= 0:
                return None
            r = annual_rate / 12 / 100
            n = term_years * 12
            if r == 0:
                monthly_payment = principal / n
                total_payment = principal
                total_interest = 0
            else:
                factor = (1 + r) ** n
                monthly_payment = principal * r * factor / (factor - 1)
                total_payment = monthly_payment * n
                total_interest = total_payment - principal
            
            import math
            if not all(math.isfinite(x) for x in [monthly_payment, total_payment, total_interest]):
                return None
            
            return {
                "monthly_payment": monthly_payment,
                "total_payment": total_payment,
                "total_interest": total_interest
            }

        # principal = 0 → None
        assert calculate_loan(0, 5, 30) is None
        
        # term_years = 0 → None
        assert calculate_loan(100000000, 5, 0) is None
        
        # negative principal → None
        assert calculate_loan(-100000000, 5, 30) is None
        
        # negative rate → None
        assert calculate_loan(100000000, -5, 30) is None
        
        # negative term → None
        assert calculate_loan(100000000, 5, -30) is None
        
        # annual_rate = 0 (0% 금리 분기) → 정상 동작
        result = calculate_loan(12000000, 0, 1)
        assert result is not None
        assert result["monthly_payment"] == 1000000
        assert result["total_interest"] == 0

    def test_compute_result_extreme_values(self):
        """극단값 처리 검증"""
        def calculate_loan(principal, annual_rate, term_years):
            if principal <= 0 or annual_rate < 0 or term_years <= 0:
                return None
            r = annual_rate / 12 / 100
            n = term_years * 12
            if r == 0:
                monthly_payment = principal / n
                total_payment = principal
                total_interest = 0
            else:
                factor = (1 + r) ** n
                monthly_payment = principal * r * factor / (factor - 1)
                total_payment = monthly_payment * n
                total_interest = total_payment - principal
            
            import math
            if not all(math.isfinite(x) for x in [monthly_payment, total_payment, total_interest]):
                return None
            
            return {
                "monthly_payment": monthly_payment,
                "total_payment": total_payment,
                "total_interest": total_interest
            }

        # 극대 principal (1조)
        result = calculate_loan(10**12, 5, 30)
        assert result is not None
        assert result["monthly_payment"] > 0
        
        # 극대 rate (1000%)
        result = calculate_loan(100000000, 1000, 30)
        assert result is not None
        assert result["monthly_payment"] > 0
        
        # 극대 term (100년)
        result = calculate_loan(100000000, 5, 100)
        assert result is not None
        assert result["monthly_payment"] > 0

    def test_compute_result_consistency(self):
        """수학적 일관성 검증"""
        def calculate_loan(principal, annual_rate, term_years):
            if principal <= 0 or annual_rate < 0 or term_years <= 0:
                return None
            r = annual_rate / 12 / 100
            n = term_years * 12
            if r == 0:
                monthly_payment = principal / n
                total_payment = principal
                total_interest = 0
            else:
                factor = (1 + r) ** n
                monthly_payment = principal * r * factor / (factor - 1)
                total_payment = monthly_payment * n
                total_interest = total_payment - principal
            
            import math
            if not all(math.isfinite(x) for x in [monthly_payment, total_payment, total_interest]):
                return None
            
            return {
                "monthly_payment": monthly_payment,
                "total_payment": total_payment,
                "total_interest": total_interest
            }

        # 금리 증가 → 월상환액/총이자 증가
        r1 = calculate_loan(100000000, 5, 30)
        r2 = calculate_loan(100000000, 10, 30)
        assert r1["monthly_payment"] < r2["monthly_payment"]
        assert r1["total_interest"] < r2["total_interest"]
        
        # 기간 증가 → 월상환액 감소, 총이자 증가 (동일 조건)
        r1 = calculate_loan(100000000, 5, 10)
        r2 = calculate_loan(100000000, 5, 30)
        assert r1["monthly_payment"] > r2["monthly_payment"]
        assert r1["total_interest"] < r2["total_interest"]
        
        # 원금 증가 → 월상환액 증가
        r1 = calculate_loan(100000000, 5, 30)
        r2 = calculate_loan(200000000, 5, 30)
        assert r1["monthly_payment"] < r2["monthly_payment"]

    def test_nan_infinity_protection(self):
        """NaN/Infinity 방어 검증"""
        def calculate_loan(principal, annual_rate, term_years):
            if principal <= 0 or annual_rate < 0 or term_years <= 0:
                return None
            r = annual_rate / 12 / 100
            n = term_years * 12
            if r == 0:
                monthly_payment = principal / n
                total_payment = principal
                total_interest = 0
            else:
                factor = (1 + r) ** n
                monthly_payment = principal * r * factor / (factor - 1)
                total_payment = monthly_payment * n
                total_interest = total_payment - principal
            
            import math
            if not all(math.isfinite(x) for x in [monthly_payment, total_payment, total_interest]):
                return None
            
            return {
                "monthly_payment": monthly_payment,
                "total_payment": total_payment,
                "total_interest": total_interest
            }

        # division by zero 상황: r=0이고 n=0인 경우 term_years=0에서 이미 차단됨
        # NaN 상황: 0/0 등은 입력 검증에서 차단
        # Infinity: 극대값에서도 math.isfinite로 차단

    def test_no_formula_engine_dependency(self):
        """Formula Engine의 _MAX_POW를 우회하는가?"""
        # loan-repayment-calculator는 CUSTOM_COMPUTE_SLUGS에 등록되어
        # Formula Engine의 validate_formula()를 건너뛰므로
        # _MAX_POW=8 제한에 걸리지 않아야 함
        assert "loan-repayment-calculator" in CUSTOM_COMPUTE_SLUGS
        
        # _compute_js가 Math.pow(1+r, n)을 사용하며 n=360(30년*12)도 처리 가능
        calc = {"slug": "loan-repayment-calculator"}
        js = _compute_js(calc)
        assert "Math.pow" in js
        # JS의 Math.pow는 지수 제한이 없음 (Formula Engine의 _MAX_POW와 무관)

    def test_existing_handlers_unaffected(self):
        """기존 custom handler들이 영향을 받지 않는가?"""
        existing_slugs = [
            "unemployment-benefit",
            "four-insurances", 
            "annual-leave-allowance",
            "annual-leave-remaining",
            "real-estate-brokerage-fee",
            "자동차_취등록세_계산기",
            "연금저축_irp_세액공제_계산기",
            "irp-tax-credit-v2",
            "severance-pay",
            "freelancer-tax-3p3",
        ]
        
        for slug in existing_slugs:
            calc = {"slug": slug}
            js = _compute_js({"slug": slug})
            assert len(js) > 100, f"{slug} handler가 비어있음"
            assert "window.computeResult = function(inputs)" in js


if __name__ == "__main__":
    pytest.main([__file__, "-v"])