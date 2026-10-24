"""Bounded, explanatory analysis of one stored application assessment via local Ollama."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MODEL_TAG = "qwen3:4b-instruct-2507-q4_K_M"
PROMPT_VERSION = "credit-score-explainer-v4"
MAX_INPUT_BYTES = 12_000
MAX_OUTPUT_BYTES = 8_000
MAX_RECOMMENDATIONS = 4
MAX_WARNINGS = 4


class AIRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["REVIEW_REQUIRED", "VERIFY_DATA", "REQUEST_INFORMATION", "CONTINUE_REVIEW"]
    text: str = Field(min_length=1, max_length=500)
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
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=800)
    summary_fact_ids: list[str] = Field(min_length=1, max_length=8)
    recommendations: list[AIRecommendation] = Field(min_length=1, max_length=MAX_RECOMMENDATIONS)
    data_warnings: list[AIDataWarning] = Field(max_length=MAX_WARNINGS)


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


def _score_phrase(score: int) -> str:
    last_two = score % 100
    last = score % 10
    if 11 <= last_two <= 14:
        word = "баллов"
    elif last == 1:
        word = "балл"
    elif 2 <= last <= 4:
        word = "балла"
    else:
        word = "баллов"
    return f"{score} {word} из 100"


SYSTEM_PROMPT = """Ты помощник сотрудника банка, который только поясняет уже рассчитанные факты.
Используй исключительно переданные факты одной заявки. Не пересчитывай балл и риск,
не выдумывай сведения, причины, правила или проверки. Не одобряй и не отклоняй кредит,
не формулируй финальное решение и не заявляй, что заявку можно выдать или рассмотрение
завершить. Не отменяй ограничения. Рекомендации могут касаться только проверки фактов,
запроса недостающих сведений или продолжения рассмотрения человеком. Не утверждай, что
условия продукта соблюдены, если это прямо не подтверждено фактами underwriting. Не
делай выводы о полноте или согласованности данных, кроме перечисленных пропусков и
проверенных результатов. Каждое утверждение подкрепляй идентификаторами фактов из входа.
В предупреждения включай только явные пропуски либо противоречия из входа; если их нет,
верни пустой список. Не переписывай цифрами суммы, сроки, баллы, даты и коды: исходные
значения интерфейс покажет отдельно по ссылкам на факты. Дай краткое резюме максимум в
двух предложениях и одну короткую рекомендацию. Пиши живым, ясным русским языком для
сотрудника без технической терминологии. Не повторяй английские коды риска, решений и
проверок. Для сильного профиля назови положительные факторы и подчеркни, что это рекомендация
скоринга, а не одобрение кредита. Для слабого профиля объясни конкретные неблагоприятные
факторы из переданных причин/факторов и что сотруднику можно перепроверить или запросить.
Не советуй менять верные сведения и не обещай, что исправление гарантирует одобрение.
Верни только JSON строго по переданной схеме. Пиши по-русски."""


def _prompt_fact_value(fact: dict) -> str:
    value = fact["value"]
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
    if fact["id"] in {"score.risk", "score.recommendation", "score.status"} or fact["id"].endswith(".status"):
        return localized.get(value, value)
    if fact["id"].startswith("underwriting.rule."):
        match = re.match(r"([^:]+):\s*(PASS|REVIEW|REJECT)(.*)", value)
        if match:
            reason = {"PASS": "пройдено", "REVIEW": "нужна ручная проверка", "REJECT": "ограничение"}[match.group(2)]
            return f"{match.group(1)}: {reason}{match.group(3)}"
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
    add("app.debt", "Существующие месячные платежи, руб.", input_data.get("existing_monthly_debt_payment"))
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
        "options": {"temperature": 0, "num_predict": 512, "num_ctx": 4096},
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
        missing_fields = list(result.get("missing_fields") or [])
        mandatory_blocking_reasons = [
            reason for reason in blocking_reasons
            if not reason.startswith("Оценка неполная:")
        ]
        blocking_fact_ids = [fact["id"] for fact in facts
                             if fact["id"].startswith(("underwriting.rule.", "score.hard_stop.", "data.missing."))]
        score_fact_ids = [fact_id for fact_id in ("score.score", "score.scale", "score.risk", "score.recommendation")
                          if fact_id in {fact["id"] for fact in facts}]
        missing_fact_ids = [fact["id"] for fact in facts if fact["id"].startswith("data.missing.")]
        if missing_fields and not mandatory_blocking_reasons:
            field_labels = {
                "requested_amount": "сумма кредита", "term_months": "срок кредита", "purpose": "цель кредита",
                "average_monthly_revenue": "средняя месячная выручка",
                "average_monthly_operating_expenses": "средние месячные расходы",
                "existing_monthly_debt_payment": "текущие платежи по долгам",
            }
            missing_labels = [field_labels.get(name, name) for name in missing_fields[:4]]
            answer.summary = "Для завершения рассмотрения запросите недостающие сведения: " + ", ".join(missing_labels) + "."
            answer.summary_fact_ids = (missing_fact_ids + score_fact_ids)[:8]
            answer.recommendations = [AIRecommendation(
                action="REQUEST_INFORMATION",
                text="Запросите у клиента перечисленные обязательные сведения, затем обновите оценку.",
                fact_ids=missing_fact_ids[:6] or answer.summary_fact_ids[:6],
            )]
        else:
            answer.summary = (
                "Заявку блокирует обязательная проверка. Её результат нужно разрешить по установленной процедуре; "
                "ИИ не может снять это ограничение."
            )
            answer.summary_fact_ids = (blocking_fact_ids[:4] + score_fact_ids)[:8]
            answer.recommendations = [AIRecommendation(
                action="REVIEW_REQUIRED",
                text="Выдача заблокирована обязательной проверкой. Причину следует разрешать только по установленной процедуре.",
                fact_ids=[fact["id"] for fact in facts if fact["id"].startswith(("underwriting.", "score.hard_stop."))][:6]
                       or answer.summary_fact_ids[:6],
            )]
    else:
        answer.recommendations = [
            item for item in answer.recommendations if item.action != "REVIEW_REQUIRED"
        ] or [AIRecommendation(
            action="CONTINUE_REVIEW", text="Продолжить рассмотрение по установленной процедуре.",
            fact_ids=answer.summary_fact_ids[:6],
        )]
    valid_ids = {fact["id"] for fact in facts}
    cited = set(answer.summary_fact_ids)
    for item in answer.recommendations:
        cited.update(item.fact_ids)
    for item in answer.data_warnings:
        cited.update(item.fact_ids)
    if not cited.issubset(valid_ids):
        raise InvalidModelAnswer("Ответ модели содержит ссылки на отсутствующие факты.")
    evidence_by_id = {fact["id"]: fact for fact in facts}
    narratives = [(answer.summary, answer.summary_fact_ids)]
    narratives.extend((item.text, item.fact_ids) for item in answer.recommendations)
    narratives.extend((item.text, item.fact_ids) for item in answer.data_warnings)
    forbidden_decision_claim = re.compile(
        r"(заявк\w*.{0,35}(одобр|отклон|отказ)|кредит\w*.{0,35}(одобр|отклон|отказ)|"
        r"решени\w*.{0,20}(одобр|отказ)|можно.{0,15}выдать|выдать.{0,15}кредит|"
        r"одобрить.{0,20}заявк|отказать.{0,20}заявк|завершить.{0,25}рассмотрен|"
        r"завершено.{0,20}без.{0,20}провер|скоринг.{0,30}(подтвержд.{0,20}одобр|подтверждает одобр))",
        re.IGNORECASE,
    )
    product_claim = re.compile(r"соответств\w*.{0,30}(услов|требован)", re.IGNORECASE)
    completeness_claim = re.compile(r"все сведения.{0,20}(полны|согласован)", re.IGNORECASE)
    no_review_claim = re.compile(r"(не требует.{0,20}провер|без дополнительн\w*.{0,20}провер)", re.IGNORECASE)
    passed_checks_claim = re.compile(
        r"(?:(?:все\s+)?(?:обязательн\w+\s+)?(?:провер\w*|правил\w*).{0,60}"
        r"(?:пройден\w*|выполн\w*|успеш\w*|соблюден\w*)|"
        r"(?:пройден\w*|выполн\w*|успеш\w*|соблюден\w*).{0,60}(?:провер\w*|правил\w*))",
        re.IGNORECASE,
    )
    unsafe_text = False
    try:
        for narrative, fact_ids in narratives:
            if forbidden_decision_claim.search(narrative):
                raise InvalidModelAnswer("Ответ модели содержит формулировку итогового кредитного решения.")
            if product_claim.search(narrative):
                underwriting_rules = [fact for fact in facts if fact["id"].startswith("underwriting.rule.")]
                if not underwriting_rules or any(": PASS;" not in fact["value"] for fact in underwriting_rules):
                    raise InvalidModelAnswer("Ответ модели содержит неподтверждённый вывод о проверках или условиях.",
                                             code="UNSUPPORTED_CHECK_CLAIM", narrative=narrative)
                for fact in underwriting_rules:
                    if fact["id"] not in fact_ids:
                        fact_ids.append(fact["id"])
                limit = 8 if fact_ids is answer.summary_fact_ids else 6
                if len(fact_ids) > limit:
                    raise InvalidModelAnswer("Ответ модели ссылается на слишком много фактов.")
            if completeness_claim.search(narrative) and (result.get("missing_fields") or result.get("assessment_status") != "COMPLETED"):
                raise InvalidModelAnswer("Ответ модели утверждает, что неполные данные заполнены.",
                                         code="UNSUPPORTED_COMPLETENESS_CLAIM", narrative=narrative)
            if no_review_claim.search(narrative):
                raise InvalidModelAnswer("Ответ модели утверждает, что дополнительная проверка не нужна.",
                                         code="UNSUPPORTED_REVIEW_CLAIM", narrative=narrative)
            if passed_checks_claim.search(narrative):
                check_fact_ids = {
                    fact["id"] for fact in facts
                    if (fact["id"].startswith("check.") and fact["id"].endswith(".status"))
                    or fact["id"].startswith("underwriting.rule.")
                    or fact["id"] in {"bki.status", "compliance.status", "underwriting.status"}
                }
                check_facts = [fact for fact in facts if fact["id"] in check_fact_ids]
                if not check_fact_ids or not check_fact_ids.issubset(set(fact_ids)):
                    raise InvalidModelAnswer("Общий вывод о проверках не ссылается на все исходные результаты.",
                                             code="UNSUPPORTED_CHECK_CLAIM", narrative=narrative)
                statuses_are_clear = all(
                    fact["value"].split(":", 1)[-1].strip().split(";", 1)[0] in
                    {"PASS", "AVAILABLE", "CLEAR", "NO_HISTORY"}
                    for fact in check_facts
                )
                if not statuses_are_clear:
                    raise InvalidModelAnswer("Ответ модели утверждает, что обязательные проверки пройдены.",
                                             code="UNSUPPORTED_CHECK_CLAIM", narrative=narrative)
            allowed_numbers = set()
            for fact_id in fact_ids:
                allowed_numbers.update(_numbers_in_text(evidence_by_id[fact_id]["value"]))
            unsupported_numbers = _numbers_in_text(narrative) - allowed_numbers
            if unsupported_numbers:
                raise InvalidModelAnswer("Ответ модели содержит число; проверьте точные значения в списке исходных фактов.",
                                         code="UNSUPPORTED_NUMBER", number=sorted(unsupported_numbers)[0], narrative=narrative)
    except InvalidModelAnswer:
        unsafe_text = True
        answer.data_warnings = []
        missing_fields = list(result.get("missing_fields") or [])
        if missing_fields or result.get("assessment_status") != "COMPLETED":
            answer.summary = "Оценка неполная. В списке фактов указаны недостающие обязательные данные."
            answer.summary_fact_ids = ([fact["id"] for fact in facts if fact["id"].startswith("data.missing.")][:8]
                                       or (["score.status"] if "score.status" in valid_ids else [facts[0]["id"]]))
        elif blocking_reasons:
            score_fact_ids = [fact_id for fact_id in ("score.score", "score.scale", "score.risk", "score.recommendation")
                              if fact_id in valid_ids]
            blocking_fact_ids = [fact["id"] for fact in facts
                                 if fact["id"].startswith(("underwriting.rule.", "score.hard_stop."))]
            answer.summary = (
                "Заявку блокирует обязательная проверка. Её результат нужно разрешить по установленной процедуре; "
                "ИИ не может снять это ограничение."
            )
            answer.summary_fact_ids = (blocking_fact_ids[:4] + score_fact_ids)[:8]
        elif result.get("recommendation") == "APPROVE" and result.get("risk_level") == "LOW":
            answer.summary = (
                f"По текущим данным профиль выглядит сильным: {_score_phrase(result['score'])}, риск низкий. "
                "Скоринг даёт положительную рекомендацию; итоговое решение остаётся за сотрудником."
            )
            answer.summary_fact_ids = [
                fact_id for fact_id in ("score.score", "score.scale", "score.risk", "score.recommendation")
                if fact_id in valid_ids
            ]
        else:
            score_ids = [fact_id for fact_id in ("score.score", "score.scale", "score.risk", "score.recommendation")
                         if fact_id in valid_ids]
            issue_ids = [fact["id"] for fact in facts
                         if fact["id"].startswith(("score.reason.", "score.factor."))]
            parts = []
            if result.get("score") is not None:
                parts.append(f"Балл скоринга: {result['score']} из 100.")
            if result.get("risk_level"):
                risk = {"LOW": "низкий", "MEDIUM": "средний", "HIGH": "высокий"}.get(
                    result["risk_level"], "не определён")
                parts.append(f"Оценка риска — {risk}.")
            if result.get("recommendation"):
                recommendation = {
                    "APPROVE": "положительная, но это не итоговое решение банка",
                    "REVIEW": "нужно дополнительное рассмотрение",
                    "DECLINE": "отрицательная, но это не итоговое решение банка",
                    "REQUEST_INFO": "нужно запросить сведения",
                }.get(result["recommendation"], "не сформирована")
                parts.append(f"Рекомендация скоринга: {recommendation}.")
            if issue_ids and result.get("recommendation") in {"DECLINE", "REVIEW"}:
                parts.append("Факторы, повлиявшие на оценку: " + "; ".join(
                    evidence_by_id[fact_id]["value"].rstrip(".; ") for fact_id in issue_ids[:2]
                ) + ".")
            answer.summary = " ".join(parts) or "Сохранённая оценка сформирована; см. факты заявки и результаты проверок."
            answer.summary_fact_ids = (score_ids + issue_ids[:2])[:8]
        if not blocking_reasons and missing_fields:
            answer.recommendations = [AIRecommendation(
                action="REQUEST_INFORMATION",
                text="Запросить недостающие обязательные сведения, перечисленные в предупреждениях.",
                fact_ids=[fact["id"] for fact in facts if fact["id"].startswith("data.missing.")][:6]
                    or answer.summary_fact_ids[:6],
            )]
        elif not blocking_reasons and result.get("recommendation") in {"DECLINE", "REVIEW"}:
            issue_ids = [fact["id"] for fact in facts
                         if fact["id"].startswith(("score.reason.", "score.factor."))]
            answer.recommendations = [AIRecommendation(
                action="VERIFY_DATA",
                text=("Перепроверьте показатели, перечисленные среди факторов оценки. Если сведения актуальны, "
                      "сотрудник может рассмотреть дальнейшие варианты в рамках правил банка."),
                fact_ids=(issue_ids[:5] or answer.summary_fact_ids[:5]),
            )]
        elif not blocking_reasons:
            answer.recommendations = [AIRecommendation(
                action="CONTINUE_REVIEW", text="Продолжить рассмотрение человеком по установленной процедуре.",
                fact_ids=answer.summary_fact_ids[:6],
            )]
    model_warnings_ignored = bool(answer.data_warnings)
    answer.data_warnings = []
    used_ids = set(answer.summary_fact_ids)
    for item in answer.recommendations:
        used_ids.update(item.fact_ids)
    for item in answer.data_warnings:
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
        recommendations=answer.recommendations, data_warnings=data_warnings,
        blocking_reasons=blocking_reasons, is_blocked=bool(blocking_reasons),
        used_safe_fallback=unsafe_text or model_warnings_ignored,
    )
