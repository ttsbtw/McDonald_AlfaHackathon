import csv
import io
import json
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .alternatives import generate_alternatives
from .auth import DB, BankEmployee, Client, CurrentUser, create_token, dummy_hash, password_hash
from .errors import APIError
from .models import (
    AlternativeOffer,
    Application,
    ApplicationEvent,
    Assessment,
    AuditLog,
    Company,
    ComplianceReview,
    CreditProduct,
    ReviewAction,
    User,
    utc_now,
)
from .pipeline.processing import ProcessingPipeline
from .schemas import (
    AlternativeCandidateOut,
    AlternativeDecisionIn,
    AlternativeSetOut,
    ApplicationEventOut,
    AssessmentOut,
    BankApplicationOut,
    BankApplicationPage,
    ClientAlternativeOfferOut,
    CompanyOut,
    ComplianceReviewIn,
    DecisionIn,
    DraftCreate,
    DraftOut,
    DraftPage,
    DraftUpdate,
    ErrorResponse,
    ProductOut,
    RequestInfoIn,
    SubmitIn,
    TokenOut,
    UserOut,
)
from .scoring.contracts import PolicyValidationError, to_json_value

router = APIRouter(prefix="/api/v1", responses={
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)
})

processing_pipeline = ProcessingPipeline()


def add_audit(db, item, company, actor_id, event_type, source, payload):
    db.add(AuditLog(
        application_id=item.id, client_identifier=company.inn, actor_id=actor_id,
        event_type=event_type, source=source, payload=to_json_value(payload),
    ))


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


def approved_actions_by_application(db, items):
    application_ids = [item.id for item in items]
    if not application_ids:
        return {}
    actions = db.scalars(
        select(ReviewAction)
        .where(ReviewAction.application_id.in_(application_ids), ReviewAction.action == "APPROVED")
        .order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
    ).all()
    latest = {}
    for action in actions:
        latest.setdefault(action.application_id, action)
    return latest


def approved_alternative_risks_by_application(db, items):
    application_ids = [item.id for item in items]
    if not application_ids:
        return {}
    offers = db.scalars(
        select(AlternativeOffer)
        .where(AlternativeOffer.application_id.in_(application_ids), AlternativeOffer.status == "ACCEPTED")
        .order_by(AlternativeOffer.decided_at.desc(), AlternativeOffer.id.desc())
    ).all()
    latest = {}
    for offer in offers:
        scoring = (offer.evaluation or {}).get("scoring", {})
        risk_level = scoring.get("risk_level")
        if risk_level in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            latest.setdefault(offer.application_id, risk_level)
    return latest


def client_application_out(item, approved_action=None, has_pending_alternative_offer=False):
    payload = DraftOut.model_validate(item).model_dump()
    payload["has_pending_alternative_offer"] = has_pending_alternative_offer
    if approved_action is not None:
        payload.update(
            approved_amount=approved_action.approved_amount,
            approved_term_months=approved_action.approved_term_months,
            approved_annual_interest_rate=approved_action.annual_interest_rate,
        )
    return DraftOut(**payload)


@router.post("/applications", response_model=DraftOut, status_code=201, tags=["Черновики"])
def create_draft(payload: DraftCreate, db: DB, user: Client, response: Response):
    company = own_company(db, user)
    validate_product(db, payload.product_code)
    item = Application(owner_id=user.id, company_id=company.id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(ApplicationEvent(
        application_id=item.id, actor_id=user.id, application_revision=item.revision,
        event_type="DRAFT_CREATED", from_status=None, to_status="DRAFT",
    ))
    add_audit(db, item, company, user.id, "APPLICATION_CREATED", "applications",
              {"revision": item.revision, "status": item.status})
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
    approved_actions = approved_actions_by_application(db, items)
    application_ids = [item.id for item in items]
    latest_assessment_id = (
        select(Assessment.id)
        .where(Assessment.application_id == AlternativeOffer.application_id)
        .order_by(Assessment.application_revision.desc())
        .limit(1)
        .correlate(AlternativeOffer)
        .scalar_subquery()
    )
    pending_offer_ids = set(db.scalars(
        select(AlternativeOffer.application_id).where(
            AlternativeOffer.application_id.in_(application_ids),
            AlternativeOffer.status == "OFFERED",
            AlternativeOffer.assessment_id == latest_assessment_id,
        )
    ).all()) if application_ids else set()
    total = db.scalar(select(func.count()).select_from(Application).where(Application.owner_id == user.id))
    return {
        "items": [
            client_application_out(item, approved_actions.get(item.id), item.id in pending_offer_ids)
            for item in items
        ],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/applications/{application_id}", response_model=DraftOut, tags=["Черновики"])
def get_draft(application_id: UUID, db: DB, user: Client):
    item = own_application(db, user, application_id)
    approved_action = approved_actions_by_application(db, [item]).get(item.id)
    return client_application_out(item, approved_action)


@router.delete("/applications/{application_id}", status_code=204, response_class=Response, tags=["Черновики"])
def delete_draft(application_id: UUID, db: DB, user: Client):
    item = own_application(db, user, application_id)
    if item.status != "DRAFT":
        raise APIError(409, "APPLICATION_NOT_DELETABLE", "Удалить можно только черновик со статусом DRAFT.")
    db.delete(item)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "REVISION_CONFLICT", "Черновик изменён. Обновите список заявок.") from None
    return Response(status_code=204)


@router.get("/applications/{application_id}/events", response_model=list[ApplicationEventOut], tags=["Заявки"])
def application_events(application_id: UUID, db: DB, user: Client):
    own_application(db, user, application_id)
    return db.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.created_at, ApplicationEvent.id)
    ).all()


def bank_application_query():
    latest_revision = (
        select(func.max(Assessment.application_revision))
        .where(Assessment.application_id == Application.id)
        .correlate(Application)
        .scalar_subquery()
    )
    return (
        select(Application, Company, User, CreditProduct, Assessment)
        .join(Company, Company.id == Application.company_id)
        .join(User, User.id == Application.owner_id)
        .outerjoin(CreditProduct, CreditProduct.code == Application.product_code)
        .outerjoin(Assessment, and_(
            Assessment.application_id == Application.id,
            Assessment.application_revision == latest_revision,
        ))
    )


def bank_application_out(row, approved_action=None, approved_risk_level=None):
    item, company, client, product, assessment = row
    result = assessment.result if assessment else {}
    payload = DraftOut.model_validate(item).model_dump()
    if approved_action is not None:
        payload.update(
            approved_amount=approved_action.approved_amount,
            approved_term_months=approved_action.approved_term_months,
            approved_annual_interest_rate=approved_action.annual_interest_rate,
        )
    return BankApplicationOut(
        **payload,
        client=client,
        company=company,
        product=product,
        risk_level=result.get("risk_level"),
        approved_risk_level=approved_risk_level,
        score=result.get("score"),
        recommendation=result.get("recommendation"),
        preliminary_decision=result.get("preliminary_decision"),
    )


def latest_submission_times(db, application_ids):
    if not application_ids:
        return {}
    events = db.scalars(
        select(ApplicationEvent)
        .where(
            ApplicationEvent.application_id.in_(application_ids),
            ApplicationEvent.event_type.in_(("SUBMITTED", "RESUBMITTED")),
        )
        .order_by(ApplicationEvent.created_at.desc(), ApplicationEvent.id.desc())
    ).all()
    latest = {}
    for event in events:
        latest.setdefault(event.application_id, event.created_at)
    return latest


@router.get("/bank/applications", response_model=BankApplicationPage, tags=["Рабочее место сотрудника"])
def bank_applications(
    db: DB,
    user: BankEmployee,
    status: Annotated[Literal["SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = [Application.status != "DRAFT"]
    if status is not None:
        filters.append(Application.status == status)
    items = db.execute(
        bank_application_query().where(*filters)
        .order_by(Application.created_at, Application.id)
        .limit(limit).offset(offset)
    ).all()
    approved_actions = approved_actions_by_application(db, [row[0] for row in items])
    approved_risks = approved_alternative_risks_by_application(db, [row[0] for row in items])
    total = db.scalar(select(func.count()).select_from(Application).where(*filters))
    return {
        "items": [bank_application_out(row, approved_actions.get(row[0].id), approved_risks.get(row[0].id))
                  for row in items],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/bank/companies/{company_id}/history", response_model=BankApplicationPage,
            tags=["Рабочее место сотрудника"])
def bank_company_history(
    company_id: UUID,
    db: DB,
    user: BankEmployee,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if db.get(Company, company_id) is None:
        raise APIError(404, "COMPANY_NOT_FOUND", "Компания не найдена.")
    filters = [Application.company_id == company_id, Application.status != "DRAFT"]
    items = db.execute(
        bank_application_query().where(*filters)
        .order_by(Application.created_at.desc(), Application.id.desc())
        .limit(limit).offset(offset)
    ).all()
    applications = [row[0] for row in items]
    approved_actions = approved_actions_by_application(db, applications)
    approved_risks = approved_alternative_risks_by_application(db, applications)
    submitted_at = latest_submission_times(db, [item.id for item in applications])
    total = db.scalar(select(func.count()).select_from(Application).where(*filters))
    return {
        "items": [
            history_item(row, approved_actions, approved_risks, submitted_at)
            for row in items
        ],
        "total": total, "limit": limit, "offset": offset,
    }


def history_item(row, approved_actions, approved_risks, submitted_at):
    item = row[0]
    payload = bank_application_out(
        row, approved_actions.get(item.id), approved_risks.get(item.id),
    ).model_dump()
    payload["submitted_at"] = submitted_at.get(item.id)
    return BankApplicationOut(**payload)


@router.get("/bank/applications/{application_id}", response_model=BankApplicationOut, tags=["Рабочее место сотрудника"])
def bank_application(application_id: UUID, db: DB, user: BankEmployee):
    row = db.execute(bank_application_query().where(
        Application.id == application_id, Application.status != "DRAFT",
    )).one_or_none()
    if row is None:
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    approved_action = approved_actions_by_application(db, [row[0]]).get(row[0].id)
    approved_risk = approved_alternative_risks_by_application(db, [row[0]]).get(row[0].id)
    return bank_application_out(row, approved_action, approved_risk)


@router.get("/bank/applications/{application_id}/assessments", response_model=list[AssessmentOut], tags=["Рабочее место сотрудника"])
def bank_assessments(application_id: UUID, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None or item.status == "DRAFT":
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    return db.scalars(
        select(Assessment)
        .where(Assessment.application_id == application_id)
        .order_by(Assessment.application_revision.desc())
    ).all()


@router.get("/bank/applications/{application_id}/audit", tags=["Рабочее место сотрудника"])
def bank_audit_export(application_id: UUID, db: DB, user: BankEmployee,
                      format: Literal["json", "csv"] = "json"):
    item = db.get(Application, application_id)
    if item is None or item.status == "DRAFT":
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    rows = db.scalars(select(AuditLog).where(AuditLog.application_id == application_id)
                      .order_by(AuditLog.created_at, AuditLog.id)).all()
    records = [{"id": str(row.id), "application_id": str(row.application_id),
                "client_identifier": row.client_identifier, "actor_id": str(row.actor_id) if row.actor_id else None,
                "event_type": row.event_type, "source": row.source,
                "payload": row.payload, "created_at": row.created_at.isoformat()} for row in rows]
    if format == "json":
        return {"application_id": str(application_id), "records": records}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=("id", "application_id", "client_identifier", "actor_id",
                                                "event_type", "source", "payload", "created_at"))
    writer.writeheader()
    for record in records:
        writer.writerow({**record, "payload": json.dumps(record["payload"], ensure_ascii=False, sort_keys=True)})
    return Response(stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="application-{application_id}-audit.csv"'})


def employee_alternative_out(row):
    amount = Decimal(str(row.amount))
    monthly_payment = Decimal(str(row.monthly_payment))
    debt_burden = Decimal(str(row.debt_burden)) if row.debt_burden is not None else None
    return {
        "id": str(row.id), "assessment_id": str(row.assessment_id),
        "generation_id": str(row.generation_id), "position": row.position, "amount": format(amount, ".2f"),
        "term_months": row.term_months, "annual_interest_rate": format(Decimal(str(row.annual_interest_rate)), ".2f"),
        "monthly_payment": format(monthly_payment, ".2f"),
        "debt_burden": format(debt_burden, ".8f") if debt_burden is not None else None,
        "reason_code": row.reason_code, "reason": row.reason, "differences": row.differences,
        "evaluation": row.evaluation, "versions": row.versions,
        "status": row.status, "created_at": row.created_at.isoformat(),
        "offered_at": row.offered_at.isoformat() if row.offered_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_comment": row.decision_comment,
    }


def client_alternative_out(row):
    amount = Decimal(str(row.amount))
    monthly_payment = Decimal(str(row.monthly_payment))
    debt_burden = Decimal(str(row.debt_burden)) if row.debt_burden is not None else None
    return {
        "id": str(row.id), "amount": format(amount, ".2f"),
        "term_months": row.term_months, "annual_interest_rate": format(Decimal(str(row.annual_interest_rate)), ".2f"),
        "monthly_payment": format(monthly_payment, ".2f"),
        "debt_burden": format(debt_burden, ".8f") if debt_burden is not None else None,
        "reason": row.reason, "differences": row.differences, "status": row.status,
        "is_demo": True, "offered_at": row.offered_at.isoformat() if row.offered_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_comment": row.decision_comment,
    }


@router.post("/bank/applications/{application_id}/alternatives/generate", response_model=AlternativeSetOut,
             tags=["Рабочее место сотрудника"])
def create_alternative_set(application_id: UUID, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None or item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Альтернативы доступны только для заявки на рассмотрении.")
    assessment = current_assessment(db, item)
    already_accepted = db.scalar(select(AlternativeOffer.id).where(
        AlternativeOffer.application_id == item.id,
        AlternativeOffer.assessment_id == assessment.id,
        AlternativeOffer.status == "ACCEPTED",
    ).limit(1))
    if already_accepted:
        raise APIError(409, "ALTERNATIVE_ALREADY_ACCEPTED", "Клиент уже принял предложение по текущей оценке.")
    awaiting_client = db.scalar(select(AlternativeOffer.id).where(
        AlternativeOffer.application_id == item.id,
        AlternativeOffer.assessment_id == assessment.id,
        AlternativeOffer.status == "OFFERED",
    ).limit(1))
    if awaiting_client:
        raise APIError(409, "ALTERNATIVE_AWAITING_CLIENT", "Сначала дождитесь ответа клиента на текущее предложение.")
    result = assessment.result
    snapshot = result.get("input_snapshot") or assessment.input_snapshot
    input_data = snapshot.get("input_data") or {}
    product_policy = snapshot.get("product_policy") or {}
    checks = snapshot.get("checks") or []
    reports = result.get("check_reports") or {}
    bki, compliance = reports.get("bki"), reports.get("compliance")
    if not input_data or not product_policy or not bki or not compliance:
        raise APIError(409, "ASSESSMENT_CONTEXT_UNAVAILABLE", "В оценке отсутствуют данные для безопасного подбора альтернатив.")
    company = db.get(Company, item.company_id)
    generated = generate_alternatives(
        input_data=input_data, product_policy=product_policy, checks=checks,
        bki=bki, compliance=compliance, subject_id=company.inn,
        registration_date=company.registration_date,
        original_result=result, original_underwriting=result.get("underwriting", {}),
    )
    now = utc_now()
    old_rows = db.scalars(select(AlternativeOffer).where(
        AlternativeOffer.application_id == item.id,
        AlternativeOffer.status.in_(["GENERATED", "OFFERED"]),
    )).all()
    for old in old_rows:
        old.status = "SUPERSEDED"
        old.decided_at = now

    generation_id = uuid4()
    rows = []
    versions = result.get("versions", {})
    for position, candidate in enumerate(generated["alternatives"], start=1):
        row = AlternativeOffer(
            application_id=item.id, assessment_id=assessment.id, generation_id=generation_id,
            client_identifier=company.inn, employee_id=user.id,
            position=position,
            amount=candidate["amount"], term_months=candidate["term_months"],
            annual_interest_rate=candidate["annual_interest_rate"],
            monthly_payment=candidate["monthly_payment"], debt_burden=candidate["debt_burden"],
            reason_code=candidate["reason_code"], reason=candidate["reason"],
            differences=candidate["differences"],
            evaluation={"scoring": candidate["scoring"], "underwriting": candidate["underwriting"]},
            versions=versions, status="GENERATED", created_at=now,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    add_audit(db, item, company, user.id, "ALTERNATIVES_GENERATED", "alternative_engine", {
        "assessment_id": str(assessment.id), "generation_id": str(generation_id),
        "status": generated["status"], "reason_code": generated["reason_code"],
        "reason": generated["reason"], "original": generated["original"],
        "alternatives": [{key: value for key, value in candidate.items() if key != "_distance"}
                          for candidate in generated["alternatives"]],
        "versions": versions,
    })
    db.commit()
    return {
        "application_id": str(item.id), "assessment_id": str(assessment.id),
        "generation_id": str(generation_id), "status": generated["status"],
        "reason_code": generated["reason_code"], "reason": generated["reason"],
        "original": generated["original"], "versions": versions,
        "alternatives": [employee_alternative_out(row) for row in rows],
    }


@router.get("/bank/applications/{application_id}/alternatives", response_model=AlternativeSetOut,
            tags=["Рабочее место сотрудника"])
def get_alternative_set(application_id: UUID, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None or item.status == "DRAFT":
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    latest_assessment = db.scalar(select(Assessment).where(
        Assessment.application_id == item.id,
    ).order_by(Assessment.application_revision.desc()).limit(1))
    generated_event = db.scalar(select(AuditLog).where(
        AuditLog.application_id == item.id, AuditLog.event_type == "ALTERNATIVES_GENERATED",
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1))
    if (generated_event is None or latest_assessment is None
            or generated_event.payload.get("assessment_id") != str(latest_assessment.id)):
        return {"application_id": str(item.id), "status": "NOT_GENERATED", "alternatives": [], "active_offer": None}
    payload = generated_event.payload
    generation_value = payload.get("generation_id")
    generation_id = UUID(generation_value) if generation_value else None
    rows = db.scalars(select(AlternativeOffer).where(
        AlternativeOffer.application_id == item.id,
        AlternativeOffer.generation_id == generation_id,
    ).order_by(AlternativeOffer.position)).all() if generation_id else []
    active_offer = db.scalar(select(AlternativeOffer).where(
        AlternativeOffer.application_id == item.id, AlternativeOffer.assessment_id == latest_assessment.id,
        AlternativeOffer.status == "OFFERED",
    ).order_by(AlternativeOffer.offered_at.desc(), AlternativeOffer.id.desc()).limit(1))
    return {
        "application_id": str(item.id), "assessment_id": payload.get("assessment_id"),
        "generation_id": generation_value, "status": payload.get("status"),
        "reason_code": payload.get("reason_code"), "reason": payload.get("reason"),
        "original": payload.get("original"), "versions": payload.get("versions", {}),
        "alternatives": [employee_alternative_out(row) for row in rows],
        "active_offer": employee_alternative_out(active_offer) if active_offer else None,
    }


@router.post("/bank/applications/{application_id}/alternatives/{alternative_id}/offer",
             response_model=AlternativeCandidateOut, tags=["Рабочее место сотрудника"])
def offer_alternative(application_id: UUID, alternative_id: UUID, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None or item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Предложение можно отправить только по заявке на рассмотрении.")
    assessment = current_assessment(db, item)
    offer = db.get(AlternativeOffer, alternative_id)
    if offer is None or offer.application_id != item.id:
        raise APIError(404, "ALTERNATIVE_NOT_FOUND", "Вариант условий не найден.")
    if offer.assessment_id != assessment.id or offer.status != "GENERATED":
        raise APIError(409, "ALTERNATIVE_NOT_OFFERABLE", "Вариант устарел или уже использован. Пересчитайте альтернативы.")
    now = utc_now()
    previous = db.scalars(select(AlternativeOffer).where(
        AlternativeOffer.application_id == item.id, AlternativeOffer.status == "OFFERED",
    )).all()
    for old in previous:
        old.status = "SUPERSEDED"
        old.decided_at = now
    siblings = db.scalars(select(AlternativeOffer).where(
        AlternativeOffer.generation_id == offer.generation_id,
        AlternativeOffer.id != offer.id, AlternativeOffer.status == "GENERATED",
    )).all()
    for sibling in siblings:
        sibling.status = "SUPERSEDED"
        sibling.decided_at = now
    offer.status = "OFFERED"
    offer.employee_id = user.id
    offer.offered_at = now
    company = db.get(Company, item.company_id)
    add_audit(db, item, company, user.id, "ALTERNATIVE_OFFERED", "employee_alternatives", {
        "assessment_id": str(assessment.id), "offer_id": str(offer.id),
        "generation_id": str(offer.generation_id), "amount": format(offer.amount, ".2f"),
        "term_months": offer.term_months, "monthly_payment": format(offer.monthly_payment, ".2f"),
        "annual_interest_rate": format(offer.annual_interest_rate, ".2f"),
        "debt_burden": format(offer.debt_burden, ".8f") if offer.debt_burden is not None else None,
        "versions": offer.versions,
    })
    db.commit()
    return employee_alternative_out(offer)


@router.get("/applications/{application_id}/alternative-offer", response_model=ClientAlternativeOfferOut | None,
            tags=["Заявки"])
def get_client_alternative_offer(application_id: UUID, db: DB, user: Client):
    own_application(db, user, application_id)
    latest_assessment = db.scalar(select(Assessment).where(
        Assessment.application_id == application_id,
    ).order_by(Assessment.application_revision.desc()).limit(1))
    if latest_assessment is None:
        return None
    offer = db.scalar(select(AlternativeOffer).where(
        AlternativeOffer.application_id == application_id,
        AlternativeOffer.assessment_id == latest_assessment.id,
        AlternativeOffer.status.in_(["OFFERED", "ACCEPTED", "DECLINED"]),
    ).order_by(AlternativeOffer.offered_at.desc(), AlternativeOffer.id.desc()).limit(1))
    return client_alternative_out(offer) if offer else None


@router.post("/applications/{application_id}/alternative-offers/{alternative_id}/decision",
             response_model=ClientAlternativeOfferOut, tags=["Заявки"])
def decide_alternative_offer(application_id: UUID, alternative_id: UUID, payload: AlternativeDecisionIn,
                             db: DB, user: Client):
    item = own_application(db, user, application_id)
    if item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Ответить на предложение можно только по заявке на рассмотрении.")
    assessment = current_assessment(db, item)
    offer = db.get(AlternativeOffer, alternative_id)
    if offer is None or offer.application_id != item.id:
        raise APIError(404, "ALTERNATIVE_NOT_FOUND", "Предложение не найдено.")
    if offer.assessment_id != assessment.id or offer.status != "OFFERED":
        raise APIError(409, "ALTERNATIVE_NOT_PENDING", "Предложение уже обработано или устарело.")
    offer.status = payload.decision
    offer.decision_comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None
    offer.decided_at = utc_now()
    event_type = "ALTERNATIVE_ACCEPTED" if payload.decision == "ACCEPTED" else "ALTERNATIVE_DECLINED"
    db.add(ApplicationEvent(
        application_id=item.id, actor_id=user.id, application_revision=assessment.application_revision,
        event_type=event_type, from_status=item.status, to_status=item.status,
        message=offer.decision_comment,
    ))
    company = db.get(Company, item.company_id)
    add_audit(db, item, company, user.id, event_type, "client_alternatives", {
        "assessment_id": str(assessment.id), "offer_id": str(offer.id),
        "decision": payload.decision, "comment": offer.decision_comment,
        "amount": format(offer.amount, ".2f"), "term_months": offer.term_months,
    })
    db.commit()
    return client_alternative_out(offer)


@router.post("/bank/applications/{application_id}/compliance-review", tags=["Рабочее место сотрудника"])
def resolve_compliance_review(application_id: UUID, payload: ComplianceReviewIn, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None or item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Compliance-проверка доступна для заявки на рассмотрении.")
    assessment = current_assessment(db, item)
    compliance_rules = {"COMPLIANCE_POTENTIAL_MATCH", "COMPLIANCE_CONFIRMED_MATCH", "COMPLIANCE_ERROR"}
    rules = assessment.result.get("underwriting", {}).get("rules", [])
    if not any(rule.get("code") in compliance_rules for rule in rules):
        raise APIError(409, "COMPLIANCE_REVIEW_NOT_REQUIRED", "В оценке нет совпадения или ошибки Compliance для разбора.")
    review = ComplianceReview(
        application_id=item.id, assessment_id=assessment.id, employee_id=user.id,
        outcome=payload.outcome, comment=payload.comment.strip(),
    )
    db.add(review)
    company = db.get(Company, item.company_id)
    add_audit(db, item, company, user.id, "COMPLIANCE_REVIEW", "employee_compliance", {
        "assessment_id": str(assessment.id), "outcome": payload.outcome, "comment": payload.comment.strip(),
    })
    db.commit()
    return {"application_id": str(item.id), "assessment_id": str(assessment.id),
            "outcome": review.outcome, "comment": review.comment, "created_at": review.created_at}


def current_assessment(db, item):
    assessment = db.scalar(
        select(Assessment)
        .where(Assessment.application_id == item.id)
        .order_by(Assessment.application_revision.desc())
        .limit(1)
    )
    if assessment is None:
        raise APIError(409, "ASSESSMENT_REQUIRED", "Для заявки нет сохранённой оценки.")
    if assessment.application_revision + 1 != item.revision:
        raise APIError(409, "ASSESSMENT_STALE", "Оценка устарела. Клиент должен повторно отправить актуальную редакцию.")
    return assessment


def save_review_action(db, item, employee, assessment, action, message, target_status,
                       related_offer_id=None, **terms):
    previous_status = item.status
    db.add(ReviewAction(
        application_id=item.id,
        assessment_id=assessment.id,
        application_revision=assessment.application_revision,
        employee_id=employee.id,
        action=action,
        comment=message or "",
        **terms,
    ))
    item.status = target_status
    item.updated_at = utc_now()
    company = db.get(Company, item.company_id)
    try:
        db.flush()
        db.add(ApplicationEvent(
            application_id=item.id,
            actor_id=employee.id,
            application_revision=item.revision,
            event_type="INFO_REQUESTED" if action == "REQUEST_INFO" else action,
            from_status=previous_status,
            to_status=target_status,
            message=message,
        ))
        add_audit(db, item, company, employee.id, "REVIEW_ACTION", "employee_review", {
            "action": action, "from_status": previous_status, "to_status": target_status,
            "application_revision": assessment.application_revision, "message": message,
            "alternative_offer_id": related_offer_id,
        })
        if action in {"REQUEST_INFO", "APPROVED", "REJECTED"}:
            pending_offers = db.scalars(select(AlternativeOffer).where(
                AlternativeOffer.application_id == item.id,
                AlternativeOffer.status.in_(["GENERATED", "OFFERED"]),
            )).all()
            for pending_offer in pending_offers:
                pending_offer.status = "SUPERSEDED"
                pending_offer.decided_at = utc_now()
                add_audit(db, item, company, employee.id, "ALTERNATIVE_SUPERSEDED", "employee_review", {
                    "offer_id": str(pending_offer.id), "reason": action,
                })
        db.commit()
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise APIError(409, "REVIEW_CONFLICT", "Заявку уже изменил другой сотрудник. Обновите карточку.") from None
    return item


@router.post("/bank/applications/{application_id}/request-info", response_model=DraftOut, tags=["Рабочее место сотрудника"])
def request_application_info(application_id: UUID, payload: RequestInfoIn, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None:
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    if item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Уточнение можно запросить только по заявке на рассмотрении.")
    assessment = current_assessment(db, item)
    return save_review_action(
        db, item, user, assessment, "REQUEST_INFO", payload.comment, "NEEDS_INFO",
    )


@router.post("/bank/applications/{application_id}/decision", response_model=DraftOut, tags=["Рабочее место сотрудника"])
def decide_application(application_id: UUID, payload: DecisionIn, db: DB, user: BankEmployee):
    item = db.get(Application, application_id)
    if item is None:
        raise APIError(404, "APPLICATION_NOT_FOUND", "Заявка не найдена.")
    if item.status != "UNDER_REVIEW":
        raise APIError(409, "APPLICATION_NOT_REVIEWABLE", "Решение можно принять только по заявке на рассмотрении.")
    assessment = current_assessment(db, item)
    result = assessment.result

    if payload.decision == "REJECTED":
        message = payload.comment.strip() if payload.comment and payload.comment.strip() else None
        terms = {}
        related_offer_id = None
    else:
        accepted_offer = db.scalar(select(AlternativeOffer).where(
            AlternativeOffer.application_id == item.id,
            AlternativeOffer.assessment_id == assessment.id,
            AlternativeOffer.status == "ACCEPTED",
        ).order_by(AlternativeOffer.decided_at.desc(), AlternativeOffer.id.desc()).limit(1))
        approved_result = accepted_offer.evaluation.get("scoring", {}) if accepted_offer else result
        underwriting = accepted_offer.evaluation.get("underwriting", {}) if accepted_offer else result.get("underwriting", {})
        if approved_result.get("assessment_status") != "COMPLETED" or approved_result.get("missing_fields"):
            raise APIError(409, "ASSESSMENT_INCOMPLETE", "Нельзя одобрить заявку без полной оценки и проверок.")
        if approved_result.get("hard_stops"):
            raise APIError(409, "ASSESSMENT_HARD_STOP", "Нельзя одобрить заявку с обязательным ограничением.")
        if underwriting.get("status") != "PASS":
            rules = underwriting.get("rules", [])
            compliance_codes = {"COMPLIANCE_POTENTIAL_MATCH", "COMPLIANCE_CONFIRMED_MATCH", "COMPLIANCE_ERROR"}
            review_codes = {rule.get("code") for rule in rules if rule.get("outcome") == "REVIEW"}
            has_reject = any(rule.get("outcome") == "REJECT" for rule in rules)
            latest_compliance_review = db.scalar(
                select(ComplianceReview)
                .where(ComplianceReview.application_id == item.id,
                       ComplianceReview.assessment_id == assessment.id)
                .order_by(ComplianceReview.created_at.desc(), ComplianceReview.id.desc())
                .limit(1)
            )
            compliance_manually_cleared = (
                bool(review_codes) and review_codes.issubset(compliance_codes) and not has_reject
                and latest_compliance_review is not None and latest_compliance_review.outcome == "CLEAR"
            )
            if not compliance_manually_cleared:
                raise APIError(409, "MANUAL_CHECK_REQUIRED", "Не пройдены обязательные проверки; требуется дополнительная проверка.")
        product = db.get(CreditProduct, item.product_code)
        if product is None:
            raise APIError(409, "PRODUCT_UNAVAILABLE", "Не удалось получить условия продукта.")
        amount = accepted_offer.amount if accepted_offer else item.requested_amount
        term = accepted_offer.term_months if accepted_offer else item.term_months
        rate = accepted_offer.annual_interest_rate if accepted_offer else product.annual_interest_rate
        conditions = (
            f"Условия демо-продукта: {amount:.2f} руб., {term} мес., "
            f"расчётная ставка {rate:.2f}% годовых."
        )
        approval_note = payload.comment.strip() if payload.comment and payload.comment.strip() else None
        message = f"{approval_note}\n{conditions}" if approval_note else conditions
        terms = {"approved_amount": amount, "approved_term_months": term, "annual_interest_rate": rate}
        related_offer_id = str(accepted_offer.id) if accepted_offer else None
    return save_review_action(
        db, item, user, assessment, payload.decision, message, payload.decision,
        related_offer_id=related_offer_id, **terms,
    )


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
    old_status = item.status
    for field, value in changes.items():
        setattr(item, field, value)
    if changes:
        item.updated_at = utc_now()
    try:
        if changes:
            db.flush()
            db.add(ApplicationEvent(
                application_id=item.id, actor_id=user.id, application_revision=item.revision,
                event_type="DRAFT_UPDATED", from_status=old_status, to_status=old_status,
            ))
            company = db.get(Company, item.company_id)
            add_audit(db, item, company, user.id, "APPLICATION_UPDATED", "applications", {
                "revision": item.revision, "fields": sorted(changes), "status": old_status,
            })
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "REVISION_CONFLICT", "Заявка изменена. Загрузите актуальную версию.") from None
    return item


@router.post("/applications/{application_id}/submit", response_model=DraftOut, tags=["Заявки"])
def submit_application(application_id: UUID, db: DB, user: Client, payload: SubmitIn = SubmitIn()):
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

    try:
        processing = processing_pipeline.run(item, company, product,
                                             payload.credit_history_consent, utc_now())
    except PolicyValidationError:
        add_audit(db, item, company, user.id, "PIPELINE_ERROR", "scoring",
                  {"code": "SCORING_POLICY_INVALID", "revision": item.revision})
        db.commit()
        raise APIError(503, "SCORING_POLICY_INVALID", "Правила оценки продукта временно недоступны.") from None
    except Exception as exc:
        add_audit(db, item, company, user.id, "PIPELINE_ERROR", "processing_pipeline",
                  {"code": "PROCESSING_FAILED", "error_type": type(exc).__name__, "revision": item.revision})
        db.commit()
        raise APIError(503, "PROCESSING_UNAVAILABLE", "Не удалось выполнить проверки. Заявка не одобрена и может быть отправлена повторно.") from None
    bki, compliance, result = processing["bki"], processing["compliance"], processing["result"]
    underwriting = processing["underwriting"]
    input_data, checks = processing["input_data"], processing["checks"]

    previous_status = item.status
    assessment = Assessment(
        application_id=item.id, application_revision=item.revision,
        input_snapshot=to_json_value(result["input_snapshot"] or {"input_data": input_data, "checks": checks}),
        result=to_json_value(result),
    )
    db.add(assessment)
    add_audit(db, item, company, user.id, "BKI_CHECK", bki["source"], bki)
    add_audit(db, item, company, user.id, "COMPLIANCE_CHECK", compliance["source"], compliance)
    add_audit(db, item, company, user.id, "UNDERWRITING_EVALUATED", "underwriting_rules", underwriting)
    add_audit(db, item, company, user.id, "SCORING_COMPLETED", "scoring", {
        "assessment_id": str(assessment.id), "revision": item.revision,
        "input_snapshot": result.get("input_snapshot"), "result": result,
    })
    item.status = "UNDER_REVIEW"
    item.updated_at = utc_now()
    try:
        db.flush()
        db.add(ApplicationEvent(
            application_id=item.id, actor_id=user.id, application_revision=item.revision,
            event_type="RESUBMITTED" if previous_status == "NEEDS_INFO" else "SUBMITTED",
            from_status=previous_status, to_status="UNDER_REVIEW",
        ))
        add_audit(db, item, company, user.id, "APPLICATION_SUBMITTED", "applications",
                  {"revision": item.revision, "from_status": previous_status, "to_status": "UNDER_REVIEW"})
        db.commit()
    except StaleDataError:
        db.rollback()
        raise APIError(409, "REVISION_CONFLICT", "Заявка изменилась. Загрузите актуальную версию.") from None
    return item
