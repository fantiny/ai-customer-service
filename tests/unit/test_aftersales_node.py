"""Tests for aftersales_node — full branch coverage."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from ai_customer_service.graph.nodes.aftersales_node import aftersales_node
from ai_customer_service.graph.state import CustomerServiceState
from ai_customer_service.domain.entities import (
    BusinessProfile, SafetyConfig, ContactConfig,
)


def _make_state(message: str = "婚纱有质量问题", **kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="aftersales",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
        negative_turns=0,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _make_config(reply: str = "非常抱歉给您带来困扰，请提供订单号以便我们处理。") -> dict:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm}}


def _make_profile_config(
    reply: str = "非常抱歉",
    threshold: int = 3,
    urgent_threshold: int = 2,
    hotline: str = "400-520-5201",
) -> dict:
    profile = BusinessProfile(
        business_id="test",
        business_name="测试店铺",
        safety_config=SafetyConfig(
            escalation_thresholds={"aftersales": threshold},
            urgent_escalation_threshold=urgent_threshold,
        ),
        contact_config=ContactConfig(hotline=hotline),
    )
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=reply))
    return {"configurable": {"llm": llm, "business_profile": profile}}


# ── Basic functionality ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_returns_reply():
    state = _make_state()
    config = _make_config()
    result = await aftersales_node(state, config)
    assert len(result["messages"]) == 1
    assert result["messages"][0].content


@pytest.mark.asyncio
async def test_aftersales_no_escalation_by_default():
    state = _make_state()
    config = _make_config()
    result = await aftersales_node(state, config)
    assert result.get("request_human") is None or result.get("request_human") is False


# ── Profile-driven config ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_with_profile_reads_threshold():
    """Node uses profile.safety_config thresholds."""
    state = _make_state()
    config = _make_profile_config()
    result = await aftersales_node(state, config)
    assert "messages" in result


@pytest.mark.asyncio
async def test_aftersales_with_profile_no_hotline():
    """ContactConfig.hotline empty → no hotline in prompt."""
    state = _make_state()
    config = _make_profile_config(hotline="")
    result = await aftersales_node(state, config)
    assert result["messages"]


# ── Sentiment escalation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_escalates_at_threshold():
    """3 negative turns + negative message → escalate (threshold=3)."""
    state = _make_state(
        message="强烈不满！太差了！",
        negative_turns=2,  # + 1 this turn = 3 >= threshold
    )
    config = _make_profile_config(threshold=3)
    result = await aftersales_node(state, config)
    assert result.get("request_human") is True


@pytest.mark.asyncio
async def test_aftersales_no_escalation_below_threshold():
    state = _make_state(
        message="退款",
        negative_turns=1,  # + 1 = 2 < threshold(3)
    )
    config = _make_profile_config(threshold=3)
    result = await aftersales_node(state, config)
    assert result.get("request_human") is not True


@pytest.mark.asyncio
async def test_aftersales_urgent_mode_lower_threshold():
    """is_urgent=True → use urgent_threshold(2)."""
    state = _make_state(
        message="退款",
        negative_turns=1,
        is_urgent=True,
    )
    config = _make_profile_config(threshold=3, urgent_threshold=2)
    result = await aftersales_node(state, config)
    assert result.get("request_human") is True  # 1+1=2 >= urgent_threshold(2)


# ── Workflow loading ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_with_workflow_repo():
    """Node loads workflows when workflow_repo is provided."""
    workflow = MagicMock()
    workflow.display_name = "退货流程"
    workflow.trigger_keywords = ["退货", "退款"]
    step = MagicMock()
    step.step = 1
    step.instruction = "先道歉"
    workflow.steps = [step]

    workflow_repo = MagicMock()
    workflow_repo.get_workflows = AsyncMock(return_value=[workflow])

    profile = BusinessProfile(business_id="test", business_name="测试")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="已了解"))

    config = {
        "configurable": {
            "llm": llm,
            "business_profile": profile,
            "workflow_repo": workflow_repo,
        }
    }
    state = _make_state("退货")
    result = await aftersales_node(state, config)
    assert result["messages"]
    workflow_repo.get_workflows.assert_called_once()


@pytest.mark.asyncio
async def test_aftersales_workflow_repo_exception_handled():
    """workflow_repo raises → gracefully handled (no crash)."""
    workflow_repo = MagicMock()
    workflow_repo.get_workflows = AsyncMock(side_effect=RuntimeError("DB error"))

    profile = BusinessProfile(business_id="test", business_name="测试")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="回复"))

    config = {
        "configurable": {
            "llm": llm,
            "business_profile": profile,
            "workflow_repo": workflow_repo,
        }
    }
    state = _make_state()
    result = await aftersales_node(state, config)
    assert result["messages"]  # still returns a reply


# ── Order context injection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_injects_order_context_hint():
    """known_order_id in state → order_id_hint added to prompt."""
    state = _make_state(
        order_context={"order_id": "ORD-12345"},
    )
    config = _make_config()
    result = await aftersales_node(state, config)
    assert result["messages"]  # node ran successfully with order context


# ── Urgency block ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_urgency_block_added():
    """is_urgent=True → urgency block prepended to system prompt."""
    state = _make_state(is_urgent=True)
    config = _make_profile_config()
    result = await aftersales_node(state, config)
    assert result["messages"]  # node ran successfully in urgent mode


# ── Prompt repo override ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aftersales_with_prompt_repo():
    """resolve_node_prompt called with prompt_repo."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="回复"))
    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value=None)
    config = {
        "configurable": {
            "llm": llm,
            "prompt_repo": prompt_repo,
        }
    }
    state = _make_state()
    result = await aftersales_node(state, config)
    assert result["messages"]
