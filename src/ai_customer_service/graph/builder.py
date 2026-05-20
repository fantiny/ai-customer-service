from __future__ import annotations

from typing import Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as CompiledGraph

from .edges import route_after_router, route_after_safety
from .nodes.aftersales_node import aftersales_node
from .nodes.faq_node import faq_node
from .nodes.general_node import general_node
from .nodes.human_escalation_node import human_escalation_node
from .nodes.measurement_guide_node import measurement_guide_node
from .nodes.order_read_node import order_read_node
from .nodes.order_write_node import order_write_node
from .nodes.product_node import product_node
from .nodes.router_node import router_node
from .nodes.safety_check_node import safety_check_node
from .nodes.unified_agent_node import unified_agent_node
from .state import CustomerServiceState

# ── Built-in node registry ─────────────────────────────────────────────────────
# All available handler functions, keyed by the name stored in business_intents.
# New business-specific handlers can be added here without changing the builder.
_BUILTIN_NODE_REGISTRY: dict[str, Callable] = {
    "product_node":          product_node,
    "faq_node":              faq_node,
    "order_read_node":       order_read_node,
    "order_write_node":      order_write_node,
    "aftersales_node":       aftersales_node,
    "general_node":             general_node,
    "human_escalation_node":    human_escalation_node,
    "measurement_guide_node":   measurement_guide_node,
    # Unified agent: handles all read-only intents with multi-tool calling.
    # Replaces product_node / faq_node / order_read_node / aftersales_node /
    # general_node in the routing layer (edges.py), while the individual
    # node functions are preserved for unit tests and direct invocation.
    "unified_agent_node":    unified_agent_node,
}


def build_graph(
    business_profile: object,
    checkpointer: object,
) -> CompiledGraph:
    """Assemble and compile the customer service StateGraph.

    When a ``BusinessProfile`` is provided the graph topology is built
    dynamically from ``profile.intents``:
    - Only nodes referenced in the profile are registered (no dead nodes).
    - Safety-check continuation targets and router dispatch targets are both
      derived from the profile, so no hardcoded mappings remain.

    The three framework nodes (safety_check_node, router_node,
    human_escalation_node) are always registered regardless of the profile.

    Graph structure (dynamic example with 6 intents):
        START → safety_check_node
                  ├─[failed]─────────────────────► END
                  ├─[continuation nodes from profile]► <node> ► END
                  ├─[transfer_to_human]───────────► human_escalation_node ► END
                  └─[passed]──────────────────────► router_node
                        └─[intent → handler from profile]► <node> ► END
    """
    builder: StateGraph = StateGraph(CustomerServiceState)

    # ── Always-present framework nodes ────────────────────────────────────────
    builder.add_node("safety_check_node", safety_check_node)
    builder.add_node("router_node", router_node)
    builder.add_node("human_escalation_node", human_escalation_node)

    # ── Collect handler nodes required by this profile ─────────────────────────
    if business_profile is not None and hasattr(business_profile, "intents"):
        required_handler_nodes: set[str] = {
            intent.handler_node
            for intent in business_profile.intents  # type: ignore[union-attr]
        }
    else:
        # Fallback: register all built-in business nodes (wedding-dress default)
        required_handler_nodes = {
            "product_node", "faq_node", "order_read_node", "order_write_node",
            "aftersales_node", "general_node", "measurement_guide_node",
        }

    # Always register unified_agent_node — it is the target for all read-only
    # intents regardless of which specific handler nodes the profile lists.
    # The individual specialized nodes (product_node, faq_node, etc.) remain
    # in the registry for unit tests but are no longer reachable via routing.
    required_handler_nodes = required_handler_nodes | {"unified_agent_node"}

    # Register only the nodes this business needs (excluding framework nodes
    # already registered above)
    framework_nodes = {"safety_check_node", "router_node", "human_escalation_node"}
    for node_name in required_handler_nodes - framework_nodes:
        fn = _BUILTIN_NODE_REGISTRY.get(node_name)
        if fn is None:
            raise ValueError(
                f"build_graph: handler node {node_name!r} not found in "
                f"_BUILTIN_NODE_REGISTRY. Register it there or add a plugin."
            )
        builder.add_node(node_name, fn)

    # ── Entry point ────────────────────────────────────────────────────────────
    builder.set_entry_point("safety_check_node")

    # ── Safety → dispatch ──────────────────────────────────────────────────────
    # Build the target set for add_conditional_edges from the profile so
    # LangGraph's edge validation passes (all string values must be node names
    # known to the graph at compile time).
    if business_profile is not None and hasattr(business_profile, "intents"):
        continuation_map: dict[str, str] = {
            intent.handler_node: intent.handler_node
            for intent in business_profile.intents  # type: ignore[union-attr]
            if intent.is_continuation_node
        }
    else:
        continuation_map = {
            "order_read_node": "order_read_node",
            "order_write_node": "order_write_node",
        }

    safety_targets: dict[str, str] = {
        "router_node":           "router_node",
        "human_escalation_node": "human_escalation_node",
        END:                     END,
        **continuation_map,
    }
    builder.add_conditional_edges("safety_check_node", route_after_safety, safety_targets)

    # ── Router → handler ───────────────────────────────────────────────────────
    # route_after_router already resolves intent → handler node name, so we use
    # an identity mapping here (node_name → node_name).  LangGraph looks up the
    # routing function's return value as a KEY in this dict; using intent IDs as
    # keys would cause a KeyError because the function returns node names.
    if business_profile is not None and hasattr(business_profile, "intents"):
        router_targets: dict[str, str] = {
            intent.handler_node: intent.handler_node
            for intent in business_profile.intents  # type: ignore[union-attr]
        }
    else:
        router_targets = {
            "product_node":           "product_node",
            "faq_node":               "faq_node",
            "order_read_node":        "order_read_node",
            "order_write_node":       "order_write_node",
            "aftersales_node":        "aftersales_node",
            "general_node":           "general_node",
            "measurement_guide_node": "measurement_guide_node",
        }
    router_targets[END] = END  # type: ignore[assignment]  # for "blocked" intent
    # unified_agent_node is the target for all read-only intents; add it to the
    # targets map so LangGraph edge validation accepts the return value from
    # route_after_router even when no profile intent maps to it explicitly.
    router_targets["unified_agent_node"] = "unified_agent_node"
    builder.add_conditional_edges("router_node", route_after_router, router_targets)

    # ── Terminal edges ─────────────────────────────────────────────────────────
    leaf_nodes = (required_handler_nodes - framework_nodes) | {"human_escalation_node"}
    for node in leaf_nodes:
        builder.add_edge(node, END)

    return builder.compile(checkpointer=checkpointer)
