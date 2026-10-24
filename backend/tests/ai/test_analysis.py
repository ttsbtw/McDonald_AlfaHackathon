import io
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest

from app.ai_analysis import (
    InvalidModelAnswer,
    OllamaModelMissing,
    OllamaUnavailable,
    analyze_with_ollama,
    make_facts,
)


def fixture_application(result=None):
    application = SimpleNamespace(
        id=UUID(int=42), revision=2, requested_amount=Decimal("300000.00"), term_months=12,
        purpose="Оборотные средства", product_code="working_capital",
    )
    company = SimpleNamespace(legal_form="OOO", registration_date=date(2020, 1, 1))
    assessment = SimpleNamespace(
        id=UUID(int=43), application_revision=1,
        input_snapshot={"input_data": {"average_monthly_revenue": "1000000.00", "average_monthly_operating_expenses": "600000.00"},
                        "checks": [{"source": "credit_history", "status": "PASS", "reason_code": "HISTORY_CLEAR"}]},
        result=result or {
            "score": 82, "risk_level": "LOW", "recommendation": "APPROVE", "assessment_status": "COMPLETED",
            "hard_stops": [], "reasons": [{"code": "SCORE_SUFFICIENT", "explanation": "Балл выше порога"}],
            "check_reports": {"bki": {"status": "CLEAR", "current_overdue_amount": "0.00"},
                              "compliance": {"status": "CLEAR", "reason_code": "NO_MATCH"}},
            "underwriting": {"status": "PASS", "rules": []},
        },
    )
    return application, company, assessment


def valid_content():
    return json.dumps({
        "summary": "Балл скоринга высокий, риск низкий.",
        "summary_fact_ids": ["score.score", "score.scale", "score.risk"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение человеком.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps({"message": {"content": self.payload}}).encode()


def settings():
    return SimpleNamespace(ollama_model="qwen3:4b-instruct-2507-q4_K_M",
                           ollama_base_url="http://ollama:11434", ollama_timeout_seconds=1)


def test_valid_json_is_checked_and_has_only_used_source_facts(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse(valid_content())

    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.summary == "Балл скоринга высокий, риск низкий."
    assert {fact.id for fact in result.evidence} == {
        "score.score", "score.scale", "score.risk", "score.recommendation",
    }
    assert len(captured["body"]["messages"]) == 2
    assert captured["body"]["options"]["num_ctx"] == 4096
    assert captured["timeout"] == 1
    assert str(application.id) in captured["body"]["messages"][1]["content"]
    assert "Демо-компания" not in captured["body"]["messages"][1]["content"]


@pytest.mark.parametrize("content", ["not json", '{"summary":"no fields"}',
                                       json.dumps({"summary": "Выручка 1 млн.", "summary_fact_ids": ["made.up"],
                                                   "recommendations": [{"action": "CONTINUE_REVIEW", "text": "ok", "fact_ids": ["score.score"]}],
                                                   "data_warnings": []})])
def test_invalid_or_unreferenced_answer_is_rejected(monkeypatch, content):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    with pytest.raises(InvalidModelAnswer):
        analyze_with_ollama(application, company, assessment, settings())


def test_ollama_unavailable_has_a_distinct_error(monkeypatch):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")))
    application, company, assessment = fixture_application()
    with pytest.raises(OllamaUnavailable):
        analyze_with_ollama(application, company, assessment, settings())


def test_missing_model_has_a_distinct_error(monkeypatch):
    error = HTTPError("http://ollama:11434/api/chat", 404, "missing", {}, io.BytesIO(b'{"error":"model not found"}'))
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    application, company, assessment = fixture_application()
    with pytest.raises(OllamaModelMissing):
        analyze_with_ollama(application, company, assessment, settings())


def test_mandatory_check_block_cannot_be_overridden_by_model(monkeypatch):
    content = json.dumps({
        "summary": "Скоринг высокий.", "summary_fact_ids": ["score.score"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Одобрить заявку сразу.", "fact_ids": ["score.score"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    assessment_result = {
        "score": 95, "risk_level": "LOW", "recommendation": "APPROVE", "assessment_status": "COMPLETED",
        "hard_stops": [], "reasons": [], "check_reports": {"compliance": {"status": "CONFIRMED_MATCH"}},
        "underwriting": {"status": "REVIEW", "rules": [{"code": "COMPLIANCE_CONFIRMED_MATCH",
            "outcome": "REVIEW", "reason": "Подтверждено совпадение обязательного реестра"}]},
    }
    application, company, assessment = fixture_application(assessment_result)
    facts, _ = make_facts(application, company, assessment)
    assert any(fact["id"] == "underwriting.rule.0" for fact in facts)
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.is_blocked is True
    assert result.blocking_reasons == ["COMPLIANCE_CONFIRMED_MATCH: Подтверждено совпадение обязательного реестра"]
    assert result.recommendations[0].action == "REVIEW_REQUIRED"
    assert "заблокирована" in result.recommendations[0].text


def test_unsafe_model_text_is_replaced_with_source_fact_summary(monkeypatch):
    content = json.dumps({
        "summary": "Скоринг подтверждает одобрение, сумма составляет 3000000 рублей.",
        "summary_fact_ids": ["score.score", "score.recommendation"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Заявку можно одобрить.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.used_safe_fallback is True
    assert "подтверждает одобрение" not in result.summary
    assert "3000000" not in result.summary
    assert result.recommendations[0].action == "CONTINUE_REVIEW"
    assert set(result.summary_fact_ids).issubset({fact.id for fact in result.evidence})


def test_general_claim_that_all_checks_passed_requires_every_check_fact(monkeypatch):
    content = json.dumps({
        "summary": "Все обязательные проверки и правила выполнены.",
        "summary_fact_ids": ["check.credit_history.status", "underwriting.status"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение человеком.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.used_safe_fallback is True
    assert "проверки и правила выполнены" not in result.summary.lower()
    assert result.summary_fact_ids == ["score.score", "score.scale", "score.risk", "score.recommendation"]
