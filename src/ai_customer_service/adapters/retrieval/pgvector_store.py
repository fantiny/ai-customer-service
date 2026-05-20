from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from ...domain.entities import Document
from ...use_cases.interfaces import IVectorStore


class PGVectorStore(IVectorStore):
    """Stores and retrieves documents using pgvector cosine similarity."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        category: str | None = None,
    ) -> None:
        self._pool = pool
        self._category = category

    async def similarity_search(
        self, query_embedding: list[float], k: int, min_score: float = 0.0
    ) -> list[Document]:  # type: ignore[override]
        """Search by pre-computed embedding vector.

        Args:
            min_score: Minimum cosine similarity (0-1) to include a result.
                       0.0 (default) returns all neighbours; 0.5+ filters out
                       semantically distant documents.
        """
        async with self._pool.acquire() as conn:
            if self._category:
                rows = await conn.fetch(
                    """
                    SELECT doc_id, content, metadata, knowledge_type,
                           1 - (embedding <=> $1::vector) AS score
                    FROM faq_documents
                    WHERE embedding IS NOT NULL
                      AND metadata->>'category' = $3
                      AND (1 - (embedding <=> $1::vector)) >= $4
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                    """,
                    str(query_embedding),
                    k,
                    self._category,
                    min_score,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT doc_id, content, metadata, knowledge_type,
                           1 - (embedding <=> $1::vector) AS score
                    FROM faq_documents
                    WHERE embedding IS NOT NULL
                      AND (1 - (embedding <=> $1::vector)) >= $3
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                    """,
                    str(query_embedding),
                    k,
                    min_score,
                )
        return [
            Document(
                doc_id=row["doc_id"],
                content=row["content"],
                metadata={
                    **(json.loads(row["metadata"]) if isinstance(row["metadata"], str)
                       else (dict(row["metadata"]) if row["metadata"] else {})),
                    "knowledge_type": row["knowledge_type"] or "industry_knowledge",
                },
                score=float(row["score"]),
            )
            for row in rows
        ]

    async def similarity_search_by_text(
        self, query_embedding: list[float], k: int
    ) -> list[Document]:
        return await self.similarity_search(query_embedding, k)

    async def upsert(self, documents: list[Document], embeddings: list[list[float]]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for doc, emb in zip(documents, embeddings):
                    await conn.execute(
                        """
                        INSERT INTO faq_documents (doc_id, content, metadata, embedding, knowledge_type)
                        VALUES ($1, $2, $3, $4::vector, $5)
                        ON CONFLICT (doc_id) DO UPDATE
                          SET content = EXCLUDED.content,
                              metadata = EXCLUDED.metadata,
                              embedding = EXCLUDED.embedding,
                              knowledge_type = EXCLUDED.knowledge_type,
                              updated_at = NOW()
                        """,
                        doc.doc_id or str(uuid.uuid4()),
                        doc.content,
                        json.dumps(doc.metadata),
                        str(emb),
                        doc.metadata.get("knowledge_type", "industry_knowledge"),
                    )
