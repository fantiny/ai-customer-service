from __future__ import annotations

import functools
import re

from langchain_core.messages import AIMessage
from langgraph.types import RunnableConfig

from ..state import CustomerServiceState

# ── Security baseline — prompt injection detection ────────────────────────────
# These stay hardcoded: they are a universal security measure, not business logic.
_BLOCKED_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(previous|all|above)\s+instructions",
        r"disregard\s+(your|the)\s+(system\s+)?prompt",
        r"you\s+are\s+now\s+(a\s+)?(?!a\s+customer)",  # role-hijack attempts
        r"<\s*script",
        r"eval\s*\(",
        r"__import__",
        r"prompt\s+injection",
    ]
]

# ── Escape signals for multi-turn continuation ─────────────────────────────────
# User signals that they no longer want to continue the previous intent.
_ESCAPE_SIGNALS = [
    "没有订单", "还没下单", "没下单", "不是这个意思", "算了",
    "不问了", "换个问题", "不需要了", "新购", "想买新的",
    "我要问", "其他问题", "没买过", "我想问的是",
]

# ── Fallback config when BusinessProfile is not yet loaded ────────────────────
# Used only during startup probe and in tests without DI.
_FALLBACK_ESCALATION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"转人工", r"找人工", r"人工客服", r"人工服务", r"真人客服", r"真人",
        r"要投诉", r"我要投诉", r"联系客服",
        r"call.*agent", r"speak.*human", r"talk.*person",
    ]
]
_FALLBACK_MAX_INPUT = 2000
_FALLBACK_CONTINUATION_NODES = frozenset({
    "order_read_node",
    "order_write_node",
    "measurement_guide_node",
})


@functools.lru_cache(maxsize=32)
def _compile_escalation_patterns(
    keywords: tuple[str, ...],
) -> tuple[re.Pattern, ...]:
    """Compile keyword list to regex patterns, cached by keyword tuple."""
    return tuple(re.compile(kw, re.IGNORECASE) for kw in keywords)


async def safety_check_node(
    state: CustomerServiceState, config: RunnableConfig
) -> dict:
    """First node in every graph run.

    1. Resets all ephemeral state fields.
    2. Blocks prompt injection / malicious input (hardcoded security baseline).
    3. Detects multi-turn continuation — routes directly to the waiting node,
       bypassing the router.
    4. Detects human-escalation keywords (loaded from BusinessProfile when
       available, falls back to hardcoded list).
    """
    # ── Read business profile config ──────────────────────────────────────────
    profile = config["configurable"].get("business_profile")
    if profile is not None:
        escalation_patterns = _compile_escalation_patterns(
            profile.safety_config.escalation_keywords
        )
        max_input = profile.safety_config.max_input_length
        continuation_nodes = profile.continuation_node_ids()
    else:
        escalation_patterns = _FALLBACK_ESCALATION_PATTERNS
        max_input = _FALLBACK_MAX_INPUT
        continuation_nodes = _FALLBACK_CONTINUATION_NODES

    # ── Reset ephemeral fields ─────────────────────────────────────────────────
    base_reset: dict = {
        "intent": "general",
        "retrieved_docs": [],
        "pending_action": {},
        "safety_passed": False,
        "awaiting_order_id": "",  # consumed here; cleared for next turn
        "request_human": False,
        "handoff_context": {},    # cleared each turn; repopulated by product/faq nodes on escalation
        "reply_sources": [],      # cleared each turn; repopulated by unified_agent_node tool calls
    }

    messages = state.get("messages", [])
    if not messages:
        return {**base_reset, "safety_passed": True}

    latest = messages[-1]
    if getattr(latest, "type", None) != "human":
        return {**base_reset, "safety_passed": True}

    content: str = latest.content or ""

    # ── Length check ──────────────────────────────────────────────────────────
    if len(content) > max_input:
        return {
            **base_reset,
            "messages": [
                AIMessage(
                    content=(
                        f"您的消息过长（{len(content)} 字符），"
                        f"请将其控制在 {max_input} 字符以内。"
                    )
                )
            ],
        }

    # ── Prompt injection block ─────────────────────────────────────────────────
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(content):
            return {
                **base_reset,
                "messages": [AIMessage(content="抱歉，我无法处理该请求。如有需要请联系人工客服。")],
            }

    # ── Multi-turn continuation ────────────────────────────────────────────────
    awaiting = state.get("awaiting_order_id", "")
    if awaiting and awaiting in continuation_nodes:
        is_escape = any(signal in content for signal in _ESCAPE_SIGNALS)
        if not is_escape:
            return {**base_reset, "safety_passed": True, "intent": awaiting}
        # Escape detected: fall through to normal routing

    # ── Human escalation keywords ──────────────────────────────────────────────
    for pattern in escalation_patterns:
        if pattern.search(content):
            return {**base_reset, "safety_passed": True, "intent": "transfer_to_human"}

    return {**base_reset, "safety_passed": True}
