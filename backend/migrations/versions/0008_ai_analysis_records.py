"""Persist the latest checked AI explanation per application."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_ai_analysis_records"
down_revision = "0007_alternative_offers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_analysis_records",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("assessment_id", sa.Uuid(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_analysis_records_assessment", "ai_analysis_records", ["assessment_id"])


def downgrade():
    op.drop_index("ix_ai_analysis_records_assessment", table_name="ai_analysis_records")
    op.drop_table("ai_analysis_records")
