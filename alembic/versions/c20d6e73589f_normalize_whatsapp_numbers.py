"""normalize_whatsapp_numbers

Revision ID: c20d6e73589f
Revises: 45f64e6f38dc
Create Date: 2026-02-12 20:43:15.328819

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'c20d6e73589f'
down_revision = '45f64e6f38dc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Strip leading '+' from WhatsApp numbers in business_clients
    op.execute(
        "UPDATE business_clients "
        "SET whatsapp_number = LTRIM(whatsapp_number, '+') "
        "WHERE whatsapp_number LIKE '+%'"
    )
    # Strip leading '+' from WhatsApp numbers in users table
    op.execute(
        "UPDATE users "
        "SET whatsapp_number = LTRIM(whatsapp_number, '+') "
        "WHERE whatsapp_number LIKE '+%'"
    )
    # For bare 10-digit Indian numbers (starting with 6-9), prepend '91'
    op.execute(
        "UPDATE business_clients "
        "SET whatsapp_number = '91' || whatsapp_number "
        "WHERE whatsapp_number ~ '^[6-9][0-9]{9}$'"
    )


def downgrade() -> None:
    # Normalization is not reversible — cannot determine original format
    pass