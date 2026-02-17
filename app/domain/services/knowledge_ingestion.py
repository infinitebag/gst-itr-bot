# app/domain/services/knowledge_ingestion.py
"""
Knowledge ingestion pipeline — chunk + embed + store.

Handles both manual document ingestion and auto-learning from CA review
outcomes (precedent capture).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories.knowledge_repository import KnowledgeRepository
from app.infrastructure.vector.chunking import chunk_document
from app.infrastructure.vector.embedding_service import embed_batch

logger = logging.getLogger("services.knowledge_ingestion")


@dataclass
class IngestionResult:
    """Result of a knowledge document ingestion."""

    document_id: str
    title: str
    chunk_count: int
    category: str


async def ingest_document(
    title: str,
    content: str,
    category: str,
    db: AsyncSession,
    source: str | None = None,
    effective_date: date | None = None,
    metadata: dict | None = None,
) -> IngestionResult:
    """
    Full ingestion pipeline:

    1. Create KnowledgeDocument record
    2. Chunk text via chunk_document()
    3. Embed all chunks via embed_batch()
    4. Store chunks with embeddings in DB
    5. Update document.chunk_count
    6. Commit transaction
    """
    repo = KnowledgeRepository(db)

    # 1. Create document
    doc = await repo.create_document(
        title=title,
        content=content,
        category=category,
        source=source,
        effective_date=effective_date,
        metadata=metadata,
    )
    logger.info("Created knowledge document %s: %s", doc.id, title)

    # 2. Chunk
    chunks = chunk_document(content)
    if not chunks:
        logger.warning("No chunks generated for document %s", doc.id)
        await db.commit()
        return IngestionResult(
            document_id=str(doc.id),
            title=title,
            chunk_count=0,
            category=category,
        )

    logger.info("Generated %d chunks for document %s", len(chunks), doc.id)

    # 3. Embed all chunk texts
    chunk_texts = [c.content for c in chunks]
    embeddings = await embed_batch(chunk_texts)

    # 4. Store chunks with embeddings
    chunk_dicts: List[Dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings):
        chunk_dicts.append(
            {
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "embedding": embedding,
                "section_header": chunk.section_header,
                "metadata_json": None,
            }
        )

    stored = await repo.store_chunks(doc.id, chunk_dicts)

    # 5. Update chunk count
    await repo.update_chunk_count(doc.id, stored)

    # 6. Commit
    await db.commit()

    logger.info(
        "Ingested document %s ('%s'): %d chunks stored",
        doc.id, title, stored,
    )

    return IngestionResult(
        document_id=str(doc.id),
        title=title,
        chunk_count=stored,
        category=category,
    )


async def ingest_ca_precedent(
    assessment_id: UUID,
    db: AsyncSession,
) -> IngestionResult | None:
    """
    Auto-extract knowledge from a completed CA review.

    1. Load RiskAssessment by ID
    2. Build text from risk flags + CA notes + outcome
    3. Ingest as category="ca_precedent"
    """
    from app.infrastructure.db.repositories.risk_assessment_repository import (
        RiskAssessmentRepository,
    )

    risk_repo = RiskAssessmentRepository(db)
    assessment = await risk_repo.get_by_id(assessment_id)
    if not assessment:
        logger.warning("RiskAssessment %s not found for precedent", assessment_id)
        return None

    # Only ingest if CA has provided a final outcome
    if not assessment.ca_final_outcome:
        logger.debug("No CA outcome yet for %s, skipping precedent", assessment_id)
        return None

    # Build knowledge text from assessment
    parts: List[str] = []
    parts.append(f"CA Review Outcome: {assessment.ca_final_outcome}")
    parts.append(f"Risk Score: {assessment.risk_score}/100")
    parts.append(f"Risk Level: {assessment.risk_level}")

    if assessment.risk_flags:
        try:
            flags = json.loads(assessment.risk_flags)
            if flags:
                parts.append("\nRisk Flags Identified:")
                for flag in flags:
                    code = flag.get("code", "UNKNOWN")
                    severity = flag.get("severity", "")
                    evidence = flag.get("evidence", "")
                    parts.append(f"- [{severity}] {code}: {evidence}")
        except (json.JSONDecodeError, TypeError):
            pass

    if assessment.recommended_actions:
        try:
            actions = json.loads(assessment.recommended_actions)
            if actions:
                parts.append("\nRecommended Actions:")
                for action in actions:
                    parts.append(f"- {action.get('action', '')}: {action.get('why', '')}")
        except (json.JSONDecodeError, TypeError):
            pass

    if assessment.ca_override_notes:
        parts.append(f"\nCA Notes: {assessment.ca_override_notes}")

    if assessment.post_filing_outcome:
        parts.append(f"\nPost-Filing Outcome: {assessment.post_filing_outcome}")

    content = "\n".join(parts)
    title = (
        f"CA Precedent: {assessment.ca_final_outcome} "
        f"(Risk {assessment.risk_score}/100)"
    )

    return await ingest_document(
        title=title,
        content=content,
        category="ca_precedent",
        db=db,
        source=f"ca_review:{assessment_id}",
        metadata={
            "assessment_id": str(assessment_id),
            "period_id": str(assessment.period_id),
            "risk_score": assessment.risk_score,
            "risk_level": assessment.risk_level,
            "outcome": assessment.ca_final_outcome,
        },
    )
