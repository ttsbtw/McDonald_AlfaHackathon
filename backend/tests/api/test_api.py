import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import BACKEND, EMPLOYEE_PASSWORD, SECOND_PASSWORD, SECRET, auth_headers, migration_config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.db import Base
from app.main import create_app
from app.models import Application, Company, CreditProduct, User
from app.seed import seed_demo

pytestmark = pytest.mark.postgres


def create(client, headers, payload=None):
    response = client.post("/api/v1/applications", json=payload or {}, headers=headers)
    assert response.status_code == 201, response.text
    assert response.headers["location"].endswith(response.json()["id"])
    return response.json()


def test_login_and_identity(client, headers):
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == "CLIENT"
    assert "password_hash" not in response.json()
    company = client.get("/api/v1/company", headers=headers).json()
    assert company["name"] == "Демо-компания 1"
    assert "owner_id" not in company


@pytest.mark.parametrize("username,password", [("client1", "bad"), ("absent", "bad")])
def test_bad_credentials(client, username, password):
    response = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.parametrize("path", ["/auth/me", "/products", "/company", "/applications"])
def test_auth_required(client, path):
    response = client.get("/api/v1" + path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("kind", ["expired", "bad_signature", "wrong_audience", "bad_subject", "missing_exp", "none_algorithm"])
def test_invalid_tokens(client, kind):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(UUID(int=1)), "iat": now, "exp": now + timedelta(minutes=10),
               "iss": "mcdonald-backend", "aud": "credit-cabinet"}
    secret = SECRET
    if kind == "expired":
        payload["exp"] = now - timedelta(minutes=1)
    elif kind == "bad_signature":
        secret = "another-secret-with-more-than-32-characters"
    elif kind == "wrong_audience":
        payload["aud"] = "other-app"
    elif kind == "bad_subject":
        payload["sub"] = "not-a-uuid"
    elif kind == "missing_exp":
        del payload["exp"]
    token = jwt.encode(payload, key=None if kind == "none_algorithm" else secret,
                       algorithm="none" if kind == "none_algorithm" else "HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_inactive_user_rejected_immediately(client, application, headers):
    with application.state.session_factory() as session:
        session.get(User, UUID(int=1)).is_active = False
        session.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    response = client.post("/api/v1/auth/login", data={"username": "client1", "password": "Client-one-test-password!"})
    assert response.status_code == 401


def test_roles_come_from_database(client, application, headers):
    with application.state.session_factory() as session:
        session.get(User, UUID(int=1)).role = "BANK_EMPLOYEE"
        session.commit()
    assert client.post("/api/v1/applications", json={}, headers=headers).status_code == 403


def test_employee_cannot_use_client_routes(client):
    headers = auth_headers(client, "employee", EMPLOYEE_PASSWORD)
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "BANK_EMPLOYEE"
    assert client.get("/api/v1/products", headers=headers).status_code == 200
    assert client.get("/api/v1/company", headers=headers).status_code == 403
    assert client.get("/api/v1/applications", headers=headers).status_code == 403
    assert client.post("/api/v1/applications", json={}, headers=headers).status_code == 403


def test_products_and_inactive_product(client, application, headers):
    products = client.get("/api/v1/products", headers=headers).json()
    assert len(products) == 2
    assert products[0]["annual_interest_rate"] == "24.00"
    assert products[0]["source_url"].startswith("https://alfabank.ru/")
    assert "scoring_policy" not in products[0]
    with application.state.session_factory() as session:
        session.get(CreditProduct, "equipment").is_active = False
        session.commit()
    assert len(client.get("/api/v1/products", headers=headers).json()) == 1
    assert client.get("/api/v1/products/equipment", headers=headers).status_code == 404
    assert client.post("/api/v1/applications", json={"product_code": "equipment"}, headers=headers).status_code == 422


def test_empty_and_partial_draft(client, headers):
    draft = create(client, headers)
    assert draft["status"] == "DRAFT" and draft["revision"] == 1
    assert draft["requested_amount"] is None
    assert draft["created_at"].endswith("Z") or draft["created_at"].endswith("+00:00")
    assert client.get(f"/api/v1/applications/{draft['id']}", headers=headers).json() == draft
    result = client.patch(f"/api/v1/applications/{draft['id']}", headers=headers,
                          json={"revision": 1, "requested_amount": "300000.01", "term_months": 12})
    assert result.status_code == 200
    updated = result.json()
    assert updated["requested_amount"] == "300000.01"
    assert updated["term_months"] == 12
    assert updated["revision"] == 2
    assert updated["purpose"] is None


def test_explicit_null_clears_field_but_omitted_field_is_preserved(client, headers):
    draft = create(client, headers, {"purpose": "Оборудование", "requested_amount": "300000.00"})
    response = client.patch(f"/api/v1/applications/{draft['id']}", headers=headers,
                            json={"revision": 1, "purpose": None})
    assert response.status_code == 200
    assert response.json()["purpose"] is None
    assert response.json()["requested_amount"] == "300000.00"


def test_owner_isolation_get_patch_and_list(client, headers):
    draft = create(client, headers, {"purpose": "Личная заявка первого клиента"})
    other = auth_headers(client, "client2", SECOND_PASSWORD)
    for path in (draft["id"], str(uuid4())):
        assert client.get(f"/api/v1/applications/{path}", headers=other).status_code == 404
        assert client.patch(f"/api/v1/applications/{path}", headers=other,
                            json={"revision": 1, "purpose": "Чужое изменение"}).status_code == 404
    assert client.get("/api/v1/applications", headers=other).json()["total"] == 0
    assert client.get("/api/v1/applications", headers=headers).json()["total"] == 1
    assert client.get(f"/api/v1/applications/{draft['id']}", headers=headers).json() == draft


@pytest.mark.parametrize("field,value", [("owner_id", str(UUID(int=2))), ("company_id", str(UUID(int=102))),
                                       ("status", "APPROVED"), ("score", 100), ("role", "BANK_EMPLOYEE"),
                                       ("current_overdue_amount", "0.00"), ("scoring_policy", {})])
def test_protected_fields_cannot_be_injected(client, headers, field, value):
    response = client.post("/api/v1/applications", headers=headers, json={field: value})
    assert response.status_code == 422
    draft = create(client, headers)
    assert client.patch(f"/api/v1/applications/{draft['id']}", headers=headers,
                        json={"revision": 1, field: value}).status_code == 422


@pytest.mark.parametrize("payload", [
    {"requested_amount": 300000.0}, {"requested_amount": "NaN"}, {"requested_amount": "-1"},
    {"requested_amount": "0"}, {"requested_amount": "1.001"}, {"requested_amount": True},
    {"average_monthly_revenue": "1000000000000.01"}, {"existing_monthly_debt_payment": -1},
    {"term_months": True}, {"term_months": 0}, {"term_months": "12"}, {"term_months": 361},
    {"purpose": " "}, {"product_code": "missing-product"},
])
def test_invalid_draft_data(client, headers, payload):
    response = client.post("/api/v1/applications", headers=headers, json=payload)
    assert response.status_code == 422
    assert "error" in response.json()


def test_stale_patch_and_missing_revision(client, headers):
    draft = create(client, headers)
    url = f"/api/v1/applications/{draft['id']}"
    assert client.patch(url, headers=headers, json={"purpose": "нет версии"}).status_code == 422
    assert client.patch(url, headers=headers, json={"revision": 1, "purpose": "первое изменение"}).status_code == 200
    response = client.patch(url, headers=headers, json={"revision": 1, "purpose": "устаревшее изменение"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"
    assert client.get(url, headers=headers).json()["purpose"] == "первое изменение"


def test_non_draft_is_not_editable(client, application, headers):
    draft = create(client, headers)
    with application.state.session_factory() as session:
        record = session.get(Application, UUID(draft["id"]))
        record.status = "UNDER_REVIEW"
        session.commit()
        revision = record.revision
    response = client.patch(f"/api/v1/applications/{draft['id']}", headers=headers,
                            json={"revision": revision, "purpose": "изменение"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPLICATION_NOT_EDITABLE"


def test_pagination_is_scoped_and_bounded(client, headers):
    for _ in range(3):
        create(client, headers)
    response = client.get("/api/v1/applications?limit=2&offset=1", headers=headers)
    assert response.json()["total"] == 3
    assert len(response.json()["items"]) == 2
    assert client.get("/api/v1/applications?limit=101", headers=headers).status_code == 422


def test_database_detects_concurrent_writes(client, application, headers):
    draft = create(client, headers)
    with application.state.session_factory() as first, application.state.session_factory() as second:
        item1 = first.get(Application, UUID(draft["id"]))
        item2 = second.get(Application, UUID(draft["id"]))
        item1.purpose = "первый"
        first.commit()
        item2.purpose = "второй"
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()


def test_company_owner_constraint(application):
    with application.state.session_factory() as session:
        session.add(Application(owner_id=UUID(int=1), company_id=UUID(int=102)))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_seed_preserves_existing_drafts_passwords_and_products(client, application, settings, headers):
    draft = create(client, headers, {"purpose": "Не терять"})
    with application.state.session_factory() as session:
        before_hash = session.get(User, UUID(int=1)).password_hash
        session.get(CreditProduct, "equipment").description = "Обновлено вручную"
        session.commit()
        seed_demo(session, settings)
        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Company)) == 2
        assert session.scalar(select(func.count()).select_from(CreditProduct)) == 2
        assert session.get(User, UUID(int=1)).password_hash == before_hash
        assert session.get(CreditProduct, "equipment").description == "Обновлено вручную"
    assert client.get(f"/api/v1/applications/{draft['id']}", headers=headers).json()["purpose"] == "Не терять"


def test_persistence_after_application_restart(client, application, settings, headers):
    draft = create(client, headers, {"requested_amount": "350000.45", "purpose": "После перезапуска"})
    application.state.engine.dispose()
    restarted = create_app(settings)
    with TestClient(restarted) as new_client:
        new_headers = auth_headers(new_client)
        response = new_client.get(f"/api/v1/applications/{draft['id']}", headers=new_headers)
        assert response.status_code == 200
        assert response.json() == draft


def test_health_readiness_and_swagger(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/v1/applications/{application_id}" in spec["paths"]
    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
    assert spec == json.loads((BACKEND / "docs" / "openapi.json").read_text(encoding="utf-8"))


def test_ready_fails_without_migration(client, application):
    with application.state.engine.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


def test_migration_matches_models_and_roundtrip(database_url):
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    config = migration_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004_review_actions"
    engine.dispose()


@pytest.mark.parametrize("product_code", ["working_capital", "equipment"])
def test_submit_persists_explained_assessment_for_selected_product(client, application, headers, product_code):
    draft = create(client, headers, {
        "product_code": product_code, "requested_amount": "300000.00", "term_months": 12,
        "purpose": "Закупка", "average_monthly_revenue": "1000000.00",
        "average_monthly_operating_expenses": "600000.00", "existing_monthly_debt_payment": "50000.00",
    })

    submitted = client.post(f"/api/v1/applications/{draft['id']}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "UNDER_REVIEW"

    employee_headers = auth_headers(client, "employee", EMPLOYEE_PASSWORD)
    queue = client.get("/api/v1/bank/applications?status=UNDER_REVIEW", headers=employee_headers)
    assert queue.status_code == 200
    row = next(item for item in queue.json()["items"] if item["id"] == draft["id"])
    assert row["product"]["code"] == product_code
    assert row["score"] == 100
    assert row["recommendation"] == "APPROVE"

    assessments = client.get(f"/api/v1/bank/applications/{draft['id']}/assessments", headers=employee_headers)
    assert assessments.status_code == 200
    assert len(assessments.json()) == 1
    assessment = assessments.json()[0]
    assert assessment["application_revision"] == draft["revision"]
    assert assessment["result"]["application_id"] == draft["id"]
    assert assessment["result"]["application_revision"] == draft["revision"]
    assert assessment["result"]["policy_version"] == row["product"]["policy_version"]
    assert assessment["result"]["recommendation"] == "APPROVE"
    assert assessment["result"]["hard_stops"] == []
    assert assessment["input_snapshot"]["input_data"]["product_code"] == product_code
    assert [item["source"] for item in assessment["input_snapshot"]["checks"]] == [
        "company_registry", "credit_history",
    ]

    # A retry after a successful submit must not create a second assessment.
    retried = client.post(f"/api/v1/applications/{draft['id']}/submit", headers=headers)
    assert retried.status_code == 200
    assert client.get(f"/api/v1/bank/applications/{draft['id']}/assessments",
                      headers=employee_headers).json() == assessments.json()


@pytest.mark.parametrize(("expenses", "existing_debt", "expected_score", "recommendation"), [
    ("600000.00", "50000.00", 100, "APPROVE"),
    ("900000.00", "12000.00", 73, "REVIEW"),
    ("900000.00", "100000.00", 48, "DECLINE"),
])
def test_submit_expected_approval_review_and_decline_outcomes(
    client, headers, expenses, existing_debt, expected_score, recommendation,
):
    draft = create(client, headers, {
        "product_code": "working_capital", "requested_amount": "300000.00", "term_months": 12,
        "purpose": "Пополнение оборотных средств", "average_monthly_revenue": "1000000.00",
        "average_monthly_operating_expenses": expenses, "existing_monthly_debt_payment": existing_debt,
    })
    submitted = client.post(f"/api/v1/applications/{draft['id']}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text

    employee_headers = auth_headers(client, "employee", EMPLOYEE_PASSWORD)
    assessments = client.get(f"/api/v1/bank/applications/{draft['id']}/assessments", headers=employee_headers)
    result = assessments.json()[0]["result"]
    assert result["score"] == expected_score
    assert result["recommendation"] == recommendation
    if recommendation == "APPROVE":
        assert "SCORE_SUFFICIENT" in result["reason_codes"]
    elif recommendation == "REVIEW":
        assert "MANUAL_REVIEW" in result["reason_codes"]
    else:
        assert "EXCESSIVE_DEBT_BURDEN" in result["hard_stops"]


def test_employee_can_request_information_and_client_resubmits_new_assessment(client, headers):
    draft = create(client, headers, {
        "product_code": "working_capital", "requested_amount": "300000.00", "term_months": 12,
        "purpose": "Пополнение оборотных средств", "average_monthly_revenue": "1000000.00",
        "average_monthly_operating_expenses": "900000.00", "existing_monthly_debt_payment": "12000.00",
    })
    submitted = client.post(f"/api/v1/applications/{draft['id']}/submit", headers=headers)
    assert submitted.status_code == 200

    employee_headers = auth_headers(client, "employee", EMPLOYEE_PASSWORD)
    bank_card = client.get(f"/api/v1/bank/applications/{draft['id']}", headers=employee_headers).json()
    assert bank_card["recommendation"] == "REVIEW"
    requested = client.post(f"/api/v1/bank/applications/{draft['id']}/request-info", headers=employee_headers,
                            json={"comment": "Уточните среднемесячные расходы и сумму текущих кредитных платежей."})
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "NEEDS_INFO"

    updated = client.patch(f"/api/v1/applications/{draft['id']}", headers=headers, json={
        "revision": requested.json()["revision"],
        "average_monthly_operating_expenses": "600000.00",
        "existing_monthly_debt_payment": "50000.00",
    })
    assert updated.status_code == 200, updated.text
    resubmitted = client.post(f"/api/v1/applications/{draft['id']}/submit", headers=headers)
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "UNDER_REVIEW"

    assessments = client.get(f"/api/v1/bank/applications/{draft['id']}/assessments", headers=employee_headers)
    assert [item["application_revision"] for item in assessments.json()] == [updated.json()["revision"], draft["revision"]]
    assert assessments.json()[0]["result"]["score"] == 100
    assert assessments.json()[0]["result"]["recommendation"] == "APPROVE"
