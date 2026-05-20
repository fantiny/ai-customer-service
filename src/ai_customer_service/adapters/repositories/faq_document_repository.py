"""FAQDocumentRepository — persistence layer for knowledge-base documents.

Centralises all raw SQL that was previously scattered across the workspace
REST router.  The router becomes a thin HTTP adapter; business logic and
query construction live here.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg


@dataclass
class FAQDocumentRow:
    """Lightweight read model returned by repository queries."""
    doc_id: str
    content: str
    title: str
    category: str
    created_at: datetime | None = None
    has_embedding: bool = False
    knowledge_type: str = "industry_knowledge"


def _parse_metadata(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return dict(raw)


def _row_to_doc(row: asyncpg.Record) -> FAQDocumentRow:
    meta = _parse_metadata(row["metadata"])
    return FAQDocumentRow(
        doc_id=row["doc_id"],
        content=row["content"],
        title=meta.get("title", ""),
        category=meta.get("category", ""),
        created_at=row.get("created_at"),
        has_embedding=row.get("has_embedding", False),
        knowledge_type=row.get("knowledge_type") or "industry_knowledge",
    )


class FAQDocumentRepository:
    """CRUD + embedding operations for the faq_documents table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def list_all(self) -> list[FAQDocumentRow]:
        """Return all documents ordered by creation date, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT doc_id, content, metadata, knowledge_type, created_at,
                       (embedding IS NOT NULL) AS has_embedding
                  FROM faq_documents
                 ORDER BY created_at DESC
                """
            )
        return [_row_to_doc(r) for r in rows]

    async def get(self, doc_id: str) -> FAQDocumentRow | None:
        """Return a single document or None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT doc_id, content, metadata, knowledge_type, created_at,
                       (embedding IS NOT NULL) AS has_embedding
                  FROM faq_documents
                 WHERE doc_id = $1
                """,
                doc_id,
            )
        return _row_to_doc(row) if row else None

    async def list_without_embedding(self, category: str = "all") -> list[dict[str, str]]:
        """Return (doc_id, content) for documents that still need embedding."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT doc_id, content
                  FROM faq_documents
                 WHERE embedding IS NULL
                   AND ($1 = 'all' OR metadata->>'category' = $1)
                 ORDER BY created_at
                """,
                category,
            )
        return [{"doc_id": r["doc_id"], "content": r["content"]} for r in rows]

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create(self, content: str, title: str, category: str) -> FAQDocumentRow:
        """Insert a new document. Embedding is NULL until explicitly generated."""
        doc_id = str(uuid.uuid4())
        metadata = json.dumps({"title": title, "category": category})
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO faq_documents (doc_id, content, metadata, embedding, created_at, updated_at)
                VALUES ($1, $2, $3::jsonb, NULL, NOW(), NOW())
                RETURNING doc_id, content, metadata, created_at,
                          (embedding IS NOT NULL) AS has_embedding
                """,
                doc_id, content, metadata,
            )
        return _row_to_doc(row)

    async def update(self, doc_id: str, content: str, title: str, category: str) -> FAQDocumentRow | None:
        """Update content and metadata. Clears embedding so it must be re-generated."""
        metadata = json.dumps({"title": title, "category": category})
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE faq_documents
                   SET content  = $2,
                       metadata = $3::jsonb,
                       embedding = NULL,        -- force re-embed after content change
                       updated_at = NOW()
                 WHERE doc_id = $1
                RETURNING doc_id, content, metadata, created_at,
                          (embedding IS NOT NULL) AS has_embedding
                """,
                doc_id, content, metadata,
            )
        return _row_to_doc(row) if row else None

    async def delete(self, doc_id: str) -> bool:
        """Delete a document. Returns True if a row was removed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM faq_documents WHERE doc_id = $1", doc_id
            )
        return result.endswith("1")

    # ── Embedding ─────────────────────────────────────────────────────────────

    async def save_embedding(self, doc_id: str, vector: list[float]) -> None:
        """Persist a pre-computed embedding vector for the given document."""
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE faq_documents SET embedding = $1::vector, updated_at = NOW() WHERE doc_id = $2",
                vector_str, doc_id,
            )

    async def save_embeddings_batch(
        self, items: list[dict[str, Any]]
    ) -> int:
        """Persist embeddings for multiple documents.

        Each item must have ``doc_id`` (str) and ``vector`` (list[float]).
        Returns the number of rows updated.
        """
        count = 0
        async with self._pool.acquire() as conn:
            for item in items:
                vector_str = "[" + ",".join(str(v) for v in item["vector"]) + "]"
                await conn.execute(
                    "UPDATE faq_documents SET embedding = $1::vector, updated_at = NOW() WHERE doc_id = $2",
                    vector_str, item["doc_id"],
                )
                count += 1
        return count
