"""human_escalation_node — handles explicit customer requests to speak with a human agent.

Triggered by keyword detection in safety_check_node (转人工/找人工/人工客服 etc.).
Generates a warm transfer message and sets request_human=True so socket_server
can trigger ws.transfer_to_human() immediately after the graph completes.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from ..state import CustomerServiceState
from ._utils import lang_format, get_default_lang

_TRANSFER_MSG_ZH = (
    "好的，正在为您转接专属顾问，请稍候片刻 💐\n"
    "顾问接入后会直接与您沟通，感谢您的耐心等待。"
)


async def human_escalation_node(
    state: CustomerServiceState, config: RunnableConfig
) -> dict:
    """Generate a warm transfer message in the customer's language and signal escalation."""
    llm = config["configurable"]["llm"]
    last_user_msg: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config)
    transfer_msg = await lang_format(llm, _TRANSFER_MSG_ZH, last_user_msg, default_lang)
    return {
        "messages": [AIMessage(content=transfer_msg)],
        "request_human": True,
    }
