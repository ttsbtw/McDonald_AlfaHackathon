from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm.exc import StaleDataError

from .auth import DB, Client, CurrentUser, create_token, dummy_hash, password_hash
from .errors import APIError
from .models import Application, Company, CreditProduct, User, utc_now
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
