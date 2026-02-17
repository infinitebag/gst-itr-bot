"""add filing_records table

Revision ID: a1b2c3d4e5f6
Revises: c5ef92d32a33
Create Date: 2026-02-11 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "c5ef92d32a33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filing_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filing_type", sa.String(length=20), nullable=False),
        sa.Column("form_type", sa.String(length=20), nullable=False),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_filing_records_user_id"),
        "filing_records",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_filing_records_user_id"), table_name="filing_records")
    op.drop_table("filing_records")
