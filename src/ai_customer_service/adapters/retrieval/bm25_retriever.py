from __future__ import annotations

import json

import asyncpg
from rank_bm25 import BM25Okapi

from ...domain.entities import Document


class BM25Retriever:
    """In-memory BM25 retriever built from the FAQ document corpus.

    BM25 is a lexical-matching *boost* in the hybrid retrieval pipeline;
    PGVector semantic search is the primary path. For Chinese content BM25
    keyword overlap is lower than for Latin text, which is acceptable — the
    vector store handles semantic matching. Do NOT patch BM25 with traditional
    NLP tokenisers (jieba etc.); the correct fix for retrieval gaps is to
    ensure all documents have embeddings (hard requirement).
    """

    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents
        tokenized = [doc.content.lower().split() for doc in documents]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    @classmethod
    async def from_db(
        cls, pool: asyncpg.Pool, category: str | None = None
    ) -> "BM25Retriever":
        async with pool.acquire() as conn:
            if category:
                rows = await conn.fetch(
                    "SELECT doc_id, content, metadata, knowledge_type FROM faq_documents "
                    "WHERE metadata->>'category' = $1",
                    category,
                )
            else:
                rows = await conn.fetch(
                    "SELECT doc_id, content, metadata, knowledge_type FROM faq_documents"
                )
        docs = [
            Document(
                doc_id=row["doc_id"],
                content=row["content"],
                metadata={
                    **(json.loads(row["metadata"]) if isinstance(row["metadata"], str)
                       else (dict(row["metadata"]) if row["metadata"] else {})),
                    "knowledge_type": row["knowledge_type"] or "industry_knowledge",
                },
            )
            for row in rows
        ]
        return cls(docs)

    def search(self, query: str, k: int) -> list[Document]:
        if not self._bm25 or not self._documents:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(scores, self._documents), key=lambda x: x[0], reverse=True
        )
        return [
            Document(doc_id=doc.doc_id, content=doc.content, metadata=doc.metadata, score=score)
            for score, doc in ranked[:k]
            if score > 0
        ]

    def rebuild(self, documents: list[Document]) -> None:
        """Hot-reload the index when documents are added."""
        self._documents = documents
        tokenized = [doc.content.lower().split() for doc in documents]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
