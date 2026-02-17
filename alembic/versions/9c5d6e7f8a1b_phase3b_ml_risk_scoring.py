"""phase3b: ml_model_artifacts table + ML columns on risk_assessments

Revision ID: 9c5d6e7f8a1b
Revises: 8b4c5d6e7f0a
Create Date: 2026-02-13 23:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "9c5d6e7f8a1b"
down_revision = "8b4c5d6e7f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create ml_model_artifacts table
    op.create_table(
        "ml_model_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("model_name", sa.String(100), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("model_binary", sa.LargeBinary(), nullable=False),
        sa.Column("model_size_bytes", sa.Integer(), nullable=True),
        sa.Column("training_samples", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("f1_macro", sa.Float(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("feature_names_json", sa.Text(), nullable=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # 2. Add ML columns to risk_assessments
    op.add_column(
        "risk_assessments",
        sa.Column("ml_risk_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "risk_assessments",
        sa.Column("ml_prediction_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "risk_assessments",
        sa.Column("blend_weight", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("risk_assessments", "blend_weight")
    op.drop_column("risk_assessments", "ml_prediction_json")
    op.drop_column("risk_assessments", "ml_risk_score")
    op.drop_table("ml_model_artifacts")
