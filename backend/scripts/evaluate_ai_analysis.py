#!/usr/bin/env python3
"""Run a small four-case factuality smoke evaluation against local Ollama."""

import json
import os
from pathlib import Path
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_analysis import InvalidModelAnswer, analyze_with_ollama


def case(name, score, risk, recommendation, missing=(), stops=(), uw_status="PASS", rules=(),
         reasons=(), factors=(), expenses="600000.00", debt="50000.00",
         registration_date="2020-01-01", features=()):
    application_id = UUID(int=len(name) + score if isinstance(score, int) else len(name) + 500)
    application = SimpleNamespace(
        id=application_id, revision=2, requested_amount=Decimal("300000.00"), term_months=12,
        purpose="Оборотные средства", product_code="working_capital",
        existing_monthly_debt_payment=Decimal(debt),
    )
    registration_date = date.fromisoformat(registration_date)
    company = SimpleNamespace(legal_form="OOO", registration_date=registration_date)
    product = SimpleNamespace(name="Оборотные средства", description="Пополнение оборотных средств")
    if not rules:
        rules = (
            {"code": "MIN_BUSINESS_AGE", "outcome": "PASS", "explanation": "Возраст бизнеса выше минимума."},
            {"code": "PRODUCT_AMOUNT_LIMIT", "outcome": "PASS", "explanation": "Сумма в диапазоне продукта."},
            {"code": "DEBT_BURDEN", "outcome": "UNKNOWN" if missing else "PASS",
             "explanation": "Нагрузка не рассчитана." if missing else "Нагрузка в допустимом диапазоне."},
            {"code": "BKI_HISTORY", "outcome": "PASS", "explanation": "История доступна."},
            {"code": "COMPLIANCE_CLEAR", "outcome": "PASS", "explanation": "Совпадений нет."},
        )
    assessment = SimpleNamespace(
        id=UUID(int=900 + len(name)), application_revision=1,
        input_snapshot={"input_data": {
            "product_code": "working_capital", "average_monthly_revenue": None if missing else "1000000.00",
            "average_monthly_operating_expenses": expenses, "existing_monthly_debt_payment": debt,
            "registration_date": registration_date.isoformat(), "as_of_date": "2026-10-24",
        }, "checks": [{"source": "credit_history", "status": "PASS", "reason_code": "HISTORY_CLEAR"}]},
        result={
            "score": score, "risk_level": risk, "recommendation": recommendation,
            "assessment_status": "INCOMPLETE" if missing else "COMPLETED", "hard_stops": list(stops),
            "missing_fields": list(missing), "reasons": list(reasons), "factors": list(factors),
            "features": dict(features),
            "check_reports": {"bki": {"status": "AVAILABLE", "monthly_payment": debt,
                                       "current_overdue_amount": "0.00"},
                              "compliance": {"status": "CONFIRMED_MATCH" if uw_status == "REVIEW" else "CLEAR"}},
            "underwriting": {"status": "UNKNOWN" if missing else uw_status, "rules": list(rules)},
        },
    )
    return application, company, assessment, product


def main():
    settings = SimpleNamespace(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M"),
        ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
    )
    cases = [
        ("обычное рассмотрение", case("ordinary", 100, "LOW", "APPROVE"), False, False),
        ("высокий риск", case(
            "high-risk", 43, "HIGH", "DECLINE", expenses="956000.00", debt="0.00",
            registration_date="2026-04-24",
            reasons=({"code": "LOW_SCORE", "explanation": "Балл ниже порога рекомендации продукта."},),
            factors=(
                {"code": "BUSINESS_AGE", "points": 5, "max_points": 20,
                 "explanation": "Полных месяцев работы: 6; вклад 5 из 20."},
                {"code": "OPERATING_MARGIN", "points": 8, "max_points": 25,
                 "explanation": "Доля выручки после операционных расходов — 4,4%; вклад 8 из 25."},
                {"code": "DEBT_BURDEN", "points": 10, "max_points": 35,
                 "explanation": "Кредитные платежи относительно дохода после расходов — 64,5%; вклад 10 из 35."},
                {"code": "PAYMENT_HISTORY", "points": 20, "max_points": 20,
                 "explanation": "Текущих просрочек нет; вклад 20 из 20."},
            ),
            features={"business_age_months": 6, "monthly_operating_profit": "44000.00",
                      "operating_margin": "0.044", "new_monthly_payment": "28367.88",
                      "total_monthly_debt_payment": "28367.88", "debt_burden": "0.6447245455"},
        ), False, False),
        ("обязательная блокировка", case("blocked", 96, "LOW", "APPROVE", uw_status="REVIEW",
            rules=({"code": "COMPLIANCE_CONFIRMED_MATCH", "outcome": "REVIEW", "reason": "Требуется разбор сотрудником"},)), True, False),
        ("неполные данные", case("incomplete", None, "UNKNOWN", "REQUEST_INFO",
            missing=("average_monthly_revenue",)), True, True),
    ]
    report = []
    for name, inputs, must_be_blocked, must_warn_missing in cases:
        selected = os.getenv("AI_EVAL_CASE")
        if selected and selected != name:
            continue
        try:
            application, company, assessment, product = inputs
            result = analyze_with_ollama(application, company, assessment, settings, product=product)
        except InvalidModelAnswer as error:
            detail = f"; число: {error.number}" if error.number else ""
            if os.getenv("AI_EVAL_DEBUG") and error.narrative:
                detail += f"; текст: {error.narrative}"
            raise SystemExit(f"{name}: {error}{detail}") from None
        evidence_ids = {fact.id for fact in result.evidence}
        citations = set(result.summary_fact_ids)
        for recommendation in result.recommendations:
            citations.update(recommendation.fact_ids)
        for warning in result.data_warnings:
            citations.update(warning.fact_ids)
        if not citations.issubset(evidence_ids):
            raise SystemExit(f"{name}: вывод содержит ссылки без исходных фактов")
        if result.is_blocked != must_be_blocked:
            raise SystemExit(f"{name}: статус блокировки не совпал с обязательными проверками")
        if must_warn_missing and not result.data_warnings:
            raise SystemExit(f"{name}: отсутствует предупреждение о неполных данных")
        summary_source = ("backend_override" if result.blocking_reasons else
                          "backend_fallback" if result.used_safe_fallback else "model")
        report.append({"case": name, "summary_source": summary_source,
                       "analysis": result.model_dump(mode="json")})
    print(json.dumps({"model": settings.ollama_model, "cases": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
