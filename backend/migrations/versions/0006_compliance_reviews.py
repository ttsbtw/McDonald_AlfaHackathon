"""Persist employee resolutions for compliance matches."""
import sqlalchemy as sa
from alembic import op

revision = "0006_compliance_reviews"
down_revision = "0005_audit_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "compliance_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), sa.ForeignKey("assessments.id"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("outcome IN ('CLEAR', 'CONFIRMED_MATCH')", name="ck_compliance_review_outcome"),
    )
    op.create_index("ix_compliance_reviews_application_created", "compliance_reviews",
                    ["application_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_compliance_reviews_application_created", table_name="compliance_reviews")
    op.drop_table("compliance_reviews")
