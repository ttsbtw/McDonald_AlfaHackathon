"""Persist employee decisions and their approved terms."""
import sqlalchemy as sa
from alembic import op

revision = "0004_review_actions"
down_revision = "0003_application_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), sa.ForeignKey("assessments.id"), nullable=False),
        sa.Column("application_revision", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("approved_amount", sa.Numeric(15, 2)),
        sa.Column("approved_term_months", sa.Integer()),
        sa.Column("annual_interest_rate", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "application_revision", name="uq_review_action_application_revision"),
        sa.CheckConstraint("action IN ('REQUEST_INFO', 'APPROVED', 'REJECTED')", name="ck_review_action_action"),
        sa.CheckConstraint(
            "(action = 'APPROVED' AND approved_amount IS NOT NULL AND approved_term_months IS NOT NULL "
            "AND annual_interest_rate IS NOT NULL) OR "
            "(action <> 'APPROVED' AND approved_amount IS NULL AND approved_term_months IS NULL "
            "AND annual_interest_rate IS NULL)",
            name="ck_review_action_approval_terms",
        ),
    )


def downgrade():
    op.drop_table("review_actions")
