"""Unified read-only agent node.

Handles all non-write, non-measurement intents through multi-tool calling.
The LLM autonomously decides which tools to invoke based on the full user
message, enabling natural multi-intent responses without sequential node hops.

Replaces (in routing):
  product_node, faq_node, order_read_node, aftersales_node, general_node

Preserved as dedicated nodes (not replaced):
  order_write_node  — requires HITL interrupt()
  measurement_guide_node — requires multi-turn state machine

Data pipeline:
  retrieve_knowledge → FAQService → HybridRetriever (BM25 + PGVector) → faq_documents
  get_order_info     → OrderService → orders table (PostgreSQL)
  list_products      → ProductService → products table (PostgreSQL)
  get_product_detail → ProductService → products table (PostgreSQL)
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..state import CustomerServiceState
from ._utils import get_default_lang, make_lang_rule, strip_thinking

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

UNIFIED_AGENT_SYSTEM_PROMPT = """\
你是「{business_name}」的智能客服，能同时完整回答客户的多个问题。

## 工作方式
1. 仔细阅读客户消息，判断需要哪些信息才能完整回答
2. 主动调用必要的工具获取真实数据（可同时调用多个工具）
3. 将所有数据综合成一条自然、完整的回复

## 工具使用原则
- 涉及政策/流程/费用/保障等业务问题 → 必须调用 retrieve_knowledge
- 涉及订单状态/进度/物流/退款进度 → 必须调用 get_order_info
- 涉及商品推荐或款式询问 → 必须调用 list_products 或 get_product_detail
- 售后投诉 → 调用 retrieve_knowledge 获取处理政策，结合人文关怀回复
- 若客户同时有多个问题，先调全部工具收集数据，再统一综合回答
- 不确定时优先查询，不要猜测

## 数据可靠性
- 工具返回含 [POLICY] 标记的文档：严格基于文档，禁止补充文档未提及的政策、价格、期限
- 工具返回含 [KNOWLEDGE] 标记的文档：可结合行业通用知识适当补充
- 无相关文档但问题涉及退换货/赔偿/保障等政策：说明无法确认，建议联系人工客服
- 商品信息：只使用工具返回的真实数据，禁止生成任何 URL 或虚构价格

## 回复规范
- 自然口语，像真实客服发短信一样
- 严禁 Markdown（不用 **加粗**、#标题、列表符号、分隔线）
- 最多 1 个 emoji
- 若客户有多个问题，按逻辑顺序逐一回答，自然衔接

## 行动按钮（选用）
若回复后客户明显有下一步可操作，在消息末尾附加行动按钮（最多2个）：
[ACTION:按钮文字:发送内容]
规则：按钮文字≤8字；仅在有明确下一步操作时才添加，不强制
示例：[ACTION:查看物流:查询ORD-001物流进度][ACTION:申请退货:我要申请退货]
{order_context_hint}
{lang_rule}"""


# ── Node ─────────────────────────────────────────────────────────────────────

async def unified_agent_node(
    state: CustomerServiceState,
    config: RunnableConfig,
) -> dict:
    """Handle all read-only queries via multi-tool LLM agent.

    The agent calls whichever combination of read tools the user's message
    requires, then synthesises a single comprehensive natural-language reply.
    """
    cfg = config.get("configurable", config)
    llm = cfg.get("llm")
    faq_service = cfg.get("faq_service")
    order_service = cfg.get("order_service")
    product_service = cfg.get("product_service")
    profile = cfg.get("business_profile")
    handler = cfg.get("langfuse_handler")
    callbacks = [handler] if handler else []

    user_id: str = state.get("user_id", "")
    business_name = profile.business_name if profile else "缘梦婚纱"
    progress_callback = cfg.get("progress_callback")  # async (stage, text) -> None; injected by socket_server

    if llm is None:
        return {"messages": [AIMessage(content="客服服务暂时不可用，请稍后重试。")]}

    last_user_text: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_text)
    lang_rule = make_lang_rule(default_lang, business_name=business_name)

    # Inject existing order context as a hint (avoids re-asking for order ID)
    order_ctx: dict = state.get("order_context") or {}
    if order_ctx:
        order_context_hint = (
            f"\n[已知订单上下文]\n"
            f"订单号：{order_ctx.get('order_id', '')}\n"
            f"状态：{order_ctx.get('status', '')}\n"
        )
    else:
        order_context_hint = ""

    system_content = UNIFIED_AGENT_SYSTEM_PROMPT.format(
        business_name=business_name,
        order_context_hint=order_context_hint,
        lang_rule=lang_rule,
    )

    # Build tools from available services; sources_sink collects citation info
    reply_sources: list[dict] = []
    tools = _make_tools(faq_service, order_service, product_service, user_id, reply_sources)

    if not tools:
        # No data services — pure conversational response (general / greetings)
        try:
            response = await llm.ainvoke(
                [SystemMessage(content=system_content), *state["messages"][-6:]],
                config={"callbacks": callbacks},
            )
            reply = strip_thinking(response.content) or "您好！有什么可以帮您的？"
            return {"messages": [AIMessage(content=reply)], "reply_sources": []}
        except Exception:
            logger.exception("unified_agent_node LLM error (no tools)")
            return {"messages": [AIMessage(content="客服遇到问题，请稍后重试。")]}

    agent_llm = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    messages = [SystemMessage(content=system_content), *state["messages"][-8:]]
    response = None

    # Progress hint text per tool name
    _PROGRESS_HINTS: dict[str, str] = {
        "retrieve_knowledge": "正在检索相关政策和知识…",
        "get_order_info": "正在查询您的订单信息…",
        "list_products": "正在查询商品目录…",
        "get_product_detail": "正在查询商品详情…",
    }

    try:
        for _ in range(5):  # max 5 tool-call rounds
            response = await agent_llm.ainvoke(
                messages, config={"callbacks": callbacks}
            )
            if not response.tool_calls:
                break  # LLM has gathered all needed data → produce final reply
            messages.append(response)
            # Emit progress before executing this round's tool calls
            if progress_callback:
                for tc in response.tool_calls:
                    hint = _PROGRESS_HINTS.get(tc["name"], "正在获取信息…")
                    try:
                        await progress_callback("tool_start", hint)
                    except Exception:
                        pass  # never let progress errors abort the main flow
            for tc in response.tool_calls:
                t = tool_map.get(tc["name"])
                if t:
                    try:
                        result = await t.ainvoke(tc["args"])
                    except Exception as exc:
                        logger.warning("unified_agent tool %s error: %s", tc["name"], exc)
                        result = f"工具调用出错，请稍后重试。"
                else:
                    result = f"未知工具：{tc['name']}"
                messages.append(
                    ToolMessage(content=str(result), tool_call_id=tc["id"])
                )

        if response is None:  # pragma: no cover — range(5) always fires at least once
            return {"messages": [AIMessage(content="客服遇到问题，请稍后重试。")]}

        reply = strip_thinking(response.content)
        if not reply.strip():
            reply = "很抱歉，我暂时无法回答您的问题，请稍后重试或联系人工客服。"

        return {"messages": [AIMessage(content=reply)], "reply_sources": reply_sources}

    except Exception:
        logger.exception("unified_agent_node unexpected error")
        return {"messages": [AIMessage(content="客服遇到问题，请稍后重试或联系人工客服。")]}


# ── Tool factory ──────────────────────────────────────────────────────────────

def _make_tools(
    faq_service,
    order_service,
    product_service,
    user_id: str,
    sources_sink: list | None = None,
) -> list:
    """Create LangChain tools with services captured in closure.

    Only services that are not None contribute tools, so the agent adapts
    gracefully to partial dependency injection (e.g. tests without DB).

    *sources_sink* is a mutable list that tools append citation dicts to as
    they run.  Each entry: {type, id, title, knowledge_type?}.  Pass in a
    list created by the caller so it accumulates across all tool calls during
    one agent loop.  Passing None (default) is safe — an internal throwaway
    list is used instead, preserving backward compatibility for tests.
    """
    _sink: list = sources_sink if sources_sink is not None else []
    tools = []

    if faq_service is not None:

        @tool
        async def retrieve_knowledge(query: str) -> str:
            """检索业务知识和政策文档（退换货政策、定制流程、加急费用、行业常识等）。
            适用于：政策/流程咨询、售后处理方案、产品知识、保养保障等任何知识类问题。"""
            docs = await faq_service.retrieve(query)
            if not docs:
                return "暂无相关资料。"
            parts = []
            for d in docs:
                kt = d.metadata.get("knowledge_type", "industry_knowledge")
                label = "[POLICY]" if kt == "business_policy" else "[KNOWLEDGE]"
                title = d.metadata.get("title", "")
                parts.append(f"{label}【{title}】\n{d.content}")
                # Accumulate citation for workspace source panel
                _sink.append({
                    "type": "knowledge",
                    "id": getattr(d, "doc_id", "") or d.metadata.get("doc_id", ""),
                    "title": title or "知识库文档",
                    "knowledge_type": kt,
                })
            return "\n\n".join(parts)

        tools.append(retrieve_knowledge)

    if order_service is not None:

        @tool
        async def get_order_info(
            order_id: str = "",
            query_type: Literal[
                "get_status",
                "get_production_progress",
                "get_tracking",
                "get_refund_status",
            ] = "get_status",
        ) -> str:
            """查询订单信息。
            order_id: 订单号（如 ORD-001），未知时留空（系统将自动查找）
            query_type: get_status（订单状态）| get_production_progress（生产进度）
                        | get_tracking（物流）| get_refund_status（退款进度）"""
            from ...domain.entities import OrderActionRequest
            from ...domain.exceptions import (
                InvalidOrderActionError,
                OrderAccessDeniedError,
                OrderNotFoundError,
            )

            # Auto-detect order_id from user's order list if not provided
            if not order_id and user_id:
                try:
                    user_orders = await order_service.list_orders(user_id)
                    if len(user_orders) == 1:
                        order_id = user_orders[0].order_id
                    elif len(user_orders) > 1:
                        order_lines = "\n".join(
                            f"- {o.order_id}（{o.status.value}）"
                            for o in user_orders[:5]
                        )
                        return f"您有多笔订单，请告知要查哪一笔：\n{order_lines}"
                except Exception:
                    pass

            if not order_id:
                return "请提供您的订单号以便查询。"

            try:
                result = await order_service.execute(
                    OrderActionRequest(action=query_type, order_id=order_id),
                    user_id,
                )
                # Record order citation for workspace source panel
                _sink.append({"type": "order", "id": order_id, "title": f"订单 {order_id}"})
                return result.message
            except OrderNotFoundError as e:
                return f"未找到订单 {e.order_id}，请确认订单号是否正确。"
            except OrderAccessDeniedError:
                return "该订单与当前账号不匹配，无法查询。"
            except InvalidOrderActionError as e:
                return str(e)
            except Exception as exc:
                logger.warning("get_order_info error: %s", exc)
                return "查询订单时遇到问题，请稍后重试。"

        tools.append(get_order_info)

    if product_service is not None:

        @tool
        async def list_products(
            style: str | None = None,
            max_price: float | None = None,
            min_price: float | None = None,
            stock_type: str | None = None,
            rush_only: bool = False,
        ) -> str:
            """搜索或列出婚纱商品目录。
            style: 款式关键词（鱼尾裙/蓬蓬裙/A型裙/中式）
            max_price/min_price: 价格范围（元）
            stock_type: 'ready'现货 或 'custom'定制
            rush_only: 仅显示支持加急的商品
            不传任何参数时返回全部商品。"""
            if any(v is not None for v in (style, max_price, min_price, stock_type)) or rush_only:
                products = await product_service.search(
                    style=style,
                    max_price=max_price,
                    min_price=min_price,
                    stock_type=stock_type,
                    rush_only=rush_only,
                )
            else:
                products = await product_service.list_all()
            if not products:
                return "暂无符合条件的商品。"
            for p in products:
                _sink.append({"type": "product", "id": getattr(p, "product_id", ""), "title": getattr(p, "name", "商品")})
            return "\n\n".join(p.to_context_str() for p in products)

        @tool
        async def get_product_detail(product_id: str) -> str:
            """查询指定商品编号的详细信息（如 WD-P001）。"""
            product = await product_service.get(product_id)
            if not product:
                return f"商品编号 {product_id} 不存在。"
            _sink.append({"type": "product", "id": product_id, "title": getattr(product, "name", product_id)})
            return product.to_context_str()

        tools.extend([list_products, get_product_detail])

    return tools
