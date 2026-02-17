# app/domain/services/rag_tax_qa.py
"""
RAG-enhanced Tax Q&A pipeline.

Embeds the user question → searches pgvector for relevant knowledge chunks →
augments the GPT-4o prompt with retrieved context → returns answer + sources.

Falls back gracefully to vanilla GPT-4o when:
- No database session available
- No relevant chunks found (below similarity threshold)
- Any RAG infrastructure error
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger("services.rag_tax_qa")


# ── RAG system prompt template ─────────────────────────────────────

RAG_SYSTEM_PROMPT = """\
You are a helpful Indian tax assistant specializing in GST and ITR.

IMPORTANT: Use the following reference material to answer the user's question.
Cite the source when using information from it. If the reference material
doesn't contain relevant information, answer based on your general knowledge
but mention that.

--- REFERENCE MATERIAL ---
{context}
--- END REFERENCE ---

{base_rules}
"""


# ── result dataclass ───────────────────────────────────────────────


@dataclass
class RAGAnswer:
    """Result of a RAG-enhanced tax Q&A query."""

    answer: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    used_rag: bool = False


# ── main function ──────────────────────────────────────────────────


async def rag_tax_qa(
    question: str,
    lang: str,
    history: list[dict] | None = None,
    db: AsyncSession | None = None,
) -> RAGAnswer:
    """
    RAG-enhanced Tax Q&A pipeline.

    1. Embed the user question
    2. Search pgvector for top-k relevant chunks
    3. If relevant chunks found (score ≥ threshold):
       - Build augmented system prompt with retrieved context
       - Call GPT-4o with context + question + history
       - Return answer + source references
    4. If no relevant chunks (or db is None):
       - Fall back to vanilla tax_qa() from openai_client.py
       - Return answer with used_rag=False
    """
    # If no DB session, fall back to vanilla immediately
    if db is None:
        return await _vanilla_fallback(question, lang, history)

    try:
        # 1. Embed the user question
        from app.infrastructure.vector.embedding_service import embed_text

        query_embedding = await embed_text(question)

        # 2. Search for relevant chunks
        from app.infrastructure.db.repositories.knowledge_repository import (
            KnowledgeRepository,
        )

        repo = KnowledgeRepository(db)
        results = await repo.search_similar(
            query_embedding=query_embedding,
            top_k=settings.RAG_TOP_K,
            similarity_threshold=settings.RAG_SIMILARITY_THRESHOLD,
        )

        # 3. If no relevant chunks, fall back
        if not results:
            logger.debug("No relevant RAG chunks for: %s", question[:100])
            return await _vanilla_fallback(question, lang, history)

        # 4. Build context from retrieved chunks
        context_parts: List[str] = []
        sources: List[Dict[str, Any]] = []

        for r in results:
            header = f"[{r['category'].upper()}] {r['document_title']}"
            if r.get("section_header"):
                header += f" — {r['section_header']}"
            context_parts.append(f"### {header}\n{r['content']}")

            sources.append(
                {
                    "title": r["document_title"],
                    "category": r["category"],
                    "similarity": round(r["similarity_score"], 3),
                    "snippet": r["content"][:200],
                    "source": r.get("source"),
                }
            )

        context = "\n\n".join(context_parts)

        # 5. Build augmented system prompt
        from app.infrastructure.external.openai_client import (
            TAX_QA_SYSTEM_PROMPT,
            _get_client,
        )

        # Base rules from original prompt (everything after the knowledge areas)
        base_rules = (
            "Rules:\n"
            "1. Answer in the SAME language the user asks in\n"
            '2. Cite relevant section numbers (e.g. "Section 16 of CGST Act")\n'
            "3. Keep answers concise (under 300 words) since this is WhatsApp\n"
            "4. If unsure, say so clearly - do not make up information\n"
            "5. For complex cases, recommend consulting a Chartered Accountant (CA)\n"
            "6. Never provide advice on tax evasion\n"
            "7. Include current financial year context where relevant"
        )

        system_prompt = RAG_SYSTEM_PROMPT.format(
            context=context,
            base_rules=base_rules,
        )

        # 6. Call GPT-4o with augmented context
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": f"[lang={lang}] {question}"})

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=800,
        )

        answer = response.choices[0].message.content or ""

        logger.info(
            "RAG answer generated with %d sources for: %s",
            len(sources),
            question[:80],
        )

        return RAGAnswer(answer=answer, sources=sources, used_rag=True)

    except Exception:
        logger.exception("RAG pipeline failed, falling back to vanilla")
        return await _vanilla_fallback(question, lang, history)


# ── vanilla fallback ───────────────────────────────────────────────


async def _vanilla_fallback(
    question: str,
    lang: str,
    history: list[dict] | None = None,
) -> RAGAnswer:
    """Fall back to the original vanilla tax_qa() function."""
    from app.infrastructure.external.openai_client import tax_qa

    answer = await tax_qa(question, lang, history)
    return RAGAnswer(answer=answer, sources=[], used_rag=False)
