"""phase2: risk_assessments, payment_records, annual_returns + extend return_periods & business_clients

Revision ID: 7a3b9c5d1e2f
Revises: 5102d902fbff
Create Date: 2026-02-13 20:00:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "7a3b9c5d1e2f"
down_revision = "5102d902fbff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create risk_assessments table ──────────────────────────────
    op.create_table(
        "risk_assessments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "period_id",
            UUID(as_uuid=True),
            sa.ForeignKey("return_periods.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Overall score & level
        sa.Column("risk_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "risk_level",
            sa.String(20),
            server_default="LOW",
            nullable=False,
        ),
        # Detailed flags & recommendations (JSON text)
        sa.Column("risk_flags", sa.Text(), nullable=True),
        sa.Column("recommended_actions", sa.Text(), nullable=True),
        # Per-category scores
        sa.Column(
            "category_a_score", sa.Integer(), server_default="0", nullable=False
        ),  # Data Quality (max 20)
        sa.Column(
            "category_b_score", sa.Integer(), server_default="0", nullable=False
        ),  # ITC & 2B Recon (max 35)
        sa.Column(
            "category_c_score", sa.Integer(), server_default="0", nullable=False
        ),  # Liability/Payment/Filing (max 20)
        sa.Column(
            "category_d_score", sa.Integer(), server_default="0", nullable=False
        ),  # Behavioral/Anomaly (max 15)
        sa.Column(
            "category_e_score", sa.Integer(), server_default="0", nullable=False
        ),  # Policy/Structural (max 10)
        # CA calibration
        sa.Column("ca_override_score", sa.Integer(), nullable=True),
        sa.Column("ca_override_notes", sa.Text(), nullable=True),
        sa.Column("ca_final_outcome", sa.String(30), nullable=True),
        sa.Column("post_filing_outcome", sa.String(30), nullable=True),
        # Timestamps
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
    op.create_index(
        "ix_risk_assessments_period_id", "risk_assessments", ["period_id"], unique=True
    )

    # ── 2. Create payment_records table ───────────────────────────────
    op.create_table(
        "payment_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "period_id",
            UUID(as_uuid=True),
            sa.ForeignKey("return_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("challan_number", sa.String(50), nullable=True),
        sa.Column("challan_date", sa.Date(), nullable=True),
        sa.Column(
            "igst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "cgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "sgst", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "cess", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column(
            "total", sa.Numeric(14, 2), server_default="0", nullable=False
        ),
        sa.Column("payment_mode", sa.String(20), nullable=True),
        sa.Column("bank_reference", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_payment_records_period_id", "payment_records", ["period_id"]
    )

    # ── 3. Create annual_returns table ────────────────────────────────
    op.create_table(
        "annual_returns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gstin", sa.String(20), nullable=False),
        sa.Column("fy", sa.String(10), nullable=False),
        sa.Column(
            "status", sa.String(30), server_default="draft", nullable=False
        ),
        # Aggregated totals
        sa.Column(
            "total_outward_taxable",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_inward_taxable",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_itc_claimed",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_itc_reversed",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_tax_paid",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
        # Discrepancy analysis (JSON)
        sa.Column("monthly_vs_annual_diff", sa.Text(), nullable=True),
        sa.Column("books_vs_gst_diff", sa.Text(), nullable=True),
        # Risk & assignments
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column(
            "ca_id",
            sa.Integer(),
            sa.ForeignKey("ca_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "filing_record_id",
            UUID(as_uuid=True),
            sa.ForeignKey("filing_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_annual_returns_user_id", "annual_returns", ["user_id"])
    op.create_index("ix_annual_returns_ca_id", "annual_returns", ["ca_id"])
    op.create_unique_constraint(
        "uq_annual_returns_gstin_fy", "annual_returns", ["gstin", "fy"]
    )

    # ── 4. Extend return_periods with new columns ─────────────────────
    op.add_column(
        "return_periods",
        sa.Column(
            "late_fee",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "return_periods",
        sa.Column(
            "interest",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "return_periods",
        sa.Column(
            "cess_output",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "return_periods",
        sa.Column(
            "cess_itc",
            sa.Numeric(14, 2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "return_periods",
        sa.Column("risk_assessment_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_return_periods_risk_assessment",
        "return_periods",
        "risk_assessments",
        ["risk_assessment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── 5. Extend business_clients with taxpayer type ─────────────────
    op.add_column(
        "business_clients",
        sa.Column(
            "taxpayer_type",
            sa.String(20),
            server_default="regular",
            nullable=False,
        ),
    )
    op.add_column(
        "business_clients",
        sa.Column("composition_rate", sa.Numeric(5, 2), nullable=True),
    )


def downgrade() -> None:
    # 5. Drop business_clients columns
    op.drop_column("business_clients", "composition_rate")
    op.drop_column("business_clients", "taxpayer_type")

    # 4. Drop return_periods columns
    op.drop_constraint(
        "fk_return_periods_risk_assessment", "return_periods", type_="foreignkey"
    )
    op.drop_column("return_periods", "risk_assessment_id")
    op.drop_column("return_periods", "cess_itc")
    op.drop_column("return_periods", "cess_output")
    op.drop_column("return_periods", "interest")
    op.drop_column("return_periods", "late_fee")

    # 3. Drop annual_returns
    op.drop_constraint(
        "uq_annual_returns_gstin_fy", "annual_returns", type_="unique"
    )
    op.drop_index("ix_annual_returns_ca_id", table_name="annual_returns")
    op.drop_index("ix_annual_returns_user_id", table_name="annual_returns")
    op.drop_table("annual_returns")

    # 2. Drop payment_records
    op.drop_index("ix_payment_records_period_id", table_name="payment_records")
    op.drop_table("payment_records")

    # 1. Drop risk_assessments
    op.drop_index(
        "ix_risk_assessments_period_id", table_name="risk_assessments"
    )
    op.drop_table("risk_assessments")
