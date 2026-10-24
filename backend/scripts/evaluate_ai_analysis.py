#!/usr/bin/env python3
"""Run a small four-case factuality smoke evaluation against local Ollama."""

import json
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.ai_analysis import InvalidModelAnswer, analyze_with_ollama


def case(name, score, risk, recommendation, missing=(), stops=(), uw_status="PASS", rules=(),
         reasons=(), factors=(), expenses="600000.00", debt="50000.00"):
    application_id = UUID(int=len(name) + score if isinstance(score, int) else len(name) + 500)
    application = SimpleNamespace(
        id=application_id, revision=2, requested_amount=Decimal("300000.00"), term_months=12,
        purpose="Оборотные средства", product_code="working_capital",
    )
    company = SimpleNamespace(legal_form="OOO", registration_date=date(2020, 1, 1))
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
        }, "checks": [{"source": "credit_history", "status": "PASS", "reason_code": "HISTORY_CLEAR"}]},
        result={
            "score": score, "risk_level": risk, "recommendation": recommendation,
            "assessment_status": "INCOMPLETE" if missing else "COMPLETED", "hard_stops": list(stops),
            "missing_fields": list(missing), "reasons": list(reasons), "factors": list(factors),
            "check_reports": {"bki": {"status": "CLEAR", "current_overdue_amount": "0.00"},
                              "compliance": {"status": "CONFIRMED_MATCH" if uw_status == "REVIEW" else "CLEAR"}},
            "underwriting": {"status": "UNKNOWN" if missing else uw_status, "rules": list(rules)},
        },
    )
    return application, company, assessment


def main():
    settings = SimpleNamespace(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M"),
        ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
    )
    cases = [
        ("обычное рассмотрение", case("ordinary", 82, "LOW", "APPROVE"), False, False),
        ("высокий риск", case(
            "high-risk", 38, "HIGH", "DECLINE", expenses="900000.00", debt="100000.00",
            reasons=({"code": "EXCESSIVE_DEBT_BURDEN", "explanation": "Долговая нагрузка превышает лимит продукта."},),
            factors=({"code": "DEBT_BURDEN", "points": 0, "max_points": 20,
                      "explanation": "Долговые платежи занимают значительную часть прибыли."},),
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
            result = analyze_with_ollama(*inputs, settings)
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
        report.append({"case": name, "analysis": result.model_dump(mode="json")})
    print(json.dumps({"model": settings.ollama_model, "cases": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
