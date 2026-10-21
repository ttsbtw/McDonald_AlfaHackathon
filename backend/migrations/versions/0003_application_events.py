"""Add application edit and status history."""
import sqlalchemy as sa
from alembic import op

revision = "0003_application_events"
down_revision = "0002_assessments"
branch_labels = None
depends_on = None

STATUSES = "'DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'NEEDS_INFO', 'APPROVED', 'REJECTED'"


def upgrade():
    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("application_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"from_status IS NULL OR from_status IN ({STATUSES})", name="ck_application_event_from_status"),
        sa.CheckConstraint(f"to_status IN ({STATUSES})", name="ck_application_event_to_status"),
    )
    op.create_index(
        "ix_application_events_application_created", "application_events", ["application_id", "created_at", "id"],
    )


def downgrade():
    op.drop_index("ix_application_events_application_created", table_name="application_events")
    op.drop_table("application_events")
