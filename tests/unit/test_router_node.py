from __future__ import annotations

from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from ai_customer_service.graph.nodes.router_node import IntentClassification
from ai_customer_service.graph.nodes.router_node import router_node
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(message: str) -> CustomerServiceState:
    return CustomerServiceState(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="general",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )


def _make_config(intent: Literal["faq", "order_read", "order_write", "product", "aftersales", "general"]) -> dict:
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=IntentClassification(intent=intent, confidence=0.95)
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return {"configurable": {"llm": llm, "langfuse_handler": None}}


@pytest.mark.asyncio
async def test_routes_faq_intent():
    state = _make_state("退货政策是什么？")
    result = await router_node(state, config=_make_config("faq"))
    assert result["intent"] == "faq"


@pytest.mark.asyncio
async def test_routes_order_read_intent():
    state = _make_state("我要查询订单 #12345 的状态")
    result = await router_node(state, config=_make_config("order_read"))
    assert result["intent"] == "order_read"


@pytest.mark.asyncio
async def test_routes_order_write_intent():
    state = _make_state("我要取消订单 WD-20240001")
    result = await router_node(state, config=_make_config("order_write"))
    assert result["intent"] == "order_write"


@pytest.mark.asyncio
async def test_routes_general_intent():
    state = _make_state("你好，谢谢你的帮助")
    result = await router_node(state, config=_make_config("general"))
    assert result["intent"] == "general"


@pytest.mark.asyncio
async def test_router_system_prompt_contains_purchase_decision_rule():
    """ROUTER_SYSTEM_PROMPT must explicitly classify purchase decisions as product intent."""
    from ai_customer_service.graph.nodes.router_node import ROUTER_SYSTEM_PROMPT
    # The prompt must guide LLM to classify "就定这款" as product, not order_write
    assert "就定" in ROUTER_SYSTEM_PROMPT or "购买意向" in ROUTER_SYSTEM_PROMPT or "购买决" in ROUTER_SYSTEM_PROMPT
    # The prompt must warn against misclassifying purchase decisions as order_write
    assert "order_write" in ROUTER_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_purchase_decision_routes_to_product():
    """When customer says '就定这款了' LLM should return product intent."""
    state = _make_state("就定这款云裳鱼尾婚纱了！")
    result = await router_node(state, config=_make_config("product"))
    assert result["intent"] == "product"
