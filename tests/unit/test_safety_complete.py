"""Additional safety_check_node tests for missing branches."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.domain.entities import BusinessProfile, SafetyConfig
from ai_customer_service.graph.nodes.safety_check_node import (
    _compile_escalation_patterns,
    safety_check_node,
)
from ai_customer_service.graph.state import CustomerServiceState


def _make_state(**kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content="你好")],
        thread_id="t1",
        user_id="u1",
        intent="general",
        retrieved_docs=[],
        pending_action={},
        safety_passed=False,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _config_with_profile(
    keywords: tuple[str, ...] = ("转人工",),
    max_input: int = 2000,
) -> dict:
    profile = BusinessProfile(
        business_id="test",
        business_name="测试",
        safety_config=SafetyConfig(
            escalation_keywords=keywords,
            max_input_length=max_input,
        ),
    )
    return {"configurable": {"business_profile": profile}}


# ── _compile_escalation_patterns ─────────────────────────────────────────────


def test_compile_escalation_patterns_returns_compiled():
    """Line 57: _compile_escalation_patterns LRU-cached function."""
    patterns = _compile_escalation_patterns(("转人工", "找人工"))
    assert len(patterns) == 2
    assert any(p.search("我要转人工") for p in patterns)


def test_compile_escalation_patterns_cached():
    """Second call with same keywords returns cached result."""
    k = ("测试关键词",)
    p1 = _compile_escalation_patterns(k)
    p2 = _compile_escalation_patterns(k)
    assert p1 is p2  # same object from cache


# ── Profile-driven config ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safety_with_profile_uses_profile_keywords():
    """Lines 75-79: profile.safety_config.escalation_keywords used."""
    state = _make_state(messages=[HumanMessage(content="转人工")])
    result = await safety_check_node(state, config=_config_with_profile(("转人工",)))
    assert result["safety_passed"] is True
    assert result["intent"] == "transfer_to_human"


@pytest.mark.asyncio
async def test_safety_with_profile_max_input_respected():
    """max_input_length from profile limits message size."""
    # Profile sets 50-char limit
    state = _make_state(messages=[HumanMessage(content="x" * 51)])
    result = await safety_check_node(
        state, config=_config_with_profile(max_input=50)
    )
    assert result["safety_passed"] is False
    assert "过长" in result["messages"][0].content


# ── Non-human last message ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_human_last_message_passes():
    """Line 102: last message is AI → still passes (reset only, no content check)."""
    state = _make_state(messages=[AIMessage(content="AI reply")])
    result = await safety_check_node(state, config={"configurable": {}})
    assert result["safety_passed"] is True


# ── Multi-turn continuation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_continuation_sets_intent_to_awaiting_node():
    """Lines 131-133: awaiting_order_id in continuation_nodes → intent set."""
    state = _make_state(
        messages=[HumanMessage(content="好的，继续")],
        awaiting_order_id="order_read_node",
    )
    result = await safety_check_node(state, config={"configurable": {}})
    assert result["safety_passed"] is True
    assert result["intent"] == "order_read_node"


@pytest.mark.asyncio
async def test_escape_signal_bypasses_continuation():
    """Escape signal → fall through to normal routing."""
    state = _make_state(
        messages=[HumanMessage(content="算了，没有订单")],
        awaiting_order_id="order_read_node",
    )
    result = await safety_check_node(state, config={"configurable": {}})
    assert result["safety_passed"] is True
    # Should NOT route to order_read_node; falls through to normal
    assert result["intent"] != "order_read_node"


# ── Human escalation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_human_escalation_keyword_detected():
    """Line 139: escalation keyword → transfer_to_human intent."""
    state = _make_state(messages=[HumanMessage(content="我要转人工")])
    result = await safety_check_node(state, config={"configurable": {}})
    assert result["safety_passed"] is True
    assert result["intent"] == "transfer_to_human"


@pytest.mark.asyncio
async def test_human_escalation_english_phrase():
    state = _make_state(messages=[HumanMessage(content="speak to a human please")])
    result = await safety_check_node(state, config={"configurable": {}})
    assert result["intent"] == "transfer_to_human"
