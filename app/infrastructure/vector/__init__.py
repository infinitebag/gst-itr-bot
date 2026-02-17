# app/infrastructure/vector/__init__.py
"""Vector / RAG infrastructure — embeddings, chunking, and similarity search."""

from app.infrastructure.vector.embedding_service import embed_text, embed_batch
from app.infrastructure.vector.chunking import chunk_document, DocumentChunk

__all__ = ["embed_text", "embed_batch", "chunk_document", "DocumentChunk"]
