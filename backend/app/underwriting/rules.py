"""Versioned deterministic internal rules, separate from risk scoring."""

from datetime import date
from decimal import Decimal

from .config import RULES_VERSION, SYNTHETIC_BLACKLIST, SYNTHETIC_WHITELIST


def evaluate_underwriting(*, subject_id: str, product_code: str, requested_amount: Decimal,
                          registration_date: date, as_of_date: date, debt_burden: Decimal | None,
                          bki: dict, compliance: dict, product_policy: dict) -> dict:
    rules = []

    def add(code, outcome, explanation):
        rules.append({"code": code, "outcome": outcome, "explanation": explanation})

    if subject_id in SYNTHETIC_BLACKLIST:
        add("SYNTHETIC_INTERNAL_BLACKLIST", "REJECT", "Синтетический внутренний стоп-фактор.")
    elif subject_id in SYNTHETIC_WHITELIST:
        add("SYNTHETIC_INTERNAL_WHITELIST", "PASS", "Синтетическая запись белого списка; не отменяет проверки.")

    age_months = (as_of_date.year - registration_date.year) * 12 + as_of_date.month - registration_date.month
    if as_of_date.day < registration_date.day:
        age_months -= 1
    min_age = int(product_policy["min_business_age_months"])
    add("MIN_BUSINESS_AGE", "PASS" if age_months >= min_age else "REJECT",
        f"Возраст бизнеса: {age_months} мес.; минимум продукта: {min_age} мес.")
    minimum = Decimal(str(product_policy["min_amount"]))
    maximum = Decimal(str(product_policy["max_amount"]))
    within_amount = minimum <= requested_amount <= maximum
    add("PRODUCT_AMOUNT_LIMIT", "PASS" if within_amount else "REJECT",
        "Сумма соответствует диапазону продукта." if within_amount else "Сумма вне диапазона продукта.")
    if debt_burden is None:
        add("DEBT_BURDEN", "REVIEW", "Долговую нагрузку нельзя рассчитать по имеющимся данным.")
    else:
        debt_burden = Decimal(str(debt_burden))
        limit = Decimal(str(product_policy["max_debt_burden"]))
        allowed = debt_burden <= limit
        add("DEBT_BURDEN", "PASS" if allowed else "REJECT",
            f"Долговая нагрузка {debt_burden:.4f}; лимит {limit:.4f}.")
    if bki["status"] not in {"AVAILABLE", "NO_HISTORY"}:
        add("BKI_AVAILABILITY", "REVIEW", "БКИ не вернуло пригодный результат; требуется повторная или ручная проверка.")
    elif bki["status"] == "AVAILABLE" and Decimal(bki.get("current_overdue_amount", "0")) > 0:
        add("CURRENT_OVERDUE", "REJECT", "В синтетическом отчёте БКИ есть текущая просрочка.")
    else:
        add("BKI_HISTORY", "PASS", "История получена либо отсутствие истории подтверждено.")

    compliance_status = compliance["status"]
    if compliance_status == "CONFIRMED_MATCH":
        add("COMPLIANCE_CONFIRMED_MATCH", "REVIEW", "Автоматическое одобрение заблокировано; требуется предусмотренная ручная compliance-проверка.")
    elif compliance_status == "POTENTIAL_MATCH":
        add("COMPLIANCE_POTENTIAL_MATCH", "REVIEW", "Требуется ручная проверка совпадения сотрудником.")
    elif compliance_status == "ERROR":
        add("COMPLIANCE_ERROR", "REVIEW", "Проверка недоступна; технический сбой не является отказом.")
    else:
        add("COMPLIANCE_CLEAR", "PASS", "Синтетическая проверка не обнаружила совпадений.")

    outcomes = {rule["outcome"] for rule in rules}
    mandatory_review = (bki["status"] not in {"AVAILABLE", "NO_HISTORY"}
                        or compliance_status in {"POTENTIAL_MATCH", "CONFIRMED_MATCH", "ERROR"})
    status = "REVIEW" if mandatory_review else "REJECT" if "REJECT" in outcomes else "REVIEW" if "REVIEW" in outcomes else "PASS"
    return {"status": status, "rules_version": RULES_VERSION, "rules": rules,
            "reason_codes": [rule["code"] for rule in rules if rule["outcome"] != "PASS"],
            "product_code": product_code}
