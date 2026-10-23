"""Synthetic credit-history provider. No network calls or real personal data."""

from datetime import datetime
from decimal import Decimal
from typing import Protocol


class BKIProvider(Protocol):
    def lookup(self, subject_type: str, subject_id: str, application_id: str,
               consent_confirmed: bool, checked_at: datetime) -> dict: ...


class MockBKIProvider:
    """Stable fixtures selected by synthetic identifiers, never by personal name."""

    _fixtures = {
        "000000000001": {
            "status": "AVAILABLE", "history_code": "POSITIVE_HISTORY",
            "active_loans": 1, "current_debt": "120000.00", "monthly_payment": "10000.00",
            "current_overdue_amount": "0.00", "max_overdue_days_12m": 0,
            "payments_12m": 12, "on_time_payments_12m": 12,
        },
        "000000000002": {
            "status": "AVAILABLE", "history_code": "OVERDUE_DEBT",
            "active_loans": 2, "current_debt": "640000.00", "monthly_payment": "45000.00",
            "current_overdue_amount": "18000.00", "max_overdue_days_12m": 46,
            "payments_12m": 12, "on_time_payments_12m": 9,
        },
        "000000000003": {
            "status": "NO_HISTORY", "history_code": "NO_CREDIT_HISTORY",
            "active_loans": 0, "current_debt": "0.00", "monthly_payment": "0.00",
            "current_overdue_amount": "0.00", "max_overdue_days_12m": 0,
            "payments_12m": 0, "on_time_payments_12m": 0,
        },
        "000000000004": {"status": "UNAVAILABLE", "history_code": "PROVIDER_UNAVAILABLE"},
        "000000000005": {"status": "ERROR", "history_code": "SYNTHETIC_PROVIDER_ERROR"},
    }

    def lookup(self, subject_type: str, subject_id: str, application_id: str,
               consent_confirmed: bool, checked_at: datetime) -> dict:
        if subject_type not in {"LEGAL_ENTITY", "INDIVIDUAL"}:
            return self._result(application_id, subject_type, subject_id, checked_at,
                                "ERROR", "UNSUPPORTED_SUBJECT_TYPE", consent_confirmed)
        if not consent_confirmed:
            return self._result(application_id, subject_type, subject_id, checked_at,
                                "ERROR", "CONSENT_REQUIRED", consent_confirmed)
        fixture = self._fixtures.get(subject_id)
        if fixture is None:
            fixture = {"status": "NO_HISTORY", "history_code": "NO_CREDIT_HISTORY",
                       "active_loans": 0, "current_debt": "0.00", "monthly_payment": "0.00",
                       "current_overdue_amount": "0.00", "max_overdue_days_12m": 0,
                       "payments_12m": 0, "on_time_payments_12m": 0}
        return {**self._result(application_id, subject_type, subject_id, checked_at,
                               fixture["status"], fixture["history_code"], consent_confirmed),
                **{key: value for key, value in fixture.items() if key not in {"status", "history_code"}},
                "source": "synthetic_bki_fixture"}

    @staticmethod
    def _result(application_id, subject_type, subject_id, checked_at, status, reason_code, consent_confirmed):
        return {"application_id": application_id, "subject_type": subject_type,
                "subject_id": subject_id, "checked_at": checked_at.isoformat(),
                "status": status, "reason_code": reason_code, "consent_confirmed": consent_confirmed,
                "source": "synthetic_bki_fixture"}


def bki_scoring_values(report: dict, declared_monthly_payment: Decimal) -> dict:
    available = report["status"] in {"AVAILABLE", "NO_HISTORY"}
    return {
        "credit_history_available": report["status"] == "AVAILABLE",
        "current_overdue_amount": report.get("current_overdue_amount", "0.00"),
        "max_overdue_days_12m": report.get("max_overdue_days_12m", 0),
        "existing_monthly_debt_payment": format(
            declared_monthly_payment + Decimal(report.get("monthly_payment", "0.00")), ".2f"),
        "check_status": "PASS" if available else "UNKNOWN",
        "check_reason": report["reason_code"],
    }
