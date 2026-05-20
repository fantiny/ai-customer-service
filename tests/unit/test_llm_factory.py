from __future__ import annotations

import pytest

from ai_customer_service.adapters.llm.factory import LLMFactory
from ai_customer_service.infrastructure.config import Settings


def _settings(**kwargs) -> Settings:
    defaults = {
        "LLM_API_KEY": "test-key",
        "LLM_BASE_URL": "http://localhost:8080/v1",
        "LLM_MODEL": "test-model",
        "LLM_TEMPERATURE": 0.0,
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_API_KEY": "test-key",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_build_openai_compat():
    from langchain_openai import ChatOpenAI

    settings = _settings(LLM_PROVIDER="openai_compat")
    llm = LLMFactory.build(settings)
    assert isinstance(llm, ChatOpenAI)
    assert llm.openai_api_base == "http://localhost:8080/v1"


def test_build_openai():
    from langchain_openai import ChatOpenAI

    settings = _settings(LLM_PROVIDER="openai", LLM_BASE_URL="")
    llm = LLMFactory.build(settings)
    assert isinstance(llm, ChatOpenAI)


def test_build_anthropic():
    from langchain_anthropic import ChatAnthropic

    settings = _settings(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="ant-key")
    llm = LLMFactory.build(settings)
    assert isinstance(llm, ChatAnthropic)


def test_build_unknown_provider_raises():
    # LLM_PROVIDER is a Literal in Settings — pydantic rejects unknown values at construction
    with pytest.raises(Exception):
        _settings(LLM_PROVIDER="unknown")  # type: ignore[arg-type]
