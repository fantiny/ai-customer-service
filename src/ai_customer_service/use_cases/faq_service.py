from __future__ import annotations

from ..adapters.retrieval.hybrid_retriever import HybridRetriever
from ..domain.entities import Document
from .interfaces import IFAQService


class FAQService(IFAQService):
    """Retrieval service for the FAQ knowledge base."""

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    async def retrieve(self, query: str) -> list[Document]:
        return await self._retriever.retrieve(query)
