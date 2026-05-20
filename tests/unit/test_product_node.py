"""Unit tests for product_node — hallucination prevention and DB-backed replies.

Scenarios covered:
- LLM makes tool call → result fed back → LLM generates final answer (happy path)
- LLM skips tool calls → redirect message returned (no fabrication allowed)
- product_service=None → seamless handoff, request_human=True
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.graph.nodes.product_node import product_node
from ai_customer_service.graph.state import CustomerServiceState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(message: str = "推荐婚纱") -> CustomerServiceState:
    return CustomerServiceState(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="product",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )


def _make_product_service(products=None) -> MagicMock:
    svc = MagicMock()
    svc.list_all = AsyncMock(return_value=products or [])
    svc.search = AsyncMock(return_value=products or [])
    svc.get = AsyncMock(return_value=None)
    return svc


def _ai_message_with_tool_call(tool_name: str = "list_all_products") -> AIMessage:
    """Simulate LLM response that includes a tool call."""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {
            "id": "call_001",
            "name": tool_name,
            "args": {},
        }
    ]
    return msg


def _ai_message_no_tool_call(text: str = "推荐一款鱼尾婚纱") -> AIMessage:
    """Simulate LLM response WITHOUT any tool call."""
    msg = AIMessage(content=text)
    msg.tool_calls = []
    return msg


def _config(llm, product_service=None, rules_service=None) -> dict:
    return {
        "configurable": {
            "llm": llm,
            "product_service": product_service,
            "rules_service": rules_service,
            "langfuse_handler": None,
        }
    }


# ── Happy path: LLM calls tool → result used in final answer ──────────────────

@pytest.mark.asyncio
async def test_tool_called_result_returned():
    """When LLM makes a tool call, result is fed back and final answer returned."""
    # First LLM call: returns a tool call
    # Second LLM call (after tool result injected): returns final answer
    call_count = 0
    final_answer = "为您推荐：法式蕾丝鱼尾婚纱（WD-P001），¥12,800，约45天定制。"

    async def fake_ainvoke(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ai_message_with_tool_call("list_all_products")
        return AIMessage(content=final_answer)

    llm = MagicMock()
    llm.ainvoke = fake_ainvoke
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("推荐几款婚纱")
    config = _config(llm, product_service=_make_product_service())

    result = await product_node(state, config=config)

    # Final answer from second LLM call should be returned
    assert final_answer in result["messages"][0].content
    assert call_count == 2  # two LLM calls: extract tool call, then final answer
    assert not result.get("request_human")


@pytest.mark.asyncio
async def test_tool_called_no_hallucinated_urls():
    """URLs not from DB tool output are scrubbed from final answer."""
    call_count = 0
    hallucinated_reply = "推荐：法式鱼尾婚纱 https://taobao.com/item/123 定价¥12,800"

    async def fake_ainvoke(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ai_message_with_tool_call("list_all_products")
        return AIMessage(content=hallucinated_reply)

    llm = MagicMock()
    llm.ainvoke = fake_ainvoke
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("推荐婚纱")
    config = _config(llm, product_service=_make_product_service())

    result = await product_node(state, config=config)

    # Hallucinated taobao URL should be stripped
    assert "taobao.com" not in result["messages"][0].content


# ── No tool call → redirect, no fabrication ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_tool_call_returns_redirect():
    """When LLM skips tool calls, a redirect prompt is returned (no fabrication)."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=_ai_message_no_tool_call("我觉得您适合鱼尾裙"))
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("推荐婚纱")
    config = _config(llm, product_service=_make_product_service())

    result = await product_node(state, config=config)

    reply = result["messages"][0].content
    # The LLM's fabricated text should NOT appear in the reply
    assert "鱼尾裙" not in reply or "款式" in reply  # either redirect or a proper query prompt
    # Should NOT contain any made-up product numbers or prices
    assert "WD-" not in reply  # no fabricated product IDs
    # Should be a redirect/guidance message, not raw LLM content
    assert len(reply) < 150  # short guidance message, not a long product description
    assert not result.get("request_human")


@pytest.mark.asyncio
async def test_no_tool_call_does_not_expose_llm_fabrication():
    """Critical: LLM-generated text without tool call must never reach the user."""
    fabricated = "推荐：魔力鱼尾婚纱（WD-X999），¥99,999，全球限量版！"

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=_ai_message_no_tool_call(fabricated))
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("推荐顶级婚纱")
    config = _config(llm, product_service=_make_product_service())

    result = await product_node(state, config=config)

    reply = result["messages"][0].content
    # None of the fabricated content should appear
    assert "WD-X999" not in reply
    assert "99,999" not in reply
    assert "全球限量版" not in reply


# ── product_service=None → seamless handoff ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_product_service_triggers_handoff():
    """When product_service is None, request_human=True is set (no LLM call)."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="should not be called"))
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("推荐婚纱")
    config = _config(llm, product_service=None)

    result = await product_node(state, config=config)

    assert result.get("request_human") is True
    assert result["handoff_context"]["reason"] == "product_unavailable"
    # LLM should NOT be called
    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_product_service_handoff_context_has_user_question():
    """handoff_context carries user question for human agent."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=""))
    llm.bind_tools = MagicMock(return_value=llm)

    state = _make_state("我想要一件中式秀禾服")
    config = _config(llm, product_service=None)

    result = await product_node(state, config=config)

    assert result["handoff_context"]["user_question"] == "我想要一件中式秀禾服"
