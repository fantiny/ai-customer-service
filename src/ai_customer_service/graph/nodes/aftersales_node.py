from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import CustomerServiceState
from ._utils import check_sentiment_escalation, resolve_node_prompt, strip_thinking, make_lang_rule, get_default_lang

AFTERSALES_SYSTEM_PROMPT = """你是「{business_name}」的售后专员，处理客户的质量投诉和售后问题。

处理原则：
1. 先诚恳道歉，表达重视（1-2句，不夸张）
2. 询问具体问题（破损部位、尺寸偏差多少、与描述哪里不符）
3. 请客户提供订单号，说明核实后会优先跟进
4. 如情况紧急（截止日期临近）：同时提供紧急热线{hotline}

投诉处理指引（质量问题、收货异常、服务投诉）：
1. 首先表达歉意，承认问题
2. 同步收集：订单号 + 具体问题描述 + 截止日期（判断紧急程度）
3. 如截止日期临近：标记为紧急，优先处理，给出直接解决方案选项
4. 如截止日期充裕：按正常流程处理，询问客户倾向的解决方式
5. 不要每条消息都单独问一个问题，尽量在1-2条内收集所有必要信息
6. 不要捏造解决时间表或承诺无法兑现的内容

订单信息处理：
- 如果系统提示已提供订单号，不要再重复索要订单号
- 已有订单上下文时，直接围绕已知信息进行问题处理

回复要求：
- 自然口语，不超过120字，真实客服发短信的感觉
- 严禁 Markdown（不用标题、表格、加粗、列表符号）
- 最多1个 emoji
- 语气真诚有温度，不过分客套
{lang_rule}"""

# Fallback thresholds (used when BusinessProfile is not injected)
_ESCALATION_THRESHOLD_AFTERSALES = 3
_URGENT_ESCALATION_THRESHOLD = 2


async def aftersales_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Handle after-sales complaints: quality issues, size problems, service feedback."""
    llm = config["configurable"]["llm"]
    prompt_repo = config["configurable"].get("prompt_repo")
    workflow_repo = config["configurable"].get("workflow_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []
    profile = config["configurable"].get("business_profile")

    # ── Read config from BusinessProfile with fallbacks ────────────────────────
    if profile is not None:
        sc = profile.safety_config
        cc = profile.contact_config
        threshold = sc.escalation_thresholds.get("aftersales", _ESCALATION_THRESHOLD_AFTERSALES)
        urgent_threshold = sc.urgent_escalation_threshold
        business_name = profile.business_name
        hotline = f" {cc.hotline}" if cc.hotline else ""
    else:
        threshold = _ESCALATION_THRESHOLD_AFTERSALES
        urgent_threshold = _URGENT_ESCALATION_THRESHOLD
        business_name = "缘梦婚纱"
        hotline = " 400-520-5201"

    last_user_text: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_text)
    lang_rule = make_lang_rule(default_lang, business_name=business_name)

    _active_prompt = await resolve_node_prompt(prompt_repo, "aftersales_node", AFTERSALES_SYSTEM_PROMPT)

    # ── Load SOP workflows from DB ────────────────────────────────────────────
    workflow_block = ""
    if workflow_repo and profile:
        try:
            workflows = await workflow_repo.get_workflows(
                profile.business_id, trigger_intent="aftersales"
            )
            if workflows:
                sop_lines = ["[售后处理标准流程 — 请严格按步骤引导客户]"]
                for wf in workflows:
                    sop_lines.append(f"\n▸ {wf.display_name}（触发关键词：{', '.join(wf.trigger_keywords) if wf.trigger_keywords else '通用'}）")
                    for step in wf.steps:
                        sop_lines.append(f"  第{step.step}步：{step.instruction}")
                workflow_block = "\n" + "\n".join(sop_lines) + "\n"
        except Exception:
            import logging
            logging.getLogger(__name__).warning("aftersales_node: failed to load workflows", exc_info=True)

    # Inject order-ID context hint when already known from a previous order query.
    # NOTE: awaiting_order_id stores a *node name* for multi-turn routing, NOT an
    # order ID. The actual order ID lives in state["order_context"]["order_id"].
    order_id_hint = ""
    known_order_id = (state.get("order_context") or {}).get("order_id")
    if known_order_id:
        order_id_hint = f"\n[系统提示：客户订单号已确认为 {known_order_id}，无需再次索要订单号]"

    # Urgency block: built from profile contact config
    urgent_block = ""
    if state.get("is_urgent"):
        hotline_line = f"\n- 同时提供紧急热线{hotline}" if hotline.strip() else ""
        urgent_block = (
            "\n[紧急模式：截止日期临近]"
            "\n- 跳过信息收集阶段，立即给出解决方案选项"
            f"{hotline_line}"
            "\n- 语气更直接，减少寒暄，2-3句话内给出行动方案\n"
        )

    system_content = (
        _active_prompt.format(
            lang_rule=lang_rule,
            business_name=business_name,
            hotline=hotline,
        )
        + workflow_block
        + order_id_hint
        + urgent_block
    )

    response = await llm.ainvoke(
        [SystemMessage(content=system_content), *state["messages"][-5:]],
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
