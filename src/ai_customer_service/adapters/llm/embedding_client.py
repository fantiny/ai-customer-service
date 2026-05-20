"""LangChainEmbeddingClient — concrete IEmbeddingClient wrapping any LangChain embeddings object.

LangChain embedding classes (OpenAIEmbeddings, MinimaxEmbeddings, etc.) all
expose ``aembed_query`` and ``aembed_documents`` but don't inherit from our
domain interface.  This thin adapter bridges the gap so that callers typed
against IEmbeddingClient get full static type-checking while the concrete
LangChain object remains swappable.
"""
from __future__ import annotations

from typing import Any

from ...use_cases.interfaces import IEmbeddingClient


class LangChainEmbeddingClient(IEmbeddingClient):
    """Adapter that wraps a LangChain embeddings instance (duck-typed)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def aembed_query(self, text: str) -> list[float]:
        return await self._client.aembed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)
