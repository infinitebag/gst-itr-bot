"""phase6-10: user_gstins, refund_claims, gst_notices, notification_schedules + new features

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-02-13 16:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 0. Add is_active to users table ----
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))

    # ---- 1. Create user_gstins table ----
    op.create_table(
        "user_gstins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("gstin", sa.String(15), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "gstin", name="uq_user_gstin"),
    )

    # ---- 2. Create refund_claims table ----
    op.create_table(
        "refund_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gstin", sa.String(15), index=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("claim_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("period", sa.String(10), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("arn", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ---- 3. Create gst_notices table ----
    op.create_table(
        "gst_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gstin", sa.String(15), index=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("notice_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ---- 4. Create notification_schedules table ----
    op.create_table(
        "notification_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            index=True,
            nullable=True,
        ),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("template_params", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ---- 5. Insert new features (IDs 10-14) ----
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
            {"id": 10, "code": "filing_status",   "name": "Filing Status",      "category": "gst", "display_order": 25, "whatsapp_state": "GST_FILING_STATUS",  "i18n_key": "GST_MENU_ITEM_filing_status"},
            {"id": 11, "code": "credit_check",     "name": "Credit Check",       "category": "gst", "display_order": 45, "whatsapp_state": "MEDIUM_CREDIT_CHECK","i18n_key": "GST_MENU_ITEM_credit_check"},
            {"id": 12, "code": "refund_tracking",  "name": "Refund Tracking",    "category": "gst", "display_order": 92, "whatsapp_state": "REFUND_MENU",        "i18n_key": "GST_MENU_ITEM_refund_tracking"},
            {"id": 13, "code": "notice_mgmt",      "name": "Notice Management",  "category": "gst", "display_order": 94, "whatsapp_state": "NOTICE_MENU",        "i18n_key": "GST_MENU_ITEM_notice_mgmt"},
            {"id": 14, "code": "export_services",  "name": "Export Services",    "category": "gst", "display_order": 96, "whatsapp_state": "EXPORT_MENU",        "i18n_key": "GST_MENU_ITEM_export_services"},
        ],
    )

    # ---- 6. Update existing features whatsapp_state ----
    op.execute("UPDATE features SET whatsapp_state = 'EINVOICE_MENU' WHERE code = 'e_invoice'")
    op.execute("UPDATE features SET whatsapp_state = 'EWAYBILL_MENU' WHERE code = 'e_waybill'")
    op.execute("UPDATE features SET whatsapp_state = 'MULTI_GSTIN_MENU' WHERE code = 'multi_gstin'")

    # ---- 7. Insert segment_features for new features ----
    sf_table = sa.table(
        "segment_features",
        sa.column("segment", sa.String),
        sa.column("feature_id", sa.Integer),
        sa.column("enabled", sa.Boolean),
    )
    rows = []
    # filing_status (10): all 3 segments
    for seg in ["small", "medium", "enterprise"]:
        rows.append({"segment": seg, "feature_id": 10, "enabled": True})
    # credit_check (11): medium, enterprise
    for seg in ["medium", "enterprise"]:
        rows.append({"segment": seg, "feature_id": 11, "enabled": True})
    # refund_tracking (12): medium, enterprise
    for seg in ["medium", "enterprise"]:
        rows.append({"segment": seg, "feature_id": 12, "enabled": True})
    # notice_mgmt (13): medium, enterprise
    for seg in ["medium", "enterprise"]:
        rows.append({"segment": seg, "feature_id": 13, "enabled": True})
    # export_services (14): enterprise only
    rows.append({"segment": "enterprise", "feature_id": 14, "enabled": True})
    op.bulk_insert(sf_table, rows)


def downgrade() -> None:
    # ---- 1. Remove segment_features for feature IDs 10-14 ----
    op.execute("DELETE FROM segment_features WHERE feature_id IN (10, 11, 12, 13, 14)")

    # ---- 2. Revert whatsapp_state updates on existing features ----
    op.execute("UPDATE features SET whatsapp_state = NULL WHERE code = 'e_invoice'")
    op.execute("UPDATE features SET whatsapp_state = NULL WHERE code = 'e_waybill'")
    op.execute("UPDATE features SET whatsapp_state = NULL WHERE code = 'multi_gstin'")

    # ---- 3. Remove new features ----
    op.execute("DELETE FROM features WHERE code IN ('filing_status', 'credit_check', 'refund_tracking', 'notice_mgmt', 'export_services')")

    # ---- 4. Drop tables in reverse order ----
    op.drop_table("notification_schedules")
    op.drop_table("gst_notices")
    op.drop_table("refund_claims")
    op.drop_table("user_gstins")
