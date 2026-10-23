"""Synthetic compliance screening with identifier-confirmed fixture matches."""

from datetime import datetime
from typing import Protocol


class ComplianceProvider(Protocol):
    def screen(self, subject_type: str, subject_id: str, subject_name: str,
               application_id: str, checked_at: datetime) -> dict: ...


class MockComplianceProvider:
    _fixtures = {
        "000000000008": ("POTENTIAL_MATCH", "SYNTHETIC_POTENTIAL_MATCH"),
        "000000000009": ("CONFIRMED_MATCH", "SYNTHETIC_CONFIRMED_MATCH"),
        "000000000010": ("ERROR", "SYNTHETIC_PROVIDER_ERROR"),
    }

    def screen(self, subject_type: str, subject_id: str, subject_name: str,
               application_id: str, checked_at: datetime) -> dict:
        status, reason = self._fixtures.get(subject_id, ("CLEAR", "NO_SYNTHETIC_MATCH"))
        return {
            "application_id": application_id, "subject_type": subject_type,
            "subject_id": subject_id, "subject_name": subject_name,
            "status": status, "reason_code": reason,
            "source": "synthetic_compliance_fixture", "checked_at": checked_at.isoformat(),
            "lists": {"rosfinmonitoring": status, "foreign_agents": "CLEAR"},
            "explanation": ("Совпадения по одному ФИО недостаточно; синтетический сценарий "
                            "сопоставляет устойчивый идентификатор субъекта."),
            "requires_manual_review": status in {"POTENTIAL_MATCH", "CONFIRMED_MATCH"},
        }
