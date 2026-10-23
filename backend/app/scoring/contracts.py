"""Validation of the proposed v1 backend/scoring contract; stdlib only."""

from datetime import date
from decimal import Decimal
import re
from uuid import UUID


SCHEMA_VERSION = "1.0"
SCORING_VERSION = "demo-scorecard-1.0"
MONEY_LIMIT = Decimal("1000000000000")
MONEY_FIELDS = (
    "requested_amount", "average_monthly_revenue",
    "average_monthly_operating_expenses", "existing_monthly_debt_payment",
    "current_overdue_amount",
)


class PolicyValidationError(ValueError):
    """Backend configuration error, never a credit rejection."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid product policy: " + ", ".join(e["field"] for e in errors))


def issue(field, code, message):
    return {"field": field, "code": code, "message": message}


def money(value):
    # Reject floats, booleans, exponent notation and sub-kopeck values.
    if isinstance(value, Decimal):
        if not value.is_finite() or value.as_tuple().exponent < -2:
            raise ValueError("Ожидается конечная сумма с точностью до копеек.")
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,13}(\.[0-9]{1,2})?", value):
        result = Decimal(value)
    else:
        raise ValueError("Ожидается десятичная строка или Decimal, до двух знаков после точки.")
    if not 0 <= result <= MONEY_LIMIT:
        raise ValueError("Сумма должна быть от 0 до 1000000000000 рублей.")
    return result.quantize(Decimal("0.01"))


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Ожидается целое число от {minimum} до {maximum}.")
    return value


def boolean(value):
    if type(value) is not bool:
        raise ValueError("Ожидается логическое значение.")
    return value


def text_value(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("Ожидается непустая строка длиной до 200 символов.")
    return value


def iso_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Ожидается дата YYYY-MM-DD без времени.")
    return date.fromisoformat(value)


def identifier(value):
    return str(UUID(text_value(value)))


def version(value):
    if value != SCHEMA_VERSION:
        raise ValueError("Поддерживается только schema_version=1.0.")
    return value


def validate_fields(raw, validators, prefix=""):
    if not isinstance(raw, dict):
        return {}, [issue(prefix or "input", "INVALID", "Ожидается объект.")]
    parsed, errors = {}, []
    for name, validator in validators.items():
        field = f"{prefix}.{name}" if prefix else name
        if raw.get(name) is None:
            errors.append(issue(field, "MISSING", "Обязательное поле отсутствует."))
            continue
        try:
            parsed[name] = validator(raw[name])
        except (ValueError, TypeError, OverflowError):
            errors.append(issue(field, "INVALID", "Неверный тип, формат или допустимый диапазон."))
    # Ignore no unexpected fields: a typo must not silently change a decision.
    if any(key not in validators for key in raw):
        errors.append(issue(prefix or "input", "UNKNOWN_FIELDS", "Объект содержит неизвестные поля."))
    return parsed, errors


def validate_input(raw):
    validators = {
        "schema_version": version,
        "application_id": identifier,
        "application_revision": lambda v: integer(v, 1, 2147483647),
        "as_of_date": iso_date,
        "product_code": text_value,
        "term_months": lambda v: integer(v, 1, 360),
        "purpose": text_value,
        "legal_form": text_value,
        "registration_date": iso_date,
        **{name: money for name in MONEY_FIELDS},
        "max_overdue_days_12m": lambda v: integer(v, 0, 366),
    }
    if isinstance(raw, dict) and "credit_history_available" in raw:
        validators["credit_history_available"] = boolean
    parsed, errors = validate_fields(raw, validators)
    if isinstance(raw, dict) and "credit_history_available" in raw:
        if type(raw["credit_history_available"]) is not bool:
            errors.append(issue("credit_history_available", "INVALID", "Ожидается логическое значение."))
    if parsed.get("requested_amount") == 0:
        errors.append(issue("requested_amount", "INVALID", "Сумма кредита должна быть положительной."))
    if "registration_date" in parsed and "as_of_date" in parsed:
        if parsed["registration_date"] > parsed["as_of_date"]:
            errors.append(issue("registration_date", "INVALID", "Регистрация позже даты оценки."))
    return parsed, errors


def required_checks(value):
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValueError("Ожидается от 1 до 20 обязательных проверок.")
    if any(not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", v) for v in value):
        raise ValueError("Некорректное имя проверки.")
    if len(set(value)) != len(value):
        raise ValueError("Проверки не должны повторяться.")
    return sorted(value)


def validate_policy(raw):
    validators = {
        "policy_version": text_value,
        "product_code": text_value,
        "min_amount": money, "max_amount": money,
        "min_term_months": lambda v: integer(v, 1, 360),
        "max_term_months": lambda v: integer(v, 1, 360),
        "annual_interest_rate": money,
        "min_business_age_months": lambda v: integer(v, 0, 1200),
        "max_debt_burden": money,
        "max_overdue_days_12m": lambda v: integer(v, 0, 366),
        "approve_score": lambda v: integer(v, 1, 100),
        "review_score": lambda v: integer(v, 0, 99),
        "required_checks": required_checks,
    }
    parsed, errors = validate_fields(raw, validators, "policy")
    if not errors:
        conditions = (
            (0 < parsed["min_amount"] <= parsed["max_amount"], "min_amount"),
            (parsed["min_term_months"] <= parsed["max_term_months"], "min_term_months"),
            (parsed["annual_interest_rate"] <= 100, "annual_interest_rate"),
            (0 < parsed["max_debt_burden"] <= 1, "max_debt_burden"),
            (parsed["review_score"] < parsed["approve_score"], "review_score"),
        )
        for valid, field in conditions:
            if not valid:
                errors.append(issue(f"policy.{field}", "INVALID", "Несогласованные ограничения продукта."))
    if errors:
        raise PolicyValidationError(errors)
    return parsed


def validate_checks(raw):
    if raw is None:
        return [], []  # Required sources are reported as missing by policy rules.
    if not isinstance(raw, list) or len(raw) > 20:
        return [], [issue("checks", "INVALID", "Ожидается список не более чем из 20 проверок.")]
    parsed, errors, sources = [], [], set()
    for index, check in enumerate(raw):
        prefix = f"checks[{index}]"
        item, item_errors = validate_fields(check, {
            "source": lambda v: required_checks([v])[0],
            "status": text_value, "reason_code": text_value,
        }, prefix)
        errors.extend(item_errors)
        if item_errors:
            continue
        if item["status"] not in ("PASS", "FAIL", "UNKNOWN"):
            errors.append(issue(f"{prefix}.status", "INVALID", "Допустимы PASS, FAIL, UNKNOWN."))
        if item["source"] in sources:
            errors.append(issue(f"{prefix}.source", "DUPLICATE", "Источник проверки повторяется."))
        sources.add(item["source"])
        parsed.append(item)
    return sorted(parsed, key=lambda c: c["source"]), errors


def to_json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    return value
