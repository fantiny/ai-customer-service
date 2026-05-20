from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from ...infrastructure.config import Settings


class LLMFactory:
    """Thin dispatcher: reads resolved connection kwargs from Settings and
    instantiates the appropriate LangChain chat model.

    All provider-specific connection logic lives in Settings.llm_kwargs()
    and Settings.embedding_kwargs() — not here.
    """

    @classmethod
    def build(cls, settings: Settings, callbacks: list[Any] | None = None) -> BaseChatModel:
        provider = settings.LLM_PROVIDER
        kwargs = settings.llm_kwargs()
        if callbacks:
            kwargs["callbacks"] = callbacks

        if provider in ("openai", "openai_compat"):
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(**kwargs)

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(**kwargs)

        if provider == "ollama":
            from langchain_ollama import ChatOllama
            return ChatOllama(**kwargs)

        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            "Choose from: openai, openai_compat, anthropic, ollama"
        )

    @classmethod
    def build_embedding_client(cls, settings: Settings) -> Any:
        """Build an embedding client.

        Provider priority:
          1. EMBEDDING_PROVIDER=local  → fastembed (fully local, no API key needed)
          2. MiniMax base URL          → MinimaxEmbeddings (custom adapter)
          3. Everything else           → OpenAIEmbeddings
        """
        if settings.EMBEDDING_PROVIDER == "local":
            from .local_embedding import LocalEmbeddingClient
            model = settings.EMBEDDING_MODEL or "BAAI/bge-small-zh-v1.5"
            return LocalEmbeddingClient(model)

        base_url = (settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL or "").rstrip("/")
        if "minimaxi.com" in base_url or "minimax" in base_url.lower():
            from .minimax_embeddings import MinimaxEmbeddings
            return MinimaxEmbeddings(
                api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
                base_url=base_url,
                model=settings.EMBEDDING_MODEL or "embo-01",
            )

        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(**settings.embedding_kwargs())
