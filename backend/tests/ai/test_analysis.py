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
    _prompt_fact_value,
    analyze_with_ollama,
    make_facts,
)
from app.schemas import AIAnalysisOut as AIAnalysisResponse


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
        "summary": ("Заявка на 300000 ₽ на 12 месяцев для пополнения оборотных средств. "
                    "Скоринг — 82 из 100, риск низкий. Передайте заявку сотруднику банка для итогового решения."),
        "summary_fact_ids": ["app.amount", "app.term", "app.purpose", "score.score", "score.scale", "score.risk"],
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
    assert "для пополнения оборотных средств" in result.summary
    assert {fact.id for fact in result.evidence} == {
        "app.amount", "app.term", "app.purpose", "score.score", "score.scale", "score.risk",
    }
    assert len(captured["body"]["messages"]) == 2
    assert captured["body"]["options"]["num_ctx"] == 4096
    assert captured["timeout"] == 1
    assert str(application.id) in captured["body"]["messages"][1]["content"]
    assert "Демо-компания" not in captured["body"]["messages"][1]["content"]
    model_facts = json.loads(captured["body"]["messages"][1]["content"])["facts"]
    assert next(fact["value"] for fact in model_facts if fact["id"] == "score.risk") == "низкий"
    assert set(captured["body"]["format"]["properties"]) == {"summary", "summary_fact_ids"}
    assert "положительная рекомендация скоринга" in next(
        fact["value"] for fact in model_facts if fact["id"] == "score.recommendation"
    )
    assert next(fact["value"] for fact in model_facts if fact["id"] == "app.revenue") == "1 000 000 ₽/мес."


def test_prompt_receives_explicit_financial_sources_and_precomputed_ratios(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["facts"] = json.loads(json.loads(request.data)["messages"][1]["content"])["facts"]
        return FakeResponse(valid_content())

    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    application.existing_monthly_debt_payment = Decimal("450000.00")
    assessment.input_snapshot["input_data"].update({
        "average_monthly_revenue": "3050000.00",
        "average_monthly_operating_expenses": "1950000.00",
        "existing_monthly_debt_payment": "495000.00",
    })
    assessment.result["features"] = {
        "operating_margin": "0.3606557", "debt_burden": "0.5965971",
        "monthly_operating_profit": "1100000.00", "new_monthly_payment": "161256.85",
        "total_monthly_debt_payment": "656256.85",
    }
    assessment.result["check_reports"]["bki"]["monthly_payment"] = "45000.00"
    analyze_with_ollama(application, company, assessment, settings())

    facts = {fact["id"]: fact["value"] for fact in captured["facts"]}
    assert facts["app.revenue"] == "3 050 000 ₽/мес."
    assert facts["app.declared_debt"] == "450 000 ₽/мес."
    assert facts["bki.monthly_payment"] == "45 000 ₽/мес."
    assert facts["app.debt"] == "495 000 ₽/мес."
    assert facts["finance.operating_profit"] == "1 100 000 ₽/мес."
    assert facts["finance.operating_margin"] == "36,1%"
    assert facts["finance.debt_burden"] == "59,7%"


@pytest.mark.parametrize("low_risk", [True, False])
def test_payment_source_hallucination_is_replaced_with_fact_grounded_summary(monkeypatch, low_risk):
    content = json.dumps({
        "summary": ("Платежи в анкете указаны как 0 ₽, но в БКИ и скоринге зафиксированы "
                    "45 000 ₽ в месяц — это разрыв в данных."),
        "summary_fact_ids": ["app.declared_debt", "app.debt", "bki.monthly_payment"],
    })
    captured = {}

    def fake_urlopen(request, timeout):
        captured["facts"] = json.loads(json.loads(request.data)["messages"][1]["content"])["facts"]
        return FakeResponse(content)

    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    if not low_risk:
        assessment.result.update(risk_level="MEDIUM", recommendation="REVIEW")
    application.existing_monthly_debt_payment = Decimal("45000.00")
    assessment.input_snapshot["input_data"]["existing_monthly_debt_payment"] = "45000.00"
    assessment.result["check_reports"]["bki"].update({
        "monthly_payment": "45000.00", "status": "AVAILABLE",
    })

    result = analyze_with_ollama(application, company, assessment, settings())

    comparison = next(fact["value"] for fact in captured["facts"] if fact["id"] == "data.payment_comparison")
    assert "совпадают" in comparison
    if low_risk:
        assert result.used_safe_fallback is False
        assert result.summary == json.loads(content)["summary"]
        return
    assert result.used_safe_fallback is True
    assert "разрыв в данных" not in result.summary
    assert "анкете указаны как 0" not in result.summary


def test_real_payment_source_difference_remains_in_model_summary(monkeypatch):
    content = json.dumps({
        "summary": "В анкете указан платёж 0 ₽, тогда как в скоринге и БКИ учтено 45 000 ₽/мес.; значения расходятся.",
        "summary_fact_ids": ["app.declared_debt", "app.debt", "bki.monthly_payment"],
    })
    captured = {}

    def fake_urlopen(request, timeout):
        captured["facts"] = json.loads(json.loads(request.data)["messages"][1]["content"])["facts"]
        return FakeResponse(content)

    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    application.existing_monthly_debt_payment = Decimal("0.00")
    assessment.input_snapshot["input_data"]["existing_monthly_debt_payment"] = "45000.00"
    assessment.result["check_reports"]["bki"].update({"monthly_payment": "45000.00", "status": "AVAILABLE"})

    result = analyze_with_ollama(application, company, assessment, settings())

    comparison = next(fact for fact in captured["facts"] if fact["id"] == "data.payment_comparison")
    assert "различаются" in comparison["value"]
    assert result.used_safe_fallback is False
    assert "значения расходятся" in result.summary
    assert "data.payment_comparison" in result.summary_fact_ids
    assert "БКИ сверяется с общей суммой анкеты и не прибавляется к ней" in comparison["value"]


def test_payment_comparison_explains_declared_total_and_bki_verification(monkeypatch):
    content = json.dumps({
        "summary": ("Клиент указал общие платежи 50 000 ₽/мес., БКИ показывает 45 000 ₽/мес.; "
                    "скоринг учитывает 50 000 ₽/мес., поскольку БКИ используется для сверки, а не складывается с анкетой."),
        "summary_fact_ids": ["app.declared_debt", "app.debt", "bki.monthly_payment", "data.payment_comparison"],
    })
    captured = {}

    def fake_urlopen(request, timeout):
        captured["facts"] = json.loads(json.loads(request.data)["messages"][1]["content"])["facts"]
        return FakeResponse(content)

    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    application.existing_monthly_debt_payment = Decimal("50000.00")
    assessment.input_snapshot["input_data"]["existing_monthly_debt_payment"] = "50000.00"
    assessment.result["check_reports"]["bki"].update({"monthly_payment": "45000.00", "status": "AVAILABLE"})

    result = analyze_with_ollama(application, company, assessment, settings())

    comparison = next(fact["value"] for fact in captured["facts"] if fact["id"] == "data.payment_comparison")
    assert "анкета — 50 000 ₽/мес." in comparison
    assert "БКИ — 45 000 ₽/мес." in comparison
    assert "учтено 50 000 ₽/мес." in comparison
    assert "не прибавляется к ней" in comparison
    assert result.used_safe_fallback is False


@pytest.mark.parametrize("low_risk", [True, False])
def test_product_fit_claim_without_matching_description_is_replaced(monkeypatch, low_risk):
    content = json.dumps({
        "summary": ("Цель связана с операционными расходами, что соответствует продукту «Оборудование». "
                    "Скоринг — 82 из 100, риск низкий."),
        "summary_fact_ids": ["app.purpose", "app.product", "app.product_description", "score.score", "score.risk"],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    if not low_risk:
        assessment.result.update(risk_level="MEDIUM", recommendation="REVIEW")
    application.purpose = "Оплата аренды помещения и закупка сырья на ближайшие три месяца"
    application.product_code = "equipment"
    product = SimpleNamespace(name="Оборудование — демо", description="Приобретение оборудования")

    result = analyze_with_ollama(application, company, assessment, settings(), product=product)

    if low_risk:
        assert result.used_safe_fallback is False
        assert result.summary == json.loads(content)["summary"]
        return
    assert result.used_safe_fallback is True
    assert "цель «оплата аренды помещения и закупка сырья" in result.summary.lower()
    assert "продукт «Оборудование»" in result.summary
    assert "назначением «Приобретение оборудования»" in result.summary
    assert "не подтверждают соответствие цели продукту" in result.summary


def test_personal_use_and_cover_story_cannot_be_summarized_as_product_fit(monkeypatch):
    content = json.dumps({
        "summary": ("Сумма соответствует назначению продукта — приобретению оборудования, но клиент хочет перевести деньги "
                    "на личную карту, указав в заявке покупку оборудования."),
        "summary_fact_ids": ["app.purpose", "app.product", "app.product_description"],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    application.purpose = "Хочу вывести деньги себе на личную карту, а в заявке указать покупку оборудования."
    application.product_code = "equipment"
    product = SimpleNamespace(name="Оборудование — демо", description="Приобретение оборудования")

    result = analyze_with_ollama(application, company, assessment, settings(), product=product)

    assert result.used_safe_fallback is True
    assert "одновременно описывает личное использование средств" in result.summary
    assert "намерение указать в анкете покупку оборудования" in result.summary
    assert "соответствует назначению продукта" not in result.summary.lower()


def test_low_risk_salary_and_rent_purpose_keeps_model_explanation(monkeypatch):
    summary = ("Средства нужны для зарплаты, налогов и аренды при задержках оплаты от клиентов. "
               "Это соответствует назначению продукта «Оборотные средства». "
               "Скоринг — 75 из 100, риск низкий; окончательное решение принимает сотрудник.")
    content = json.dumps({"summary": summary, "summary_fact_ids": ["app.purpose", "score.score"]})
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    application.purpose = "Выплата зарплаты сотрудникам, налогов и аренды при задержках оплаты по актам"
    assessment.result["score"] = 75
    product = SimpleNamespace(name="Оборотные средства — демо", description="Закупки и текущие расходы")
    result = analyze_with_ollama(application, company, assessment, settings(), product=product)
    assert result.summary == summary
    assert result.used_safe_fallback is False


def test_nonpositive_profit_is_named_as_root_cause_of_block(monkeypatch):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(valid_content()))
    result_data = {
        "score": 32, "risk_level": "HIGH", "recommendation": "DECLINE", "assessment_status": "COMPLETED",
        "hard_stops": ["NON_POSITIVE_OPERATING_PROFIT"],
        "features": {"monthly_operating_profit": "-50000.00"},
        "reasons": [{"code": "NON_POSITIVE_OPERATING_PROFIT",
                     "message": "Доход после операционных расходов не позволяет обслуживать кредит."}],
        "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "REVIEW", "rules": [{"code": "DEBT_BURDEN", "outcome": "REVIEW",
            "reason": "Долговую нагрузку нельзя рассчитать по имеющимся данным."}]},
    }
    application, company, assessment = fixture_application(result_data)
    result = analyze_with_ollama(application, company, assessment, settings())

    assert "расходы превышают выручку на 50 000 ₽/мес." in result.summary.lower()
    assert "долговую нагрузку нельзя рассчитать" in result.summary.lower()
    assert "ии не может снять обязательное ограничение" in result.summary.lower()


def test_model_can_return_its_own_longer_natural_summary(monkeypatch):
    payload = json.loads(valid_content())
    payload["summary"] += " " + ("Сотрудник оценивает цель заявки и определяет следующий шаг. " * 9)
    assert len(payload["summary"]) > 500
    assert len(payload["summary"].split()) > 85
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(json.dumps(payload)))
    application, company, assessment = fixture_application()

    result = analyze_with_ollama(application, company, assessment, settings())

    assert result.used_safe_fallback is False
    assert len(result.summary) > 500
    assert len(result.recommendations[0].text) <= 500


def test_saved_analysis_response_accepts_longer_model_limits(monkeypatch):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(valid_content()))
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())
    payload = result.model_dump()
    payload["summary_fact_ids"] = [f"fact.{index}" for index in range(20)]
    payload["summary"] = "Пояснение. " * 100
    response = AIAnalysisResponse.model_validate(payload)
    assert len(response.summary_fact_ids) == 20
    assert len(response.summary) > 800


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
    assert "Заявку блокирует обязательная проверка" in result.summary
    assert "ИИ не может снять ограничение" in result.summary
    assert result.used_safe_fallback is True
    assert result.recommendations[0].action == "REVIEW_REQUIRED"
    assert "обязательную проверку" in result.recommendations[0].text


def test_debt_burden_block_is_shown_as_percentages(monkeypatch):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(valid_content()))
    result_data = {
        "score": 40, "risk_level": "HIGH", "recommendation": "REVIEW", "assessment_status": "COMPLETED",
        "hard_stops": ["DEBT_BURDEN: Долговая нагрузка 0.9520; лимит 0.7000"],
        "reasons": [], "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "PASS", "rules": []},
    }
    application, company, assessment = fixture_application(result_data)
    result = analyze_with_ollama(application, company, assessment, settings())
    assert "Долговая нагрузка — 95,2%" in result.summary
    assert "допустимый предел — 70%" in result.summary
    assert "0.9520" not in result.summary


def test_incomplete_assessment_requests_missing_information_without_claiming_hard_stop(monkeypatch):
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(valid_content()))
    assessment_result = {
        "score": None, "risk_level": "UNKNOWN", "recommendation": "REQUEST_INFO",
        "assessment_status": "INCOMPLETE", "hard_stops": [], "reasons": [],
        "missing_fields": ["average_monthly_revenue"],
        "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "UNKNOWN", "rules": []},
    }
    application, company, assessment = fixture_application(assessment_result)
    result = analyze_with_ollama(application, company, assessment, settings())

    assert result.is_blocked is True
    assert "запросите у клиента среднюю месячную выручку" in result.summary.lower()
    assert result.recommendations[0].action == "REQUEST_INFORMATION"
    assert result.data_warnings[0].text == "Не заполнено обязательное поле: средняя месячная выручка."
    assert result.blocking_reasons == ["Оценка неполная: нельзя завершить одобрение до получения недостающих данных."]


@pytest.mark.parametrize("low_risk", [True, False])
def test_unsafe_model_text_is_replaced_with_source_fact_summary(monkeypatch, low_risk):
    content = json.dumps({
        "summary": "Скоринг подтверждает одобрение, сумма составляет 3000000 рублей.",
        "summary_fact_ids": ["score.score", "score.recommendation"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Заявку можно одобрить.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    if not low_risk:
        assessment.result.update(risk_level="MEDIUM", recommendation="REVIEW")
    result = analyze_with_ollama(application, company, assessment, settings())
    if low_risk:
        assert result.used_safe_fallback is False
        assert result.summary == json.loads(content)["summary"]
        return
    assert result.used_safe_fallback is True
    assert "подтверждает одобрение" not in result.summary
    assert "3000000" not in result.summary
    assert "Скоринг рекомендует дополнительное рассмотрение" in result.summary
    assert "300 000 ₽" in result.summary and "82 из 100" in result.summary
    assert result.recommendations[0].action == "VERIFY_DATA"
    assert set(result.summary_fact_ids).issubset({fact.id for fact in result.evidence})


def test_model_generated_alternative_is_not_replaced_by_a_manual_template(monkeypatch):
    content = json.dumps({
        "summary": ("Заявка на 300000 ₽ на 12 месяцев для пополнения оборотных средств. Скоринг — 82 из 100, риск низкий; "
                    "можно отдельно пересчитать меньшую сумму. Передайте заявку сотруднику для решения."),
        "summary_fact_ids": ["app.amount", "app.term", "app.purpose", "score.score", "score.scale", "score.risk"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())

    assert result.used_safe_fallback is False
    assert "пересчитать меньшую сумму" in result.summary.lower()


def test_natural_product_question_passes_without_style_rewriting(monkeypatch):
    content = json.dumps({
        "summary": ("Заявка на 300000 ₽ на 12 месяцев для помощи бездомным, но выбран продукт «Оборудование» — "
                    "сотруднику стоит уточнить связь цели и продукта. Скоринг — 82 из 100, риск низкий; "
                    "обязательные проверки пройдены. Передайте заявку сотруднику для итогового решения."),
        "summary_fact_ids": ["app.amount", "app.term", "app.purpose", "app.product", "score.score", "score.risk",
                             "underwriting.status"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    captured = {}
    def fake_urlopen(request, timeout):
        captured["facts"] = json.loads(json.loads(request.data)["messages"][1]["content"])["facts"]
        return FakeResponse(content)
    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application()
    application.purpose = "Помощь бездомным"
    application.product_code = "equipment"
    result = analyze_with_ollama(application, company, assessment, settings())

    assert result.used_safe_fallback is False
    assert result.summary.startswith("Заявка на 300000 ₽")
    product_fact = next(fact for fact in captured["facts"] if fact["id"] == "app.product")
    assert product_fact["value"] == "Оборудование"


def test_debt_burden_rule_is_explained_as_below_or_above_its_limit():
    passed = _prompt_fact_value({"id": "underwriting.rule.2", "value":
                                "DEBT_BURDEN: PASS; Долговая нагрузка 0.6907; лимит 0.7000."})
    rejected = _prompt_fact_value({"id": "underwriting.rule.2", "value":
                                   "DEBT_BURDEN: REJECT; Долговая нагрузка 0.9520; лимит 0.7000."})

    assert passed == "Долговая нагрузка в пределах лимита продукта: 69,1%; допустимый предел — 70%."
    assert rejected == "Долговая нагрузка выше лимита продукта: 95,2%; допустимый предел — 70%."


def test_generated_explanation_is_not_replaced_by_phrase_level_checks(monkeypatch):
    content = json.dumps({
        "summary": ("Заявка на 300000 ₽ на 12 месяцев для оборотных средств. Скоринг — 82 из 100, риск низкий; "
                    "долговая нагрузка превышает допустимый лимит. Передайте заявку сотруднику."),
        "summary_fact_ids": ["app.amount", "app.term", "app.purpose", "score.score", "score.risk",
                             "score.factor.DEBT_BURDEN", "underwriting.status"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    result_data = {
        "score": 82, "risk_level": "LOW", "recommendation": "APPROVE", "assessment_status": "COMPLETED",
        "hard_stops": [], "reasons": [],
        "factors": [{"code": "DEBT_BURDEN", "points": 25, "max_points": 35,
                     "explanation": "Кредитные платежи относительно дохода после расходов."}],
        "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "PASS", "rules": [{"code": "DEBT_BURDEN", "outcome": "PASS",
            "reason": "Долговая нагрузка 0.40; лимит 0.70."}]},
    }
    application, company, assessment = fixture_application(result_data)
    result = analyze_with_ollama(application, company, assessment, settings())

    assert result.used_safe_fallback is False
    assert "превышает допустимый лимит" in result.summary.lower()


def test_low_score_fallback_explains_scoring_factors_and_safe_next_step(monkeypatch):
    content = json.dumps({
        "summary": "Заявку можно отклонить сразу.", "summary_fact_ids": ["score.score"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Отказать.", "fact_ids": ["score.score"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    result_data = {
        "score": 38, "risk_level": "HIGH", "recommendation": "DECLINE", "assessment_status": "COMPLETED",
        "hard_stops": [], "reasons": [{"code": "EXCESSIVE_DEBT_BURDEN", "explanation": "Долговая нагрузка превышает лимит."}],
        "factors": [{"code": "DEBT_BURDEN", "points": 0, "max_points": 20,
                     "explanation": "Большая часть месячной прибыли уходит на платежи."}],
        "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "PASS", "rules": []},
    }
    application, company, assessment = fixture_application(result_data)
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.used_safe_fallback is True
    assert "долговая нагрузка" in result.summary
    assert "пересч" not in result.summary.lower()
    assert "проверьте" not in result.summary.lower()
    assert "скоринговая рекомендация отрицательная" in result.summary.lower()
    assert len(result.summary.split()) <= 85
    assert result.recommendations[0].action == "VERIFY_DATA"
    assert "передайте заявку" in result.recommendations[0].text.lower()
    evidence = {fact.id for fact in result.evidence}
    assert set(result.summary_fact_ids).issubset(evidence)
    assert set(result.recommendations[0].fact_ids).issubset(evidence)


def test_model_summary_is_kept_without_requiring_a_score_recap(monkeypatch):
    content = json.dumps({
        "summary": "Операционная маржа получила неполный вклад в оценку.",
        "summary_fact_ids": ["score.factor.OPERATING_MARGIN"],
        "recommendations": [{"action": "VERIFY_DATA", "text": "Запросите доход.",
                             "fact_ids": ["score.factor.OPERATING_MARGIN"]}],
        "data_warnings": [],
    })
    captured = {}
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return FakeResponse(content)
    monkeypatch.setattr("app.ai_analysis.urlopen", fake_urlopen)
    application, company, assessment = fixture_application({
        "score": 73, "risk_level": "MEDIUM", "recommendation": "REVIEW", "assessment_status": "COMPLETED",
        "hard_stops": [], "reasons": [],
        "factors": [
            {"code": "BUSINESS_AGE", "points": 20, "max_points": 20, "explanation": "Полные месяцы работы"},
            {"code": "OPERATING_MARGIN", "points": 8, "max_points": 25,
             "explanation": "Доля выручки после операционных расходов; при нулевой выручке показатель не определён."},
            {"code": "DEBT_BURDEN", "points": 25, "max_points": 35,
             "explanation": "Кредитные платежи относительно дохода после расходов."},
            {"code": "PAYMENT_HISTORY", "points": 20, "max_points": 20, "explanation": "Текущие просрочки"},
        ],
        "check_reports": {"bki": {"status": "AVAILABLE"}, "compliance": {"status": "CLEAR"}},
        "underwriting": {"status": "PASS", "rules": []},
    })
    assessment.input_snapshot["input_data"].update({
        "average_monthly_revenue": "2350000", "average_monthly_operating_expenses": "2200000",
        "existing_monthly_debt_payment": "0",
    })
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.used_safe_fallback is False
    assert result.summary == "Операционная маржа получила неполный вклад в оценку."
    model_facts = json.loads(captured["body"]["messages"][1]["content"])["facts"]
    margin = next(fact["value"] for fact in model_facts if fact["id"] == "score.factor.OPERATING_MARGIN")
    assert "нулевой выручке" not in margin
    assert set(result.summary_fact_ids).issubset({fact.id for fact in result.evidence})


def test_general_claim_that_checks_passed_uses_authoritative_underwriting_result(monkeypatch):
    content = json.dumps({
        "summary": ("Заявка на 300000 ₽ на 12 месяцев для оборотных средств. Скоринг — 82 из 100, риск низкий; "
                    "все обязательные проверки и правила выполнены. Передайте заявку сотруднику для итогового решения."),
        "summary_fact_ids": ["app.amount", "app.term", "app.purpose", "score.score", "score.scale", "score.risk",
                             "underwriting.status"],
        "recommendations": [{"action": "CONTINUE_REVIEW", "text": "Продолжить рассмотрение человеком.",
                             "fact_ids": ["score.recommendation"]}],
        "data_warnings": [],
    })
    monkeypatch.setattr("app.ai_analysis.urlopen", lambda *_args, **_kwargs: FakeResponse(content))
    application, company, assessment = fixture_application()
    result = analyze_with_ollama(application, company, assessment, settings())
    assert result.used_safe_fallback is False
    assert "проверки и правила выполнены" in result.summary.lower()
