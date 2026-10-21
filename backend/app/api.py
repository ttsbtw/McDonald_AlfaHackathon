from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm.exc import StaleDataError

from .auth import DB, Client, CurrentUser, create_token, dummy_hash, password_hash
from .errors import APIError
from .models import Application, Assessment, Company, CreditProduct, User, utc_now
from .scoring import assess_application
from .scoring.contracts import PolicyValidationError
from .schemas import (
    CompanyOut,
    DraftCreate,
    DraftOut,
    DraftPage,
    DraftUpdate,
    ErrorResponse,
    ProductOut,
    TokenOut,
    UserOut,
)

router = APIRouter(prefix="/api/v1", responses={
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)
})


@router.post("/auth/login", response_model=TokenOut, tags=["Авторизация"])
def login(request: Request, response: Response, db: DB,
          form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    if len(form.username) > 100 or len(form.password) > 128:
        raise APIError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.")
    user = db.scalar(select(User).where(User.username == form.username))
    valid = password_hash.verify(form.password, user.password_hash if user else dummy_hash)
    if not user or not valid or not user.is_active:
        raise APIError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.",
                       headers={"WWW-Authenticate": "Bearer"})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return create_token(user, request.app.state.settings)


@router.get("/auth/me", response_model=UserOut, tags=["Авторизация"])
def me(user: CurrentUser):
    return user


def own_company(db, user):
    company = db.scalar(select(Company).where(Company.owner_id == user.id))
    if company is None:
        raise APIError(409, "COMPANY_REQUIRED", "Для клиента не подготовлены сведения о компании.")
    return company


@router.get("/company", response_model=CompanyOut, tags=["Компания"])
def company(db: DB, user: Client):
    return own_company(db, user)


@router.get("/products", response_model=list[ProductOut], tags=["Продукты"])
def products(db: DB, user: CurrentUser):
    return db.scalars(select(CreditProduct).where(CreditProduct.is_active.is_(True))
                      .order_by(CreditProduct.code)).all()


@router.get("/products/{code}", response_model=ProductOut, tags=["Продукты"])
def product(code: str, db: DB, user: CurrentUser):
    item = db.get(CreditProduct, code)
    if item is None or not item.is_active:
        raise APIError(404, "PRODUCT_NOT_FOUND", "Продукт не найден.")
    return item


def validate_product(db, code):
    if code is not None:
        item = db.get(CreditProduct, code)
        if item is None or not item.is_active:
            raise APIError(422, "INVALID_PRODUCT", "Выбранный продукт недоступен.", fields=[{
                "field": "product_code", "code": "UNAVAILABLE", "message": "Выберите доступный продукт.",
            }])


def own_application(db, user, application_id):
    item = db.scalar(select(Application).where(Application.id == application_id,
                                               Application.owner_id == user.id))
    if item is None:
        # The same response for unknown and other clients' IDs.
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    return item


@router.post("/applications", response_model=DraftOut, status_code=201, tags=["Черновики"])
def create_draft(payload: DraftCreate, db: DB, user: Client, response: Response):
    company = own_company(db, user)
    validate_product(db, payload.product_code)
    item = Application(owner_id=user.id, company_id=company.id, **payload.model_dump())
    db.add(item)
    db.commit()
    response.headers["Location"] = f"/api/v1/applications/{item.id}"
    return item


@router.get("/applications", response_model=DraftPage, tags=["Черновики"])
def list_drafts(db: DB, user: Client,
                limit: Annotated[int, Query(ge=1, le=100)] = 20,
                offset: Annotated[int, Query(ge=0)] = 0):
    query = select(Application).where(Application.owner_id == user.id)
    items = db.scalars(query.order_by(Application.created_at.desc(), Application.id)
                       .limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count()).select_from(Application).where(Application.owner_id == user.id))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/applications/{application_id}", response_model=DraftOut, tags=["Черновики"])
def get_draft(application_id: UUID, db: DB, user: Client):
    return own_application(db, user, application_id)


@router.patch("/applications/{application_id}", response_model=DraftOut, tags=["Черновики"])
def update_draft(application_id: UUID, payload: DraftUpdate, db: DB, user: Client):
    item = own_application(db, user, application_id)
    if item.status not in ("DRAFT", "NEEDS_INFO"):
        raise APIError(409, "APPLICATION_NOT_EDITABLE", "Заявка уже передана на рассмотрение.")
    if item.revision != payload.revision:
        raise APIError(409, "REVISION_CONFLICT", "Заявка изменена. Загрузите актуальную версию.")
    changes = payload.model_dump(exclude_unset=True, exclude={"revision"})
    if "product_code" in changes:
        validate_product(db, changes["product_code"])
    for field, value in changes.items():
        setattr(item, field, value)
    if changes:
        item.updated_at = utc_now()
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "REVISION_CONFLICT", "Заявка изменена. Загрузите актуальную версию.") from None
    return item


@router.post("/applications/{application_id}/submit", response_model=DraftOut, tags=["Заявки"])
def submit_application(application_id: UUID, db: DB, user: Client):
    item = own_application(db, user, application_id)
    if item.status == "UNDER_REVIEW":
        # Retrying a successful submit is safe and does not create another assessment.
        return item
    if item.status not in ("DRAFT", "NEEDS_INFO"):
        raise APIError(409, "APPLICATION_NOT_SUBMITTABLE", "Заявку нельзя отправить из текущего состояния.")

    required = (
        "product_code", "requested_amount", "term_months", "purpose",
        "average_monthly_revenue", "average_monthly_operating_expenses",
        "existing_monthly_debt_payment",
    )
    missing = [{"field": field, "code": "REQUIRED", "message": "Заполните обязательное поле."}
               for field in required if getattr(item, field) is None]
    if missing:
        raise APIError(422, "APPLICATION_INCOMPLETE", "Заполните обязательные поля перед отправкой.", fields=missing)

    product = db.get(CreditProduct, item.product_code)
    company = db.get(Company, item.company_id)
    if product is None or not product.is_active or company is None:
        raise APIError(409, "APPLICATION_DATA_UNAVAILABLE", "Не удалось получить данные продукта или компании.")

    # Local deterministic simulators: the demo company registry confirms the
    # stored synthetic company, and credit-history fixtures have no delinquencies.
    checks = [
        {"source": "company_registry", "status": "PASS", "reason_code": "SYNTHETIC_COMPANY_MATCH"},
        {"source": "credit_history", "status": "PASS", "reason_code": "NO_DEMO_DELINQUENCIES"},
    ]
    as_of_date = utc_now().date()
    input_data = {
        "schema_version": "1.0", "application_id": str(item.id),
        "application_revision": item.revision, "as_of_date": as_of_date.isoformat(),
        "product_code": item.product_code, "requested_amount": item.requested_amount,
        "term_months": item.term_months, "purpose": item.purpose,
        "legal_form": company.legal_form, "registration_date": company.registration_date.isoformat(),
        "average_monthly_revenue": item.average_monthly_revenue,
        "average_monthly_operating_expenses": item.average_monthly_operating_expenses,
        "existing_monthly_debt_payment": item.existing_monthly_debt_payment,
        "current_overdue_amount": "0.00", "max_overdue_days_12m": 0,
    }
    try:
        result = assess_application(input_data, product.scoring_policy, checks)
    except PolicyValidationError:
        raise APIError(503, "SCORING_POLICY_INVALID", "Правила оценки продукта временно недоступны.") from None

    assessment = Assessment(
        application_id=item.id, application_revision=item.revision,
        input_snapshot=result["input_snapshot"] or {"input_data": input_data, "checks": checks},
        result=result,
    )
    db.add(assessment)
    item.status = "UNDER_REVIEW"
    item.updated_at = utc_now()
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "REVISION_CONFLICT", "Заявка изменилась. Загрузите актуальную версию.") from None
    return item
