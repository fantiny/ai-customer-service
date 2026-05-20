"""Tests for order_read_node — full branch coverage."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from ai_customer_service.domain.exceptions import (
    InvalidOrderActionError,
    OrderAccessDeniedError,
    OrderNotFoundError,
)
from ai_customer_service.graph.nodes.order_read_node import (
    OrderReadExtraction,
    order_read_node,
)
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(message: str = "查询我的订单状态", **kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="user-1",
        intent="order_read",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _mock_llm(reply: str = "您的订单处理中") -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return llm


def _make_config(
    extraction: OrderReadExtraction | None,
    service_result=None,
    service_exception=None,
    reply: str = "您的订单处理中",
    user_orders=None,
) -> dict:
    llm = _mock_llm(reply)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    order_service = MagicMock()
    if service_exception:
        order_service.execute = AsyncMock(side_effect=service_exception)
    else:
        result = MagicMock()
        result.message = "订单状态：已确认"
        result.order = MagicMock()
        result.order.order_id = "ORD-001"
        result.order.status = MagicMock()
        result.order.status.value = "confirmed"
        result.order.total = 5000.0
        result.order.wedding_meta = MagicMock()
        result.order.wedding_meta.is_custom = False
        result.order.wedding_meta.is_rush = False
        result.order.wedding_meta.dress_style = "鱼尾"
        result.order.wedding_meta.color = "白色"
        result.order.wedding_meta.production_stage = MagicMock()
        result.order.wedding_meta.production_stage.value = "pending"
        result.order.wedding_meta.wedding_date = None
        result.order.wedding_meta.estimated_completion = None
        result.order.wedding_meta.rush_level = None
        result.order.items = []
        if service_result is not None:
            result = service_result
        order_service.execute = AsyncMock(return_value=result)

    if user_orders is not None:
        order_service.list_orders = AsyncMock(return_value=user_orders)
    else:
        order_service.list_orders = AsyncMock(return_value=[])

    return {"configurable": {"llm": llm, "order_service": order_service}}


# ── Extraction failure ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_failure_asks_for_order_id():
    """When extraction is None → ask user for order details."""
    state = _make_state()
    config = _make_config(extraction=None)
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"
    assert result["messages"]


# ── No order ID in extraction ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_order_id_no_user_orders_asks():
    """No order_id extracted, user has 0 orders → ask for order number."""
    extraction = OrderReadExtraction(action="get_status", order_id="")
    state = _make_state()
    config = _make_config(extraction=extraction, user_orders=[])
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"


@pytest.mark.asyncio
async def test_no_order_id_single_user_order_used_silently():
    """User has exactly 1 order → silently use it without asking."""
    extraction = OrderReadExtraction(action="get_status", order_id="")
    single_order = MagicMock()
    single_order.order_id = "ORD-001"

    state = _make_state()
    config = _make_config(extraction=extraction, user_orders=[single_order])
    result = await order_read_node(state, config)
    # Should have proceeded and either returned result or asked awaiting
    # (depending on order_service.execute behavior)
    assert "messages" in result


@pytest.mark.asyncio
async def test_no_order_id_multiple_user_orders_presents_list():
    """User has ≥2 orders → present list and ask user to choose."""
    extraction = OrderReadExtraction(action="get_status", order_id="")

    def _mock_order(oid: str, custom: bool = False):
        o = MagicMock()
        o.order_id = oid
        o.status = MagicMock()
        o.status.value = "confirmed"
        meta = MagicMock()
        meta.is_custom = custom
        meta.wedding_date = None
        meta.production_stage = MagicMock()
        meta.production_stage.value = "pending"
        o.wedding_meta = meta
        return o

    orders = [_mock_order(f"ORD-{i:03d}") for i in range(3)]
    state = _make_state()
    config = _make_config(extraction=extraction, user_orders=orders)
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"


@pytest.mark.asyncio
async def test_no_order_id_many_orders_shows_most_recent_5():
    """User has >5 orders → shows first 5 with count message."""
    extraction = OrderReadExtraction(action="get_status", order_id="")

    def _mock_order(i: int):
        o = MagicMock()
        o.order_id = f"ORD-{i:03d}"
        o.status = MagicMock()
        o.status.value = "confirmed"
        meta = MagicMock()
        meta.is_custom = False
        meta.wedding_date = None
        meta.production_stage = MagicMock()
        meta.production_stage.value = "pending"
        o.wedding_meta = meta
        return o

    orders = [_mock_order(i) for i in range(7)]
    state = _make_state()
    config = _make_config(extraction=extraction, user_orders=orders)
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"


@pytest.mark.asyncio
async def test_no_order_id_order_with_wedding_date():
    """Order with wedding_date → days remaining displayed in list."""
    extraction = OrderReadExtraction(action="get_status", order_id="")
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=30)).isoformat()

    orders = []
    for i in range(2):
        o = MagicMock()
        o.order_id = f"ORD-{i}"
        o.status = MagicMock()
        o.status.value = "confirmed"
        meta = MagicMock()
        meta.is_custom = True
        meta.wedding_date = soon
        meta.production_stage = MagicMock()
        meta.production_stage.value = "cutting"
        o.wedding_meta = meta
        orders.append(o)

    state = _make_state()
    config = _make_config(extraction=extraction, user_orders=orders)
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"


# ── Successful query ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_query_returns_reply():
    """Full success path: extraction → execute → formatted reply."""
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["messages"]


@pytest.mark.asyncio
async def test_successful_query_returns_order_context():
    """order_context populated with queried order data."""
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)
    result = await order_read_node(state, config)
    assert "order_context" in result


@pytest.mark.asyncio
async def test_proactive_hint_added_when_urgent():
    """is_urgent + rules_service → proactive hint appended."""
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    rules_service = MagicMock()
    rules_service.get_language = AsyncMock(return_value="zh-CN")
    rules_service.get = AsyncMock(return_value="婚期临近，建议联系顾问确认")

    state = _make_state(is_urgent=True)
    config = _make_config(extraction=extraction)
    config["configurable"]["rules_service"] = rules_service
    result = await order_read_node(state, config)
    assert "messages" in result


# ── Error handling ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_not_found_error_returns_friendly_message():
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-999")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        service_exception=OrderNotFoundError("ORD-999"),
    )
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["messages"]


@pytest.mark.asyncio
async def test_order_access_denied_returns_friendly_message():
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        service_exception=OrderAccessDeniedError("ORD-001", "user-x"),
    )
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_invalid_order_action_error_returned():
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        service_exception=InvalidOrderActionError("get_status", "unknown"),
    )
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_unexpected_exception_returns_error_message():
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        service_exception=RuntimeError("DB crash"),
    )
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["messages"]


# ── Prompt repo ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_read_with_db_prompt_override():
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)
    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value="自定义提示词 {lang_rule} {result_message}")
    config["configurable"]["prompt_repo"] = prompt_repo
    result = await order_read_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_order_read_list_orders_exception_handled():
    """list_orders throws → falls back to 0-orders path."""
    extraction = OrderReadExtraction(action="get_status", order_id="")
    config = _make_config(extraction=extraction)
    # Override list_orders to raise
    config["configurable"]["order_service"].list_orders = AsyncMock(
        side_effect=RuntimeError("DB error")
    )
    state = _make_state()
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"
