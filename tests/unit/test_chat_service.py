"""Unit tests for ChatService.

Covers:
- send_message() with and without extra_config
- extra_config merges into config["configurable"]
- _parse_result() correctly extracts reply_sources
- _parse_result() handles interrupted state
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.use_cases.chat_service import ChatResponse, ChatService


def _make_service(graph_result: dict) -> tuple[ChatService, MagicMock]:
    """Helper: build a ChatService with a mock graph that returns graph_result."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=graph_result)

    message_repo = MagicMock()

    settings = MagicMock()
    settings.LANGFUSE_SECRET_KEY = None
    settings.LANGFUSE_PUBLIC_KEY = None
    settings.LANGFUSE_HOST = None

    def _factory(thread_id, user_id, handler):
        return {"configurable": {"thread_id": thread_id, "user_id": user_id}}

    service = ChatService(
        graph=graph,
        message_repo=message_repo,
        settings=settings,
        graph_config_factory=_factory,
    )
    return service, graph


@pytest.mark.asyncio
async def test_send_message_basic():
    """send_message returns a ChatResponse with reply from AI messages."""
    ai_msg = AIMessage(content="你好，有什么可以帮您？")
    service, graph = _make_service({"messages": [ai_msg]})

    with patch("ai_customer_service.use_cases.chat_service.build_langfuse_handler", return_value=None):
        result = await service.send_message("t1", "u1", "你好")

    assert isinstance(result, ChatResponse)
    assert result.reply == "你好，有什么可以帮您？"
    assert result.status == "complete"
    assert result.reply_sources == []


@pytest.mark.asyncio
async def test_send_message_extra_config_merged():
    """extra_config is merged into config['configurable'] before graph invocation."""
    captured_configs = []

    async def _fake_ainvoke(input_data, config):
        captured_configs.append(config)
        return {"messages": [AIMessage(content="ok")]}

    graph = MagicMock()
    graph.ainvoke = _fake_ainvoke

    settings = MagicMock()
    settings.LANGFUSE_SECRET_KEY = None

    def _factory(thread_id, user_id, handler):
        return {"configurable": {"thread_id": thread_id}}

    service = ChatService(graph=graph, message_repo=MagicMock(), settings=settings, graph_config_factory=_factory)

    sentinel = object()
    with patch("ai_customer_service.use_cases.chat_service.build_langfuse_handler", return_value=None):
        await service.send_message("t1", "u1", "msg", extra_config={"progress_callback": sentinel})

    cfg = captured_configs[0]["configurable"]
    assert cfg.get("progress_callback") is sentinel


@pytest.mark.asyncio
async def test_send_message_no_extra_config_backward_compatible():
    """send_message without extra_config still works (backward compatible)."""
    service, graph = _make_service({"messages": [AIMessage(content="test")]})

    with patch("ai_customer_service.use_cases.chat_service.build_langfuse_handler", return_value=None):
        result = await service.send_message("t1", "u1", "hello")  # no extra_config

    assert result.reply == "test"


def test_parse_result_extracts_reply_sources():
    """_parse_result extracts reply_sources list from graph result."""
    sources = [
        {"type": "knowledge", "id": "doc-1", "title": "退款政策", "knowledge_type": "business_policy"},
        {"type": "order", "id": "ORD-001", "title": "订单 ORD-001"},
    ]
    result = ChatService._parse_result(
        {"messages": [AIMessage(content="已为您查询")], "reply_sources": sources},
        "t1",
    )
    assert result.reply_sources == sources
    assert len(result.reply_sources) == 2


def test_parse_result_empty_reply_sources_when_missing():
    """_parse_result returns [] for reply_sources when key is absent."""
    result = ChatService._parse_result(
        {"messages": [AIMessage(content="ok")]},
        "t1",
    )
    assert result.reply_sources == []


def test_parse_result_interrupted_status():
    """_parse_result returns 'interrupted' status when __interrupt__ is present."""
    from unittest.mock import MagicMock
    interrupt_val = MagicMock()
    interrupt_val.value = {"action": "cancel_order", "order_id": "ORD-001"}
    result = ChatService._parse_result(
        {"__interrupt__": [interrupt_val]},
        "t1",
    )
    assert result.status == "interrupted"
    assert result.reply is None
    assert result.pending_action == {"action": "cancel_order", "order_id": "ORD-001"}


def test_chat_response_default_reply_sources():
    """ChatResponse.reply_sources defaults to [] (not None mutable default)."""
    r1 = ChatResponse(thread_id="t1", reply="hi", status="complete")
    r2 = ChatResponse(thread_id="t2", reply="hey", status="complete")
    assert r1.reply_sources == []
    assert r2.reply_sources == []
    # Mutating one must not affect the other
    r1.reply_sources.append("x")
    assert r2.reply_sources == []
