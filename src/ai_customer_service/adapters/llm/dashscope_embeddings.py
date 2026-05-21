"""DashScope text-embedding-v2 client.

Uses DashScope's native REST API directly (not the OpenAI-compatible layer),
because the compatible layer rejects batched requests from LangChain.

API docs: https://help.aliyun.com/zh/model-studio/developer-reference/text-embedding-api
"""
from __future__ import annotations

import httpx

DASHSCOPE_EMBED_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings"
    "/text-embedding/text-embedding"
)


class DashScopeEmbeddings:
    """Minimal async DashScope embedding client compatible with LangChainEmbeddingClient."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-v2",
        text_type: str = "document",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._text_type = text_type

    # ── single text ────────────────────────────────────────────────────────────

    async def aembed_query(self, text: str) -> list[float]:
        return (await self._call([text]))[0]

    # ── batch ─────────────────────────────────────────────────────────────────

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        # DashScope allows up to 25 texts per request
        results: list[list[float]] = []
        for i in range(0, len(texts), 25):
            batch = texts[i : i + 25]
            results.extend(await self._call(batch))
        return results

    # ── internal ──────────────────────────────────────────────────────────────

    async def _call(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                DASHSCOPE_EMBED_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "input": {"texts": texts},
                    "parameters": {"text_type": self._text_type},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data["output"]["embeddings"]
            # Sort by index to preserve order
            embeddings.sort(key=lambda e: e["text_index"])
            return [e["embedding"] for e in embeddings]
