from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..state import CustomerServiceState
from ._utils import strip_thinking, make_lang_rule, get_default_lang, build_handoff_message, get_handoff_suggestion, resolve_node_prompt

_logger = logging.getLogger(__name__)

# Matches URLs from known hallucination-prone e-commerce platforms.
# Our own store URLs (explicitly set in the products DB) come through to_context_str()
# and are already present verbatim in the tool output, so the LLM only needs to repeat them.
# We only strip URLs that the LLM spontaneously generates that are NOT in the tool output.
_HALLUCINATED_URL_PATTERN = re.compile(
    r"https?://(?!)"   # placeholder — replaced by _make_scrubber per-invocation
    r"|\Z",            # never matches by default
    re.IGNORECASE,
)

_KNOWN_BAD_DOMAINS = re.compile(
    r"https?://(?:(?:detail\.)?tmall\.com|taobao\.com|jd\.com|pinduoduo\.com|suning\.com)\S*"
    r"|(?:detail\.tmall|taobao|jd\.com)\S+",
    re.IGNORECASE,
)


def _scrub_urls(text: str, allowed_urls: set[str] | None = None) -> str:
    """Strip hallucinated URLs. URLs that came from DB tool output are preserved."""
    # Step 1: remove known bad platform URLs unconditionally
    cleaned, n1 = _KNOWN_BAD_DOMAINS.subn("", text)
    # Step 2: remove any remaining https:// URL not in the allowed set
    def _check(m: re.Match) -> str:
        url = m.group(0)
        if allowed_urls and any(url.startswith(a) for a in allowed_urls if a):
            return url
        return ""
    cleaned, n2 = re.subn(r"https?://\S+", _check, cleaned, flags=re.IGNORECASE)
    total = n1 + n2
    if total:
        _logger.warning(
            "product_node: scrubbed %d hallucinated URL(s) from reply. Original: %r",
            total, text,
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned

PRODUCT_SYSTEM_PROMPT = """你是「{business_name}」的商品顾问，帮客户找到最合适的商品。

你可以调用以下工具：
- list_all_products：获取所有在售商品
- search_products：按款式/价格/库存类型筛选
- get_product_detail：查询指定商品编号的详情

回复要求：
- 严禁在未调用工具获取真实数据的情况下推荐或描述任何具体商品
- 只推荐工具返回的真实商品，使用商品编号和准确价格
- 自然口语，像真实客服发短信，最多推荐3款
- 推荐格式：商品名(编号) + 核心特点1-2句 + 准确价格 + 定制周期
- 如问的款式不存在，诚实说明并推荐最接近的
- 严禁 Markdown，最多1个emoji
- 严禁生成任何 URL、链接、网址（含 http/https/淘宝/天猫等形式）；商品数据库中没有购买链接字段，任何链接都是幻觉
{lang_rule}"""


async def product_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Handle product catalog inquiries using DB-backed tools.

    The LLM decides which tool(s) to call; this node executes them and
    feeds the results back for the final natural-language answer.
    """
    llm = config["configurable"]["llm"]
    product_service = config["configurable"].get("product_service")
    prompt_repo = config["configurable"].get("prompt_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []

    profile = config["configurable"].get("business_profile")
    business_name = profile.business_name if profile else "我们"

    last_user_text: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_text)
    lang_rule = make_lang_rule(default_lang, business_name=business_name)

    _active = await resolve_node_prompt(prompt_repo, "product_node", PRODUCT_SYSTEM_PROMPT)
    system_msg = SystemMessage(
        content=_active.format(lang_rule=lang_rule, business_name=business_name)
    )

    # ── Guard: no product service → seamless handoff to human ───────────────
    if not product_service:
        msg = await build_handoff_message(config, "handoff.product_unavailable")
        suggestion = await get_handoff_suggestion(config, "product_unavailable")
        return {
            "messages": [AIMessage(content=msg)],
            "request_human": True,
            "handoff_context": {
                "reason": "product_unavailable",
                "user_question": last_user_text,
                "ai_attempted": "商品查询服务不可用，无法检索数据库",
                "order_context": state.get("order_context"),
                "suggested_action": suggestion,
            },
            "retrieved_docs": [],
        }

    # ── Define tools backed by the injected service ───────────────────────────
    @tool
    async def list_all_products() -> str:
        """获取缘梦婚纱所有在售商品目录，返回完整列表。"""
        products = await product_service.list_all()
        if not products:
            return "暂无商品信息。"
        return "\n\n".join(p.to_context_str() for p in products)

    @tool
    async def search_products(
        style: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        stock_type: str | None = None,
        rush_only: bool = False,
    ) -> str:
        """按条件搜索婚纱商品。
        style: 款式关键词，如"鱼尾裙"/"蓬蓬裙"/"A型裙"/"轻纱款"/"中式秀禾服"
        max_price: 最高价格（元）
        min_price: 最低价格（元）
        stock_type: "ready"现货 或 "custom"定制
        rush_only: 只看支持加急的商品
        """
        products = await product_service.search(
            style=style,
            max_price=max_price,
            min_price=min_price,
            stock_type=stock_type,
            rush_only=rush_only,
        )
        if not products:
            return "没有找到符合条件的商品。"
        return "\n\n".join(p.to_context_str() for p in products)

    @tool
    async def get_product_detail(product_id: str) -> str:
        """获取指定商品编号的详细信息，如 WD-P001。"""
        product = await product_service.get(product_id)
        if not product:
            return f"商品编号 {product_id} 不存在。"
        return product.to_context_str()

    tools = [list_all_products, search_products, get_product_detail]
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    # ── Multi-round tool execution loop (max 3 rounds) ───────────────────────
    # Some models (e.g. MiniMax) output tool calls in subsequent rounds even
    # after receiving ToolMessage results. We keep executing until the model
    # produces a plain text reply or we hit the cap.
    MAX_ROUNDS = 3
    messages = [system_msg, *state["messages"][-5:]]
    response = None
    made_tool_call = False
    # Collect URLs that appeared in DB tool output — these are safe to keep in the reply
    allowed_urls: set[str] = set()

    for _ in range(MAX_ROUNDS):
        response = await llm_with_tools.ainvoke(messages, config={"callbacks": callbacks})
        if not response.tool_calls:
            break
        made_tool_call = True
        tool_messages: list[ToolMessage] = []
        for tc in response.tool_calls:
            t = tool_map.get(tc["name"])
            if t:
                try:
                    result = await t.ainvoke(tc["args"])
                    # Harvest any URLs present in the tool output (from purchase_url field)
                    for m in re.finditer(r"https?://\S+", str(result), re.IGNORECASE):
                        allowed_urls.add(m.group(0))
                except Exception as exc:
                    result = f"工具调用失败：{exc}"
            else:
                result = f"未知工具：{tc['name']}"
            tool_messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"])
            )
        messages = [*messages, response, *tool_messages]

    if response is None or not made_tool_call:
        # LLM skipped tool calls — cannot fabricate product data.
        reply = (
            f"我帮您查询{business_name}的商品，能告诉我您偏好的款式"
            "或预算范围吗？这样我能更快找到合适的。"
        )
    else:
        reply = _scrub_urls(strip_thinking(response.content), allowed_urls=allowed_urls)

    return {
        "messages": [AIMessage(content=reply)],
        "retrieved_docs": [],
    }
