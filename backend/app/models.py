from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('CLIENT', 'BANK_EMPLOYEE')", name="ck_user_role"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_company_owner"),
        CheckConstraint("legal_form IN ('IP', 'OOO')", name="ck_company_legal_form"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    legal_form: Mapped[str] = mapped_column(String(10))
    registration_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CreditProduct(Base):
    __tablename__ = "credit_products"
    __table_args__ = (
        CheckConstraint("min_amount > 0 AND max_amount >= min_amount", name="ck_product_amounts"),
        CheckConstraint("min_term_months > 0 AND max_term_months >= min_term_months AND max_term_months <= 360", name="ck_product_terms"),
        CheckConstraint("annual_interest_rate >= 0 AND annual_interest_rate <= 100", name="ck_product_rate"),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    min_term_months: Mapped[int]
    max_term_months: Mapped[int]
    annual_interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    rate_note: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(100))
    scoring_policy: Mapped[dict] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(Text)
    source_checked_on: Mapped[date]
    assumptions: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"], name="fk_application_company_owner"),
        CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'NEEDS_INFO', 'APPROVED', 'REJECTED')", name="ck_application_status"),
        CheckConstraint("revision > 0", name="ck_application_revision"),
        CheckConstraint("requested_amount > 0 AND requested_amount <= 1000000000000", name="ck_application_amount"),
        CheckConstraint("term_months BETWEEN 1 AND 360", name="ck_application_term"),
        *[CheckConstraint(f"{field} >= 0 AND {field} <= 1000000000000", name=f"ck_app_{field}") for field in (
            "average_monthly_revenue", "average_monthly_operating_expenses", "existing_monthly_debt_payment",
        )],
        Index("ix_applications_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[UUID] = mapped_column(Uuid)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("credit_products.code"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    requested_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    term_months: Mapped[int | None]
    purpose: Mapped[str | None] = mapped_column(String(200))
    average_monthly_revenue: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    average_monthly_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    existing_monthly_debt_payment: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __mapper_args__ = {"version_id_col": revision}
