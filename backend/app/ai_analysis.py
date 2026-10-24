"""Bounded, explanatory analysis of one stored application assessment via local Ollama."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MODEL_TAG = "qwen3:4b-instruct-2507-q4_K_M"
PROMPT_VERSION = "credit-score-explainer-v15"
MAX_INPUT_BYTES = 12_000
MAX_OUTPUT_BYTES = 12_000
MAX_RECOMMENDATIONS = 1
MAX_WARNINGS = 4


class AIRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["REVIEW_REQUIRED", "VERIFY_DATA", "REQUEST_INFORMATION", "CONTINUE_REVIEW"]
    text: str = Field(min_length=1, max_length=160)
    fact_ids: list[str] = Field(min_length=1, max_length=6)


class AIDataWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=400)
    fact_ids: list[str] = Field(default_factory=list, max_length=6)


class AIEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    value: str


class AIModelAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=1_200)
    summary_fact_ids: list[str] = Field(min_length=1, max_length=32)


class AIAnalysisOut(BaseModel):
    analysis_id: UUID
    application_id: UUID
    analyzed_at: datetime
    model: str
    prompt_version: str
    summary: str
    summary_fact_ids: list[str]
    evidence: list[AIEvidence]
    recommendations: list[AIRecommendation]
    data_warnings: list[AIDataWarning]
    blocking_reasons: list[str]
    is_blocked: bool
    used_safe_fallback: bool


class OllamaUnavailable(Exception):
    pass


class OllamaModelMissing(Exception):
    pass


class InvalidModelAnswer(Exception):
    def __init__(self, message: str, code: str | None = None, number: str | None = None,
                 narrative: str | None = None):
        super().__init__(message)
        self.code = code
        self.number = number
        self.narrative = narrative


def _canonical_number(value: str) -> str | None:
    normalized = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        number = Decimal(normalized).normalize()
    except InvalidOperation:
        return None
    return format(number, "f")


def _format_ru_number(value: str) -> str:
    normalized = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return value
    rendered = format(number.normalize(), "f")
    integer, dot, fraction = rendered.partition(".")
    sign = "-" if integer.startswith("-") else ""
    integer = integer.lstrip("-")
    grouped = re.sub(r"(?<!^)(?=(\d{3})+$)", " ", integer)
    return sign + grouped + (("," + fraction) if dot and fraction else "")


def _percent_value(value) -> str | None:
    if value is None:
        return None
    try:
        percentage = (Decimal(str(value)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return format(percentage, "f")


def _format_blocking_cause(cause: str) -> str:
    match = re.search(
        r"(Долговая нагрузка)\s+([+-]?\d+(?:[.,]\d+)?)\s*;\s*(?:лимит|предел)\s*([+-]?\d+(?:[.,]\d+)?)",
        cause, re.IGNORECASE,
    )
    if not match:
        return cause

    def percent(value: str) -> str:
        number = Decimal(value.replace(",", ".")) * 100
        rounded = number.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return _format_ru_number(format(rounded, "f")) + "%"

    return f"{match.group(1)} — {percent(match.group(2))}; допустимый предел — {percent(match.group(3))}"


def _numbers_in_text(value: str) -> set[str]:
    numbers = set()
    for match in re.finditer(r"(?<!\w)\d+(?:[ .\u00a0]\d{3})*(?:[,.]\d+)?(?!\w)", value):
        canonical = _canonical_number(match.group())
        if canonical is not None:
            numbers.add(canonical)
    multipliers = {"тыс": Decimal(1000), "тысяч": Decimal(1000), "млн": Decimal(1_000_000),
                   "миллион": Decimal(1_000_000), "млрд": Decimal(1_000_000_000),
                   "миллиард": Decimal(1_000_000_000)}
    for match in re.finditer(r"(\d+(?:[,.]\d+)?)\s*(тыс\w*|млн\w*|миллион\w*|млрд\w*|миллиард\w*)", value, re.IGNORECASE):
        amount = _canonical_number(match.group(1))
        unit = match.group(2).lower()
        multiplier = next((factor for prefix, factor in multipliers.items() if unit.startswith(prefix)), None)
        if amount is not None and multiplier is not None:
            numbers.add(_canonical_number(str(Decimal(amount) * multiplier)))
    return numbers


_FIELD_LABELS = {
    "requested_amount": "сумму кредита", "term_months": "срок кредита", "purpose": "цель кредита",
    "average_monthly_revenue": "среднюю месячную выручку",
    "average_monthly_operating_expenses": "средние месячные расходы",
    "existing_monthly_debt_payment": "текущие платежи по долгам",
}


def _safe_brief_summary(result: dict, facts: list[dict], blocking_reasons: list[str]) -> tuple[str, list[str]]:
    """Build a fact-grounded, human-readable explanation if model text is unsafe."""
    fact_map = {fact["id"]: fact for fact in facts}
    fact_ids = set(fact_map)
    missing_fields = list(result.get("missing_fields") or [])
    mandatory_blocks = [reason for reason in blocking_reasons if not reason.startswith("Оценка неполная:")]
    missing_ids = [fact["id"] for fact in facts if fact["id"].startswith("data.missing.")]

    request_parts = []
    context_ids = []
    for fact_id, label in (("app.amount", "Запрошено"), ("app.term", "на")):
        if fact_id in fact_map:
            value = fact_map[fact_id]["value"]
            suffix = " ₽" if fact_id == "app.amount" else " месяцев"
            request_parts.append(f"{label} {_format_ru_number(value)}{suffix}")
            context_ids.append(fact_id)
    purpose = fact_map.get("app.purpose")
    request_context = " ".join(request_parts)
    if purpose:
        purpose_text = purpose["value"].strip().rstrip(".")
        if len(purpose_text) > 180:
            purpose_text = purpose_text[:177].rsplit(" ", 1)[0] + "…"
        request_context += f"; цель — {purpose_text}" if request_context else f"Цель — {purpose_text}"
        context_ids.append("app.purpose")
    score_ids = [fact_id for fact_id in ("score.score", "score.scale", "score.risk", "score.recommendation")
                 if fact_id in fact_ids]
    risk_labels = {"LOW": "низкий", "MEDIUM": "средний", "HIGH": "высокий", "UNKNOWN": "не определён"}
    risk = risk_labels.get(result.get("risk_level"), "не определён")
    score_text = f"Скоринг — {result['score']} из 100, риск — {risk}. " if result.get("score") is not None else ""

    if mandatory_blocks:
        block_ids = [fact["id"] for fact in facts
                     if fact["id"].startswith(("underwriting.rule.", "score.hard_stop."))]
        cause = mandatory_blocks[0].split(":", 1)[-1].strip().rstrip(".")
        cause = _format_blocking_cause(cause)
        cause_text = f" Причина: {cause}." if cause else ""
        return (
            f"{request_context}. {score_text}Заявку блокирует обязательная проверка.{cause_text} "
            "Завершите разбор по процедуре банка: ИИ не может снять ограничение.",
            (context_ids + score_ids + block_ids)[:12],
        )

    if missing_fields or result.get("assessment_status") != "COMPLETED":
        labels = [_FIELD_LABELS.get(name, name) for name in missing_fields[:3]]
        if labels:
            summary = f"{request_context}. Для завершения оценки запросите у клиента " + ", ".join(labels) + ". После получения сведений оценка обновится."
        else:
            summary = f"{request_context}. Оценка не завершена: запросите недостающие сведения, чтобы продолжить рассмотрение."
        return summary, (context_ids + missing_ids + score_ids)[:12] or [facts[0]["id"]]

    if result.get("recommendation") == "APPROVE" and result.get("risk_level") == "LOW":
        good_factors = [factor.get("code") for factor in (result.get("factors") or [])
                        if factor.get("points") == factor.get("max_points")]
        labels = {"BUSINESS_AGE": "срок работы бизнеса", "PAYMENT_HISTORY": "история платежей"}
        strengths = [labels[code] for code in good_factors if code in labels][:2]
        strength_text = f"Сильные стороны — {' и '.join(strengths)}. " if strengths else ""
        factor_ids = [fact["id"] for fact in facts if fact["id"].startswith("score.factor.")]
        return (f"{request_context}. {score_text}{strength_text}Скоринг рекомендует продолжить рассмотрение; "
                "итоговое решение остаётся за сотрудником банка.",
                (context_ids + score_ids + factor_ids)[:12] or [facts[0]["id"]])

    factor_labels = {
        "BUSINESS_AGE": "срок работы бизнеса",
        "OPERATING_MARGIN": "рентабельность после расходов",
        "DEBT_BURDEN": "долговая нагрузка",
        "PAYMENT_HISTORY": "история платежей",
    }
    adverse_factors = []
    for factor in result.get("factors") or []:
        try:
            if Decimal(str(factor.get("points"))) < Decimal(str(factor.get("max_points"))):
                code = factor.get("code")
                if code in factor_labels:
                    adverse_factors.append(code)
        except (InvalidOperation, TypeError):
            continue
    focus_ids = [f"score.factor.{code}" for code in adverse_factors[:2]]
    focus = " и ".join(factor_labels[code] for code in adverse_factors[:2])
    factors_text = f"На оценку повлияли {focus}. " if focus else ""
    if result.get("recommendation") == "DECLINE":
        next_step = "Скоринговая рекомендация отрицательная, но это не итоговый отказ: решение остаётся за сотрудником банка."
    else:
        next_step = "Скоринг рекомендует дополнительное рассмотрение; передайте заявку сотруднику для решения."
    summary = f"{request_context}. {score_text}{factors_text}{next_step}"
    citation_ids = context_ids + score_ids + focus_ids
    return summary, citation_ids[:12] or [fact["id"] for fact in facts[:1]]


SYSTEM_PROMPT = """Ты помощник сотрудника банка. Самостоятельно сформулируй понятное пояснение по одной заявке: что важно в её обстоятельствах, как это соотносится с результатом скоринга и что логично сделать дальше. Пиши естественно, как сотрудник объяснил бы ситуацию коллеге. Не пересказывай таблицу полей и не используй шаблонный набор фраз. Обычно достаточно 3–5 содержательных предложений; не пытайся перечислить каждый факт. Упоминай только параметры, которые помогают понять именно эту заявку; предложенный следующий шаг должен вытекать из её фактов.

Опирайся только на переданные факты и уже рассчитанные показатели. Не вычисляй финансовые коэффициенты сам и не выдумывай причины, значения, историю клиента или правила банка. В финансовых полях суммы уже указаны в рублях: сохраняй значение точно, не округляй его и не меняй порядок величины. Платежи из анкеты, БКИ и итоговый расчётный платёж после нового кредита — разные показатели; не подменяй один другим. Само по себе совпадение суммы заявки и выручки не доказывает недостоверность выручки. Если цель и выбранный продукт выглядят несвязанными, назови это поводом уточнить план использования средств, а не утверждай, что продукт не подходит или нарушена политика банка, если в фактах нет такого правила. Статусы обязательных проверок и правила underwriting авторитетны: не противоречь им. При блокирующей проверке назови ограничение и его причину; ИИ не может снять или обойти блокировку.

Не принимай кредитное решение за сотрудника: не утверждай, что кредит одобрен или отклонён, и не обещай результат. Каждое числовое утверждение должно подтверждаться указанными идентификаторами фактов. Верни только JSON по переданной схеме с полями summary и summary_fact_ids. В summary_fact_ids перечисли использованные факты. Не добавляй другие поля. Пиши по-русски."""


def _prompt_fact_value(fact: dict) -> str:
    value = fact["value"]
    if fact["id"] in {"app.amount", "app.declared_debt", "app.revenue", "app.expenses",
                       "app.debt", "bki.monthly_payment", "bki.overdue_amount",
                       "finance.operating_profit", "finance.new_monthly_payment",
                       "finance.total_monthly_debt_payment"}:
        units = {
            "app.amount": " ₽", "app.declared_debt": " ₽/мес.", "app.revenue": " ₽/мес.",
            "app.expenses": " ₽/мес.", "app.debt": " ₽/мес.", "bki.monthly_payment": " ₽/мес.",
            "bki.overdue_amount": " ₽", "finance.operating_profit": " ₽/мес.",
            "finance.new_monthly_payment": " ₽/мес.", "finance.total_monthly_debt_payment": " ₽/мес.",
        }
        return _format_ru_number(value) + units[fact["id"]]
    if fact["id"] in {"finance.operating_margin", "finance.debt_burden"}:
        return _format_ru_number(value) + "%"
    localized = {
        "LOW": "низкий",
        "MEDIUM": "средний",
        "HIGH": "высокий",
        "UNKNOWN": "не определён",
        "APPROVE": "положительная рекомендация скоринга (не итоговое решение банка)",
        "REVIEW": "нужно дополнительное рассмотрение",
        "DECLINE": "отрицательная рекомендация скоринга (не итоговое решение банка)",
        "REQUEST_INFO": "нужно запросить сведения",
        "PASS": "пройдена",
        "FAIL": "не пройдена",
        "CLEAR": "совпадений нет",
        "AVAILABLE": "данные получены",
        "NO_HISTORY": "кредитной истории нет",
        "UNAVAILABLE": "источник недоступен",
        "ERROR": "техническая ошибка источника",
        "POTENTIAL_MATCH": "возможное совпадение",
        "CONFIRMED_MATCH": "совпадение подтверждено",
        "COMPLETED": "оценка завершена",
        "INSUFFICIENT_DATA": "недостаточно данных",
    }
    if fact["id"] == "app.product":
        return {"equipment": "Оборудование", "working_capital": "Оборотные средства"}.get(value, value)
    if fact["id"] in {"score.risk", "score.recommendation", "score.status"} or fact["id"].endswith(".status"):
        return localized.get(value, value)
    if fact["id"].startswith("underwriting.rule."):
        match = re.match(r"([^:]+):\s*(PASS|REVIEW|REJECT)(.*)", value)
        if match:
            if match.group(1) == "DEBT_BURDEN":
                burden_match = re.search(
                    r"Долговая нагрузка\s+([+-]?\d+(?:[.,]\d+)?)\s*;\s*лимит\s*([+-]?\d+(?:[.,]\d+)?)",
                    match.group(3), re.IGNORECASE,
                )
                if burden_match:
                    def percent(raw_value):
                        number = (Decimal(raw_value.replace(",", ".")) * 100).quantize(
                            Decimal("0.1"), rounding=ROUND_HALF_UP)
                        return _format_ru_number(format(number, "f")) + "%"
                    burden, limit = map(percent, burden_match.groups())
                    if match.group(2) == "PASS":
                        return f"Долговая нагрузка в пределах лимита продукта: {burden}; допустимый предел — {limit}."
                    if match.group(2) == "REJECT":
                        return f"Долговая нагрузка выше лимита продукта: {burden}; допустимый предел — {limit}."
            reason = {"PASS": "пройдено", "REVIEW": "нужна ручная проверка", "REJECT": "ограничение"}[match.group(2)]
            return f"{match.group(1)}: {reason}{match.group(3)}"
    if fact["id"].startswith("score.factor."):
        code = fact["id"].rsplit(".", 1)[-1]
        labels = {
            "BUSINESS_AGE": "Срок работы бизнеса",
            "OPERATING_MARGIN": "Прибыльность после расходов",
            "DEBT_BURDEN": "Кредитные платежи относительно свободного дохода",
            "PAYMENT_HISTORY": "История платежей",
        }
        match = re.match(r"\s*(\d+(?:\.\d+)?)\s+из\s+(\d+(?:\.\d+)?):\s*(.*)", value)
        if match:
            qualifier = "полный результат по шкале" if Decimal(match.group(1)) == Decimal(match.group(2)) else "результат ниже максимума по шкале"
            explanation = match.group(3).split("; вклад", 1)[0]
            explanation = re.split(r";\s*(?:при|если|в случае)\b", explanation, maxsplit=1,
                                   flags=re.IGNORECASE)[0].strip().rstrip(".; ")
            return f"{labels.get(code, 'Фактор оценки')}: {qualifier}. Факт из оценки: {explanation}. Не делай выводов сверх него."
    return value


def make_facts(application, company, assessment, compliance_review=None) -> tuple[list[dict], list[str]]:
    result = assessment.result or {}
    snapshot = assessment.input_snapshot or {}
    input_data = snapshot.get("input_data") or result.get("input_snapshot", {}).get("input_data") or {}
    checks = snapshot.get("checks") or result.get("input_snapshot", {}).get("checks") or []
    facts: list[dict] = []

    def add(fact_id: str, label: str, value):
        if value is not None and value != "":
            facts.append({"id": fact_id, "label": label, "value": str(value)})

    add("app.amount", "Запрошенная сумма, руб.", application.requested_amount)
    add("app.term", "Срок, месяцев", application.term_months)
    add("app.purpose", "Цель кредита", application.purpose)
    add("app.product", "Код продукта", application.product_code)
    add("company.legal_form", "Организационная форма", company.legal_form)
    add("company.registration_date", "Дата регистрации", input_data.get("registration_date") or company.registration_date)
    add("app.revenue", "Средняя месячная выручка, руб.", input_data.get("average_monthly_revenue"))
    add("app.expenses", "Средние месячные расходы, руб.", input_data.get("average_monthly_operating_expenses"))
    add("app.declared_debt", "Платежи, указанные в анкете, руб./мес.",
        getattr(application, "existing_monthly_debt_payment", None))
    add("app.debt", "Существующие месячные платежи, учтённые в скоринге, руб./мес.",
        input_data.get("existing_monthly_debt_payment"))
    add("score.score", "Балл скоринга из 100", result.get("score"))
    add("score.scale", "Максимальный балл", 100 if result.get("score") is not None else None)
    add("score.risk", "Оценка риска", result.get("risk_level"))
    add("score.recommendation", "Рекомендация скоринга", result.get("recommendation"))
    add("score.status", "Полнота оценки", result.get("assessment_status"))
    for index, reason in enumerate(result.get("reasons") or []):
        add(f"score.reason.{index}", "Причина скоринговой рекомендации", reason.get("explanation") or reason.get("code"))
    for factor in result.get("factors") or []:
        code = factor.get("code") or "factor"
        points = factor.get("points")
        maximum = factor.get("max_points")
        explanation = factor.get("explanation") or ""
        value = f"{points} из {maximum}: {explanation}" if points is not None and maximum is not None else explanation
        add(f"score.factor.{code}", "Фактор, повлиявший на скоринг", value)
    features = result.get("features") or {}
    add("finance.operating_profit", "Выручка за вычетом расходов по расчёту скоринга, руб./мес.",
        features.get("monthly_operating_profit"))
    add("finance.operating_margin", "Доля выручки за вычетом расходов, рассчитанная скорингом, %",
        _percent_value(features.get("operating_margin")))
    add("finance.new_monthly_payment", "Расчётный платёж по запрашиваемому кредиту, руб./мес.",
        features.get("new_monthly_payment"))
    add("finance.total_monthly_debt_payment", "Все платежи после нового кредита, руб./мес.",
        features.get("total_monthly_debt_payment"))
    add("finance.debt_burden", "Расчётная долговая нагрузка после нового кредита, %",
        _percent_value(features.get("debt_burden")))
    for index, stop in enumerate(result.get("hard_stops") or []):
        add(f"score.hard_stop.{index}", "Код обязательного ограничения", stop)
    for check in checks:
        source = check.get("source", "check")
        add(f"check.{source}.status", f"Статус проверки {source}", check.get("status"))
        add(f"check.{source}.reason", f"Код причины проверки {source}", check.get("reason_code"))
    reports = result.get("check_reports") or {}
    for key in ("bki", "compliance"):
        report = reports.get(key) or {}
        add(f"{key}.status", f"Результат {key.upper()}", report.get("status"))
        add(f"{key}.reason", f"Код причины {key.upper()}", report.get("reason_code"))
        if key == "bki":
            add("bki.monthly_payment", "Ежемесячный платёж по данным БКИ, руб./мес.", report.get("monthly_payment"))
            add("bki.overdue_amount", "Просроченная задолженность, руб.", report.get("current_overdue_amount"))
            add("bki.overdue_days", "Максимальная просрочка за 12 месяцев, дней", report.get("max_overdue_days_12m"))

    underwriting = result.get("underwriting") or {}
    add("underwriting.status", "Результат обязательных правил", underwriting.get("status"))
    blocking_reasons: list[str] = []
    review_codes = {rule.get("code") for rule in underwriting.get("rules", []) if rule.get("outcome") == "REVIEW"}
    has_reject = any(rule.get("outcome") == "REJECT" for rule in underwriting.get("rules", []))
    compliance_codes = {"COMPLIANCE_POTENTIAL_MATCH", "COMPLIANCE_CONFIRMED_MATCH", "COMPLIANCE_ERROR"}
    compliance_cleared = bool(review_codes) and review_codes.issubset(compliance_codes) and not has_reject \
        and compliance_review is not None and compliance_review.outcome == "CLEAR"
    if compliance_review is not None:
        add("compliance.manual_review", "Итог ручной проверки Compliance", compliance_review.outcome)
    for index, rule in enumerate(underwriting.get("rules") or []):
        code = rule.get("code") or "RULE"
        outcome = rule.get("outcome") or "UNKNOWN"
        detail = rule.get("reason") or rule.get("explanation") or code
        add(f"underwriting.rule.{index}", "Результат обязательного правила", f"{code}: {outcome}; {detail}")
        if outcome == "REJECT" or (outcome == "REVIEW" and not compliance_cleared):
            blocking_reasons.append(f"{code}: {detail}")
    for index, field_name in enumerate(result.get("missing_fields") or []):
        add(f"data.missing.{index}", "Недостающее обязательное поле", field_name)
    if result.get("hard_stops"):
        blocking_reasons.extend(str(stop) for stop in result["hard_stops"])
    if underwriting.get("status") == "REJECT" and not blocking_reasons:
        blocking_reasons.append(f"Обязательные проверки имеют статус {underwriting['status']}.")
    if underwriting.get("status") == "REVIEW" and not compliance_cleared and not blocking_reasons:
        blocking_reasons.append("Обязательные проверки требуют ручного рассмотрения.")
    if result.get("missing_fields") or result.get("assessment_status") != "COMPLETED":
        blocking_reasons.append("Оценка неполная: нельзя завершить одобрение до получения недостающих данных.")
    return facts, list(dict.fromkeys(blocking_reasons))


def analyze_with_ollama(application, company, assessment, settings, compliance_review=None) -> AIAnalysisOut:
    result = assessment.result or {}
    facts, blocking_reasons = make_facts(application, company, assessment, compliance_review)
    request_input = {
        "application_id": str(application.id),
        "revision": assessment.application_revision,
        "facts": [{**fact, "value": _prompt_fact_value(fact)} for fact in facts],
    }
    encoded_input = json.dumps(request_input, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_input.encode("utf-8")) > MAX_INPUT_BYTES:
        raise InvalidModelAnswer("Сведения заявки превышают допустимый размер для анализа.")

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": encoded_input},
        ],
        "format": AIModelAnswer.model_json_schema(),
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 768, "num_ctx": 4096},
    }
    url = settings.ollama_base_url.rstrip("/") + "/api/chat"
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=settings.ollama_timeout_seconds) as response:
            raw = response.read(MAX_OUTPUT_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise OllamaModelMissing from None
        if exc.code in {400, 422}:
            raise InvalidModelAnswer("Ollama не приняла ограниченную JSON-схему ответа.",
                                     code="OLLAMA_SCHEMA_REJECTED") from None
        raise OllamaUnavailable from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise OllamaUnavailable from None
    if len(raw) > MAX_OUTPUT_BYTES:
        raise InvalidModelAnswer("Ответ модели превышает допустимый размер.")
    try:
        envelope = json.loads(raw)
        content = envelope["message"]["content"]
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("invalid content")
        answer = AIModelAnswer.model_validate_json(content)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError):
        # Ollama may use 404 both for an unknown route and a missing model; check its model registry.
        raise InvalidModelAnswer("Модель вернула ответ, который не прошёл проверку формата.") from None

    if blocking_reasons:
        # A hard stop is authoritative: the model cannot soften or remove it.
        answer.summary, answer.summary_fact_ids = _safe_brief_summary(result, facts, blocking_reasons)

    valid_ids = {fact["id"] for fact in facts}
    if not set(answer.summary_fact_ids).issubset(valid_ids):
        raise InvalidModelAnswer("Ответ модели содержит ссылки на отсутствующие факты.")
    forbidden_decision_claim = re.compile(
        r"(заявк\w*.{0,35}(одобр|отклон|отказ)|кредит\w*.{0,35}(одобр|отклон|отказ)|"
        r"решени\w*.{0,20}(одобр|отказ)|можно.{0,15}выдать|выдать.{0,15}кредит|"
        r"одобрить.{0,20}заявк|отказать.{0,20}заявк|завершить.{0,25}рассмотрен|"
        r"завершено.{0,20}без.{0,20}провер|скоринг.{0,30}(подтвержд.{0,20}одобр|подтверждает одобр))",
        re.IGNORECASE,
    )
    unsafe_text = bool(forbidden_decision_claim.search(answer.summary))
    if unsafe_text:
        answer.summary, answer.summary_fact_ids = _safe_brief_summary(result, facts, blocking_reasons)

    action_by_recommendation = {
        "APPROVE": "CONTINUE_REVIEW", "REVIEW": "VERIFY_DATA",
        "DECLINE": "VERIFY_DATA", "REQUEST_INFO": "REQUEST_INFORMATION",
    }
    action = ("REVIEW_REQUIRED" if blocking_reasons and any(
        not reason.startswith("Оценка неполная:") for reason in blocking_reasons
    ) else action_by_recommendation.get(result.get("recommendation"), "CONTINUE_REVIEW"))
    recommendation_text = {
        "REVIEW_REQUIRED": "Завершите обязательную проверку по процедуре банка.",
        "VERIFY_DATA": "Передайте заявку сотруднику для дополнительного рассмотрения.",
        "REQUEST_INFORMATION": "Запросите у клиента недостающие сведения.",
        "CONTINUE_REVIEW": "Передайте заявку сотруднику для итогового решения.",
    }[action]
    recommendations = [AIRecommendation(
        action=action, text=recommendation_text, fact_ids=answer.summary_fact_ids[:6],
    )]
    used_ids = set(answer.summary_fact_ids)
    for item in recommendations:
        used_ids.update(item.fact_ids)
    missing_fields = list(result.get("missing_fields") or [])
    field_labels = {
        "requested_amount": "сумма кредита", "term_months": "срок кредита", "purpose": "цель кредита",
        "average_monthly_revenue": "средняя месячная выручка",
        "average_monthly_operating_expenses": "средние месячные расходы",
        "existing_monthly_debt_payment": "текущие платежи по долгам",
    }
    data_warnings = [AIDataWarning(
        text=f"Не заполнено обязательное поле: {field_labels.get(name, name)}.",
        fact_ids=[f"data.missing.{index}"],
    ) for index, name in enumerate(missing_fields[:MAX_WARNINGS])]
    # Warnings are derived from deterministic missing-field facts, never invented by the model.
    for item in data_warnings:
        used_ids.update(item.fact_ids)
    return AIAnalysisOut(
        analysis_id=uuid4(), application_id=application.id,
        analyzed_at=datetime.now(timezone.utc), model=settings.ollama_model,
        prompt_version=PROMPT_VERSION, summary=answer.summary,
        summary_fact_ids=answer.summary_fact_ids,
        evidence=[AIEvidence(**fact) for fact in facts if fact["id"] in used_ids],
        recommendations=recommendations, data_warnings=data_warnings,
        blocking_reasons=blocking_reasons, is_blocked=bool(blocking_reasons),
        used_safe_fallback=unsafe_text,
    )
