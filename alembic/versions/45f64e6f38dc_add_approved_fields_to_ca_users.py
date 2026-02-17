"""Add approved fields to ca_users

Revision ID: 45f64e6f38dc
Revises: 6b1e2b22d96c
Create Date: 2026-02-12 19:29:58.362699

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "45f64e6f38dc"
down_revision = "6b1e2b22d96c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add approved columns to ca_users
    op.add_column(
        "ca_users",
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "ca_users",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Seed existing active CAs as approved so they aren't locked out
    op.execute(
        "UPDATE ca_users SET approved = true, approved_at = CURRENT_TIMESTAMP WHERE active = true"
    )


def downgrade() -> None:
    op.drop_column("ca_users", "approved_at")
    op.drop_column("ca_users", "approved")
