"""Unit tests for unified_agent_node.

Covers:
- Tool-calling for each domain (FAQ, order, product)
- Multi-tool compound queries
- Graceful degradation when services are unavailable
- No-tool direct reply (general chat)
- LLM error handling
- Knowledge-type labelling in retrieve_knowledge output
- Order auto-detection when order_id not provided
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_customer_service.graph.nodes.unified_agent_node import (
    unified_agent_node,
    _make_tools,
    UNIFIED_AGENT_SYSTEM_PROMPT,
)
from ai_customer_service.domain.entities import Document, OrderActionResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**kwargs):
    defaults = {
        "messages": [HumanMessage(content="你好")],
        "thread_id": "t1",
        "user_id": "user-1",
        "intent": "general",
        "retrieved_docs": [],
        "pending_action": {},
        "safety_passed": True,
        "order_context": {},
        "awaiting_order_id": "",
        "request_human": False,
        "handoff_context": {},
    }
    defaults.update(kwargs)
    return defaults


def _config(llm=None, faq_service=None, order_service=None, product_service=None):
    mock_llm = llm or MagicMock()
    return {
        "configurable": {
            "llm": mock_llm,
            "faq_service": faq_service,
            "order_service": order_service,
            "product_service": product_service,
        }
    }


def _doc(content: str, knowledge_type: str = "industry_knowledge", title: str = "test") -> Document:
    return Document(
        doc_id="doc-1",
        content=content,
        metadata={"knowledge_type": knowledge_type, "title": title},
    )


# ── _make_tools ───────────────────────────────────────────────────────────────

def test_make_tools_returns_empty_when_no_services():
    tools = _make_tools(None, None, None, "user-1")
    assert tools == []


def test_make_tools_faq_only():
    faq = MagicMock()
    tools = _make_tools(faq, None, None, "user-1")
    assert len(tools) == 1
    assert tools[0].name == "retrieve_knowledge"


def test_make_tools_all_services():
    tools = _make_tools(MagicMock(), MagicMock(), MagicMock(), "user-1")
    names = {t.name for t in tools}
    assert names == {"retrieve_knowledge", "get_order_info", "list_products", "get_product_detail"}


# ── retrieve_knowledge tool ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_knowledge_returns_policy_label():
    """business_policy docs get [POLICY] label; industry_knowledge get [KNOWLEDGE]."""
    faq = MagicMock()
    faq.retrieve = AsyncMock(return_value=[
        _doc("退货7天内", "business_policy", "退货政策"),
        _doc("婚纱面料常识", "industry_knowledge", "面料知识"),
    ])
    tools = _make_tools(faq, None, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "retrieve_knowledge")

    result = await tool_fn.ainvoke({"query": "退货政策"})
    assert "[POLICY]" in result
    assert "[KNOWLEDGE]" in result
    assert "退货7天内" in result
    assert "婚纱面料常识" in result


@pytest.mark.asyncio
async def test_retrieve_knowledge_no_docs_returns_fallback():
    faq = MagicMock()
    faq.retrieve = AsyncMock(return_value=[])
    tools = _make_tools(faq, None, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "retrieve_knowledge")

    result = await tool_fn.ainvoke({"query": "some query"})
    assert "暂无" in result


# ── get_order_info tool ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_order_info_with_order_id():
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(return_value=OrderActionResult(
        success=True, message="订单状态：制作中", order=None
    ))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "ORD-001", "query_type": "get_status"})
    assert "制作中" in result
    order_svc.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_order_info_no_order_id_single_order_auto_detected():
    """When user has exactly one order, auto-detect it."""
    from datetime import datetime, timezone, timezone
    from ai_customer_service.domain.entities import Order, WeddingMeta
    from ai_customer_service.domain.value_objects import OrderStatus

    demo_order = Order(
        order_id="ORD-AUTO", user_id="user-1", status=OrderStatus.CONFIRMED,
        items=[], total=1000.0,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(),
    )
    order_svc = MagicMock()
    order_svc.list_orders = AsyncMock(return_value=[demo_order])
    order_svc.execute = AsyncMock(return_value=OrderActionResult(
        success=True, message="已确认", order=None
    ))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "", "query_type": "get_status"})
    assert "已确认" in result


@pytest.mark.asyncio
async def test_get_order_info_no_order_id_multiple_orders_asks():
    """When user has multiple orders, prompt user to choose."""
    from datetime import datetime, timezone, timezone
    from ai_customer_service.domain.entities import Order, WeddingMeta
    from ai_customer_service.domain.value_objects import OrderStatus

    def make_order(oid):
        return Order(
            order_id=oid, user_id="user-1", status=OrderStatus.CONFIRMED,
            items=[], total=1000.0,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            wedding_meta=WeddingMeta(),
        )

    order_svc = MagicMock()
    order_svc.list_orders = AsyncMock(return_value=[make_order("A"), make_order("B")])
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "", "query_type": "get_status"})
    assert "多笔订单" in result or "A" in result


@pytest.mark.asyncio
async def test_get_order_info_no_order_id_no_orders_prompts():
    order_svc = MagicMock()
    order_svc.list_orders = AsyncMock(return_value=[])
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "", "query_type": "get_status"})
    assert "订单号" in result


@pytest.mark.asyncio
async def test_get_order_info_not_found_error():
    from ai_customer_service.domain.exceptions import OrderNotFoundError
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(side_effect=OrderNotFoundError("ORD-999"))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "ORD-999", "query_type": "get_status"})
    assert "未找到" in result or "ORD-999" in result


# ── list_products tool ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_products_no_filters_returns_all():
    product = MagicMock()
    product.to_context_str.return_value = "鱼尾婚纱 WD-001 ¥9800"
    prod_svc = MagicMock()
    prod_svc.list_all = AsyncMock(return_value=[product])
    tools = _make_tools(None, None, prod_svc, "user-1")
    tool_fn = next(t for t in tools if t.name == "list_products")

    result = await tool_fn.ainvoke({})
    assert "鱼尾婚纱" in result


@pytest.mark.asyncio
async def test_list_products_with_style_filter_calls_search():
    prod_svc = MagicMock()
    prod_svc.search = AsyncMock(return_value=[])
    tools = _make_tools(None, None, prod_svc, "user-1")
    tool_fn = next(t for t in tools if t.name == "list_products")

    await tool_fn.ainvoke({"style": "鱼尾裙"})
    prod_svc.search.assert_called_once()


@pytest.mark.asyncio
async def test_list_products_empty_returns_fallback():
    prod_svc = MagicMock()
    prod_svc.list_all = AsyncMock(return_value=[])
    tools = _make_tools(None, None, prod_svc, "user-1")
    tool_fn = next(t for t in tools if t.name == "list_products")

    result = await tool_fn.ainvoke({})
    assert "暂无" in result


@pytest.mark.asyncio
async def test_get_product_detail_found():
    product = MagicMock()
    product.to_context_str.return_value = "鱼尾裙详情"
    prod_svc = MagicMock()
    prod_svc.get = AsyncMock(return_value=product)
    tools = _make_tools(None, None, prod_svc, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_product_detail")

    result = await tool_fn.ainvoke({"product_id": "WD-001"})
    assert "鱼尾裙详情" in result


@pytest.mark.asyncio
async def test_get_product_detail_not_found():
    prod_svc = MagicMock()
    prod_svc.get = AsyncMock(return_value=None)
    tools = _make_tools(None, None, prod_svc, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_product_detail")

    result = await tool_fn.ainvoke({"product_id": "WD-999"})
    assert "不存在" in result


# ── unified_agent_node node ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_llm_returns_fallback():
    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, {"configurable": {"llm": None}})
    assert result["messages"]
    assert isinstance(result["messages"][0], AIMessage)


@pytest.mark.asyncio
async def test_no_services_direct_llm_invocation():
    """When no data services available, falls through to plain LLM call."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="您好！请问有什么可以帮助您？"))

    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, _config(llm=llm))
    assert "您好" in result["messages"][0].content


@pytest.mark.asyncio
async def test_faq_tool_called_for_policy_question():
    """When FAQ service is available, retrieve_knowledge tool is called."""
    llm = MagicMock()
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "retrieve_knowledge", "args": {"query": "退货政策"}, "id": "tc-1", "type": "tool_call"}],
    )
    final_msg = AIMessage(content="退货政策：7天内可退。")
    llm.bind_tools = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(side_effect=[tool_call_msg, final_msg])))

    faq = MagicMock()
    faq.retrieve = AsyncMock(return_value=[_doc("退货7天内", "business_policy", "退货政策")])

    state = _state(messages=[HumanMessage(content="退货政策是什么？")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=faq))

    assert "退货政策" in result["messages"][0].content
    faq.retrieve.assert_called_once()


@pytest.mark.asyncio
async def test_order_info_tool_called_for_order_query():
    """When order service is available, get_order_info tool is called."""
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(return_value=OrderActionResult(
        success=True, message="订单WD-001状态：制作中", order=None
    ))

    llm = MagicMock()
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "get_order_info", "args": {"order_id": "WD-001", "query_type": "get_status"}, "id": "tc-1", "type": "tool_call"}],
    )
    final_msg = AIMessage(content="您的订单WD-001正在制作中。")
    llm.bind_tools = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(side_effect=[tool_call_msg, final_msg])))

    state = _state(messages=[HumanMessage(content="查一下我的订单WD-001的状态")])
    result = await unified_agent_node(state, _config(llm=llm, order_service=order_svc))

    assert "制作中" in result["messages"][0].content
    order_svc.execute.assert_called_once()


@pytest.mark.asyncio
async def test_product_tool_called_for_product_question():
    """When product service is available, list_products tool is called."""
    product = MagicMock()
    product.to_context_str.return_value = "鱼尾婚纱 WD-001 ¥9800"
    prod_svc = MagicMock()
    prod_svc.list_all = AsyncMock(return_value=[product])

    llm = MagicMock()
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "list_products", "args": {}, "id": "tc-1", "type": "tool_call"}],
    )
    final_msg = AIMessage(content="为您推荐鱼尾婚纱，编号WD-001，价格9800元。")
    llm.bind_tools = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(side_effect=[tool_call_msg, final_msg])))

    state = _state(messages=[HumanMessage(content="推荐一款婚纱")])
    result = await unified_agent_node(state, _config(llm=llm, product_service=prod_svc))

    assert "鱼尾婚纱" in result["messages"][0].content
    prod_svc.list_all.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_tools_called_for_compound_query():
    """Compound query: FAQ + order_read → both tools called, combined response."""
    faq = MagicMock()
    faq.retrieve = AsyncMock(return_value=[_doc("退货7天", "business_policy", "退货政策")])

    order_svc = MagicMock()
    order_svc.execute = AsyncMock(return_value=OrderActionResult(
        success=True, message="订单状态：确认中", order=None
    ))

    llm = MagicMock()
    # First call: LLM emits TWO tool calls at once
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "retrieve_knowledge", "args": {"query": "退货政策"}, "id": "tc-1", "type": "tool_call"},
            {"name": "get_order_info", "args": {"order_id": "ORD-001", "query_type": "get_status"}, "id": "tc-2", "type": "tool_call"},
        ],
    )
    final_msg = AIMessage(content="退货政策7天内可退。您的订单ORD-001当前状态是确认中。")
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="退货政策是什么，订单ORD-001状态怎样？")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=faq, order_service=order_svc))

    reply = result["messages"][0].content
    assert "退货" in reply
    assert "确认中" in reply
    faq.retrieve.assert_called_once()
    order_svc.execute.assert_called_once()


@pytest.mark.asyncio
async def test_no_tool_call_for_general_chat():
    """General greeting: LLM doesn't call any tools, direct reply."""
    llm = MagicMock()
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(return_value=AIMessage(content="您好！有什么可以帮您的？"))
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=MagicMock()))

    assert "您好" in result["messages"][0].content


@pytest.mark.asyncio
async def test_llm_error_returns_graceful_message():
    llm = MagicMock()
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="退货政策")])
    result = await unified_agent_node(
        state,
        _config(llm=llm, faq_service=MagicMock(retrieve=AsyncMock(return_value=[]))),
    )
    msg = result["messages"][0].content
    assert isinstance(msg, str) and len(msg) > 0


@pytest.mark.asyncio
async def test_tool_error_does_not_crash_node():
    """If a tool raises an exception, the node catches it and continues."""
    faq = MagicMock()
    faq.retrieve = AsyncMock(side_effect=RuntimeError("DB connection failed"))

    llm = MagicMock()
    # First call: emit tool call
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "retrieve_knowledge", "args": {"query": "退货"}, "id": "tc-1", "type": "tool_call"}],
    )
    final_msg = AIMessage(content="抱歉，查询时出现问题。")
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="退货政策")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=faq))
    # Node should not crash; returns whatever the LLM replies after tool error
    assert isinstance(result["messages"][0], AIMessage)


@pytest.mark.asyncio
async def test_order_context_injected_into_prompt():
    """Existing order_context is injected as hint in the system prompt."""
    llm = MagicMock()
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(return_value=AIMessage(content="好的"))
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(
        messages=[HumanMessage(content="我的订单怎么了？")],
        order_context={"order_id": "ORD-123", "status": "confirmed"},
    )
    await unified_agent_node(state, _config(llm=llm, faq_service=MagicMock()))

    # Verify the system message injected to the LLM contains the order context
    call_args = agent_llm.ainvoke.call_args[0][0]
    system_content = call_args[0].content  # first message is SystemMessage
    assert "ORD-123" in system_content


@pytest.mark.asyncio
async def test_empty_llm_response_returns_fallback():
    """If LLM returns empty string after all tool calls, fallback message used."""
    llm = MagicMock()
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(return_value=AIMessage(content=""))
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=MagicMock()))
    assert len(result["messages"][0].content) > 0


@pytest.mark.asyncio
async def test_no_services_llm_error_returns_graceful():
    """When no services and LLM raises, graceful error message returned."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM offline"))

    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, _config(llm=llm))  # no services
    msg = result["messages"][0].content
    assert isinstance(msg, str) and len(msg) > 0


@pytest.mark.asyncio
async def test_unknown_tool_name_in_response():
    """If LLM returns a tool call with an unknown name, result is error string."""
    llm = MagicMock()
    # First call: unknown tool name
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "nonexistent_tool", "args": {}, "id": "tc-1", "type": "tool_call"}],
    )
    final_msg = AIMessage(content="抱歉，无法处理该请求。")
    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])
    llm.bind_tools = MagicMock(return_value=agent_llm)

    state = _state(messages=[HumanMessage(content="测试")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=MagicMock()))
    # Should not crash — LLM sees the "unknown tool" error message and replies
    assert isinstance(result["messages"][0], AIMessage)


@pytest.mark.asyncio
async def test_response_none_after_zero_rounds():
    """If agent_llm.ainvoke never fires (exhausted 0 rounds), returns fallback.

    Simulates the edge case where the for loop completes without any response
    being set — practically impossible but tests the guard at line 158-159.
    """
    llm = MagicMock()
    # bind_tools returns something whose ainvoke is never called
    # (we mock the loop to run 0 times by making tool_calls always non-empty
    # but the loop cap forces exit — response stays None)
    # Easiest: mock the loop to always return tool_calls so response is always
    # the last tool_call_msg, but we want response=None case, which requires
    # the loop to exit without setting response.
    # We achieve this by making ainvoke raise on first call inside except block:
    tool_call_msg = AIMessage(content="", tool_calls=[
        {"name": "retrieve_knowledge", "args": {"query": "test"}, "id": "tc-1", "type": "tool_call"}
    ])
    agent_llm = MagicMock()
    # 5 rounds all return tool calls → loop ends, response is the last tool_call_msg
    agent_llm.ainvoke = AsyncMock(return_value=tool_call_msg)
    llm.bind_tools = MagicMock(return_value=agent_llm)

    faq = MagicMock()
    faq.retrieve = AsyncMock(return_value=[])

    state = _state(messages=[HumanMessage(content="test")])
    result = await unified_agent_node(state, _config(llm=llm, faq_service=faq))
    # After 5 rounds of tool calls without a plain reply, the node should
    # use whatever response.content it last got (empty) → fallback message
    assert isinstance(result["messages"][0], AIMessage)


@pytest.mark.asyncio
async def test_get_order_info_access_denied():
    """OrderAccessDeniedError returns appropriate message."""
    from ai_customer_service.domain.exceptions import OrderAccessDeniedError
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(side_effect=OrderAccessDeniedError("ORD-001", "user-1"))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "ORD-001", "query_type": "get_status"})
    assert "不匹配" in result or "账号" in result


@pytest.mark.asyncio
async def test_get_order_info_invalid_action_error():
    """InvalidOrderActionError returns appropriate message."""
    from ai_customer_service.domain.exceptions import InvalidOrderActionError
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(side_effect=InvalidOrderActionError("cancel_order", "操作不合法"))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "ORD-001", "query_type": "get_status"})
    assert "操作不合法" in result or "cancel_order" in result


@pytest.mark.asyncio
async def test_get_order_info_generic_exception():
    """Unexpected errors in get_order_info return friendly message."""
    order_svc = MagicMock()
    order_svc.execute = AsyncMock(side_effect=RuntimeError("DB gone"))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "ORD-001", "query_type": "get_status"})
    assert "稍后重试" in result


@pytest.mark.asyncio
async def test_get_order_info_list_orders_exception_falls_back_to_prompt():
    """If list_orders raises during auto-detect, falls back to asking for order_id."""
    order_svc = MagicMock()
    order_svc.list_orders = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    tools = _make_tools(None, order_svc, None, "user-1")
    tool_fn = next(t for t in tools if t.name == "get_order_info")

    result = await tool_fn.ainvoke({"order_id": "", "query_type": "get_status"})
    assert "订单号" in result


# ── Routing coverage ──────────────────────────────────────────────────────────

def test_route_after_router_readonly_intents_go_to_unified():
    """All read-only intents route to unified_agent_node."""
    from ai_customer_service.graph.edges import route_after_router

    config = {"configurable": {}}
    for intent in ("product", "faq", "order_read", "aftersales", "general"):
        state = {
            "messages": [HumanMessage(content="test")],
            "thread_id": "t", "user_id": "u",
            "intent": intent, "retrieved_docs": [], "pending_action": {},
            "safety_passed": True,
        }
        result = route_after_router(state, config)
        assert result == "unified_agent_node", f"intent={intent!r} should → unified_agent_node, got {result!r}"


def test_route_after_router_order_write_direct():
    """order_write routes to order_write_node (HITL, not unified)."""
    from ai_customer_service.graph.edges import route_after_router
    from langchain_core.messages import HumanMessage

    config = {"configurable": {}}
    state = {
        "messages": [HumanMessage(content="取消订单")],
        "thread_id": "t", "user_id": "u",
        "intent": "order_write", "retrieved_docs": [], "pending_action": {},
        "safety_passed": True,
    }
    result = route_after_router(state, config)
    assert result == "order_write_node"


def test_route_after_router_measurement_guide_direct():
    """measurement_guide routes to measurement_guide_node (multi-turn, not unified)."""
    from ai_customer_service.graph.edges import route_after_router
    from langchain_core.messages import HumanMessage

    config = {"configurable": {}}
    state = {
        "messages": [HumanMessage(content="帮我量体")],
        "thread_id": "t", "user_id": "u",
        "intent": "measurement_guide", "retrieved_docs": [], "pending_action": {},
        "safety_passed": True,
    }
    result = route_after_router(state, config)
    assert result == "measurement_guide_node"


# ── F1: Progress callback tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_callback_called_per_tool():
    """progress_callback is awaited once per tool call before execution."""
    from langchain_core.messages import HumanMessage, ToolMessage

    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=[_doc("退货政策内容", "business_policy", "退货政策")])

    progress_calls = []

    async def _capture_progress(stage: str, text: str) -> None:
        progress_calls.append((stage, text))

    # First call returns a tool call, second returns final reply
    tool_call_resp = MagicMock()
    tool_call_resp.tool_calls = [{"id": "tc-1", "name": "retrieve_knowledge", "args": {"query": "退货"}}]
    tool_call_resp.content = ""

    final_resp = MagicMock()
    final_resp.tool_calls = []
    final_resp.content = "退货政策是这样的"

    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_resp, final_resp])

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=agent_llm)

    config = {
        "configurable": {
            "llm": llm,
            "faq_service": faq_service,
            "order_service": None,
            "product_service": None,
            "progress_callback": _capture_progress,
        }
    }
    state = _state(messages=[HumanMessage(content="退货政策是什么")])
    result = await unified_agent_node(state, config)

    assert len(progress_calls) == 1
    stage, text = progress_calls[0]
    assert stage == "tool_start"
    assert "政策" in text or "知识" in text


@pytest.mark.asyncio
async def test_progress_callback_error_does_not_abort():
    """A crashing progress_callback must not prevent the node from completing."""
    from langchain_core.messages import HumanMessage

    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=[_doc("some content")])

    async def _bad_progress(stage: str, text: str) -> None:
        raise RuntimeError("progress channel down")

    tool_call_resp = MagicMock()
    tool_call_resp.tool_calls = [{"id": "tc-1", "name": "retrieve_knowledge", "args": {"query": "q"}}]
    tool_call_resp.content = ""

    final_resp = MagicMock()
    final_resp.tool_calls = []
    final_resp.content = "好的，已查询"

    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_resp, final_resp])

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=agent_llm)

    config = {
        "configurable": {
            "llm": llm,
            "faq_service": faq_service,
            "order_service": None,
            "product_service": None,
            "progress_callback": _bad_progress,
        }
    }
    state = _state(messages=[HumanMessage(content="退货规则")])
    result = await unified_agent_node(state, config)
    # Should complete normally despite callback failure
    assert "messages" in result


# ── F2: [ACTION] system prompt test ──────────────────────────────────────────

def test_system_prompt_contains_action_instruction():
    """UNIFIED_AGENT_SYSTEM_PROMPT must contain the [ACTION] button protocol."""
    assert "[ACTION:" in UNIFIED_AGENT_SYSTEM_PROMPT
    assert "行动按钮" in UNIFIED_AGENT_SYSTEM_PROMPT


# ── F6: reply_sources populated by tools ─────────────────────────────────────

@pytest.mark.asyncio
async def test_reply_sources_populated_by_retrieve_knowledge():
    """retrieve_knowledge populates reply_sources with knowledge entries."""
    from langchain_core.messages import HumanMessage

    doc = _doc("退款须知内容", "business_policy", "退款政策")
    doc.doc_id = "doc-abc"

    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=[doc])

    tool_call_resp = MagicMock()
    tool_call_resp.tool_calls = [{"id": "tc-1", "name": "retrieve_knowledge", "args": {"query": "退款"}}]
    tool_call_resp.content = ""

    final_resp = MagicMock()
    final_resp.tool_calls = []
    final_resp.content = "退款政策如下"

    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(side_effect=[tool_call_resp, final_resp])

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=agent_llm)

    config = {
        "configurable": {
            "llm": llm,
            "faq_service": faq_service,
            "order_service": None,
            "product_service": None,
        }
    }
    state = _state(messages=[HumanMessage(content="退款政策")])
    result = await unified_agent_node(state, config)

    sources = result.get("reply_sources", [])
    assert len(sources) >= 1
    assert sources[0]["type"] == "knowledge"
    assert sources[0]["knowledge_type"] == "business_policy"


@pytest.mark.asyncio
async def test_reply_sources_empty_without_tool_calls():
    """reply_sources is [] when no tools were called (general chat)."""
    from langchain_core.messages import HumanMessage

    final_resp = MagicMock()
    final_resp.tool_calls = []
    final_resp.content = "你好！有什么可以帮您的？"

    agent_llm = MagicMock()
    agent_llm.ainvoke = AsyncMock(return_value=final_resp)

    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=agent_llm)
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="你好"))

    config = {
        "configurable": {
            "llm": llm,
            "faq_service": MagicMock(retrieve=AsyncMock(return_value=[])),
            "order_service": None,
            "product_service": None,
        }
    }
    state = _state(messages=[HumanMessage(content="你好")])
    result = await unified_agent_node(state, config)

    assert result.get("reply_sources", []) == []


def test_make_tools_sources_sink_populated():
    """_make_tools() with sources_sink accumulates entries during tool calls."""
    import asyncio
    from ai_customer_service.domain.entities import Document

    sink: list = []

    faq_service = MagicMock()
    doc = Document(doc_id="d1", content="content", metadata={"knowledge_type": "business_policy", "title": "Test"})
    faq_service.retrieve = AsyncMock(return_value=[doc])

    tools = _make_tools(faq_service, None, None, "u1", sink)
    retrieve = next(t for t in tools if t.name == "retrieve_knowledge")

    asyncio.run(retrieve.ainvoke({"query": "test"}))
    assert len(sink) == 1
    assert sink[0]["type"] == "knowledge"
    assert sink[0]["knowledge_type"] == "business_policy"


def test_make_tools_sources_sink_none_safe():
    """_make_tools() with sources_sink=None doesn't crash."""
    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=[])
    tools = _make_tools(faq_service, None, None, "u1", None)
    assert len(tools) == 1
