"""evidence request workflow

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("control_id", sa.Integer(), sa.ForeignKey("controls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("requested_by_agent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("evidence_required", sa.String(250), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("fulfilled_evidence_id", sa.Integer(), sa.ForeignKey("evidence.id"), nullable=True),
        sa.Column("notification_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evidence_requests_company_id", "evidence_requests", ["company_id"])
    op.create_index("ix_evidence_requests_control_id", "evidence_requests", ["control_id"])
    op.create_index("ix_evidence_requests_code", "evidence_requests", ["code"])


def downgrade() -> None:
    op.drop_table("evidence_requests")
