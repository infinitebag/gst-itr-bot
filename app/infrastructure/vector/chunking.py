# app/infrastructure/vector/chunking.py
"""
Token-aware document chunking pipeline for RAG.

Uses tiktoken (cl100k_base tokenizer — same as GPT-4o) for accurate
token counting. Splits on paragraph boundaries, then sentences, and
preserves Indian tax document section headers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

import tiktoken

from app.core.config import settings

# ── tokenizer singleton ────────────────────────────────────────────

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


# ── data classes ───────────────────────────────────────────────────


@dataclass
class DocumentChunk:
    """A single chunk of a knowledge document."""

    content: str
    chunk_index: int
    token_count: int
    section_header: str | None = None


# ── section header detection (Indian tax docs) ─────────────────────

_SECTION_PATTERN = re.compile(
    r"^(?:Section\s+\d+[A-Za-z]*"
    r"|Rule\s+\d+[A-Za-z]*"
    r"|Notification\s+No\.\s*\d+"
    r"|Circular\s+No\.\s*\d+"
    r"|Chapter\s+[IVXLCDM\d]+"
    r"|Schedule\s+[IVXLCDM\d]+"
    r"|FORM\s+(?:GSTR|ITR|CMP)[^\n]*)",
    re.IGNORECASE | re.MULTILINE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _extract_section_header(text: str) -> str | None:
    """Extract the nearest section/rule header from a text block."""
    match = _SECTION_PATTERN.search(text)
    if match:
        header = match.group(0).strip()
        # Truncate long headers
        return header[:300] if len(header) > 300 else header
    return None


# ── main chunking function ─────────────────────────────────────────


def chunk_document(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> List[DocumentChunk]:
    """
    Split text into overlapping token-based chunks.

    Parameters
    ----------
    text : str
        Full document text.
    chunk_size : int, optional
        Maximum tokens per chunk. Defaults to ``settings.RAG_CHUNK_SIZE``.
    chunk_overlap : int, optional
        Token overlap between adjacent chunks.
        Defaults to ``settings.RAG_CHUNK_OVERLAP``.

    Returns
    -------
    list[DocumentChunk]
        Ordered list of chunks with content, index, token count, and
        optional section header.
    """
    if chunk_size is None:
        chunk_size = settings.RAG_CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = settings.RAG_CHUNK_OVERLAP

    if not text or not text.strip():
        return []

    encoder = _get_encoder()

    # Step 1: Split into paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Step 2: Further split long paragraphs into sentences
    segments: List[str] = []
    for para in paragraphs:
        para_tokens = len(encoder.encode(para))
        if para_tokens <= chunk_size:
            segments.append(para)
        else:
            # Split by sentences
            sentences = _SENTENCE_SPLIT.split(para)
            for sent in sentences:
                sent = sent.strip()
                if sent:
                    segments.append(sent)

    # Step 3: Merge segments into chunks respecting token limits
    chunks: List[DocumentChunk] = []
    current_segments: List[str] = []
    current_tokens = 0
    current_header: str | None = None
    chunk_idx = 0

    for seg in segments:
        seg_tokens = len(encoder.encode(seg))

        # Detect section header in this segment
        header = _extract_section_header(seg)
        if header:
            current_header = header

        # If single segment exceeds chunk_size, split it forcefully by tokens
        if seg_tokens > chunk_size:
            # Flush current buffer first
            if current_segments:
                chunk_text = "\n\n".join(current_segments)
                chunks.append(
                    DocumentChunk(
                        content=chunk_text,
                        chunk_index=chunk_idx,
                        token_count=current_tokens,
                        section_header=current_header,
                    )
                )
                chunk_idx += 1
                # Overlap: keep tail segments
                current_segments, current_tokens = _apply_overlap(
                    current_segments, encoder, chunk_overlap
                )

            # Force-split the large segment
            tokens = encoder.encode(seg)
            for start in range(0, len(tokens), chunk_size - chunk_overlap):
                end = min(start + chunk_size, len(tokens))
                sub_text = encoder.decode(tokens[start:end])
                sub_tokens = end - start
                chunks.append(
                    DocumentChunk(
                        content=sub_text,
                        chunk_index=chunk_idx,
                        token_count=sub_tokens,
                        section_header=current_header,
                    )
                )
                chunk_idx += 1
            current_segments = []
            current_tokens = 0
            continue

        # Would adding this segment exceed limit?
        if current_tokens + seg_tokens > chunk_size and current_segments:
            chunk_text = "\n\n".join(current_segments)
            chunks.append(
                DocumentChunk(
                    content=chunk_text,
                    chunk_index=chunk_idx,
                    token_count=current_tokens,
                    section_header=current_header,
                )
            )
            chunk_idx += 1
            # Overlap: keep tail segments
            current_segments, current_tokens = _apply_overlap(
                current_segments, encoder, chunk_overlap
            )

        current_segments.append(seg)
        current_tokens += seg_tokens

    # Flush remaining
    if current_segments:
        chunk_text = "\n\n".join(current_segments)
        chunks.append(
            DocumentChunk(
                content=chunk_text,
                chunk_index=chunk_idx,
                token_count=current_tokens,
                section_header=current_header,
            )
        )

    return chunks


def _apply_overlap(
    segments: List[str],
    encoder: tiktoken.Encoding,
    overlap_tokens: int,
) -> tuple[List[str], int]:
    """
    Keep trailing segments that fit within the overlap window.

    Returns (remaining_segments, remaining_token_count).
    """
    if overlap_tokens <= 0 or not segments:
        return [], 0

    kept: List[str] = []
    kept_tokens = 0
    for seg in reversed(segments):
        seg_t = len(encoder.encode(seg))
        if kept_tokens + seg_t > overlap_tokens:
            break
        kept.insert(0, seg)
        kept_tokens += seg_t

    return kept, kept_tokens
