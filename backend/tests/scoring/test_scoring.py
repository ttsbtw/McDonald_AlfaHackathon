"""Contract, boundary and regression tests; run with unittest or pytest."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import json
from pathlib import Path
import unittest

from backend.app.scoring import PolicyValidationError, assess_application
from backend.app.scoring.examples.demo import scenarios


EXAMPLES = Path(__file__).resolve().parents[2] / "app" / "scoring" / "examples"


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((EXAMPLES / "request.json").read_text(encoding="utf-8"))
        self.data = self.request["input_data"]
        self.policy = self.request["product_policy"]

    def assess(self):
        return assess_application(**self.request)

    def points(self, code):
        return next(f["points"] for f in self.assess()["factors"] if f["code"] == code)

    def test_approved_result_and_json_roundtrip(self):
        result = self.assess()
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["recommendation"], "APPROVE")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["assessment_status"], "COMPLETED")
        self.assertEqual(result["score"], sum(f["points"] for f in result["factors"]))
        self.assertEqual(result["application_revision"], 1)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_committed_integration_response(self):
        expected = json.loads((EXAMPLES / "response.json").read_text(encoding="utf-8"))
        self.assertEqual(self.assess(), expected)

    def test_all_demo_scenarios(self):
        expected = {"approve": (100, "APPROVE"), "review": (58, "REVIEW"),
                    "decline": (80, "DECLINE"), "unknown_check": (100, "REQUEST_INFO"),
                    "missing_data": (None, "REQUEST_INFO"), "invalid_data": (None, "REQUEST_INFO")}
        for name, request in scenarios():
            with self.subTest(name=name):
                result = assess_application(**request)
                self.assertEqual((result["score"], result["recommendation"]), expected[name])

    def test_deterministic_and_no_mutation(self):
        original = deepcopy(self.request)
        result = self.assess()
        for _ in range(5):
            self.assertEqual(self.assess(), result)
        self.assertEqual(original, self.request)
        result["input_snapshot"]["checks"][0]["status"] = "FAIL"
        self.assertEqual(original, self.request)

    def test_independent_of_callers_decimal_context(self):
        expected = self.assess()
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            self.assertEqual(self.assess(), expected)
            self.assertEqual(context.prec, 3)
            self.assertTrue(context.traps[Inexact])

    def test_decimal_and_date_inputs_equal_json(self):
        expected = self.assess()
        self.data["requested_amount"] = Decimal("300000.00")
        self.data["registration_date"] = date(2022, 10, 20)
        self.data["as_of_date"] = date(2026, 10, 20)
        self.assertEqual(self.assess(), expected)

    def test_age_boundaries_and_hard_stop(self):
        for registration, months, points in [
            ("2026-04-21", 5, 0), ("2026-04-20", 6, 5),
            ("2025-10-21", 11, 5), ("2025-10-20", 12, 12),
            ("2024-10-21", 23, 12), ("2024-10-20", 24, 20),
        ]:
            with self.subTest(months=months):
                self.data["registration_date"] = registration
                result = self.assess()
                self.assertEqual(result["features"]["business_age_months"], months)
                self.assertEqual(self.points("BUSINESS_AGE"), points)
                self.assertEqual("BUSINESS_TOO_YOUNG" in result["hard_stops"], months < 6)

    def test_end_of_month_age_is_full_calendar_months(self):
        self.data.update(registration_date="2024-02-29", as_of_date="2025-02-28")
        self.assertEqual(self.assess()["features"]["business_age_months"], 11)
        self.data["as_of_date"] = "2025-03-01"
        self.assertEqual(self.assess()["features"]["business_age_months"], 12)

    def test_margin_boundaries(self):
        for expense, points in [("700000", 25), ("700000.01", 18),
                                ("850000", 18), ("850000.01", 8),
                                ("999999.99", 8), ("1000000", 0), ("1000001", 0)]:
            with self.subTest(expense=expense):
                self.data["average_monthly_operating_expenses"] = expense
                self.assertEqual(self.points("OPERATING_MARGIN"), points)

    def test_debt_thresholds_include_new_payment(self):
        self.policy["annual_interest_rate"] = "0"
        self.data.update(average_monthly_revenue="200000", average_monthly_operating_expenses="100000",
                         requested_amount="120000", term_months=12)
        for existing, points, stopped in [("20000", 35, False), ("20000.01", 25, False),
                                         ("40000", 25, False), ("40000.01", 10, False),
                                         ("60000", 10, False), ("60000.01", 0, True)]:
            with self.subTest(existing=existing):
                self.data["existing_monthly_debt_payment"] = existing
                self.assertEqual(self.points("DEBT_BURDEN"), points)
                self.assertEqual("EXCESSIVE_DEBT_BURDEN" in self.assess()["hard_stops"], stopped)

    def test_annuity_reference_value(self):
        self.data.update(requested_amount="120000", term_months=12)
        self.policy["annual_interest_rate"] = "12.00"
        self.assertEqual(self.assess()["features"]["new_monthly_payment"], "10661.86")

    def test_zero_rate_payment_rounds_up(self):
        self.data.update(requested_amount="100000.00", term_months=3)
        self.policy["annual_interest_rate"] = "0.00"
        self.assertEqual(self.assess()["features"]["new_monthly_payment"], "33333.34")

    def test_zero_and_negative_operating_profit(self):
        for revenue, expenses in [("0", "0"), ("0", "100"), ("100", "100"), ("100", "101")]:
            with self.subTest(revenue=revenue, expenses=expenses):
                self.data.update(average_monthly_revenue=revenue, average_monthly_operating_expenses=expenses)
                result = self.assess()
                self.assertEqual(result["recommendation"], "DECLINE")
                self.assertIsNone(result["features"]["debt_burden"])
                self.assertIn("NON_POSITIVE_OPERATING_PROFIT", result["hard_stops"])

    def test_overdue_boundaries(self):
        for days, points, stop in [(0, 20, False), (1, 12, False), (7, 12, False),
                                  (8, 5, False), (30, 5, False), (31, 0, True), (366, 0, True)]:
            with self.subTest(days=days):
                self.data["max_overdue_days_12m"] = days
                self.assertEqual(self.points("PAYMENT_HISTORY"), points)
                self.assertEqual("SEVERE_OVERDUE_HISTORY" in self.assess()["hard_stops"], stop)

    def test_current_overdue_overrides_high_score(self):
        self.data["current_overdue_amount"] = "0.01"
        result = self.assess()
        self.assertEqual(result["score"], 80)
        self.assertEqual(result["recommendation"], "DECLINE")
        self.assertIn("CURRENT_OVERDUE", result["reason_codes"])

    def test_product_bounds_are_inclusive(self):
        for field, minimum, maximum, below, above, reason in [
            ("requested_amount", "50000", "5000000", "49999.99", "5000000.01", "AMOUNT_OUT_OF_RANGE"),
            ("term_months", 6, 60, 5, 61, "TERM_OUT_OF_RANGE"),
        ]:
            original = self.data[field]
            for value in (minimum, maximum, below, above):
                with self.subTest(field=field, value=value):
                    self.data[field] = value
                    self.assertEqual(reason in self.assess()["hard_stops"], value in (below, above))
            self.data[field] = original

    def test_recommendation_score_boundaries(self):
        self.data["max_overdue_days_12m"] = 8  # 85 points, no hard stops.
        for approve, review, recommendation in [(85, 50, "APPROVE"), (86, 85, "REVIEW"), (90, 86, "DECLINE")]:
            with self.subTest(recommendation=recommendation):
                self.policy.update(approve_score=approve, review_score=review)
                result = self.assess()
                self.assertEqual(result["score"], 85)
                self.assertEqual(result["recommendation"], recommendation)
                self.assertEqual(result["hard_stops"], [])

    def test_risk_level_boundaries(self):
        self.policy["annual_interest_rate"] = "0"
        self.data.update(requested_amount="120000", average_monthly_revenue="100000",
                         average_monthly_operating_expenses="60000")
        for registration, debt, days, score, risk in [
            ("2024-10-20", "14000", 0, 75, "LOW"),
            ("2025-10-20", "6000", 7, 74, "MEDIUM"),
            ("2026-04-20", "22000", 0, 50, "MEDIUM"),
            ("2025-10-20", "22000", 7, 49, "HIGH"),
        ]:
            with self.subTest(score=score):
                self.data.update(registration_date=registration, existing_monthly_debt_payment=debt,
                                 max_overdue_days_12m=days)
                result = self.assess()
                self.assertEqual((result["score"], result["risk_level"]), (score, risk))

    def test_minimum_score(self):
        self.data.update(registration_date="2026-10-20", average_monthly_revenue="0",
                         max_overdue_days_12m=31)
        result = self.assess()
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertEqual(result["recommendation"], "DECLINE")

    def test_required_checks_missing_or_unknown(self):
        for checks in (None, [], self.request["checks"][:1], [
            {"source": "credit_history", "status": "UNKNOWN", "reason_code": "TIMEOUT"}
        ]):
            with self.subTest(checks=checks):
                result = assess_application(self.data, self.policy, checks)
                self.assertEqual(result["recommendation"], "REQUEST_INFO")
                self.assertEqual(result["score"], 100)
                self.assertIn("CHECKS_INCOMPLETE", result["reason_codes"])
                self.assertTrue(result["missing_fields"])

    def test_failed_check_overrides_score_and_unknown_check(self):
        self.request["checks"][0].update(status="FAIL", reason_code="INACTIVE")
        self.request["checks"][1].update(status="UNKNOWN", reason_code="TIMEOUT")
        result = self.assess()
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["recommendation"], "DECLINE")
        self.assertIn("CHECK_FAILED:company_registry", result["hard_stops"])
        self.assertIn("checks.credit_history", result["missing_fields"])

    def test_extra_checks_cannot_be_ignored(self):
        for status, recommendation in [("FAIL", "DECLINE"), ("UNKNOWN", "REQUEST_INFO")]:
            with self.subTest(status=status):
                checks = self.request["checks"] + [{"source": "extra", "status": status, "reason_code": "DEMO"}]
                self.assertEqual(assess_application(self.data, self.policy, checks)["recommendation"], recommendation)

    def test_check_order_does_not_change_result(self):
        expected = self.assess()
        self.request["checks"].reverse()
        self.policy["required_checks"].reverse()
        self.assertEqual(self.assess(), expected)

    def test_every_missing_field_and_null(self):
        for field in list(self.data):
            for missing in (True, False):
                with self.subTest(field=field, absent=missing):
                    request = deepcopy(self.request)
                    if missing:
                        del request["input_data"][field]
                    else:
                        request["input_data"][field] = None
                    result = assess_application(**request)
                    self.assertEqual(result["assessment_status"], "INSUFFICIENT_DATA")
                    self.assertEqual(result["recommendation"], "REQUEST_INFO")
                    self.assertIsNone(result["score"])
                    self.assertIn(field, result["missing_fields"])

    def test_invalid_money_values_are_not_credit_rejections(self):
        for field in ("requested_amount", "average_monthly_revenue", "average_monthly_operating_expenses",
                      "existing_monthly_debt_payment", "current_overdue_amount"):
            original = self.data[field]
            for value in (-1, True, 100.0, "-1", "NaN", "Infinity", "1e6", "1,00", "", "1.001",
                          Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("1.001"),
                          "1000000000000.01", [], {}):
                with self.subTest(field=field, value=value):
                    self.data[field] = value
                    result = self.assess()
                    self.assertEqual(result["recommendation"], "REQUEST_INFO")
                    self.assertIn("INVALID_DATA", result["reason_codes"])
                    self.assertIsNone(result["score"])
            self.data[field] = original

    def test_invalid_dates_integers_metadata(self):
        invalid = {
            "as_of_date": ["2026-02-30", "20261020", "2026-10-20T00:00:00Z", datetime(2026, 10, 20)],
            "registration_date": ["2026-10-21", "not-date"],
            "term_months": [True, 0, -1, 361, 12.0, "12"],
            "max_overdue_days_12m": [True, -1, 367, "0"],
            "application_revision": [False, 0, "1"],
            "application_id": ["wrong", 1], "schema_version": ["2.0", 1],
            "purpose": ["", " "], "legal_form": [[], 1], "requested_amount": ["0"],
        }
        for field, values in invalid.items():
            original = self.data[field]
            for value in values:
                with self.subTest(field=field, value=value):
                    self.data[field] = value
                    result = self.assess()
                    self.assertIsNone(result["score"])
                    self.assertEqual(result["recommendation"], "REQUEST_INFO")
            self.data[field] = original

    def test_malformed_input_and_unexpected_fields(self):
        for data in (None, [], "bad", 0, {**self.data, "income": "100"}):
            with self.subTest(data=data):
                result = assess_application(data, self.policy)
                self.assertEqual(result["assessment_status"], "INSUFFICIENT_DATA")
                self.assertEqual(result["recommendation"], "REQUEST_INFO")

    def test_malformed_checks(self):
        for checks in ({}, "PASS", [None], [{}], [self.request["checks"][0]] * 2,
                       [{"source": "x", "status": "pass", "reason_code": "OK"}],
                       [{"source": "x", "status": "PASS", "reason_code": ""}]):
            with self.subTest(checks=checks):
                result = assess_application(self.data, self.policy, checks)
                self.assertEqual(result["assessment_status"], "INSUFFICIENT_DATA")
                self.assertEqual(result["recommendation"], "REQUEST_INFO")

    def test_policy_errors_are_configuration_errors(self):
        invalid = {"annual_interest_rate": ["101", "-1", 24.0],
                   "max_debt_burden": ["0", "1.01"], "min_amount": ["0", "5000001"],
                   "min_term_months": [61], "max_term_months": [361],
                   "approve_score": [50, 101], "review_score": [75, -1],
                   "required_checks": [[], ["a", "a"], "a", [False]], "product_code": ["equipment"]}
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    policy = {**self.policy, field: value}
                    with self.assertRaises(PolicyValidationError) as caught:
                        assess_application(self.data, policy)
                    self.assertTrue(caught.exception.errors)
        for field in self.policy:
            policy = dict(self.policy)
            del policy[field]
            with self.subTest(missing=field), self.assertRaises(PolicyValidationError):
                assess_application(self.data, policy)
        for policy in (None, [], {**self.policy, "extra": 1}):
            with self.assertRaises(PolicyValidationError):
                assess_application(self.data, policy)

    def test_larger_obligations_never_improve_score(self):
        previous = 100
        for debt in ("0", "50000", "100000", "150000", "250000", "1000000"):
            self.data["existing_monthly_debt_payment"] = debt
            result = self.assess()
            self.assertLessEqual(result["score"], previous)
            self.assertTrue(0 <= result["score"] <= 100)
            previous = result["score"]

    def test_bounded_extreme_values_are_finite(self):
        self.data.update(requested_amount="1000000000000", average_monthly_revenue="0.01", term_months=360)
        self.policy["annual_interest_rate"] = "0.01"
        result = self.assess()
        self.assertEqual(result["recommendation"], "DECLINE")
        self.assertTrue(Decimal(result["features"]["new_monthly_payment"]).is_finite())
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
