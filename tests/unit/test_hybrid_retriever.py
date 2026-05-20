from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_customer_service.adapters.retrieval.hybrid_retriever import HybridRetriever
from ai_customer_service.domain.entities import Document


def _make_docs(ids: list[str]) -> list[Document]:
    return [Document(doc_id=d, content=f"content of {d}", score=1.0) for d in ids]


@pytest.fixture
def hybrid_retriever():
    vector_store = MagicMock()
    bm25 = MagicMock()
    embedding_client = MagicMock()
    embedding_client.aembed_query = AsyncMock(return_value=[0.1] * 5)

    vector_store.similarity_search = AsyncMock(
        return_value=_make_docs(["doc_a", "doc_b", "doc_c"])
    )
    bm25.search = MagicMock(return_value=_make_docs(["doc_b", "doc_d", "doc_c"]))

    return HybridRetriever(
        vector_store=vector_store,
        bm25=bm25,
        embedding_client=embedding_client,
        reranker=None,
        k=3,
    )


@pytest.mark.asyncio
async def test_rrf_merge_combines_results(hybrid_retriever):
    docs = await hybrid_retriever.retrieve("退货政策")
    ids = [d.doc_id for d in docs]
    # doc_b and doc_c appear in both lists — should rank highest
    assert "doc_b" in ids
    assert "doc_c" in ids
    assert len(docs) <= 3


@pytest.mark.asyncio
async def test_rrf_scores_are_positive(hybrid_retriever):
    docs = await hybrid_retriever.retrieve("配送")
    for doc in docs:
        assert doc.score > 0


def test_rrf_merge_deduplicates():
    retriever = HybridRetriever(
        vector_store=MagicMock(),
        bm25=MagicMock(),
        embedding_client=MagicMock(),
        k=5,
    )
    list_a = _make_docs(["a", "b", "c"])
    list_b = _make_docs(["b", "c", "d"])  # b and c duplicated
    merged = retriever._rrf_merge(list_a, list_b)
    ids = [d.doc_id for d in merged]
    # No duplicates
    assert len(ids) == len(set(ids))
    # b and c have higher RRF scores (appear in both lists)
    assert ids.index("b") < ids.index("a")
