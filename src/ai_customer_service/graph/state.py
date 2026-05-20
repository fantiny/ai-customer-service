from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class CustomerServiceState(TypedDict):
    # ── Durable (persisted by checkpointer across turns) ───────────────────
    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    user_id: str
    # Multi-turn continuation: non-empty = which node is waiting for order ID
    awaiting_order_id: str   # "" | "order_read_node" | "order_write_node"
    negative_turns: NotRequired[int]  # 连续负面情绪轮数计数，0 为初始值
    is_urgent: NotRequired[bool]      # 婚礼距今 ≤ 14 天
    low_confidence: NotRequired[bool] # True when router confidence < 0.55

    # order_context: durable across turns so faq_node can inject known order info
    # without re-asking the customer for their order ID.  Overwritten whenever
    # order_read_node or order_write_node fetches a (new) order; never reset by
    # safety_check_node.  Cleared only when a new thread starts (empty checkpointer).
    order_context: dict      # {order_id, status, production_stage, wedding_date, total, …}

    # ── Ephemeral (reset at turn start by safety_check_node) ───────────────
    intent: str              # "product"|"faq"|"order_read"|"order_write"|"aftersales"|"general"|"blocked"|"transfer_to_human"
    retrieved_docs: list     # cleared after faq/product node generates answer
    pending_action: dict     # HITL: populated before interrupt(), cleared after
    safety_passed: bool
    request_human: bool      # set True by human_escalation_node; socket_server triggers transfer
    # Structured context passed to the human agent on handoff.
    # Populated by product_node / faq_node when AI cannot reliably answer.
    # Socket server writes this into the ticket on transfer_to_human().
    # Schema: {reason, user_question, ai_attempted, order_context, suggested_action}
    handoff_context: dict
    # Sources gathered during unified_agent_node tool calls.
    # Each entry: {type: "knowledge"|"order"|"product", id, title, knowledge_type?}
    # Sent to workspace agents only (not to customers) for manual verification.
    reply_sources: list
