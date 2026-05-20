"""Additional router_node tests for missing branches."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import Literal

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from ai_customer_service.graph.nodes.router_node import (
    IntentClassification,
    _build_intent_model,
    _build_router_prompt,
    _compute_is_urgent,
    router_node,
)
from ai_customer_service.graph.state import CustomerServiceState
from ai_customer_service.domain.entities import (
    BusinessProfile, IntentDefinition, UrgencyConfig, SafetyConfig,
)


def _make_state(message: str = "test", **kwargs) -> CustomerServiceState:
    defaults = dict(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="general",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _mock_config(intent: str = "general", confidence: float = 0.95) -> dict:
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=IntentClassification(intent=intent, confidence=confidence)  # type: ignore[arg-type]
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    return {"configurable": {"llm": llm}}


# ── _build_intent_model ───────────────────────────────────────────────────────


def test_build_intent_model_returns_pydantic_model():
    """Line 92: create_model produces a model with intent field."""
    model = _build_intent_model(("product", "faq", "general"))
    assert hasattr(model, "model_fields")
    assert "intent" in model.model_fields


def test_build_intent_model_cached():
    """Same tuple → same cached model."""
    ids = ("a", "b", "c")
    m1 = _build_intent_model(ids)
    m2 = _build_intent_model(ids)
    assert m1 is m2


# ── _build_router_prompt ──────────────────────────────────────────────────────


def test_build_router_prompt_includes_intent_descriptions():
    """Lines 106-115: prompt includes all intent descriptions."""
    profile = MagicMock()
    profile.business_name = "测试店铺"
    intent = MagicMock()
    intent.intent_id = "product"
    intent.description = "商品咨询"
    profile.intents = [intent]
    prompt = _build_router_prompt(profile)
    assert "测试店铺" in prompt
    assert "product" in prompt
    assert "商品咨询" in prompt


# ── _compute_is_urgent ────────────────────────────────────────────────────────


def test_compute_is_urgent_no_profile_no_date():
    """Legacy fallback: no wedding_date → False."""
    assert _compute_is_urgent({}, None) is False


def test_compute_is_urgent_no_profile_date_within_14():
    """Legacy fallback: wedding_date within 14 days → True."""
    soon = (date.today() + timedelta(days=7)).isoformat()
    assert _compute_is_urgent({"wedding_date": soon}, None) is True


def test_compute_is_urgent_no_profile_date_far_away():
    soon = (date.today() + timedelta(days=30)).isoformat()
    assert _compute_is_urgent({"wedding_date": soon}, None) is False


def test_compute_is_urgent_no_profile_invalid_date():
    """Legacy: invalid date → False."""
    assert _compute_is_urgent({"wedding_date": "not-a-date"}, None) is False


def test_compute_is_urgent_with_profile_disabled():
    """Lines 134-136: profile.urgency_config.enabled=False → False."""
    profile = MagicMock()
    profile.urgency_config = UrgencyConfig(enabled=False)
    assert _compute_is_urgent({"wedding_date": date.today().isoformat()}, profile) is False


def test_compute_is_urgent_with_profile_enabled_within_threshold():
    """Profile urgency: deadline within threshold → True."""
    profile = MagicMock()
    soon = (date.today() + timedelta(days=5)).isoformat()
    profile.urgency_config = UrgencyConfig(
        enabled=True, deadline_field="wedding_date", urgent_days_threshold=14
    )
    assert _compute_is_urgent({"wedding_date": soon}, profile) is True


def test_compute_is_urgent_with_profile_no_deadline_field():
    """Lines 137-138: deadline field not in order_context → False."""
    profile = MagicMock()
    profile.urgency_config = UrgencyConfig(
        enabled=True, deadline_field="delivery_date", urgent_days_threshold=14
    )
    assert _compute_is_urgent({"wedding_date": "2026-12-25"}, profile) is False


def test_compute_is_urgent_with_profile_invalid_date():
    """Lines 143-145: invalid deadline date → False."""
    profile = MagicMock()
    profile.urgency_config = UrgencyConfig(
        enabled=True, deadline_field="wedding_date", urgent_days_threshold=14
    )
    assert _compute_is_urgent({"wedding_date": "bad-date"}, profile) is False


# ── router_node with profile ──────────────────────────────────────────────────


def _make_profile_config(intent: str = "product", confidence: float = 0.9):
    intents = (
        IntentDefinition(
            intent_id="product",
            display_name="商品",
            description="商品咨询",
            handler_node="product_node",
        ),
        IntentDefinition(
            intent_id="general",
            display_name="通用",
            description="通用对话",
            handler_node="general_node",
        ),
    )
    profile = BusinessProfile(
        business_id="test",
        business_name="测试",
        intents=intents,
        fallback_intent_id="general",
    )

    # Dynamic model for the profile
    from ai_customer_service.graph.nodes.router_node import _build_intent_model
    model = _build_intent_model(tuple(i.intent_id for i in intents))
    mock_result = model(intent=intent, confidence=confidence)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    return {"configurable": {"llm": llm, "business_profile": profile}}


@pytest.mark.asyncio
async def test_router_with_profile_routes_intent():
    """Lines 163-171: profile.intents path used for intent model and prompt."""
    state = _make_state("推荐一款婚纱")
    config = _make_profile_config("product", 0.9)
    result = await router_node(state, config)
    assert result["intent"] == "product"


@pytest.mark.asyncio
async def test_router_with_profile_db_prompt_override():
    """Lines 167-170: prompt_repo DB prompt takes priority over generated prompt."""
    intents = (
        IntentDefinition(
            intent_id="product",
            display_name="商品",
            description="desc",
            handler_node="product_node",
        ),
    )
    profile = BusinessProfile(
        business_id="test",
        business_name="测试",
        intents=intents,
    )
    from ai_customer_service.graph.nodes.router_node import _build_intent_model
    model = _build_intent_model(("product",))
    mock_result = model(intent="product", confidence=0.9)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value="Custom DB prompt")

    config = {
        "configurable": {
            "llm": llm,
            "business_profile": profile,
            "prompt_repo": prompt_repo,
        }
    }
    state = _make_state("test")
    result = await router_node(state, config)
    assert result["intent"] == "product"
    prompt_repo.get_active_prompt.assert_called_once_with("router_node")


@pytest.mark.asyncio
async def test_router_no_profile_with_db_prompt():
    """Lines 176-178: no profile, prompt_repo provides DB prompt."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=IntentClassification(intent="faq", confidence=0.9)  # type: ignore[arg-type]
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value="DB override prompt")

    config = {"configurable": {"llm": llm, "prompt_repo": prompt_repo}}
    state = _make_state()
    result = await router_node(state, config)
    assert result["intent"] == "faq"


@pytest.mark.asyncio
async def test_router_no_profile_no_db_prompt():
    """Lines 175-179: no profile, prompt_repo returns None → use ROUTER_SYSTEM_PROMPT."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=IntentClassification(intent="faq", confidence=0.9)  # type: ignore[arg-type]
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(return_value=None)

    config = {"configurable": {"llm": llm, "prompt_repo": prompt_repo}}
    state = _make_state()
    result = await router_node(state, config)
    assert result["intent"] == "faq"


@pytest.mark.asyncio
async def test_router_llm_exception_falls_back():
    """Lines 190-192: LLM exception → fallback to general with low_confidence."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    config = {"configurable": {"llm": llm}}
    state = _make_state()
    result = await router_node(state, config)
    assert result["intent"] == "general"  # fallback
    assert result["low_confidence"] is True


@pytest.mark.asyncio
async def test_router_result_none_returns_fallback():
    """Line 199: result is None (from exception) → fallback intent."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("error"))
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    config = {"configurable": {"llm": llm}}
    state = _make_state()
    result = await router_node(state, config)
    assert result["intent"] == "general"
    assert result["low_confidence"] is True


@pytest.mark.asyncio
async def test_router_low_confidence_uses_fallback():
    """Lines 204-208: confidence < 0.55 → fallback intent, low_confidence=True."""
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        return_value=IntentClassification(intent="product", confidence=0.3)  # type: ignore[arg-type]
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    config = {"configurable": {"llm": llm}}
    state = _make_state()
    result = await router_node(state, config)
    assert result["intent"] == "general"
    assert result["low_confidence"] is True
