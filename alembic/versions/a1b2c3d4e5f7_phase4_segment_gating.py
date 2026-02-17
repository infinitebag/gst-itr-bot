"""phase4: segment gating — features, segment_features, client_addons + BusinessClient columns

Revision ID: a1b2c3d4e5f7
Revises: 9c5d6e7f8a1b
Create Date: 2026-02-13 23:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "a1b2c3d4e5f7"
down_revision = "9c5d6e7f8a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. Add columns to business_clients ----
    op.add_column(
        "business_clients",
        sa.Column("segment", sa.String(20), nullable=False, server_default="small"),
    )
    op.add_column(
        "business_clients",
        sa.Column("annual_turnover", sa.Numeric(15, 2), nullable=True),
    )
    op.add_column(
        "business_clients",
        sa.Column("monthly_invoice_volume", sa.Integer(), nullable=True),
    )
    op.add_column(
        "business_clients",
        sa.Column("gstin_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "business_clients",
        sa.Column("is_exporter", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "business_clients",
        sa.Column("segment_override", sa.Boolean(), nullable=False, server_default="false"),
    )

    # ---- 2. Create features table ----
    op.create_table(
        "features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="gst"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("whatsapp_state", sa.String(50), nullable=True),
        sa.Column("i18n_key", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ---- 3. Create segment_features table ----
    op.create_table(
        "segment_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("segment", sa.String(20), index=True, nullable=False),
        sa.Column(
            "feature_id",
            sa.Integer(),
            sa.ForeignKey("features.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.UniqueConstraint("segment", "feature_id", name="uq_segment_feature"),
    )

    # ---- 4. Create client_addons table ----
    op.create_table(
        "client_addons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("business_clients.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "feature_id",
            sa.Integer(),
            sa.ForeignKey("features.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("granted_by", sa.String(50), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("client_id", "feature_id", name="uq_client_addon"),
    )

    # ---- 5. Seed features ----
    features_table = sa.table(
        "features",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("whatsapp_state", sa.String),
        sa.column("i18n_key", sa.String),
    )
    op.bulk_insert(
        features_table,
        [
            {"id": 1, "code": "enter_gstin",        "name": "Enter GSTIN",        "category": "gst", "display_order": 10, "whatsapp_state": "WAIT_GSTIN",        "i18n_key": "GST_MENU_ITEM_enter_gstin"},
            {"id": 2, "code": "monthly_compliance",  "name": "Monthly Filing",     "category": "gst", "display_order": 20, "whatsapp_state": "GST_PERIOD_MENU",   "i18n_key": "GST_MENU_ITEM_monthly_compliance"},
            {"id": 3, "code": "nil_return",           "name": "Zero Return",        "category": "gst", "display_order": 30, "whatsapp_state": "NIL_FILING_MENU",   "i18n_key": "GST_MENU_ITEM_nil_return"},
            {"id": 4, "code": "upload_invoices",      "name": "Scan Invoices",      "category": "gst", "display_order": 40, "whatsapp_state": "SMART_UPLOAD",      "i18n_key": "GST_MENU_ITEM_upload_invoices"},
            {"id": 5, "code": "e_invoice",            "name": "e-Invoice",          "category": "gst", "display_order": 50, "whatsapp_state": None,                "i18n_key": "GST_MENU_ITEM_e_invoice"},
            {"id": 6, "code": "e_waybill",            "name": "e-WayBill",          "category": "gst", "display_order": 60, "whatsapp_state": None,                "i18n_key": "GST_MENU_ITEM_e_waybill"},
            {"id": 7, "code": "annual_return",        "name": "Annual Summary",     "category": "gst", "display_order": 70, "whatsapp_state": "GST_ANNUAL_MENU",   "i18n_key": "GST_MENU_ITEM_annual_return"},
            {"id": 8, "code": "risk_scoring",         "name": "Risk Check",         "category": "gst", "display_order": 80, "whatsapp_state": "GST_RISK_REVIEW",   "i18n_key": "GST_MENU_ITEM_risk_scoring"},
            {"id": 9, "code": "multi_gstin",          "name": "Multi-GSTIN",        "category": "gst", "display_order": 90, "whatsapp_state": None,                "i18n_key": "GST_MENU_ITEM_multi_gstin"},
        ],
    )

    # ---- 6. Seed segment_features ----
    sf_table = sa.table(
        "segment_features",
        sa.column("segment", sa.String),
        sa.column("feature_id", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )
    rows = []
    # Small: features 1-4
    for fid in [1, 2, 3, 4]:
        rows.append({"segment": "small", "feature_id": fid, "enabled": True})
    # Medium: features 1-7
    for fid in [1, 2, 3, 4, 5, 6, 7]:
        rows.append({"segment": "medium", "feature_id": fid, "enabled": True})
    # Enterprise: features 1-9
    for fid in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
        rows.append({"segment": "enterprise", "feature_id": fid, "enabled": True})
    op.bulk_insert(sf_table, rows)


def downgrade() -> None:
    op.drop_table("client_addons")
    op.drop_table("segment_features")
    op.drop_table("features")

    op.drop_column("business_clients", "segment_override")
    op.drop_column("business_clients", "is_exporter")
    op.drop_column("business_clients", "gstin_count")
    op.drop_column("business_clients", "monthly_invoice_volume")
    op.drop_column("business_clients", "annual_turnover")
    op.drop_column("business_clients", "segment")
