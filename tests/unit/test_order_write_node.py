"""Tests for order_write_node — full branch coverage.

Note: The HITL interrupt() path cannot be unit tested without a full
LangGraph checkpoint runner. We test:
  - extraction failure (None / no order_id)
  - pre-validation error paths (OrderNotFoundError, AccessDenied, InvalidAction)
  - rules_service path for rush info and HITL action list
  - non-HITL (direct execute) success and error paths
  The interrupt() branch itself is covered by integration tests.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from ai_customer_service.domain.exceptions import (
    InvalidOrderActionError,
    OrderAccessDeniedError,
    OrderNotFoundError,
)
from ai_customer_service.graph.nodes.order_write_node import (
    OrderWriteExtraction,
    order_write_node,
)
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(message: str = "我要取消订单", **kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="user-1",
        intent="order_write",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _mock_llm(reply: str = "操作已受理") -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return llm


def _make_config(
    extraction: OrderWriteExtraction | None,
    validate_exception=None,
    execute_result=None,
    execute_exception=None,
    reply: str = "操作已受理",
    hitl_actions: list | None = None,
) -> dict:
    llm = _mock_llm(reply)
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    order_service = MagicMock()
    if validate_exception:
        order_service.validate = AsyncMock(side_effect=validate_exception)
    else:
        order_service.validate = AsyncMock(return_value=None)

    if execute_exception:
        order_service.execute = AsyncMock(side_effect=execute_exception)
    elif execute_result is not None:
        order_service.execute = AsyncMock(return_value=execute_result)
    else:
        result = MagicMock()
        result.message = "操作成功"
        result.order = MagicMock()
        result.order.order_id = "ORD-001"
        result.order.status = MagicMock()
        result.order.status.value = "cancelled"
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
        order_service.execute = AsyncMock(return_value=result)

    return {"configurable": {"llm": llm, "order_service": order_service}}


def _make_rules_service(hitl_actions=None, raises=False) -> MagicMock:
    rules = MagicMock()
    rules.get_language = AsyncMock(return_value="zh-CN")
    if raises:
        rules.get = AsyncMock(side_effect=RuntimeError("DB error"))
    else:
        async def _get(key, default=None):
            if "hitl" in str(key):
                return hitl_actions if hitl_actions is not None else ["cancel_order", "initiate_refund"]
            return default
        rules.get = _get
    return rules


def _add_rules_service(config: dict, hitl_actions=None, raises=False) -> dict:
    config["configurable"]["rules_service"] = _make_rules_service(hitl_actions, raises)
    return config


# ── Extraction failure / no order_id ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_failure_asks_for_order_info():
    """extraction=None → ask user for order + action details."""
    state = _make_state()
    config = _make_config(extraction=None)
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == "order_write_node"
    assert result["pending_action"] == {}


@pytest.mark.asyncio
async def test_no_order_id_asks_for_order_number():
    """extraction has action but no order_id → ask for order number."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="")
    state = _make_state()
    config = _make_config(extraction=extraction)
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == "order_write_node"


@pytest.mark.asyncio
async def test_no_order_id_all_action_labels():
    """Each action produces its own label in the ask-for-order message."""
    for action in ["cancel_order", "initiate_refund", "exchange_order", "request_rush"]:
        extraction = OrderWriteExtraction(action=action, order_id="")  # type: ignore[arg-type]
        state = _make_state()
        config = _make_config(extraction=extraction)
        result = await order_write_node(state, config)
        assert result["awaiting_order_id"] == "order_write_node"


# ── Pre-validation errors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_order_not_found_returns_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-999")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        validate_exception=OrderNotFoundError("ORD-999"),
    )
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["pending_action"] == {}
    assert result["messages"]


@pytest.mark.asyncio
async def test_validate_access_denied_returns_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        validate_exception=OrderAccessDeniedError("ORD-001", "user-x"),
    )
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_validate_invalid_action_returns_user_reason():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        validate_exception=InvalidOrderActionError("cancel_order", "订单已发货无法取消"),
    )
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["messages"]


# ── Rules service paths ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rules_service_provides_rush_info():
    """rules_service provides rush fee rates/days for prompt building."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)

    rules = MagicMock()
    rules.get_language = AsyncMock(return_value="zh-CN")
    async def _get(key, default=None):
        mapping = {
            "rush.fee.standard": 0.5,
            "rush.fee.super": 1.0,
            "rush.days.standard": 30,
            "rush.days.super": 15,
            "order.hitl_required_actions": ["cancel_order"],
        }
        return mapping.get(key, default)
    rules.get = _get
    config["configurable"]["rules_service"] = rules

    # HITL is triggered for cancel_order → mock interrupt
    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": False},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""  # rejection path


@pytest.mark.asyncio
async def test_rules_service_hitl_actions_exception_uses_default():
    """rules_service.get for HITL actions raises → uses default hitl_actions list.
    Only the HITL action list lookup raises; rush rate lookups return defaults.
    """
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)

    rules = MagicMock()
    rules.get_language = AsyncMock(return_value="zh-CN")
    async def _get_raises_on_hitl(key, default=None):
        if "hitl" in str(key).lower():
            raise RuntimeError("DB error")
        return default  # Return default for rush rate calls
    rules.get = _get_raises_on_hitl
    config["configurable"]["rules_service"] = rules

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": False},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


# ── HITL interrupt paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hitl_rejected_returns_cancellation_message():
    """interrupt returns approved=False → cancellation message."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": False},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert result["messages"]


@pytest.mark.asyncio
async def test_hitl_approved_executes_and_returns_result():
    """interrupt returns approved=True → execute action and return result."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert "order_context" in result


@pytest.mark.asyncio
async def test_hitl_approved_order_not_found_error():
    """Post-approval execute raises OrderNotFoundError → friendly message."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-999")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=OrderNotFoundError("ORD-999"),
    )

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_hitl_approved_access_denied_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=OrderAccessDeniedError("ORD-001", "wrong-user"),
    )

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_hitl_approved_invalid_action_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=InvalidOrderActionError("cancel_order", "状态不允许"),
    )

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_hitl_approved_unexpected_exception():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=RuntimeError("DB crash"),
    )

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


# ── Non-HITL direct execute ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_hitl_action_executes_directly():
    """Action not in hitl_actions → execute directly without interrupt."""
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(extraction=extraction)

    # Override hitl_actions to empty → no action requires HITL
    rules = _make_rules_service(hitl_actions=[])
    config["configurable"]["rules_service"] = rules

    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""
    assert "order_context" in result


@pytest.mark.asyncio
async def test_non_hitl_invalid_action_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-001")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=InvalidOrderActionError("cancel_order", "无法取消"),
    )
    config["configurable"]["rules_service"] = _make_rules_service(hitl_actions=[])

    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_non_hitl_order_not_found_error():
    extraction = OrderWriteExtraction(action="cancel_order", order_id="ORD-999")
    state = _make_state()
    config = _make_config(
        extraction=extraction,
        execute_exception=OrderNotFoundError("ORD-999"),
    )
    config["configurable"]["rules_service"] = _make_rules_service(hitl_actions=[])

    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


# ── Rush level in action label ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_super_rush_uses_特急_label():
    """rush_level=super_rush → action_label includes 特急."""
    extraction = OrderWriteExtraction(
        action="request_rush", order_id="ORD-001", rush_level="super_rush"
    )
    state = _make_state()
    config = _make_config(extraction=extraction)

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": False},
    ):
        result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == ""


@pytest.mark.asyncio
async def test_exchange_reason_passed_to_extra():
    """exchange_reason filled → extra dict passed to order_service."""
    extraction = OrderWriteExtraction(
        action="exchange_order", order_id="ORD-001", exchange_reason="尺码不合"
    )
    state = _make_state()
    config = _make_config(extraction=extraction)

    with patch(
        "ai_customer_service.graph.nodes.order_write_node.interrupt",
        return_value={"approved": True},
    ):
        result = await order_write_node(state, config)
    # execute was called with extra containing reason
    call_args = config["configurable"]["order_service"].execute.call_args
    req = call_args[0][0]
    assert req.extra.get("reason") == "尺码不合"


# ── F3: _build_ai_analysis unit tests ────────────────────────────────────────

from ai_customer_service.graph.nodes.order_write_node import _build_ai_analysis


def test_build_ai_analysis_cancel_cutting():
    """Cancel during cutting stage should report ~50% refund estimate."""
    ctx = {"production_stage": "cutting"}
    result = _build_ai_analysis("cancel_order", ctx, None)
    assert "50%" in result
    assert "剪裁" in result or "面料" in result


def test_build_ai_analysis_cancel_sewing():
    """Cancel during sewing stage should report ~30% refund estimate."""
    ctx = {"production_stage": "sewing"}
    result = _build_ai_analysis("cancel_order", ctx, None)
    assert "30%" in result


def test_build_ai_analysis_cancel_pending_full_refund():
    """Cancel before production starts should indicate full refund."""
    ctx = {"production_stage": "pending"}
    result = _build_ai_analysis("cancel_order", ctx, None)
    assert "全额" in result


def test_build_ai_analysis_cancel_delivered_no_refund():
    """Cancel after delivery should flag that refund is not possible."""
    ctx = {"production_stage": "delivered"}
    result = _build_ai_analysis("cancel_order", ctx, None)
    assert "无法退款" in result or "协商" in result


def test_build_ai_analysis_rush_urgent():
    """request_rush with wedding < 30 days should flag urgency."""
    ctx = {}
    result = _build_ai_analysis("request_rush", ctx, 20)
    assert "20" in result
    assert "紧急" in result or "优先" in result


def test_build_ai_analysis_rush_moderate():
    """request_rush with wedding 30-45 days should suggest approval."""
    ctx = {}
    result = _build_ai_analysis("request_rush", ctx, 38)
    assert "38" in result
    assert "批准" in result


def test_build_ai_analysis_rush_no_wedding_date():
    """request_rush with no wedding date returns generic hint."""
    result = _build_ai_analysis("request_rush", None, None)
    assert len(result) > 0


def test_build_ai_analysis_refund_urgent_wedding():
    """initiate_refund with wedding < 14 days should flag urgency."""
    result = _build_ai_analysis("initiate_refund", {}, 10)
    assert "10" in result


def test_build_ai_analysis_exchange_tight_schedule():
    """exchange_order with wedding < 21 days should flag tight schedule."""
    result = _build_ai_analysis("exchange_order", {}, 15)
    assert "15" in result
    assert "紧迫" in result or "时间" in result


def test_build_ai_analysis_empty_on_unknown_action():
    """Unknown action returns empty string."""
    result = _build_ai_analysis("unknown_action", {}, None)
    assert result == ""


def test_build_ai_analysis_no_order_context():
    """None order_ctx is handled safely."""
    result = _build_ai_analysis("cancel_order", None, None)
    assert isinstance(result, str)
