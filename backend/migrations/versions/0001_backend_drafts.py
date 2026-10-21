"""Users, companies, credit products and versioned drafts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_backend_drafts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('CLIENT', 'BANK_EMPLOYEE')", name="ck_user_role"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("inn", sa.String(12), nullable=False, unique=True),
        sa.Column("legal_form", sa.String(10), nullable=False),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "owner_id", name="uq_company_owner"),
        sa.CheckConstraint("legal_form IN ('IP', 'OOO')", name="ck_company_legal_form"),
    )
    op.create_table(
        "credit_products",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("min_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("min_term_months", sa.Integer(), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("rate_note", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("scoring_policy", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_checked_on", sa.Date(), nullable=False),
        sa.Column("assumptions", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("min_amount > 0 AND max_amount >= min_amount", name="ck_product_amounts"),
        sa.CheckConstraint("min_term_months > 0 AND max_term_months >= min_term_months AND max_term_months <= 360", name="ck_product_terms"),
        sa.CheckConstraint("annual_interest_rate >= 0 AND annual_interest_rate <= 100", name="ck_product_rate"),
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(64), sa.ForeignKey("credit_products.code")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(15, 2)),
        sa.Column("term_months", sa.Integer()),
        sa.Column("purpose", sa.String(200)),
        sa.Column("average_monthly_revenue", sa.Numeric(15, 2)),
        sa.Column("average_monthly_operating_expenses", sa.Numeric(15, 2)),
        sa.Column("existing_monthly_debt_payment", sa.Numeric(15, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id", "owner_id"], ["companies.id", "companies.owner_id"], name="fk_application_company_owner"),
        sa.CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'NEEDS_INFO', 'APPROVED', 'REJECTED')", name="ck_application_status"),
        sa.CheckConstraint("revision > 0", name="ck_application_revision"),
        sa.CheckConstraint("requested_amount > 0 AND requested_amount <= 1000000000000", name="ck_application_amount"),
        sa.CheckConstraint("term_months BETWEEN 1 AND 360", name="ck_application_term"),
        *[sa.CheckConstraint(f"{field} >= 0 AND {field} <= 1000000000000", name=f"ck_app_{field}") for field in (
            "average_monthly_revenue", "average_monthly_operating_expenses", "existing_monthly_debt_payment",
        )],
    )
    op.create_index("ix_applications_owner_created", "applications", ["owner_id", "created_at", "id"])


def downgrade():
    op.drop_table("applications")
    op.drop_table("credit_products")
    op.drop_table("companies")
    op.drop_table("users")
