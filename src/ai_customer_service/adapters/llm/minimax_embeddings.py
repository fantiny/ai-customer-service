"""MiniMax Embedding adapter.

MiniMax's /v1/embeddings endpoint is NOT OpenAI-compatible:
  - request  : { "model": "embo-01", "texts": [...], "type": "db"|"query" }
  - response : { "vectors": [[float, ...], ...] }

This thin wrapper presents the standard LangChain Embeddings interface so the
rest of the codebase (seed_faq.py, HybridRetriever) can stay provider-agnostic.
"""
from __future__ import annotations

import asyncio
from typing import Any, List

import httpx
from langchain_core.embeddings import Embeddings


class MinimaxEmbeddings(Embeddings):
    """LangChain-compatible wrapper around MiniMax /v1/embeddings."""

    def __init__(self, api_key: str, base_url: str, model: str = "embo-01") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    # ── internal HTTP call ────────────────────────────────────────────────────

    async def _embed(self, texts: list[str], embed_type: str = "db") -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        payload = {"model": self._model, "texts": texts, "type": embed_type}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        vectors = data.get("vectors")
        if not vectors:
            base_resp = data.get("base_resp", {})
            raise ValueError(
                f"MiniMax embeddings returned no vectors. "
                f"code={base_resp.get('status_code')} msg={base_resp.get('status_msg')}"
            )
        return vectors

    # ── LangChain Embeddings interface ────────────────────────────────────────

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return asyncio.get_event_loop().run_until_complete(
            self._embed(texts, embed_type="db")
        )

    def embed_query(self, text: str) -> List[float]:
        results = asyncio.get_event_loop().run_until_complete(
            self._embed([text], embed_type="query")
        )
        return results[0]

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self._embed(texts, embed_type="db")

    async def aembed_query(self, text: str) -> List[float]:
        results = await self._embed([text], embed_type="query")
        return results[0]
