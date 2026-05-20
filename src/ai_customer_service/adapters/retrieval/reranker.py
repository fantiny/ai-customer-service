from __future__ import annotations

from ...domain.entities import Document


class FlagReranker:
    """Cross-encoder reranker using FlagEmbedding (opt-in via RERANKER_ENABLED).

    Only imported when the 'reranker' extra is installed.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        try:
            from FlagEmbedding import FlagReranker as _FlagReranker
            self._model = _FlagReranker(model_name, use_fp16=True)  # pragma: no cover
        except ImportError as e:
            raise ImportError(
                "Install the 'reranker' extra to use the reranker: "
                "pip install 'ai-customer-service[reranker]'"
            ) from e

    def rerank(self, query: str, documents: list[Document]) -> list[Document]:
        if not documents:
            return documents
        pairs = [[query, doc.content] for doc in documents]
        scores: list[float] = self._model.compute_score(pairs)
        ranked = sorted(
            zip(scores, documents), key=lambda x: x[0], reverse=True
        )
        return [
            Document(doc_id=doc.doc_id, content=doc.content, metadata=doc.metadata, score=score)
            for score, doc in ranked
        ]
