"""Run from the repository root: python3 -m backend.app.scoring.examples.demo."""

from copy import deepcopy
import json
from pathlib import Path

from .. import assess_application


def scenarios():
    base = json.loads(Path(__file__).with_name("request.json").read_text(encoding="utf-8"))
    yield "approve", deepcopy(base)

    review = deepcopy(base)
    review["input_data"].update(registration_date="2025-11-20",
                              average_monthly_operating_expenses="900000.00",
                              existing_monthly_debt_payment="10000.00")
    yield "review", review

    decline = deepcopy(base)
    decline["input_data"]["current_overdue_amount"] = "5000.00"
    yield "decline", decline

    unknown = deepcopy(base)
    unknown["checks"][1].update(status="UNKNOWN", reason_code="UNAVAILABLE")
    yield "unknown_check", unknown

    missing = deepcopy(base)
    missing["input_data"]["average_monthly_revenue"] = None
    yield "missing_data", missing

    invalid = deepcopy(base)
    invalid["input_data"]["average_monthly_revenue"] = "-1.00"
    yield "invalid_data", invalid


if __name__ == "__main__":
    print(json.dumps({name: assess_application(**request) for name, request in scenarios()},
                     ensure_ascii=False, indent=2))
