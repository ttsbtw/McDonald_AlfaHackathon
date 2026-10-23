"""Demo scorecard. All arithmetic runs inside the entry point's Decimal context."""

from decimal import ROUND_UP, Context, Decimal, localcontext


def calculate_monthly_payment(principal: Decimal, term_months: int, annual_interest_rate: Decimal) -> Decimal:
    """Return the demo annuity payment, rounded up to the next kopeck."""
    with localcontext(Context(prec=40)):
        rate = annual_interest_rate / Decimal(1200)
        payment = principal / term_months if rate == 0 else (
            principal * rate / (1 - (1 + rate) ** -term_months)
        )
        return payment.quantize(Decimal("0.01"), rounding=ROUND_UP)


def calculate_features(data, policy):
    start, end = data["registration_date"], data["as_of_date"]
    age = (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)
    principal, term = data["requested_amount"], data["term_months"]
    payment = calculate_monthly_payment(principal, term, policy["annual_interest_rate"])
    revenue = data["average_monthly_revenue"]
    available = revenue - data["average_monthly_operating_expenses"]
    total_payment = data["existing_monthly_debt_payment"] + payment
    return {
        "business_age_months": age,
        "monthly_operating_profit": available,
        "operating_margin": available / revenue if revenue > 0 else None,
        "new_monthly_payment": payment,
        "total_monthly_debt_payment": total_payment,
        "debt_burden": total_payment / available if available > 0 else None,
    }


def calculate_score(data, features):
    age = features["business_age_months"]
    margin = features["operating_margin"]
    burden = features["debt_burden"]
    days = data["max_overdue_days_12m"]
    if age >= 24:
        age_points = 20
    elif age >= 12:
        age_points = 12
    elif age >= 6:
        age_points = 5
    else:
        age_points = 0

    margin_points = 0
    if margin is not None:
        if margin >= Decimal("0.30"):
            margin_points = 25
        elif margin >= Decimal("0.15"):
            margin_points = 18
        elif margin > 0:
            margin_points = 8

    debt_points = 0
    if burden is not None:
        if burden <= Decimal("0.30"):
            debt_points = 35
        elif burden <= Decimal("0.50"):
            debt_points = 25
        elif burden <= Decimal("0.70"):
            debt_points = 10

    history_points = 0
    if data.get("credit_history_available", True) and data["current_overdue_amount"] == 0:
        if days == 0:
            history_points = 20
        elif days <= 7:
            history_points = 12
        elif days <= 30:
            history_points = 5
    factors = [
        {"code": "BUSINESS_AGE", "value": age, "points": age_points, "max_points": 20,
         "explanation": f"Полных месяцев работы: {age}; вклад {age_points} из 20."},
        {"code": "OPERATING_MARGIN", "value": margin, "points": margin_points, "max_points": 25,
         "explanation": f"Доля выручки после операционных расходов; вклад {margin_points} из 25. При нулевой выручке показатель не определён."},
        {"code": "DEBT_BURDEN", "value": burden, "points": debt_points, "max_points": 35,
         "explanation": f"Все кредитные платежи / доход после операционных расходов; вклад {debt_points} из 35. При неположительном доходе показатель не определён."},
        {"code": "PAYMENT_HISTORY", "value": {"current_overdue_amount": data["current_overdue_amount"], "max_overdue_days_12m": days},
         "points": history_points, "max_points": 20,
         "explanation": f"Текущие просрочки и задержки за 12 месяцев; вклад {history_points} из 20."},
    ]
    score = sum(factor["points"] for factor in factors)
    return {"score": score, "risk_level": "LOW" if score >= 75 else "MEDIUM" if score >= 50 else "HIGH", "factors": factors}
