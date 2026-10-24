from datetime import datetime, timezone
from decimal import Decimal

from app.checks import MockBKIProvider, MockComplianceProvider
from app.checks.bki import bki_scoring_values
from app.underwriting import evaluate_underwriting

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def test_bki_synthetic_history_scenarios_and_consent():
    provider = MockBKIProvider()
    positive = provider.lookup("INDIVIDUAL", "000000000001", "app-1", True, NOW)
    overdue = provider.lookup("LEGAL_ENTITY", "000000000002", "app-2", True, NOW)
    absent = provider.lookup("LEGAL_ENTITY", "000000000003", "app-3", True, NOW)
    unavailable = provider.lookup("LEGAL_ENTITY", "000000000004", "app-4", True, NOW)
    error = provider.lookup("LEGAL_ENTITY", "000000000005", "app-5", True, NOW)
    no_consent = provider.lookup("LEGAL_ENTITY", "000000000001", "app-6", False, NOW)

    assert positive["status"] == "AVAILABLE" and positive["on_time_payments_12m"] == 12
    assert overdue["current_overdue_amount"] == "18000.00"
    assert absent["status"] == "NO_HISTORY"
    assert unavailable["status"] == "UNAVAILABLE"
    assert error["status"] == "ERROR"
    assert no_consent["reason_code"] == "CONSENT_REQUIRED"
    assert positive["consent_confirmed"] is True and no_consent["consent_confirmed"] is False
    assert positive["application_id"] == "app-1" and positive["checked_at"] == NOW.isoformat()


def test_bki_payment_verifies_declared_total_without_adding_it_twice():
    report = {"status": "AVAILABLE", "reason_code": "POSITIVE_HISTORY", "monthly_payment": "45000.00"}

    assert bki_scoring_values(report, Decimal("50000.00"))["existing_monthly_debt_payment"] == "50000.00"
    assert bki_scoring_values(report, Decimal("30000.00"))["existing_monthly_debt_payment"] == "45000.00"


def test_declared_total_is_used_when_bki_payment_is_unavailable():
    report = {"status": "UNAVAILABLE", "reason_code": "PROVIDER_UNAVAILABLE"}

    result = bki_scoring_values(report, Decimal("50000.00"))

    assert result["existing_monthly_debt_payment"] == "50000.00"
    assert result["check_status"] == "UNKNOWN"


def test_compliance_matches_require_identifier_based_manual_review():
    provider = MockComplianceProvider()
    clear = provider.screen("LEGAL_ENTITY", "000000000001", "Example", "app", NOW)
    potential = provider.screen("LEGAL_ENTITY", "000000000008", "Same Name", "app", NOW)
    confirmed = provider.screen("LEGAL_ENTITY", "000000000009", "Another Name", "app", NOW)
    error = provider.screen("LEGAL_ENTITY", "000000000010", "Example", "app", NOW)

    assert clear["status"] == "CLEAR"
    assert potential["status"] == "POTENTIAL_MATCH" and potential["requires_manual_review"]
    assert confirmed["status"] == "CONFIRMED_MATCH" and confirmed["requires_manual_review"]
    assert error["status"] == "ERROR"
    assert "ФИО" in confirmed["explanation"]


def test_underwriting_routes_confirmed_match_to_manual_review():
    result = evaluate_underwriting(
        subject_id="000000000009", product_code="working_capital", requested_amount=1000000,
        registration_date=NOW.date().replace(year=2022), as_of_date=NOW.date(), debt_burden=None,
        bki={"status": "AVAILABLE", "current_overdue_amount": "0.00"},
        compliance={"status": "CONFIRMED_MATCH"},
        product_policy={"min_business_age_months": 6, "min_amount": "300000", "max_amount": "5000000",
                        "max_debt_burden": "0.70"},
    )
    assert result["status"] == "REVIEW"
    assert "COMPLIANCE_CONFIRMED_MATCH" in result["reason_codes"]
