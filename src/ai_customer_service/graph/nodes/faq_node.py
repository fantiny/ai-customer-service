from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import CustomerServiceState
from ._utils import (
    build_handoff_message,
    get_default_lang,
    get_handoff_suggestion,
    make_lang_rule,
    resolve_node_prompt,
    strip_thinking,
)

# Keywords that suggest the user is asking about a business policy (not general knowledge).
# When retrieval returns nothing and the query matches these, we escalate to human
# rather than allowing the LLM to fabricate policy details.
_POLICY_KEYWORDS = (
    "退货", "退款", "换货", "保修", "期限", "政策", "规定",
    "费用", "赔偿", "责任", "保障", "条款", "退", "补偿",
    "refund", "return", "policy", "warranty", "guarantee",
)

FAQ_SYSTEM_PROMPT = """你是「{business_name}」的客服，直接用口语回答客户问题。

可参考的资料（含商品目录和业务知识）：
{context}
{order_context_hint}
回复要求：
- 用自然口语，像真实客服发短信一样
- 推荐商品时：直接说商品名、款式特点和价格，最多推荐3款，每款2-3句话，总长不超过200字
- 严禁使用 Markdown（不用#标题、**加粗**、表格、---分隔线、-列表符号）
- 严禁大量 emoji，最多1个
- 直接给出答案，不要说"根据资料显示"或"根据知识库"
- 如果对话历史中已有客户订单信息，请结合该信息回答，无需重新询问订单号
{strict_instruction}
{lang_rule}"""

_STRICT_INSTRUCTION = (
    "- 仅基于上方资料回答，不得补充任何资料中未提及的政策内容、价格或条款"
)
_FLEXIBLE_INSTRUCTION = (
    "- 优先基于上方资料回答，如资料不足可结合行业通用知识补充，"
    "但不得编造具体数字、承诺或政策条款"
)


async def faq_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Retrieve relevant FAQ documents and generate a reliable, natural answer.

    Knowledge-type-based reliability:
    - ``business_policy`` docs → strict mode: LLM cannot supplement beyond docs.
    - ``industry_knowledge`` docs → flexible: LLM can add general knowledge.
    - No docs, policy-looking query → seamless handoff to human (no LLM fabrication).
    - No docs, general knowledge query → LLM can use general knowledge.
    """
    llm = config["configurable"]["llm"]
    faq_service = config["configurable"]["faq_service"]
    handler = config["configurable"].get("langfuse_handler")
    prompt_repo = config["configurable"].get("prompt_repo")
    callbacks = [handler] if handler else []

    profile = config["configurable"].get("business_profile")
    business_name = profile.business_name if profile else "我们"

    last_user_text: str = state["messages"][-1].content if state["messages"] else ""
    # Fix: use separate variable for default_lang (not overwriting last_user_text)
    default_lang = await get_default_lang(config, last_user_text=last_user_text)
    lang_rule = make_lang_rule(default_lang, business_name=business_name)

    system_prompt = await resolve_node_prompt(prompt_repo, "faq_node", FAQ_SYSTEM_PROMPT)

    # Reuse last_user_text (already safely extracted above) — same value, no second [-1] access.
    query = last_user_text
    docs = await faq_service.retrieve(query)

    # ── Split docs by knowledge_type ─────────────────────────────────────────
    # Vector store applies min_score filter upstream; docs here are all relevant.
    policy_docs = [d for d in docs if d.metadata.get("knowledge_type") == "business_policy"]
    knowledge_docs = [d for d in docs if d.metadata.get("knowledge_type") != "business_policy"]

    if policy_docs:
        # Authoritative policy docs found → strict mode
        policy_ctx = "\n\n".join(
            f"【{d.metadata.get('title', '')}】\n{d.content}" for d in policy_docs
        )
        if knowledge_docs:
            # Append industry knowledge as supplemental reference (policy takes precedence)
            know_ctx = "\n\n".join(
                f"【参考：{d.metadata.get('title', '')}】\n{d.content}" for d in knowledge_docs
            )
            context = policy_ctx + "\n\n---\n[行业参考资料]\n" + know_ctx
        else:
            context = policy_ctx
        strict_mode = True
    elif knowledge_docs:
        # General knowledge docs only → flexible mode
        context = "\n\n".join(
            f"【{d.metadata.get('title', '')}】\n{d.content}" for d in knowledge_docs
        )
        strict_mode = False
    else:
        # No docs at all — check if this looks like a policy question
        is_policy_question = any(kw in query for kw in _POLICY_KEYWORDS)
        if is_policy_question:
            # Business policy question with no documentation → seamless handoff
            msg = await build_handoff_message(config, "handoff.policy_no_doc")
            suggestion = await get_handoff_suggestion(config, "policy_no_doc")
            return {
                "messages": [AIMessage(content=msg)],
                "request_human": True,
                "handoff_context": {
                    "reason": "policy_no_doc",
                    "user_question": query,
                    "ai_attempted": "检索知识库，未找到相关业务政策文档",
                    "order_context": state.get("order_context"),
                    "suggested_action": suggestion,
                },
                "retrieved_docs": [],
            }
        else:
            # General knowledge question — LLM can use general knowledge
            context = ""
            strict_mode = False

    strict_instruction = _STRICT_INSTRUCTION if strict_mode else _FLEXIBLE_INSTRUCTION

    # Inject known order context so AI doesn't ask for info it already has
    oc: dict = state.get("order_context") or {}
    if oc and oc.get("order_id"):
        order_context_hint = (
            f"\n已知客户订单信息（本次对话中已查询，无需再次询问订单号）：\n"
            f"- 订单号：{oc.get('order_id')}\n"
            f"- 状态：{oc.get('status', '—')}\n"
            f"- 生产阶段：{oc.get('production_stage', '—')}\n"
            f"- 婚礼日期：{oc.get('wedding_date', '—')}\n"
            f"- 订单金额：¥{oc.get('total', 0):,.0f}\n"
        )
    else:
        order_context_hint = ""

    # Build retrieved_docs list for agent workspace visibility
    retrieved_info = [
        {
            "id": doc.doc_id or doc.metadata.get("external_id", ""),
            "title": doc.metadata.get("title", doc.content[:40]),
            "knowledge_type": doc.metadata.get("knowledge_type", "industry_knowledge"),
        }
        for doc in docs
    ]

    formatted_prompt = system_prompt.format(
        context=context,
        order_context_hint=order_context_hint,
        lang_rule=lang_rule,
        strict_instruction=strict_instruction,
        business_name=business_name,
    )

    # Use full conversation history so AI has complete context
    history_msgs = state["messages"][-8:]  # last 8 messages for context window

    answer = await llm.ainvoke(
        [
            SystemMessage(content=formatted_prompt),
            *history_msgs,
        ],
        config={"callbacks": callbacks},
    )

    return {
        "messages": [AIMessage(content=strip_thinking(answer.content))],
        "retrieved_docs": retrieved_info,
    }
