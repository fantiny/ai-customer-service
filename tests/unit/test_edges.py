"""Tests for graph/edges.py — routing logic."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from langgraph.graph import END

from ai_customer_service.graph.edges import route_after_safety, route_after_router
from ai_customer_service.graph.state import CustomerServiceState
from langchain_core.messages import HumanMessage


def _make_state(**kwargs) -> CustomerServiceState:
    defaults = {
        "messages": [HumanMessage(content="test")],
        "thread_id": "t1",
        "user_id": "u1",
        "intent": "general",
        "retrieved_docs": [],
        "pending_action": {},
        "safety_passed": True,
    }
    defaults.update(kwargs)
    return CustomerServiceState(**defaults)


def _no_profile_config() -> dict:
    return {"configurable": {}}


def _profile_config(
    continuation_nodes: frozenset | None = None,
    intent_map: dict | None = None,
    fallback: str = "general",
) -> dict:
    profile = MagicMock()
    profile.continuation_node_ids.return_value = (
        continuation_nodes if continuation_nodes is not None
        else frozenset({"order_read_node", "order_write_node"})
    )
    profile.intent_to_node_map.return_value = (
        intent_map if intent_map is not None
        else {
            "product": "product_node",
            "faq": "faq_node",
            "order_read": "order_read_node",
            "general": "general_node",
        }
    )
    profile.fallback_intent_id = fallback
    return {"configurable": {"business_profile": profile}}


# ── route_after_safety ────────────────────────────────────────────────────────


def test_safety_not_passed_returns_end():
    state = _make_state(safety_passed=False)
    result = route_after_safety(state, _no_profile_config())
    assert result is END


def test_safety_passed_normal_goes_to_router():
    state = _make_state(safety_passed=True, intent="general")
    result = route_after_safety(state, _no_profile_config())
    assert result == "router_node"


def test_safety_continuation_bypasses_router():
    """When intent == node name and node is in continuation_nodes → go directly."""
    state = _make_state(
        safety_passed=True,
        intent="order_read_node",  # awaiting_order_id stored as node name
    )
    result = route_after_safety(state, _no_profile_config())
    assert result == "order_read_node"


def test_safety_transfer_to_human():
    state = _make_state(safety_passed=True, intent="transfer_to_human")
    result = route_after_safety(state, _no_profile_config())
    assert result == "human_escalation_node"


def test_safety_with_profile_uses_profile_continuation_nodes():
    """Profile provides custom continuation nodes — profile.continuation_node_ids() called."""
    state = _make_state(
        safety_passed=True,
        intent="measurement_guide_node",  # custom continuation in profile
    )
    config = _profile_config(continuation_nodes=frozenset({"measurement_guide_node"}))
    result = route_after_safety(state, config)
    assert result == "measurement_guide_node"


def test_safety_with_profile_intent_not_continuation_goes_router():
    state = _make_state(safety_passed=True, intent="faq")
    config = _profile_config(continuation_nodes=frozenset({"order_read_node"}))
    result = route_after_safety(state, config)
    assert result == "router_node"


# ── route_after_router ────────────────────────────────────────────────────────


def test_router_maps_product_intent():
    """product intent → unified_agent_node (read-only consolidation)."""
    state = _make_state(intent="product")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_maps_faq_intent():
    """faq intent → unified_agent_node (read-only consolidation)."""
    state = _make_state(intent="faq")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_maps_order_read():
    """order_read intent → unified_agent_node (read-only consolidation)."""
    state = _make_state(intent="order_read")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_maps_general():
    """general intent → unified_agent_node (read-only consolidation)."""
    state = _make_state(intent="general")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_maps_aftersales_intent():
    """aftersales intent → unified_agent_node (read-only consolidation)."""
    state = _make_state(intent="aftersales")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_maps_order_write():
    """order_write intent → order_write_node (HITL dedicated node)."""
    state = _make_state(intent="order_write")
    result = route_after_router(state, _no_profile_config())
    assert result == "order_write_node"


def test_router_maps_measurement_guide():
    """measurement_guide intent → measurement_guide_node (multi-turn dedicated node)."""
    state = _make_state(intent="measurement_guide")
    result = route_after_router(state, _no_profile_config())
    assert result == "measurement_guide_node"


def test_router_blocked_intent_returns_end():
    state = _make_state(intent="blocked")
    result = route_after_router(state, _no_profile_config())
    assert result is END


def test_router_unknown_intent_falls_back_to_unified():
    """Unknown intent falls back to general → unified_agent_node."""
    state = _make_state(intent="unknown_xyz")
    result = route_after_router(state, _no_profile_config())
    assert result == "unified_agent_node"


def test_router_with_profile_uses_profile_map_to_unified():
    """Profile intents that map to read-only nodes are redirected to unified_agent_node."""
    state = _make_state(intent="product")
    config = _profile_config(
        intent_map={
            "product": "product_node",
            "faq": "faq_node",
            "general": "general_node",
        },
        fallback="general",
    )
    result = route_after_router(state, config)
    assert result == "unified_agent_node"


def test_router_with_profile_order_write_stays_dedicated():
    """order_write_node is NOT redirected to unified_agent_node."""
    state = _make_state(intent="order_write")
    config = _profile_config(
        intent_map={"order_write": "order_write_node", "general": "general_node"},
        fallback="general",
    )
    result = route_after_router(state, config)
    assert result == "order_write_node"


def test_router_with_profile_measurement_guide_stays_dedicated():
    """measurement_guide_node is NOT redirected to unified_agent_node."""
    state = _make_state(intent="measurement_guide")
    config = _profile_config(
        intent_map={"measurement_guide": "measurement_guide_node", "general": "general_node"},
        fallback="general",
    )
    result = route_after_router(state, config)
    assert result == "measurement_guide_node"


def test_router_with_profile_unknown_intent_falls_back():
    """Unknown intent with profile falls back to fallback_intent → unified_agent_node."""
    state = _make_state(intent="completely_unknown")
    config = _profile_config(
        intent_map={"product": "product_node", "general": "general_node"},
        fallback="general",
    )
    result = route_after_router(state, config)
    assert result == "unified_agent_node"
