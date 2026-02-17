"""phase3a: pgvector extension + knowledge_documents + knowledge_chunks tables

Revision ID: 8b4c5d6e7f0a
Revises: 7a3b9c5d1e2f
Create Date: 2026-02-13 22:00:00.000000

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "8b4c5d6e7f0a"
down_revision = "7a3b9c5d1e2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Enable pgvector extension ──────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 2. Create knowledge_documents table ───────────────────────────
    op.create_table(
        "knowledge_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=False, index=True),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False, index=True),
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

    # ── 3. Create knowledge_chunks table (without embedding col) ──────
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("section_header", sa.String(300), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ── 4. Add pgvector embedding column via raw SQL ──────────────────
    # Alembic/SQLAlchemy doesn't natively support the vector type,
    # so we add it with raw DDL after table creation.
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536)"
    )

    # ── 5. Create ivfflat index for cosine similarity search ──────────
    op.execute("""
        CREATE INDEX ix_knowledge_chunks_embedding
        ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_embedding", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
