"""Persist generated alternative conditions and client decisions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_alternative_offers"
down_revision = "0006_compliance_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alternative_offers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), sa.ForeignKey("assessments.id"), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("client_identifier", sa.String(64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(15, 2), nullable=False),
        sa.Column("debt_burden", sa.Numeric(12, 8)),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("differences", postgresql.JSONB(), nullable=False),
        sa.Column("evaluation", postgresql.JSONB(), nullable=False),
        sa.Column("versions", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decision_comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('GENERATED', 'OFFERED', 'ACCEPTED', 'DECLINED', 'SUPERSEDED')",
            name="ck_alternative_offer_status",
        ),
        sa.CheckConstraint("amount > 0 AND term_months BETWEEN 1 AND 360", name="ck_alternative_offer_terms"),
    )
    op.create_index("ix_alternative_offers_application_created", "alternative_offers",
                    ["application_id", "created_at", "id"])
    op.create_index("ix_alternative_offers_generation", "alternative_offers", ["generation_id", "created_at"])


def downgrade():
    op.drop_index("ix_alternative_offers_generation", table_name="alternative_offers")
    op.drop_index("ix_alternative_offers_application_created", table_name="alternative_offers")
    op.drop_table("alternative_offers")
