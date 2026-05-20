from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models import BaseChatModel


@pytest.fixture
def mock_llm() -> MagicMock:
    """LLM mock that returns a simple AIMessage by default."""
    llm = MagicMock(spec=BaseChatModel)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="模拟回复"))
    # with_structured_output returns a runnable that also has ainvoke
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=MagicMock())
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.fixture
def mock_retriever() -> MagicMock:
    from ai_customer_service.adapters.retrieval.hybrid_retriever import HybridRetriever
    from ai_customer_service.domain.entities import Document

    retriever = MagicMock(spec=HybridRetriever)
    retriever.retrieve = AsyncMock(
        return_value=[
            Document(doc_id="doc1", content="退货政策：7天无理由退货。", score=0.9),
        ]
    )
    return retriever


@pytest.fixture
def mock_order_service() -> MagicMock:
    from ai_customer_service.use_cases.order_service import OrderService

    return MagicMock(spec=OrderService)


def make_graph_config(
    llm: MagicMock,
    retriever: MagicMock | None = None,
    order_service: MagicMock | None = None,
) -> dict:
    return {
        "configurable": {
            "thread_id": "test-thread",
            "user_id": "test-user",
            "llm": llm,
            "retriever": retriever,
            "order_service": order_service,
            "langfuse_handler": None,
        }
    }
