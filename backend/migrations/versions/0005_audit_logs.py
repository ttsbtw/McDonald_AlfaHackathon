"""Add append-only analytics audit log for credit processing."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_audit_logs"
down_revision = "0004_review_actions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_identifier", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_application_created", "audit_logs", ["application_id", "created_at", "id"])
    op.create_index("ix_audit_logs_client_created", "audit_logs", ["client_identifier", "created_at"])


def downgrade():
    op.drop_index("ix_audit_logs_client_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_application_created", table_name="audit_logs")
    op.drop_table("audit_logs")
