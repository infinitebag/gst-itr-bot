# app/api/v1/routes/knowledge.py
"""
Admin-only Knowledge Base management endpoints.

Provides CRUD for knowledge documents and vector similarity search.
Auth: ``X-Admin-Token`` header or ``admin_session`` cookie.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_token
from app.api.v1.envelope import ok, error
from app.core.db import get_db

from app.api.v1.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)

logger = logging.getLogger("api.v1.knowledge")

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base (RAG)"])


# ── Ingest ─────────────────────────────────────────────────────────


@router.post("/ingest", summary="Ingest a knowledge document")
async def ingest_document(
    body: KnowledgeIngestRequest,
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a text document into the knowledge base.

    Auto-chunks the text, embeds each chunk via OpenAI, and stores
    in pgvector for future RAG retrieval.
    """
    from app.domain.services.knowledge_ingestion import ingest_document as do_ingest

    try:
        result = await do_ingest(
            title=body.title,
            content=body.content,
            category=body.category,
            db=db,
            source=body.source,
            effective_date=body.effective_date,
            metadata=body.metadata,
        )
    except Exception as exc:
        logger.exception("Knowledge ingestion failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(
        data=KnowledgeIngestResponse(
            document_id=result.document_id,
            title=result.title,
            chunk_count=result.chunk_count,
            category=result.category,
        ).model_dump()
    )


# ── Search ─────────────────────────────────────────────────────────


@router.get("/search", summary="Vector similarity search")
async def search_knowledge(
    q: str = Query(..., min_length=3, description="Search query"),
    category: str | None = Query(None, description="Filter by category"),
    top_k: int = Query(5, ge=1, le=20),
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Search the knowledge base using semantic similarity.

    Embeds the query and performs a pgvector cosine similarity search
    against all active knowledge chunks.
    """
    from app.infrastructure.vector.embedding_service import embed_text
    from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository

    try:
        query_embedding = await embed_text(q)
        repo = KnowledgeRepository(db)
        results = await repo.search_similar(
            query_embedding=query_embedding,
            top_k=top_k,
            category=category,
            similarity_threshold=threshold,
        )
    except Exception as exc:
        logger.exception("Knowledge search failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return ok(
        data=[
            KnowledgeSearchResult(
                chunk_content=r["content"],
                section_header=r.get("section_header"),
                similarity=round(r["similarity_score"], 4),
                document_title=r["document_title"],
                category=r["category"],
                source=r.get("source"),
                document_id=r["document_id"],
            ).model_dump()
            for r in results
        ]
    )


# ── Document CRUD ──────────────────────────────────────────────────


@router.get("/documents", summary="List knowledge documents")
async def list_documents(
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """List all knowledge base documents."""
    from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository

    repo = KnowledgeRepository(db)
    docs = await repo.list_documents(category=category, limit=limit, offset=offset)
    total = await repo.count_documents(category=category)

    return ok(
        data={
            "total": total,
            "documents": [
                KnowledgeDocumentResponse(
                    id=str(d.id),
                    title=d.title,
                    category=d.category,
                    source=d.source,
                    chunk_count=d.chunk_count,
                    is_active=d.is_active,
                    effective_date=d.effective_date,
                    created_at=d.created_at.isoformat() if d.created_at else None,
                ).model_dump()
                for d in docs
            ],
        }
    )


@router.get("/documents/{doc_id}", summary="Get document detail")
async def get_document(
    doc_id: UUID,
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """Get a single knowledge document with metadata."""
    from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository

    repo = KnowledgeRepository(db)
    doc = await repo.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return ok(
        data=KnowledgeDocumentResponse(
            id=str(doc.id),
            title=doc.title,
            category=doc.category,
            source=doc.source,
            chunk_count=doc.chunk_count,
            is_active=doc.is_active,
            effective_date=doc.effective_date,
            created_at=doc.created_at.isoformat() if doc.created_at else None,
        ).model_dump()
    )


@router.delete("/documents/{doc_id}", summary="Deactivate document")
async def deactivate_document(
    doc_id: UUID,
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a knowledge document (set is_active = False)."""
    from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository

    repo = KnowledgeRepository(db)
    success = await repo.deactivate_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.commit()
    return ok(data={"deactivated": True, "document_id": str(doc_id)})


# ── Stats ──────────────────────────────────────────────────────────


@router.get("/stats", summary="Knowledge base statistics")
async def knowledge_stats(
    _: None = Depends(require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge base statistics."""
    from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository

    repo = KnowledgeRepository(db)
    total_docs = await repo.count_documents()
    total_chunks = await repo.count_chunks()

    # Per-category counts
    categories = {}
    for cat in ("gst", "itr", "general", "ca_precedent", "circular"):
        categories[cat] = await repo.count_documents(category=cat)

    return ok(
        data={
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "by_category": categories,
        }
    )
