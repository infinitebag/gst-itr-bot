# app/infrastructure/queue/embedding_jobs.py
"""
ARQ background job for asynchronous document ingestion.

For large documents, the admin API can enqueue this job instead of
blocking the HTTP request.  The job handles chunking + embedding + storage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("queue.embedding_jobs")


async def ingest_document_job(
    ctx: Dict[str, Any],
    doc_id: str,
    title: str,
    content: str,
    category: str,
    source: str | None = None,
    effective_date: str | None = None,
    metadata: dict | None = None,
) -> Dict[str, Any]:
    """
    ARQ job — ingest a knowledge document in the background.

    Parameters are all serializable (strings) because they go through Redis.
    """
    from datetime import date as date_type

    from app.core.db import async_session_factory
    from app.domain.services.knowledge_ingestion import ingest_document

    eff_date = None
    if effective_date:
        try:
            eff_date = date_type.fromisoformat(effective_date)
        except ValueError:
            pass

    async with async_session_factory() as db:
        try:
            result = await ingest_document(
                title=title,
                content=content,
                category=category,
                db=db,
                source=source,
                effective_date=eff_date,
                metadata=metadata,
            )
            logger.info(
                "Background ingestion completed: %s (%d chunks)",
                result.title,
                result.chunk_count,
            )
            return {
                "document_id": result.document_id,
                "title": result.title,
                "chunk_count": result.chunk_count,
                "category": result.category,
            }
        except Exception:
            logger.exception("Background ingestion failed for: %s", title)
            raise
