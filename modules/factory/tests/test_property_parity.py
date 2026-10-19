# -*- coding: utf-8 -*-
"""
modules.factory.tests.test_property_parity -- Property-based tests for Factory contracts

PT-01: compare_values() symmetry
PT-02: Explicit tolerance=0 comparison
PT-03: NaN/Infinity handling
PT-04: Valid loan inputs yield positive monthly payment
PT-05: Zero interest rate repayment relationship
"""
import math
from hypothesis import given, settings, strategies as st
import pytest

from modules.factory.parity import compare_values
from loan_ground_truth_parity import calculate_existing_loan


# ===== PT-01: compare_values() symmetry =====
@settings(derandomize=True, max_examples=100, deadline=None)
@given(
    a=st.floats(allow_nan=False, allow_infinity=False, width=64),
    b=st.floats(allow_nan=False, allow_infinity=False, width=64),
    tol=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_compare_values_symmetry(a, b, tol):
    """compare_values(a, b, tol) == compare_values(b, a, tol) for numeric inputs.
    
    Note: relative_diff is NOT symmetric (it's relative to reference value),
    so we only check passed, difference, and tolerance symmetry.
    """
    result_ab = compare_values(a, b, tol, "test")
    result_ba = compare_values(b, a, tol, "test")

    assert result_ab.passed == result_ba.passed
    assert result_ab.difference == result_ba.difference
    assert result_ab.tolerance == result_ba.tolerance


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    a=st.text(min_size=0, max_size=50),
    b=st.text(min_size=0, max_size=50),
    tol=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_compare_values_symmetry_strings(a, b, tol):
    """compare_values symmetry for string inputs."""
    result_ab = compare_values(a, b, tol, "test")
    result_ba = compare_values(b, a, tol, "test")

    assert result_ab.passed == result_ba.passed


# ===== PT-02: Explicit tolerance=0 comparison =====
@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    a=st.floats(allow_nan=False, allow_infinity=False, width=32),
    b=st.floats(allow_nan=False, allow_infinity=False, width=32),
)
def test_compare_values_tolerance_zero_exact_match(a, b):
    """tolerance=0 requires exact match for numeric values."""
    result = compare_values(a, b, 0.0, "test")

    if a == b:
        assert result.passed is True
        assert result.difference == 0.0
    else:
        assert result.passed is False
        assert result.difference == abs(a - b)


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    a=st.text(min_size=0, max_size=20),
    b=st.text(min_size=0, max_size=20),
)
def test_compare_values_tolerance_zero_strings(a, b):
    """tolerance=0 for strings still requires exact match."""
    result = compare_values(a, b, 0.0, "test")

    if a == b:
        assert result.passed is True
    else:
        assert result.passed is False


# ===== PT-03: NaN/Infinity handling =====
def test_compare_values_nan_reference():
    """NaN in reference value -> FAIL (not passed)."""
    result = compare_values(float('nan'), 100.0, 1e-9, "test")
    assert result.passed is False
    assert result.difference is not None and math.isnan(result.difference)


def test_compare_values_nan_production():
    """NaN in production value -> FAIL."""
    result = compare_values(100.0, float('nan'), 1e-9, "test")
    assert result.passed is False
    assert result.difference is not None and math.isnan(result.difference)


def test_compare_values_both_nan():
    """Both NaN -> FAIL (NaN comparison always fails)."""
    result = compare_values(float('nan'), float('nan'), 1e-9, "test")
    assert result.passed is False


def test_compare_values_infinity():
    """Infinity comparison: inf vs inf produces NaN diff -> FAIL per current implementation."""
    result = compare_values(float('inf'), float('inf'), 1e-9, "test")
    # inf - inf = NaN in Python, so comparison fails
    assert result.passed is False
    assert result.difference is not None and math.isnan(result.difference)

    result = compare_values(float('inf'), 100.0, 1e-9, "test")
    assert result.passed is False
    assert result.difference == float('inf')


# ===== PT-04: Valid loan inputs yield positive monthly payment =====
@settings(derandomize=True, max_examples=200, deadline=None)
@given(
    principal=st.integers(min_value=1, max_value=10_000_000_000),
    annual_rate=st.floats(min_value=1e-4, max_value=50.0, allow_nan=False, allow_infinity=False),
    term_years=st.integers(min_value=1, max_value=50),
)
def test_loan_positive_monthly_payment(principal, annual_rate, term_years):
    """Valid loan inputs yield positive monthly payment.
    
    Note: rate >= 1e-4 to avoid numerical issues with factor - 1 when rate is very small.
    """
    result = calculate_existing_loan(principal, annual_rate, term_years)

    assert result is not None, f"Valid inputs returned None: p={principal}, r={annual_rate}, t={term_years}"
    assert isinstance(result, dict)
    assert "monthly_payment" in result
    assert "total_payment" in result
    assert "total_interest" in result

    assert result["monthly_payment"] > 0, f"Monthly payment not positive: {result['monthly_payment']}"
    assert result["total_payment"] > 0
    # Allow small negative due to floating point precision
    assert result["total_interest"] >= -1e-6, f"Total interest negative: {result['total_interest']}"

    assert all(math.isfinite(v) for v in result.values()), f"Non-finite result: {result}"


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    principal=st.integers(min_value=1, max_value=10_000_000_000),
    term_years=st.integers(min_value=1, max_value=50),
)
def test_loan_zero_rate(principal, term_years):
    """Zero interest rate yields principal / months monthly payment."""
    result = calculate_existing_loan(principal, 0.0, term_years)

    assert result is not None
    expected_monthly = principal / (term_years * 12)

    assert abs(result["monthly_payment"] - expected_monthly) < 1e-9
    assert result["total_payment"] == principal
    assert result["total_interest"] == 0


# ===== PT-05: Zero interest rate repayment relationship =====
@settings(derandomize=True, max_examples=100, deadline=None)
@given(
    principal=st.integers(min_value=1, max_value=10_000_000_000),
    term_years=st.integers(min_value=1, max_value=50),
)
def test_zero_rate_repayment_relationship(principal, term_years):
    """Zero rate: total_payment == principal, total_interest == 0."""
    result = calculate_existing_loan(principal, 0.0, term_years)

    assert result is not None
    assert result["total_payment"] == principal
    assert result["total_interest"] == 0
    assert result["monthly_payment"] == principal / (term_years * 12)


# ===== Invalid input handling =====
@pytest.mark.parametrize("principal,annual_rate,term_years", [
    (0, 5.0, 30),
    (-1000, 5.0, 30),
    (100000, -1.0, 30),
    (100000, 5.0, 0),
    (100000, 5.0, -5),
])
def test_invalid_inputs_return_none(principal, annual_rate, term_years):
    """Invalid inputs return None."""
    result = calculate_existing_loan(principal, annual_rate, term_years)
    assert result is None


# ===== Finite check =====
@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    principal=st.integers(min_value=1, max_value=10_000_000_000),
    annual_rate=st.floats(min_value=1e-4, max_value=1000.0, allow_nan=False, allow_infinity=False),
    term_years=st.integers(min_value=1, max_value=100),
)
def test_all_outputs_finite(principal, annual_rate, term_years):
    """All outputs must be finite numbers."""
    result = calculate_existing_loan(principal, annual_rate, term_years)

    if result is not None:
        assert all(math.isfinite(v) for v in result.values())