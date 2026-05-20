"""Local embedding client using fastembed (onnxruntime, no GPU/torch required).

Default model: BAAI/bge-small-zh-v1.5
  - 512-dimensional vectors
  - ~90 MB, CPU-only, purpose-built for Chinese text
  - Downloads once to ~/.cache/fastembed on first use

The model is loaded lazily at first call and shared across the process.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_model_cache: dict[str, Any] = {}


def _get_model(model_name: str) -> Any:
    if model_name not in _model_cache:
        from fastembed import TextEmbedding
        logger.info("Loading local embedding model: %s", model_name)
        _model_cache[model_name] = TextEmbedding(model_name)
        logger.info("Local embedding model loaded: %s", model_name)
    return _model_cache[model_name]


class LocalEmbeddingClient:
    """IEmbeddingClient implementation backed by fastembed (fully local)."""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        self._model_name = model_name

    def embed_query(self, text: str) -> list[float]:
        model = _get_model(self._model_name)
        vecs = list(model.embed([text]))
        return [float(v) for v in vecs[0]]

    async def aembed_query(self, text: str) -> list[float]:
        # fastembed is CPU-bound; run synchronously — acceptable for single queries.
        # For bulk embedding, use embed_documents which batches internally.
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        model = _get_model(self._model_name)
        return [[float(v) for v in vec] for vec in model.embed(texts)]
