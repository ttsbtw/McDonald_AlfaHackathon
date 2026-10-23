"""Orchestrate synthetic checks, risk scoring and underwriting rules."""

from datetime import datetime

from ..checks import MockBKIProvider, MockComplianceProvider
from ..checks.bki import bki_scoring_values
from ..scoring import assess_application
from ..underwriting import evaluate_underwriting


class ProcessingPipeline:
    def __init__(self, bki_provider=None, compliance_provider=None):
        self.bki_provider = bki_provider or MockBKIProvider()
        self.compliance_provider = compliance_provider or MockComplianceProvider()

    def run(self, application, company, product, credit_history_consent: bool, checked_at: datetime) -> dict:
        subject_type = "LEGAL_ENTITY" if company.legal_form == "OOO" else "INDIVIDUAL"
        bki = self.bki_provider.lookup(subject_type, company.inn, str(application.id),
                                       credit_history_consent, checked_at)
        compliance = self.compliance_provider.screen(subject_type, company.inn, company.name,
                                                     str(application.id), checked_at)
        bki_values = bki_scoring_values(bki, application.existing_monthly_debt_payment)
        checks = [
            {"source": "company_registry", "status": "PASS", "reason_code": "SYNTHETIC_COMPANY_MATCH"},
            {"source": "credit_history", "status": bki_values["check_status"], "reason_code": bki_values["check_reason"]},
        ]
        as_of_date = checked_at.date()
        input_data = {
            "schema_version": "1.0", "application_id": str(application.id),
            "application_revision": application.revision, "as_of_date": as_of_date.isoformat(),
            "product_code": application.product_code, "requested_amount": application.requested_amount,
            "term_months": application.term_months, "purpose": application.purpose,
            "legal_form": company.legal_form, "registration_date": company.registration_date.isoformat(),
            "average_monthly_revenue": application.average_monthly_revenue,
            "average_monthly_operating_expenses": application.average_monthly_operating_expenses,
            "existing_monthly_debt_payment": bki_values["existing_monthly_debt_payment"],
            "current_overdue_amount": bki_values["current_overdue_amount"],
            "max_overdue_days_12m": bki_values["max_overdue_days_12m"],
            "credit_history_available": bki_values["credit_history_available"],
        }
        result = assess_application(input_data, product.scoring_policy, checks)
        underwriting = evaluate_underwriting(
            subject_id=company.inn, product_code=application.product_code,
            requested_amount=application.requested_amount, registration_date=company.registration_date,
            as_of_date=as_of_date, debt_burden=result.get("features", {}).get("debt_burden"),
            bki=bki, compliance=compliance, product_policy=product.scoring_policy,
        )
        result["underwriting"] = underwriting
        result["external_checks"] = [{
            "source": "compliance",
            "status": "PASS" if compliance["status"] == "CLEAR" else "UNKNOWN",
            "reason_code": compliance["reason_code"],
        }]
        result["preliminary_decision"] = (
            "DECLINE" if underwriting["status"] == "REJECT" else
            "REVIEW" if underwriting["status"] == "REVIEW" else result.get("recommendation", "REVIEW")
        )
        result["versions"] = {"scoring": result.get("scoring_version"),
                               "underwriting": underwriting["rules_version"],
                               "product_policy": product.policy_version}
        return {"bki": bki, "compliance": compliance, "input_data": input_data,
                "checks": checks, "result": result, "underwriting": underwriting,
                "as_of_date": as_of_date}
