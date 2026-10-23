"""Generate safe, deterministic alternatives from a submitted assessment."""

from datetime import date
from decimal import Decimal, ROUND_DOWN

from ..scoring import assess_application
from ..scoring.scorecard import calculate_monthly_payment
from ..underwriting import evaluate_underwriting

ADJUSTABLE_HARD_STOPS = {"EXCESSIVE_DEBT_BURDEN", "AMOUNT_OUT_OF_RANGE", "TERM_OUT_OF_RANGE"}


def _max_affordable_amount(*, minimum: Decimal, maximum: Decimal, term_months: int,
                           available_payment: Decimal, annual_interest_rate: Decimal) -> Decimal:
    """Binary search the largest cent-precision principal using the scorecard payment formula."""
    low = int(minimum * 100)
    high = int(maximum * 100)
    best = 0
    while low <= high:
        middle = (low + high) // 2
        principal = Decimal(middle) / 100
        payment = calculate_monthly_payment(principal, term_months, annual_interest_rate)
        if payment <= available_payment:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return Decimal(best) / 100


def _reason(amount_delta: Decimal, term_delta: int) -> tuple[str, str]:
    if amount_delta < 0 and term_delta > 0:
        return "REDUCE_AMOUNT_AND_EXTEND_TERM", "Уменьшение суммы и увеличение срока снижают ежемесячную нагрузку."
    if amount_delta < 0:
        return "REDUCE_AMOUNT", "Уменьшение суммы снижает ежемесячный платёж и долговую нагрузку."
    if term_delta > 0:
        return "EXTEND_TERM", "Увеличение срока снижает ежемесячный платёж и долговую нагрузку."
    if amount_delta > 0:
        return "ADJUST_PRODUCT_AMOUNT", "Сумма приведена к допустимому диапазону продукта."
    return "ADJUST_PRODUCT_TERM", "Срок приведён к допустимому диапазону продукта."


def generate_alternatives(*, input_data: dict, product_policy: dict, checks: list,
                          bki: dict, compliance: dict, subject_id: str,
                          registration_date, original_result: dict, original_underwriting: dict,
                          maximum_results: int = 3) -> dict:
    """Re-score each candidate and retain only variants that pass every mandatory rule."""
    original_amount = Decimal(str(input_data["requested_amount"]))
    original_term = int(input_data["term_months"])
    original_features = original_result.get("features", {})
    original_payment = Decimal(str(original_features.get("new_monthly_payment", "0")))
    original_burden = original_features.get("debt_burden")
    reasons = original_result.get("hard_stops", [])
    original = {
        "amount": format(original_amount, ".2f"),
        "term_months": original_term,
        "monthly_payment": format(original_payment, ".2f"),
        "debt_burden": original_burden,
    }

    if not reasons and original_underwriting.get("status") == "PASS" and original_result.get("recommendation") != "DECLINE":
        return {"status": "NOT_REQUIRED", "reason_code": "ORIGINAL_CONDITIONS_PASS",
                "reason": "Первоначальные условия проходят обязательные проверки.", "original": original,
                "alternatives": []}

    if bki.get("status") not in {"AVAILABLE", "NO_HISTORY"} or compliance.get("status") != "CLEAR":
        return {"status": "BLOCKED", "reason_code": "EXTERNAL_CHECK_REQUIRES_REVIEW",
                "reason": "Результат БКИ или Compliance требует ручной проверки.", "original": original,
                "alternatives": []}
    if any(check.get("status") != "PASS" for check in checks):
        return {"status": "BLOCKED", "reason_code": "CHECKS_REQUIRE_REVIEW",
                "reason": "Есть обязательная проверка без успешного результата.", "original": original,
                "alternatives": []}
    if any(code not in ADJUSTABLE_HARD_STOPS for code in reasons):
        return {"status": "BLOCKED", "reason_code": "NON_ADJUSTABLE_RESTRICTION",
                "reason": "Причины отказа нельзя устранить изменением суммы или срока.", "original": original,
                "alternatives": []}
    if original_underwriting.get("status") == "REVIEW":
        return {"status": "BLOCKED", "reason_code": "UNDERWRITING_REQUIRES_REVIEW",
                "reason": "Первоначальная оценка содержит обязательное ручное правило.", "original": original,
                "alternatives": []}

    rule_codes = {rule.get("code") for rule in original_underwriting.get("rules", [])
                  if rule.get("outcome") == "REJECT"}
    if rule_codes - {"PRODUCT_AMOUNT_LIMIT", "DEBT_BURDEN"}:
        return {"status": "BLOCKED", "reason_code": "NON_ADJUSTABLE_UNDERWRITING_RULE",
                "reason": "Есть блокирующее правило underwriting, которое нельзя исправить условиями.",
                "original": original, "alternatives": []}

    profit = Decimal(str(original_features.get("monthly_operating_profit") or "0"))
    existing_debt = Decimal(str(input_data["existing_monthly_debt_payment"]))
    limit = Decimal(str(product_policy["max_debt_burden"]))
    available_payment = profit * limit - existing_debt
    minimum = Decimal(str(product_policy["min_amount"]))
    maximum = Decimal(str(product_policy["max_amount"]))
    min_term = int(product_policy["min_term_months"])
    max_term = int(product_policy["max_term_months"])
    rate = Decimal(str(product_policy["annual_interest_rate"]))
    desired_amount = min(max(original_amount, minimum), maximum)
    as_of_date = input_data["as_of_date"]
    # The scoring contract accepts ISO dates; underwriting uses the same valuation date.
    as_of_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
    registration_date = date.fromisoformat(registration_date) if isinstance(registration_date, str) else registration_date

    if profit <= 0 or available_payment <= 0:
        return {"status": "NO_ALTERNATIVES", "reason_code": "NO_AFFORDABLE_PAYMENT",
                "reason": "После действующих обязательств не остаётся допустимого платежа.", "original": original,
                "alternatives": []}

    candidates = []
    for term in range(min_term, max_term + 1):
        affordable = _max_affordable_amount(minimum=minimum, maximum=maximum, term_months=term,
                                            available_payment=available_payment, annual_interest_rate=rate)
        if affordable < minimum:
            continue
        # Score whole-ruble candidates and stay below the affordable payment ceiling.
        amount = min(desired_amount, affordable).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if amount < minimum:
            continue
        if amount == original_amount and term == original_term:
            continue

        candidate_input = {**input_data, "requested_amount": format(amount, ".2f"), "term_months": term}
        result = assess_application(candidate_input, product_policy, checks)
        underwriting = evaluate_underwriting(
            subject_id=subject_id, product_code=input_data["product_code"], requested_amount=amount,
            registration_date=registration_date, as_of_date=as_of_date,
            debt_burden=result.get("features", {}).get("debt_burden"), bki=bki,
            compliance=compliance, product_policy=product_policy,
        )
        if result.get("assessment_status") != "COMPLETED" or result.get("hard_stops"):
            continue
        if result.get("recommendation") == "DECLINE" or underwriting.get("status") != "PASS":
            continue

        payment = Decimal(str(result["features"]["new_monthly_payment"]))
        burden = result["features"].get("debt_burden")
        amount_delta = amount - original_amount
        term_delta = term - original_term
        reason_code, reason = _reason(amount_delta, term_delta)
        # Prefer the least disruptive safe variant, then lower debt burden and payment.
        distance = abs(amount_delta) / max(original_amount, Decimal("1")) + Decimal(abs(term_delta)) / max(original_term, 1)
        candidates.append({
            "amount": format(amount, ".2f"), "term_months": term,
            "annual_interest_rate": format(rate, ".2f"),
            "monthly_payment": format(payment, ".2f"),
            "debt_burden": format(Decimal(str(burden)), ".8f") if burden is not None else None,
            "reason_code": reason_code, "reason": reason,
            "differences": {"amount": format(amount_delta, ".2f"), "term_months": term_delta,
                            "monthly_payment": format(payment - original_payment, ".2f"),
                            "debt_burden": (format(Decimal(str(burden)) - Decimal(str(original_burden)), ".8f")
                                            if burden is not None and original_burden is not None else None)},
            "underwriting": underwriting, "scoring": result,
            "is_demo": True, "_distance": distance,
        })

    candidates.sort(key=lambda item: (
        item["_distance"], Decimal(item["debt_burden"] or "Infinity"),
        Decimal(item["monthly_payment"]), -int(item["term_months"]),
    ))
    alternatives = []
    seen = set()
    for candidate in candidates:
        key = (candidate["amount"], candidate["term_months"])
        if key in seen:
            continue
        seen.add(key)
        candidate.pop("_distance")
        alternatives.append(candidate)
        if len(alternatives) >= maximum_results:
            break

    return {
        "status": "AVAILABLE" if alternatives else "NO_ALTERNATIVES",
        "reason_code": "ALTERNATIVES_FOUND" if alternatives else "NO_ELIGIBLE_COMBINATIONS",
        "reason": "Найдены варианты, проходящие обязательные правила." if alternatives
        else "Для этой заявки не найдено условий, проходящих все обязательные правила.",
        "original": original, "alternatives": alternatives,
    }
