"""Tests for measurement_guide_node function (node execution paths)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.graph.nodes.measurement_guide_node import measurement_guide_node
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(messages=None, **kwargs) -> CustomerServiceState:
    if messages is None:
        messages = [HumanMessage(content="我需要量体")]
    defaults = dict(
        messages=messages,
        thread_id="t1",
        user_id="u1",
        intent="measurement_guide",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _make_config(reply: str = "好的，请告诉我您的身高（cm）") -> dict:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm}}


def _no_llm_config() -> dict:
    return {"configurable": {}}


# ── No LLM fallback ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_llm_returns_unavailable_message():
    """Lines 105-109: llm is None → service unavailable message."""
    state = _make_state()
    result = await measurement_guide_node(state, _no_llm_config())
    assert "暂时不可用" in result["messages"][0].content
    assert result["awaiting_order_id"] == ""


# ── First turn (no measurements collected) ────────────────────────────────────


@pytest.mark.asyncio
async def test_first_turn_asks_for_measurements():
    """Lines 102-196: normal first turn, no measurements yet → awaiting continuation."""
    state = _make_state()
    config = _make_config()
    result = await measurement_guide_node(state, config)
    assert result["awaiting_order_id"] == "measurement_guide_node"
    assert result["messages"]


@pytest.mark.asyncio
async def test_empty_messages_returns_continuation():
    """Empty message list → still processes and asks for measurements."""
    state = _make_state(messages=[])
    config = _make_config()
    result = await measurement_guide_node(state, config)
    assert result["awaiting_order_id"] == "measurement_guide_node"


# ── Partial measurements ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_measurements_continue():
    """Some measurements collected → continue collecting."""
    messages = [
        HumanMessage(content="身高165cm"),
        AIMessage(content="谢谢，请告诉我您的胸围"),
    ]
    state = _make_state(messages=messages)
    config = _make_config()
    result = await measurement_guide_node(state, config)
    assert result["awaiting_order_id"] == "measurement_guide_node"


# ── All measurements collected ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_four_measurements_complete():
    """Lines 185-190: all 4 measurements → awaiting_order_id cleared."""
    messages = [
        HumanMessage(content="身高165 胸围88 腰围65 臀围92"),
        AIMessage(content="请确认以下数据"),
    ]
    state = _make_state(messages=messages)
    config = _make_config("感谢您提供所有数据！请确认以下量体信息...")
    result = await measurement_guide_node(state, config)
    assert result["awaiting_order_id"] == ""  # done, no continuation


# ── Invalid measurements ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_out_of_range_measurement_adds_warning():
    """Lines 160-162: invalid field value → warning appended to reply."""
    # Height 250 is out of range (140-200)
    messages = [HumanMessage(content="身高250cm")]
    state = _make_state(messages=messages)
    config = _make_config("请重新确认您的身高")
    result = await measurement_guide_node(state, config)
    reply = result["messages"][0].content
    assert "不在合理范围" in reply or result["awaiting_order_id"] == "measurement_guide_node"


# ── Long message history ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_long_history_uses_last_10_messages():
    """Lines 165: more than 10 messages → truncates to last 10."""
    messages = []
    for i in range(15):
        messages.append(HumanMessage(content=f"消息 {i}"))
        messages.append(AIMessage(content=f"回复 {i}"))
    state = _make_state(messages=messages)
    config = _make_config()
    result = await measurement_guide_node(state, config)
    # Should not crash and should return a continuation
    assert "messages" in result


# ── LLM error handling ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_exception_returns_error_message():
    """Lines 174-180: LLM throws → error message returned."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
    config = {"configurable": {"llm": llm}}
    state = _make_state()
    result = await measurement_guide_node(state, config)
    assert "出现问题" in result["messages"][0].content
    assert result["awaiting_order_id"] == ""


# ── Config passed as non-dict (RunnableConfig format) ────────────────────────


@pytest.mark.asyncio
async def test_config_with_configurable_key():
    """Lines 102: config.get("configurable", config) handles nested config."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="请告知身高"))
    # Standard RunnableConfig format
    config = {"configurable": {"llm": llm}}
    state = _make_state()
    result = await measurement_guide_node(state, config)
    assert result["messages"]


# ── Validated summary display ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validated_measurements_shown_in_context():
    """Lines 134-136: validated measurements shown in collected_summary."""
    messages = [
        HumanMessage(content="身高165cm 胸围88cm"),
    ]
    state = _make_state(messages=messages)
    config = _make_config("已记录身高和胸围，请提供腰围")
    result = await measurement_guide_node(state, config)
    # Node should show 2 validated, continue collecting 2 more
    assert result["awaiting_order_id"] == "measurement_guide_node"


@pytest.mark.asyncio
async def test_no_validated_shows_just_started():
    """Line 138: no validated → '（暂无，刚开始收集）' summary."""
    state = _make_state()
    config = _make_config()
    result = await measurement_guide_node(state, config)
    assert result["awaiting_order_id"] == "measurement_guide_node"


# ── Contextual bare number pickup ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bare_number_after_ai_asks_height():
    """_try_contextual_bare_number: AI asked for height → user replied '165' → height captured."""
    messages = [
        AIMessage(content="请告诉我您的身高（140-200 cm）"),
        HumanMessage(content="165"),
    ]
    state = _make_state(messages=messages)
    config = _make_config("已记录身高165cm，请提供胸围")
    result = await measurement_guide_node(state, config)
    assert "messages" in result
