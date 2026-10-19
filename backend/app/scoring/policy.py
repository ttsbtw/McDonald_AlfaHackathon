"""Product rules are separate from the score and from an employee's decision."""


def make_recommendation(data, checks, score, features, policy):
    reasons, stops, missing = [], [], []

    def stop(code, message):
        stops.append(code)
        reasons.append({"code": code, "message": message})

    if not policy["min_amount"] <= data["requested_amount"] <= policy["max_amount"]:
        stop("AMOUNT_OUT_OF_RANGE", "Сумма вне допустимых условий продукта; измените сумму или продукт.")
    if not policy["min_term_months"] <= data["term_months"] <= policy["max_term_months"]:
        stop("TERM_OUT_OF_RANGE", "Срок вне допустимых условий продукта; измените срок или продукт.")
    if features["business_age_months"] < policy["min_business_age_months"]:
        stop("BUSINESS_TOO_YOUNG", "Срок работы бизнеса меньше минимального для продукта.")
    if features["monthly_operating_profit"] <= 0:
        stop("NON_POSITIVE_OPERATING_PROFIT", "Доход после операционных расходов не позволяет обслуживать кредит.")
    elif features["debt_burden"] > policy["max_debt_burden"]:
        stop("EXCESSIVE_DEBT_BURDEN", "Долговая нагрузка с новым кредитом превышает лимит продукта.")
    if data["current_overdue_amount"] > 0:
        stop("CURRENT_OVERDUE", "Есть текущая просроченная задолженность.")
    if data["max_overdue_days_12m"] > policy["max_overdue_days_12m"]:
        stop("SEVERE_OVERDUE_HISTORY", "Длительность просрочек за 12 месяцев превышает лимит продукта.")

    by_source = {check["source"]: check for check in checks}
    for check in checks:
        if check["status"] == "FAIL":
            code = f"CHECK_FAILED:{check['source']}"
            stop(code, f"Проверка {check['source']} не пройдена: {check['reason_code']}.")
        elif check["status"] == "UNKNOWN":
            missing.append(f"checks.{check['source']}")
    for source in policy["required_checks"]:
        if source not in by_source:
            missing.append(f"checks.{source}")
    missing.sort()
    if missing:
        reasons.append({"code": "CHECKS_INCOMPLETE", "message": "Backend должен получить результаты отсутствующих или неизвестных проверок."})
    if stops:
        recommendation = "DECLINE"
    elif missing:
        recommendation = "REQUEST_INFO"
    elif score >= policy["approve_score"]:
        recommendation = "APPROVE"
        reasons.append({"code": "SCORE_SUFFICIENT", "message": "Балл достаточен и ограничения продукта выполнены; требуется итоговое решение сотрудника."})
    elif score >= policy["review_score"]:
        recommendation = "REVIEW"
        reasons.append({"code": "MANUAL_REVIEW", "message": "Пограничный балл; требуется дополнительная оценка сотрудником."})
    else:
        recommendation = "DECLINE"
        reasons.append({"code": "LOW_SCORE", "message": "Балл ниже минимального порога рассмотрения продукта."})
    return {"recommendation": recommendation, "hard_stops": stops,
            "reason_codes": [reason["code"] for reason in reasons], "reasons": reasons,
            "missing_fields": missing}
