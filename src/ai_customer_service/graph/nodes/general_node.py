from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import CustomerServiceState
from ._utils import check_sentiment_escalation, resolve_node_prompt, strip_thinking, make_lang_rule, get_default_lang

GENERAL_SYSTEM_PROMPT = """你是「{business_name}」的客服，用口语简短回复客户。

回复要求：
- 自然口语，不超过100字，像真实客服发短信
- 严禁 Markdown（不用标题、表格、加粗、列表符号）
- 最多1个 emoji
- 质量投诉/售后问题：先表示歉意，然后让客户提供订单号，说明会为其处理
- 问候/感谢：温暖简短回应
- 情绪支持：真诚但不过度热情
- 紧急情况（产品损坏等）：直接给紧急热线{hotline}
- 超出业务范围：礼貌说明只负责相关服务
{lang_rule}"""

# Fallback thresholds
_ESCALATION_THRESHOLD_GENERAL = 4
_URGENT_ESCALATION_THRESHOLD = 2


async def general_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Handle general messages with a short, natural customer service tone."""
    llm = config["configurable"]["llm"]
    prompt_repo = config["configurable"].get("prompt_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []
    profile = config["configurable"].get("business_profile")

    # ── Read config from BusinessProfile with fallbacks ────────────────────────
    if profile is not None:
        sc = profile.safety_config
        cc = profile.contact_config
        threshold = sc.escalation_thresholds.get("general", _ESCALATION_THRESHOLD_GENERAL)
        urgent_threshold = sc.urgent_escalation_threshold
        business_name = profile.business_name
        hotline = f" {cc.hotline}" if cc.hotline else ""
    else:
        threshold = _ESCALATION_THRESHOLD_GENERAL
        urgent_threshold = _URGENT_ESCALATION_THRESHOLD
        business_name = "缘梦婚纱"
        hotline = " 400-520-5201"

    last_user_text: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_text)
    lang_rule = make_lang_rule(default_lang, business_name=business_name)

    _active_prompt = await resolve_node_prompt(prompt_repo, "general_node", GENERAL_SYSTEM_PROMPT)

    urgent_note = (
        "\n[注意：截止日期临近，优先快速解决，必要时主动建议转接专属顾问]"
        if state.get("is_urgent") else ""
    )
    confidence_note = (
        "\n[本次意图识别置信度较低，客户问题可能属于多个类别。请先简短确认客户的主要需求，再给出回答。]"
        if state.get("low_confidence") else ""
    )

    system_content = (
        _active_prompt.format(
            lang_rule=lang_rule,
            business_name=business_name,
            hotline=hotline,
        )
        + urgent_note
        + confidence_note
    )

    response = await llm.ainvoke(
        [SystemMessage(content=system_content), *state["messages"][-3:]],
        config={"callbacks": callbacks},
    )
    reply_content = strip_thinking(response.content)

    negative_turns, should_escalate = check_sentiment_escalation(
        state, threshold=threshold, urgent_threshold=urgent_threshold,
    )
    return {
        "messages": [AIMessage(content=reply_content)],
        "negative_turns": negative_turns,
        **({"request_human": True} if should_escalate else {}),
    }
