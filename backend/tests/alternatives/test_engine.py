from datetime import date
from decimal import Decimal

from app.alternatives import generate_alternatives
from app.scoring import assess_application
from app.underwriting import evaluate_underwriting

POLICY = {
    "policy_version": "test-policy-v1", "product_code": "working_capital",
    "min_amount": "300000.00", "max_amount": "5000000.00",
    "min_term_months": 6, "max_term_months": 36,
    "annual_interest_rate": "24.00", "min_business_age_months": 6,
    "max_debt_burden": "0.70", "max_overdue_days_12m": 30,
    "approve_score": 75, "review_score": 50,
    "required_checks": ["company_registry", "credit_history"],
}
CHECKS = [
    {"source": "company_registry", "status": "PASS", "reason_code": "SYNTHETIC_COMPANY_MATCH"},
    {"source": "credit_history", "status": "PASS", "reason_code": "AVAILABLE"},
]
BKI = {
    "status": "AVAILABLE", "monthly_payment": "10000.00", "current_overdue_amount": "0.00",
    "max_overdue_days_12m": 0,
}
COMPLIANCE = {"status": "CLEAR", "reason_code": "NO_MATCH"}


def assess(amount="5000000.00", term=24, current_overdue="0.00", compliance=COMPLIANCE):
    data = {
        "schema_version": "1.0", "application_id": "00000000-0000-0000-0000-000000000123",
        "application_revision": 1, "as_of_date": "2026-10-23", "product_code": "working_capital",
        "requested_amount": amount, "term_months": term, "purpose": "Оборотные средства",
        "legal_form": "IP", "registration_date": "2022-01-15",
        "average_monthly_revenue": "1000000.00", "average_monthly_operating_expenses": "600000.00",
        "existing_monthly_debt_payment": "60000.00", "current_overdue_amount": current_overdue,
        "max_overdue_days_12m": 0, "credit_history_available": True,
    }
    result = assess_application(data, POLICY, CHECKS)
    underwriting = evaluate_underwriting(
        subject_id="000000000001", product_code="working_capital",
        requested_amount=Decimal(amount), registration_date=date(2022, 1, 15),
        as_of_date=date(2026, 10, 23),
        debt_burden=result["features"].get("debt_burden"), bki=BKI, compliance=compliance,
        product_policy=POLICY,
    )
    return data, result, underwriting


def test_generates_dynamic_variants_that_pass_scoring_and_underwriting():
    data, result, underwriting = assess()
    generated = generate_alternatives(
        input_data=data, product_policy=POLICY, checks=CHECKS, bki=BKI, compliance=COMPLIANCE,
        subject_id="000000000001", registration_date="2022-01-15",
        original_result=result, original_underwriting=underwriting,
    )

    assert generated["status"] == "AVAILABLE"
    assert 1 <= len(generated["alternatives"]) <= 3
    assert generated["original"]["amount"] == "5000000.00"
    for option in generated["alternatives"]:
        assert option["amount"] != "5000000.00" or option["term_months"] != 24
        assert Decimal(POLICY["min_amount"]) <= Decimal(option["amount"]) <= Decimal(POLICY["max_amount"])
        assert POLICY["min_term_months"] <= option["term_months"] <= POLICY["max_term_months"]
        assert option["scoring"]["hard_stops"] == []
        assert option["underwriting"]["status"] == "PASS"
        assert option["is_demo"] is True


def test_does_not_offer_alternatives_for_current_overdue_or_blocking_compliance():
    data, result, underwriting = assess(current_overdue="100.00")
    generated = generate_alternatives(
        input_data=data, product_policy=POLICY, checks=CHECKS, bki=BKI, compliance=COMPLIANCE,
        subject_id="000000000001", registration_date="2022-01-15",
        original_result=result, original_underwriting=underwriting,
    )
    assert generated["status"] == "BLOCKED"
    assert generated["alternatives"] == []

    data, result, underwriting = assess(compliance={"status": "CONFIRMED_MATCH", "reason_code": "MATCH"})
    generated = generate_alternatives(
        input_data=data, product_policy=POLICY, checks=CHECKS, bki=BKI,
        compliance={"status": "CONFIRMED_MATCH", "reason_code": "MATCH"},
        subject_id="000000000001", registration_date="2022-01-15",
        original_result=result, original_underwriting=underwriting,
    )
    assert generated["status"] == "BLOCKED"
    assert generated["alternatives"] == []


def test_returns_no_alternatives_when_original_conditions_pass():
    data, result, underwriting = assess(amount="300000.00", term=12)
    generated = generate_alternatives(
        input_data=data, product_policy=POLICY, checks=CHECKS, bki=BKI, compliance=COMPLIANCE,
        subject_id="000000000001", registration_date="2022-01-15",
        original_result=result, original_underwriting=underwriting,
    )
    assert generated["status"] == "NOT_REQUIRED"
    assert generated["alternatives"] == []
