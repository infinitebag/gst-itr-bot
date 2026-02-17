# app/infrastructure/vector/embedding_service.py
"""
OpenAI embedding service with Redis caching.

Uses ``text-embedding-3-small`` (1536 dims) by default.
Embeddings are deterministic for the same model + input, so they can be
safely cached for days.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import List

from app.core.config import settings

logger = logging.getLogger("vector.embedding")

# Cache TTL: 7 days (embeddings are deterministic for same model)
_CACHE_TTL = 60 * 60 * 24 * 7


# ── helpers ─────────────────────────────────────────────────────────


def _cache_key(text: str) -> str:
    """Build a compact Redis key for an embedding cache entry."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"emb:{settings.EMBEDDING_MODEL}:{h}"


def _get_openai_client():
    """Reuse the lazy AsyncOpenAI singleton from openai_client."""
    from app.infrastructure.external.openai_client import _get_client

    return _get_client()


def _get_redis():
    """Return the async Redis client (may be ``None`` in test)."""
    try:
        from app.infrastructure.cache.redis_client import get_redis_client

        return get_redis_client()
    except Exception:
        return None


# ── public API ──────────────────────────────────────────────────────


async def embed_text(text: str) -> List[float]:
    """
    Embed a single text string → 1536-dimensional float vector.

    Results are cached in Redis for 7 days.
    """
    if not text or not text.strip():
        return [0.0] * settings.EMBEDDING_DIMENSIONS

    # 1. Check Redis cache
    redis = _get_redis()
    if redis:
        try:
            cached = await redis.get(_cache_key(text))
            if cached:
                return json.loads(cached)
        except Exception:
            logger.debug("Redis cache miss or error for embedding")

    # 2. Call OpenAI embeddings API
    client = _get_openai_client()
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    embedding = response.data[0].embedding

    # 3. Cache result in Redis
    if redis:
        try:
            await redis.setex(
                _cache_key(text),
                _CACHE_TTL,
                json.dumps(embedding),
            )
        except Exception:
            logger.debug("Failed to cache embedding in Redis")

    return embedding


async def embed_batch(
    texts: List[str],
    batch_size: int = 100,
) -> List[List[float]]:
    """
    Embed multiple texts in batches.

    OpenAI supports up to 2048 inputs per call, but we use a smaller
    default batch_size for memory safety.
    """
    if not texts:
        return []

    all_embeddings: List[List[float]] = []
    client = _get_openai_client()
    redis = _get_redis()

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        # Separate cached from uncached
        uncached_indices: List[int] = []
        batch_embeddings: List[List[float] | None] = [None] * len(batch)

        if redis:
            for j, t in enumerate(batch):
                try:
                    cached = await redis.get(_cache_key(t))
                    if cached:
                        batch_embeddings[j] = json.loads(cached)
                        continue
                except Exception:
                    pass
                uncached_indices.append(j)
        else:
            uncached_indices = list(range(len(batch)))

        # Embed uncached texts
        if uncached_indices:
            uncached_texts = [batch[j] for j in uncached_indices]
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=uncached_texts,
                dimensions=settings.EMBEDDING_DIMENSIONS,
            )
            for k, emb_data in enumerate(response.data):
                idx = uncached_indices[k]
                batch_embeddings[idx] = emb_data.embedding

                # Cache
                if redis:
                    try:
                        await redis.setex(
                            _cache_key(batch[idx]),
                            _CACHE_TTL,
                            json.dumps(emb_data.embedding),
                        )
                    except Exception:
                        pass

        # Fill any remaining Nones with zero vectors (shouldn't happen)
        for j in range(len(batch_embeddings)):
            if batch_embeddings[j] is None:
                batch_embeddings[j] = [0.0] * settings.EMBEDDING_DIMENSIONS

        all_embeddings.extend(batch_embeddings)  # type: ignore[arg-type]

    return all_embeddings


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Local cosine similarity for optional client-side filtering."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
