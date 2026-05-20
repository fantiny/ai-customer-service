from __future__ import annotations

from langgraph.graph import END
from langgraph.types import RunnableConfig

from .state import CustomerServiceState

# ── Fallback constants (used when BusinessProfile is not injected) ─────────────
_FALLBACK_CONTINUATION_NODES = frozenset({"order_read_node", "order_write_node"})
_FALLBACK_INTENT_NODE_MAP = {
    "product":           "product_node",
    "faq":               "faq_node",
    "order_read":        "order_read_node",
    "order_write":       "order_write_node",
    "aftersales":        "aftersales_node",
    "general":           "general_node",
    "measurement_guide": "measurement_guide_node",
}
_FALLBACK_FALLBACK_INTENT = "general"

# Handler nodes that are consolidated into unified_agent_node.
# Any intent whose resolved handler_node is in this set is redirected
# to unified_agent_node so the LLM can call all read tools freely,
# enabling natural multi-intent responses in a single turn.
_UNIFIED_AGENT_HANDLER_NODES = frozenset({
    "product_node",
    "faq_node",
    "order_read_node",
    "aftersales_node",
    "general_node",
})


def route_after_safety(state: CustomerServiceState, config: RunnableConfig) -> str:
    """Route after safety check.

    - If safety failed → END (refusal message already in state).
    - If this is a multi-turn continuation (intent == handler node name) → go
      directly to that node, bypassing the router.
    - If customer explicitly requested a human agent → human_escalation_node.
    - Otherwise → router_node for intent classification.

    Continuation node set is read from BusinessProfile when available,
    falling back to the hardcoded wedding-dress defaults.
    """
    if not state.get("safety_passed"):
        return END

    profile = config["configurable"].get("business_profile")
    continuation_nodes = (
        profile.continuation_node_ids() if profile is not None
        else _FALLBACK_CONTINUATION_NODES
    )

    intent = state.get("intent", "general")
    if intent in continuation_nodes:
        return intent  # bypass router, resume the waiting node

    if intent == "transfer_to_human":
        return "human_escalation_node"

    return "router_node"


def route_after_router(state: CustomerServiceState, config: RunnableConfig) -> str:
    """Route to the appropriate handler node based on classified intent.

    Intent-to-node mapping is read from BusinessProfile when available,
    falling back to the hardcoded wedding-dress defaults.

    All read-only handler nodes (product_node, faq_node, order_read_node,
    aftersales_node, general_node) are redirected to unified_agent_node so
    the LLM can call any combination of read tools and synthesise one
    comprehensive response, naturally handling multi-intent messages.

    Dedicated nodes that bypass this consolidation:
    - order_write_node  (HITL interrupt — must stay separate)
    - measurement_guide_node (multi-turn state machine — must stay separate)
    """
    profile = config["configurable"].get("business_profile")
    if profile is not None:
        intent_map = profile.intent_to_node_map()
        fallback_intent = profile.fallback_intent_id
    else:
        intent_map = _FALLBACK_INTENT_NODE_MAP
        fallback_intent = _FALLBACK_FALLBACK_INTENT

    intent = state.get("intent", fallback_intent)
    if intent == "blocked":
        return END

    handler_node = intent_map.get(intent, intent_map.get(fallback_intent, "general_node"))

    # Redirect read-only handlers to the unified agent
    if handler_node in _UNIFIED_AGENT_HANDLER_NODES:
        return "unified_agent_node"

    return handler_node
