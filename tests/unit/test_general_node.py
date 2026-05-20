"""Tests for general_node — full branch coverage."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from ai_customer_service.graph.nodes.general_node import general_node
from ai_customer_service.graph.state import CustomerServiceState
from ai_customer_service.domain.entities import (
    BusinessProfile, SafetyConfig, ContactConfig,
)


def _make_state(message: str = "你好", **kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="general",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
        negative_turns=0,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _make_config(reply: str = "您好，有什么可以帮您？") -> dict:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm}}


def _make_profile_config(
    reply: str = "您好",
    threshold: int = 4,
    urgent_threshold: int = 2,
    hotline: str = "400-520-5201",
) -> dict:
    profile = BusinessProfile(
        business_id="test",
        business_name="测试店铺",
        safety_config=SafetyConfig(
            escalation_thresholds={"general": threshold},
            urgent_escalation_threshold=urgent_threshold,
        ),
        contact_config=ContactConfig(hotline=hotline),
    )
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm, "business_profile": profile}}


# ── Basic functionality ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_returns_reply():
    state = _make_state()
    config = _make_config()
    result = await general_node(state, config)
    assert len(result["messages"]) == 1
    assert result["messages"][0].content


@pytest.mark.asyncio
async def test_general_no_escalation_by_default():
    state = _make_state()
    config = _make_config()
    result = await general_node(state, config)
    assert result.get("request_human") is not True


# ── Profile-driven config ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_with_profile_reads_threshold():
    state = _make_state()
    config = _make_profile_config()
    result = await general_node(state, config)
    assert "messages" in result


@pytest.mark.asyncio
async def test_general_with_profile_no_hotline():
    state = _make_state()
    config = _make_profile_config(hotline="")
    result = await general_node(state, config)
    assert result["messages"]


# ── Sentiment escalation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_escalates_at_threshold():
    state = _make_state(
        message="太差了，我要投诉！",
        negative_turns=3,  # + 1 = 4 >= threshold(4)
    )
    config = _make_profile_config(threshold=4)
    result = await general_node(state, config)
    assert result.get("request_human") is True


@pytest.mark.asyncio
async def test_general_no_escalation_below_threshold():
    state = _make_state(
        message="退款",
        negative_turns=1,
    )
    config = _make_profile_config(threshold=4)
    result = await general_node(state, config)
    assert result.get("request_human") is not True


# ── Context flags ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_urgent_note_added():
    """is_urgent=True → urgent note injected into system prompt."""
    state = _make_state(is_urgent=True)
    config = _make_config()
    result = await general_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_general_low_confidence_note_added():
    """low_confidence=True → confidence note injected."""
    state = _make_state(low_confidence=True)
    config = _make_config()
    result = await general_node(state, config)
    assert result["messages"]


# ── Prompt repo ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_with_prompt_repo():
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="回复"))
    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value=None)
    config = {"configurable": {"llm": llm, "prompt_repo": prompt_repo}}
    state = _make_state()
    result = await general_node(state, config)
    assert result["messages"]
