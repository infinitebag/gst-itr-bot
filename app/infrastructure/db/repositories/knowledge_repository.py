# app/infrastructure/db/repositories/knowledge_repository.py
"""
Repository for knowledge base CRUD and pgvector similarity search.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import KnowledgeDocument, KnowledgeChunk

logger = logging.getLogger("repo.knowledge")


class KnowledgeRepository:
    """CRUD + vector search for knowledge base documents and chunks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Document CRUD ──────────────────────────────────────────────

    async def create_document(
        self,
        title: str,
        content: str,
        category: str,
        source: str | None = None,
        effective_date: date | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeDocument:
        """Create a new knowledge document."""
        doc = KnowledgeDocument(
            id=uuid.uuid4(),
            title=title,
            content=content,
            category=category,
            source=source,
            effective_date=effective_date,
            metadata_json=json.dumps(metadata) if metadata else None,
            chunk_count=0,
            is_active=True,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def get_document(self, doc_id: UUID) -> KnowledgeDocument | None:
        """Retrieve a document by ID."""
        result = await self.db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        category: str | None = None,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[KnowledgeDocument]:
        """List knowledge documents with optional category filter."""
        stmt = select(KnowledgeDocument)
        if category:
            stmt = stmt.where(KnowledgeDocument.category == category)
        if active_only:
            stmt = stmt.where(KnowledgeDocument.is_active.is_(True))
        stmt = stmt.order_by(KnowledgeDocument.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_document(self, doc_id: UUID) -> bool:
        """Soft-delete: set is_active = False."""
        result = await self.db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == doc_id)
            .values(is_active=False)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def delete_document(self, doc_id: UUID) -> bool:
        """Hard-delete: remove document + cascade chunks."""
        result = await self.db.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def update_chunk_count(self, doc_id: UUID, count: int) -> None:
        """Update the chunk_count field after ingestion."""
        await self.db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == doc_id)
            .values(chunk_count=count)
        )
        await self.db.flush()

    # ── Chunk operations ───────────────────────────────────────────

    async def store_chunks(
        self,
        doc_id: UUID,
        chunks: List[Dict[str, Any]],
    ) -> int:
        """
        Bulk-insert embedding chunks for a document.

        Each dict in ``chunks`` must have:
        - content: str
        - chunk_index: int
        - token_count: int
        - embedding: list[float]
        - section_header: str | None
        - metadata_json: str | None
        """
        if not chunks:
            return 0

        for chunk_data in chunks:
            chunk = KnowledgeChunk(
                id=uuid.uuid4(),
                document_id=doc_id,
                chunk_index=chunk_data["chunk_index"],
                content=chunk_data["content"],
                token_count=chunk_data["token_count"],
                embedding=chunk_data["embedding"],
                section_header=chunk_data.get("section_header"),
                metadata_json=chunk_data.get("metadata_json"),
            )
            self.db.add(chunk)

        await self.db.flush()
        return len(chunks)

    async def get_chunks_for_document(
        self, doc_id: UUID
    ) -> List[KnowledgeChunk]:
        """Get all chunks for a document, ordered by chunk_index."""
        result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == doc_id)
            .order_by(KnowledgeChunk.chunk_index)
        )
        return list(result.scalars().all())

    # ── Vector search ──────────────────────────────────────────────

    async def search_similar(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        category: str | None = None,
        similarity_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        pgvector cosine similarity search.

        Uses the ``<=>`` cosine distance operator:
            similarity = 1 - (embedding <=> query_vector)

        Returns list of dicts:
            [{chunk_id, content, section_header, similarity_score,
              document_title, category, document_id}]
        """
        # Build the query embedding as a pgvector literal
        vec_literal = "[" + ",".join(str(f) for f in query_embedding) + "]"

        # Build raw SQL for pgvector cosine search with JOIN.
        # NOTE: Use CAST(... AS vector) instead of ::vector to avoid
        # SQLAlchemy text() misinterpreting :: as named parameter syntax.
        # NOTE: Category filter is added conditionally to avoid asyncpg
        # ambiguous parameter type error when category is NULL.
        category_clause = ""
        params: Dict[str, Any] = {
            "query_vec": vec_literal,
            "threshold": similarity_threshold,
            "top_k": top_k,
        }
        if category is not None:
            category_clause = "AND kd.category = :category"
            params["category"] = category

        sql = text(f"""
            SELECT
                kc.id            AS chunk_id,
                kc.content       AS content,
                kc.section_header AS section_header,
                kc.chunk_index   AS chunk_index,
                kc.document_id   AS document_id,
                kd.title         AS document_title,
                kd.category      AS category,
                kd.source        AS source,
                1 - (kc.embedding <=> CAST(:query_vec AS vector)) AS similarity
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kc.document_id = kd.id
            WHERE kd.is_active = true
              AND (1 - (kc.embedding <=> CAST(:query_vec AS vector))) >= :threshold
              {category_clause}
            ORDER BY similarity DESC
            LIMIT :top_k
        """)

        result = await self.db.execute(sql, params)

        rows = result.fetchall()
        return [
            {
                "chunk_id": str(row.chunk_id),
                "content": row.content,
                "section_header": row.section_header,
                "chunk_index": row.chunk_index,
                "document_id": str(row.document_id),
                "document_title": row.document_title,
                "category": row.category,
                "source": row.source,
                "similarity_score": float(row.similarity),
            }
            for row in rows
        ]

    async def count_documents(
        self, category: str | None = None, active_only: bool = True
    ) -> int:
        """Count documents, optionally filtered by category."""
        stmt = select(func.count(KnowledgeDocument.id))
        if category:
            stmt = stmt.where(KnowledgeDocument.category == category)
        if active_only:
            stmt = stmt.where(KnowledgeDocument.is_active.is_(True))
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def count_chunks(self) -> int:
        """Count total chunks in the knowledge base."""
        result = await self.db.execute(
            select(func.count(KnowledgeChunk.id))
        )
        return result.scalar_one()
