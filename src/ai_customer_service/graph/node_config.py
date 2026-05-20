"""NodeConfig — typed contract for config["configurable"] in every graph node.

All LangGraph nodes receive configuration through the config["configurable"] dict.
This module defines the expected shape as a TypedDict so that:

  1. IDEs and type checkers can catch missing/misspelled keys at development time.
  2. `validate_node_config()` can be called at startup to fail fast if the DI
     container forgot to inject a required service.

Usage in nodes::

    from ..node_config import NodeConfig
    cfg: NodeConfig = config["configurable"]   # type: ignore[assignment]
    llm = cfg["llm"]
    order_service = cfg["order_service"]

Startup validation in Container / main.py::

    from ai_customer_service.graph.node_config import validate_node_config
    validate_node_config(graph_config["configurable"])   # raises ValueError on missing keys
"""
from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict


class NodeConfig(TypedDict):
    # ── Required ─────────────────────────────────────────────────────────────
    llm: Any                    # LangChain ChatModel (OpenAI-compat)
    faq_service: Any            # IFAQService — hybrid RAG retrieval
    order_service: Any          # IOrderService — read + write + validate
    product_service: Any        # IProductService — list / search / detail
    business_profile: Any       # BusinessProfile — generic business configuration

    # ── Optional (None → feature disabled, not a crash) ───────────────────
    rules_service: NotRequired[Any | None]      # IBusinessRulesService — dynamic config
    prompt_repo: NotRequired[Any | None]        # IPromptRepository — DB-managed prompts
    langfuse_handler: NotRequired[Any | None]   # LangfuseCallbackHandler — observability


# Keys whose absence should raise ValueError at startup
_REQUIRED_KEYS: tuple[str, ...] = (
    "llm",
    "faq_service",
    "order_service",
    "product_service",
    "business_profile",
)


def validate_node_config(configurable: dict[str, Any]) -> None:
    """Raise ValueError listing all missing required keys.

    Call this once during application startup (before serving requests) so that
    misconfigured DI containers fail loudly rather than crashing on the first
    user message.

    Example::

        # in Container.build() or app lifespan
        validate_node_config(graph_config_factory(thread_id="__probe__", user_id="__probe__", handler=None)["configurable"])
    """
    missing = [k for k in _REQUIRED_KEYS if configurable.get(k) is None]
    if missing:
        raise ValueError(
            f"NodeConfig is missing required keys: {missing}. "
            "Check Container.graph_config_factory() to ensure all services are injected."
        )
