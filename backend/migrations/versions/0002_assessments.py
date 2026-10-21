"""Persist immutable scoring results for submitted drafts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_assessments"
down_revision = "0001_backend_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_revision", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "application_revision", name="uq_assessment_application_revision"),
    )
    op.create_index("ix_assessments_application_created", "assessments", ["application_id", "created_at"])


def downgrade():
    op.drop_index("ix_assessments_application_created", table_name="assessments")
    op.drop_table("assessments")
