from datetime import date, datetime, timezone
from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from .scoring.contracts import money


def parse_money(value):
    # Reuse the scoring contract: reject floats, bools and sub-kopeck values.
    with localcontext(Context(prec=40)):
        return money(value)


Money = Annotated[Decimal, BeforeValidator(parse_money, json_schema_input_type=str)]


def parse_positive_money(value):
    result = parse_money(value)
    if result <= 0:
        raise ValueError("Сумма кредита должна быть положительной.")
    return result


PositiveMoney = Annotated[Decimal, BeforeValidator(parse_positive_money, json_schema_input_type=str)]
Term = Annotated[int, Field(strict=True, ge=1, le=360)]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class UserOut(APIModel):
    id: UUID
    username: str
    full_name: str
    role: Literal["CLIENT", "BANK_EMPLOYEE"]


class TokenOut(APIModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CompanyOut(APIModel):
    id: UUID
    name: str
    inn: str
    legal_form: str
    registration_date: date


class ProductOut(APIModel):
    code: str
    name: str
    description: str
    min_amount: Decimal
    max_amount: Decimal
    min_term_months: int
    max_term_months: int
    annual_interest_rate: Decimal
    rate_note: str
    policy_version: str
    source_url: str
    source_checked_on: date
    assumptions: str


class DraftFields(APIModel):
    product_code: str | None = Field(default=None, min_length=1, max_length=64)
    requested_amount: PositiveMoney | None = None
    term_months: Term | None = None
    purpose: str | None = Field(default=None, min_length=1, max_length=200)
    average_monthly_revenue: Money | None = None
    average_monthly_operating_expenses: Money | None = None
    existing_monthly_debt_payment: Money | None = None


class DraftCreate(DraftFields):
    pass


class DraftUpdate(DraftFields):
    revision: int = Field(strict=True, ge=1)


class DraftOut(DraftFields):
    id: UUID
    company_id: UUID
    status: Literal["DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"]
    revision: int
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)


class DraftPage(APIModel):
    items: list[DraftOut]
    total: int
    limit: int
    offset: int


class ApplicationEventOut(APIModel):
    id: UUID
    application_revision: int
    event_type: Literal["DRAFT_CREATED", "DRAFT_UPDATED", "SUBMITTED", "RESUBMITTED"]
    from_status: Literal["DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"] | None
    to_status: Literal["DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED"]
    message: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)


class FieldError(APIModel):
    field: str
    code: str
    message: str


class ErrorDetail(APIModel):
    code: str
    message: str
    fields: list[FieldError] = []


class ErrorResponse(APIModel):
    error: ErrorDetail
