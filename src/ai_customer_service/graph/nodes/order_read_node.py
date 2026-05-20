from __future__ import annotations

import logging
from datetime import date as _date
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from ...domain.entities import OrderActionRequest
from ...domain.exceptions import InvalidOrderActionError, OrderAccessDeniedError, OrderNotFoundError
from ..state import CustomerServiceState
from ._utils import extract_order_context, strip_thinking, lang_format, get_default_lang, make_lang_rule

_logger = logging.getLogger(__name__)

ORDER_READ_EXTRACTION_PROMPT = """你是「{business_name}」的订单查询解析器。
从用户消息中提取查询操作和订单号。

支持的查询类型（只读，不修改订单）：
- get_status            : 查询订单状态
- get_production_progress : 查询定制婚纱的生产进度
- get_tracking          : 查询物流/快递信息
- get_refund_status     : 查询退款进度（用于已申请退款/换货的订单）

若消息未提供订单号，order_id 返回空字符串。
若无法判断查询类型，默认为 get_status。"""

ORDER_READ_RESPONSE_PROMPT = """你是「{business_name}」的订单查询客服，根据以下订单查询结果，向客户自然地说明情况。

回复要求：
- 自然口语，不超过120字，像发短信一样简洁
- 严禁 Markdown（不用 **加粗**、→箭头、[括号标注]、列表符号、标题等）
- 最多1个 emoji
- 语气亲切，真诚有温度
{lang_rule}

订单查询结果：
{result_message}"""


class OrderReadExtraction(BaseModel):
    action: Literal["get_status", "get_production_progress", "get_tracking", "get_refund_status"] = Field(
        description="查询操作类型"
    )
    order_id: str = Field(description="订单号，未提供时为空字符串")


async def order_read_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Handle read-only order queries (status, production progress, tracking).

    Multi-turn: if no order ID is provided, asks the user and sets
    awaiting_order_id so the next message bypasses the router.
    """
    llm = config["configurable"]["llm"]
    order_service = config["configurable"]["order_service"]
    rules_service = config["configurable"].get("rules_service")
    prompt_repo = config["configurable"].get("prompt_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []
    profile = config["configurable"].get("business_profile")
    user_id: str = state.get("user_id", "")
    business_name = profile.business_name if profile else "缘梦婚纱"

    # Load dynamic response prompt from DB if available (Phase 8).
    # Falls back to the hardcoded constant; extraction prompt is never overridden
    # because it is tightly coupled to OrderReadExtraction's function-calling schema.
    _response_prompt_tpl = ORDER_READ_RESPONSE_PROMPT
    if prompt_repo:
        try:
            _db = await prompt_repo.get_active_prompt("order_read_node")
            if _db:
                _response_prompt_tpl = _db
        except Exception:
            _logger.warning("order_read_node: failed to load prompt from DB", exc_info=True)

    # 取用户最后一条消息用于语言检测，获取默认语言
    last_user_msg: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_msg)

    extractor = llm.with_structured_output(OrderReadExtraction, method="function_calling")
    try:
        extraction: OrderReadExtraction | None = await extractor.ainvoke(
            [SystemMessage(content=ORDER_READ_EXTRACTION_PROMPT.format(business_name=business_name)), *state["messages"][-5:]],
            config={"callbacks": callbacks},
        )
    except Exception:
        extraction = None

    if extraction is None:
        msg = await lang_format(
            llm,
            "请告诉我您的订单号，以及想查询什么内容（订单状态/生产进度/物流信息）。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "order_read_node",
        }

    if not extraction.order_id:
        # Try to fetch this user's orders to avoid asking for order ID unnecessarily
        user_orders = []
        if user_id:
            try:
                user_orders = await order_service.list_orders(user_id)
            except Exception:
                _logger.warning("list_orders failed for user %s", user_id)

        if len(user_orders) == 1:
            # Exactly one order — silently use it
            extraction = OrderReadExtraction(
                action=extraction.action,
                order_id=user_orders[0].order_id,
            )
        elif len(user_orders) >= 2:
            # Multiple orders — present up to 5 most recent and ask customer to choose
            display_orders = user_orders[:5]
            lines = []
            for idx, o in enumerate(display_orders, start=1):
                meta = o.wedding_meta
                stage_label = meta.production_stage.value if meta.is_custom else o.status.value
                wedding_hint = ""
                if meta.wedding_date:
                    try:
                        wedding_dt = _date.fromisoformat(meta.wedding_date)
                        days = (wedding_dt - _date.today()).days
                        wedding_hint = f"，婚期{days}天"
                    except ValueError:
                        pass
                lines.append(f"{idx}. {o.order_id}（{stage_label}{wedding_hint}）")
            header = "您有以下订单，请告知您想查询哪个："
            if len(user_orders) > 5:
                header = f"您有以下订单，请告知您想查询哪个（显示最近 5 条，共 {len(user_orders)} 条）："
            zh_list = header + "\n" + "\n".join(lines)
            msg = await lang_format(llm, zh_list, last_user_msg, default_lang)
            return {
                "messages": [AIMessage(content=msg)],
                "awaiting_order_id": "order_read_node",
            }
        else:
            # 0 orders or query failed — fall back to original prompt
            msg = await lang_format(
                llm,
                (
                    "请提供您的婚纱订单号，我来帮您查询。\n"
                    "可在购买确认邮件或个人中心「我的订单」中查找。"
                ),
                last_user_msg, default_lang,
            )
            return {
                "messages": [AIMessage(content=msg)],
                "awaiting_order_id": "order_read_node",
            }

    action_request = OrderActionRequest(
        action=extraction.action,
        order_id=extraction.order_id,
    )

    try:
        result = await order_service.execute(action_request, user_id)
        order_ctx: dict = extract_order_context(result.order)
        # Use structured response prompt to prevent LLM from generating Markdown
        lang_rule = make_lang_rule(default_lang, business_name=business_name)
        _fmt_kwargs = dict(
            business_name=business_name,
            lang_rule=lang_rule,
            result_message=strip_thinking(result.message),
        )
        try:
            _response_prompt = _response_prompt_tpl.format(**_fmt_kwargs)
        except KeyError:
            # DB prompt may omit {business_name}; fall back without it
            _response_prompt = _response_prompt_tpl.format(
                lang_rule=lang_rule,
                result_message=strip_thinking(result.message),
            )
        _formatted = await llm.ainvoke(
            [SystemMessage(content=_response_prompt), *state["messages"][-3:]],
            config={"callbacks": callbacks},
        )
        reply_content = strip_thinking(_formatted.content)

        # Proactive follow-up when order is urgent — hint text read from
        # business_rules table (key: proactive_hint.{status_value}).
        # Returns empty string when not configured, so non-wedding businesses
        # that don't seed these rules simply skip the proactive message.
        if state.get("is_urgent") and result.order and rules_service:
            status_val = (
                result.order.status.value
                if hasattr(result.order.status, "value")
                else str(result.order.status)
            )
            proactive: str = await rules_service.get(
                f"proactive_hint.{status_val}", ""
            )
            if isinstance(proactive, str) and proactive:
                reply_content = reply_content + "\n\n" + proactive.strip('"')

        return {
            "messages": [AIMessage(content=reply_content)],
            "awaiting_order_id": "",
            "order_context": order_ctx,
        }
    except OrderNotFoundError as e:
        msg = await lang_format(
            llm,
            (
                f"未找到订单 {e.order_id}，请确认订单号是否正确。"
                "如需帮助，请提供购买时的手机号或收件邮箱以便核实。"
            ),
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
        }
    except OrderAccessDeniedError:
        msg = await lang_format(
            llm,
            (
                "抱歉，该订单与您的账号不匹配，无法查询。\n"
                "如果您有多个账号，请确认下单时使用的账号登录后再试，"
                "或联系专属顾问协助核实。"
            ),
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
        }
    except InvalidOrderActionError as e:
        msg = await lang_format(llm, str(e), last_user_msg, default_lang)
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
        }
    except Exception:
        import logging
        logging.getLogger(__name__).exception("order_read_node unexpected error")
        msg = await lang_format(
            llm, "查询时遇到问题，请稍后重试或联系您的专属顾问。", last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
        }
