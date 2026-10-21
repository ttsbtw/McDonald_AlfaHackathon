"""Pure scoring API: assess_application(input_data, product_policy, checks)."""

from __future__ import annotations

from decimal import Context, ROUND_HALF_UP, localcontext

from .contracts import (
    PolicyValidationError, SCHEMA_VERSION, SCORING_VERSION, issue, to_json_value,
    validate_checks, validate_input, validate_policy,
)
from .policy import make_recommendation
from .scorecard import calculate_features, calculate_score

__all__ = ["assess_application", "PolicyValidationError"]


def assess_application(input_data: dict, product_policy: dict, checks: list | None = None) -> dict:
    """Return a JSON-compatible result; invalid policy raises PolicyValidationError.

    Inputs are never mutated. No I/O, clock, randomness or global Decimal settings
    are consulted. Backend supplies trusted product conditions and check results.
    """
    with localcontext(Context(prec=40, rounding=ROUND_HALF_UP)):
        policy = validate_policy(product_policy)
        data, errors = validate_input(input_data)
        parsed_checks, check_errors = validate_checks(checks)
        errors.extend(check_errors)
        if "product_code" in data and data["product_code"] != policy["product_code"]:
            raise PolicyValidationError([issue("policy.product_code", "MISMATCH", "Политика относится к другому продукту.")])
        result = {
            "schema_version": SCHEMA_VERSION, "scoring_version": SCORING_VERSION,
            "policy_version": policy["policy_version"],
            "application_id": data.get("application_id"),
            "application_revision": data.get("application_revision"),
            "as_of_date": data.get("as_of_date"),
            "assessment_status": "INSUFFICIENT_DATA" if errors else "COMPLETED",
            "score": None, "risk_level": "UNKNOWN", "factors": [], "features": {},
            "validation_errors": errors, "input_snapshot": None,
        }
        if errors:
            codes = []
            if any(error["code"] == "MISSING" for error in errors):
                codes.append("MISSING_DATA")
            if any(error["code"] != "MISSING" for error in errors):
                codes.append("INVALID_DATA")
            result.update({
                "recommendation": "REQUEST_INFO", "hard_stops": [], "reason_codes": codes,
                "reasons": [{"code": code, "message": "Исправьте или дополните данные, указанные в validation_errors, и повторите оценку."} for code in codes],
                "missing_fields": [error["field"] for error in errors if error["code"] == "MISSING"],
            })
        else:
            features = calculate_features(data, policy)
            result.update(calculate_score(data, features))
            result["features"] = features
            result.update(make_recommendation(data, parsed_checks, result["score"], features, policy))
            result["input_snapshot"] = {"input_data": data, "product_policy": policy, "checks": parsed_checks}
        return to_json_value(result)
