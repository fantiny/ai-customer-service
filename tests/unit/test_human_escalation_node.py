"""Tests for human_escalation_node."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from ai_customer_service.graph.nodes.human_escalation_node import human_escalation_node
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(message: str) -> CustomerServiceState:
    return CustomerServiceState(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="transfer_to_human",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )


def _make_config(reply: str = "好的，正在为您转接专属顾问，请稍候片刻 💐\n顾问接入后会直接与您沟通，感谢您的耐心等待。") -> dict:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm}}


@pytest.mark.asyncio
async def test_human_escalation_returns_warm_message():
    """Node emits a reply and sets request_human=True."""
    state = _make_state("我要转人工客服")
    config = _make_config()
    result = await human_escalation_node(state, config)
    assert result["request_human"] is True
    assert len(result["messages"]) == 1
    assert result["messages"][0].content  # has content


@pytest.mark.asyncio
async def test_human_escalation_chinese_user_no_translation():
    """Chinese user message → lang_format fast path (no second LLM call)."""
    state = _make_state("请帮我转接人工客服，谢谢")
    llm = MagicMock()
    # lang_format Chinese fast path doesn't call ainvoke for translation
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="正在为您转接专属顾问，请稍候片刻 💐\n感谢您的耐心等待。")
    )
    config = {"configurable": {"llm": llm}}
    result = await human_escalation_node(state, config)
    assert result["request_human"] is True


@pytest.mark.asyncio
async def test_human_escalation_empty_messages_handles_gracefully():
    """If messages is empty, node still runs without error."""
    state = CustomerServiceState(
        messages=[],
        thread_id="t1",
        user_id="u1",
        intent="transfer_to_human",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    config = _make_config()
    result = await human_escalation_node(state, config)
    assert result["request_human"] is True
