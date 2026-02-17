"""add gst monthly compliance

Revision ID: 5102d902fbff
Revises: c20d6e73589f
Create Date: 2026-02-13 17:49:43.341352

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "5102d902fbff"
down_revision = "c20d6e73589f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create return_periods table first (before itc_matches, since invoices FK -> itc_matches)
    op.create_table(
        "return_periods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gstin", sa.String(20), nullable=False),
        sa.Column("fy", sa.String(10), nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column(
            "filing_mode",
            sa.String(20),
            server_default="monthly",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(30), server_default="draft", nullable=False
        ),
        # Invoice counts
        sa.Column("outward_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inward_count", sa.Integer(), server_default="0", nullable=False),
        # Output tax
        sa.Column(
            "output_tax_igst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "output_tax_cgst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "output_tax_sgst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        # ITC
        sa.Column(
            "itc_igst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "itc_cgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "itc_sgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        # Net payable
        sa.Column(
            "net_payable_igst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "net_payable_cgst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "net_payable_sgst",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        # RCM
        sa.Column(
            "rcm_igst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "rcm_cgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "rcm_sgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        # Metadata
        sa.Column("risk_flags", sa.Text(), nullable=True),
        sa.Column(
            "ca_id",
            sa.Integer(),
            sa.ForeignKey("ca_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gstr1_filing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("filing_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gstr3b_filing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("filing_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("due_date_gstr1", sa.Date(), nullable=True),
        sa.Column("due_date_gstr3b", sa.Date(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_return_periods_user_id", "return_periods", ["user_id"])
    op.create_index("ix_return_periods_ca_id", "return_periods", ["ca_id"])
    op.create_unique_constraint(
        "uq_return_periods_gstin_period", "return_periods", ["gstin", "period"]
    )

    # 2. Create itc_matches table
    op.create_table(
        "itc_matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "period_id",
            UUID(as_uuid=True),
            sa.ForeignKey("return_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_invoice_id",
            UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("gstr2b_supplier_gstin", sa.String(20), nullable=False),
        sa.Column("gstr2b_invoice_number", sa.String(50), nullable=False),
        sa.Column("gstr2b_invoice_date", sa.Date(), nullable=True),
        sa.Column("gstr2b_taxable_value", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "gstr2b_igst",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "gstr2b_cgst",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "gstr2b_sgst",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("match_status", sa.String(20), nullable=False),
        sa.Column("mismatch_details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_itc_matches_period_id", "itc_matches", ["period_id"])
    op.create_index(
        "ix_itc_matches_supplier_inv",
        "itc_matches",
        ["gstr2b_supplier_gstin", "gstr2b_invoice_number"],
    )

    # 3. Add monthly compliance columns to invoices table
    op.add_column(
        "invoices",
        sa.Column(
            "direction",
            sa.String(10),
            server_default="outward",
            nullable=False,
        ),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "itc_eligible",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "reverse_charge",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "invoices",
        sa.Column("blocked_itc_reason", sa.String(100), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("gstr2b_match_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("gstr2b_match_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_invoices_direction", "invoices", ["direction"])
    op.create_foreign_key(
        "fk_invoices_gstr2b_match",
        "invoices",
        "itc_matches",
        ["gstr2b_match_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop invoice columns (reverse order)
    op.drop_constraint("fk_invoices_gstr2b_match", "invoices", type_="foreignkey")
    op.drop_index("ix_invoices_direction", table_name="invoices")
    op.drop_column("invoices", "gstr2b_match_id")
    op.drop_column("invoices", "gstr2b_match_status")
    op.drop_column("invoices", "blocked_itc_reason")
    op.drop_column("invoices", "reverse_charge")
    op.drop_column("invoices", "itc_eligible")
    op.drop_column("invoices", "direction")

    # Drop itc_matches
    op.drop_index("ix_itc_matches_supplier_inv", table_name="itc_matches")
    op.drop_index("ix_itc_matches_period_id", table_name="itc_matches")
    op.drop_table("itc_matches")

    # Drop return_periods
    op.drop_constraint(
        "uq_return_periods_gstin_period", "return_periods", type_="unique"
    )
    op.drop_index("ix_return_periods_ca_id", table_name="return_periods")
    op.drop_index("ix_return_periods_user_id", table_name="return_periods")
    op.drop_table("return_periods")
