from __future__ import annotations

import asyncio
from typing import Any

from ...domain.entities import Document
from .bm25_retriever import BM25Retriever
from .pgvector_store import PGVectorStore
from .reranker import FlagReranker


class HybridRetriever:
    """Combines BM25 + vector search via Reciprocal Rank Fusion (RRF).

    RRF score: score(d) = Σ 1 / (rank_i + k) across result lists,
    where k=60 is the standard smoothing constant.
    """

    RRF_K = 60

    def __init__(
        self,
        vector_store: PGVectorStore,
        bm25: BM25Retriever,
        embedding_client: Any,
        reranker: FlagReranker | None = None,
        k: int = 5,
        min_vector_score: float = 0.0,
    ) -> None:
        self._vector_store = vector_store
        self._bm25 = bm25
        self._embedding_client = embedding_client
        self._reranker = reranker
        self._k = k
        self._min_vector_score = min_vector_score

    async def refresh_bm25(self) -> int:
        """Rebuild the in-memory BM25 index from the current DB state.

        Call this after new documents are embedded so BM25 sees them without
        requiring a process restart. Returns the new document count.
        """
        new_bm25 = await BM25Retriever.from_db(
            self._vector_store._pool,
            category=self._vector_store._category,
        )
        self._bm25.rebuild(new_bm25._documents)
        return len(new_bm25._documents)

    async def retrieve(self, query: str) -> list[Document]:
        fetch_k = self._k * 2

        # Try embedding-based vector search; fall back to BM25-only on error
        try:
            query_embedding = await self._embedding_client.aembed_query(query)
            bm25_res, vector_res = await asyncio.gather(
                asyncio.to_thread(self._bm25.search, query, fetch_k),
                self._vector_store.similarity_search(
                    query_embedding, fetch_k, min_score=self._min_vector_score
                ),
            )
        except Exception:
            # Embedding API unavailable (no balance, network error, etc.)
            # Gracefully degrade to BM25-only retrieval
            bm25_res = await asyncio.to_thread(self._bm25.search, query, fetch_k)
            vector_res = []

        fused = self._rrf_merge(bm25_res, vector_res)[: self._k]

        if self._reranker:
            fused = await asyncio.to_thread(self._reranker.rerank, query, fused)

        return fused

    def _rrf_merge(
        self, list_a: list[Document], list_b: list[Document]
    ) -> list[Document]:
        scores: dict[str, float] = {}
        seen: dict[str, Document] = {}

        for rank, doc in enumerate(list_a):
            scores[doc.doc_id] = scores.get(doc.doc_id, 0.0) + 1.0 / (rank + self.RRF_K)
            seen[doc.doc_id] = doc

        for rank, doc in enumerate(list_b):
            scores[doc.doc_id] = scores.get(doc.doc_id, 0.0) + 1.0 / (rank + self.RRF_K)
            seen[doc.doc_id] = doc

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for doc_id, rrf_score in ranked:
            d = seen[doc_id]
            result.append(
                Document(
                    doc_id=d.doc_id,
                    content=d.content,
                    metadata=d.metadata,
                    score=rrf_score,
                )
            )
        return result
