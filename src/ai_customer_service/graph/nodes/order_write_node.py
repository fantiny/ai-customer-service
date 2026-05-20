from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ...domain.entities import OrderActionRequest
from ...domain.exceptions import InvalidOrderActionError, OrderAccessDeniedError, OrderNotFoundError
from ...use_cases.rules_keys import RulesKey
from ..state import CustomerServiceState
from ._utils import extract_order_context, strip_thinking, lang_format, get_default_lang

_logger = logging.getLogger(__name__)

ORDER_WRITE_EXTRACTION_PROMPT = """你是「{business_name}」的订单操作解析器。
从用户消息中提取写操作类型和订单号。

支持的写操作（均需人工审批）：
- cancel_order          : 取消订单
- initiate_refund       : 申请退款（已签收商品可直接退款）
- exchange_order        : 申请换货（已签收，尺码/款式/质量问题）
- request_rush          : 申请加急制作

rush_level 仅在 action=request_rush 时填写：
{rush_info}
- 其他情况留空

若消息未提供订单号，order_id 返回空字符串。"""


class OrderWriteExtraction(BaseModel):
    action: Literal["cancel_order", "initiate_refund", "exchange_order", "request_rush"] = Field(
        description="写操作类型"
    )
    order_id: str = Field(description="订单号，未提供时为空字符串")
    rush_level: Literal["standard_rush", "super_rush", ""] = Field(
        default="", description="加急等级，仅 request_rush 时有效"
    )
    exchange_reason: str = Field(
        default="", description="换货原因，仅 exchange_order 时填写（如：尺码不合/做工问题/款式不符）"
    )


_STAGE_LABELS: dict[str, str] = {
    "pending": "待排产", "confirmed": "已排产", "cutting": "面料剪裁",
    "sewing": "主体缝制", "beading": "珠绣工艺", "qc": "质量检验",
    "ready": "制作完成", "shipped": "已发货", "delivered": "已送达",
}
_CANCEL_REFUND_PCT: dict[str, int] = {
    "cutting": 50, "sewing": 30, "beading": 20, "qc": 10,
}


def _build_ai_analysis(
    action: str,
    order_ctx: dict | None,
    days_to_wedding: int | None,
) -> str:
    """Generate a one-sentence agent hint for the HITL approval card.

    Pure rule-based — zero LLM calls, zero latency.
    Returns an empty string when no meaningful hint can be formed.
    """
    ctx = order_ctx or {}
    stage = ctx.get("production_stage", "")
    if action == "cancel_order":
        pct = _CANCEL_REFUND_PCT.get(stage)
        if pct is not None:
            label = _STAGE_LABELS.get(stage, stage)
            return f"婚纱已进入{label}阶段，预计退款约 {pct}%"
        if stage in ("ready", "shipped", "delivered"):
            return "婚纱已完成/发货，按协议无法退款，建议转人工协商"
        return "订单处于备料阶段，可全额退款"
    elif action == "initiate_refund":
        if days_to_wedding is not None and days_to_wedding < 14:
            return f"婚礼仅剩 {days_to_wedding} 天，建议优先处理退款申请"
        return "满足退款条件，建议批准"
    elif action == "exchange_order":
        if days_to_wedding is not None and days_to_wedding < 21:
            return f"婚礼仅剩 {days_to_wedding} 天，换货时间紧迫，需确认能否赶制"
        return "换货申请，核实原因后批准"
    elif action == "request_rush":
        if days_to_wedding is not None:
            if days_to_wedding < 30:
                return f"婚礼仅剩 {days_to_wedding} 天，情况紧急，建议优先批准"
            if days_to_wedding < 45:
                return f"婚礼剩余 {days_to_wedding} 天，建议批准加急"
            return f"婚礼剩余 {days_to_wedding} 天，酌情处理"
        return "确认产能后批准，附加费单独通知客户"
    return ""


async def order_write_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Handle order write operations (cancel, refund, rush) — all require HITL approval.

    Multi-turn: if no order ID is provided, asks the user and sets
    awaiting_order_id so the next message bypasses the router.
    """
    llm = config["configurable"]["llm"]
    order_service = config["configurable"]["order_service"]
    rules_service = config["configurable"].get("rules_service")
    workflow_repo = config["configurable"].get("workflow_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []
    profile = config["configurable"].get("business_profile")
    business_name = profile.business_name if profile else "缘梦婚纱"
    user_id: str = state.get("user_id", "")
    last_user_msg: str = state["messages"][-1].content if state["messages"] else ""
    default_lang = await get_default_lang(config, last_user_text=last_user_msg)

    # Fetch rush fee rates and days from business rules
    if rules_service:
        standard_rush_rate = await rules_service.get(RulesKey.RUSH_FEE_STANDARD, 0.50)
        super_rush_rate    = await rules_service.get(RulesKey.RUSH_FEE_SUPER,    1.00)
        standard_rush_days = await rules_service.get(RulesKey.RUSH_DAYS_STANDARD, 30)
        super_rush_days    = await rules_service.get(RulesKey.RUSH_DAYS_SUPER,    15)
    else:
        standard_rush_rate, super_rush_rate = 0.50, 1.00
        standard_rush_days, super_rush_days = 30, 15

    rush_info = (
        f"- standard_rush : 加急{standard_rush_days}天交付（+{int(float(standard_rush_rate) * 100)}%附加费）\n"
        f"- super_rush    : 特急{super_rush_days}天交付（+{int(float(super_rush_rate) * 100)}%附加费）"
    )

    extraction_prompt = ORDER_WRITE_EXTRACTION_PROMPT.format(business_name=business_name, rush_info=rush_info)

    extractor = llm.with_structured_output(OrderWriteExtraction, method="function_calling")
    try:
        extraction: OrderWriteExtraction | None = await extractor.ainvoke(
            [SystemMessage(content=extraction_prompt), *state["messages"][-5:]],
            config={"callbacks": callbacks},
        )
    except Exception:
        extraction = None

    if extraction is None:
        msg = await lang_format(
            llm,
            "请告诉我您的订单号，以及想办理什么业务（取消订单/申请退款/申请换货/申请加急）。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "order_write_node",
            "pending_action": {},
        }

    if not extraction.order_id:
        action_labels = {
            "cancel_order":   "取消订单",
            "initiate_refund": "申请退款",
            "exchange_order": "申请换货",
            "request_rush":   "申请加急制作",
        }
        action_label = action_labels.get(extraction.action, extraction.action)
        msg = await lang_format(
            llm,
            f"好的，帮您办理{action_label}。请提供您的婚纱订单号，格式示例：WD-20240001",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "order_write_node",
            "pending_action": {},
        }

    extra: dict = {}
    if extraction.rush_level:
        extra["rush_level"] = extraction.rush_level
    if extraction.exchange_reason:
        extra["reason"] = extraction.exchange_reason
    action_request = OrderActionRequest(
        action=extraction.action,
        order_id=extraction.order_id,
        extra=extra,
    )

    # ── Pre-validation: check feasibility BEFORE triggering HITL ─────────────
    # This avoids the bad UX of approving an action that will immediately fail.
    # validate() returns the fetched Order so we can extract wedding_date for
    # the ai_analysis hint without a second DB round-trip.
    validated_order = None
    try:
        validated_order = await order_service.validate(action_request, user_id)
    except OrderNotFoundError as e:
        msg = await lang_format(
            llm,
            f"未找到订单 {e.order_id}，请确认订单号是否正确。\n"
            "可在购买确认短信或个人中心「我的订单」中查找。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
    except OrderAccessDeniedError:
        msg = await lang_format(
            llm,
            "抱歉，该订单与您的账号不匹配，无法操作。\n"
            "请确认您使用的是下单时的账号，或联系专属顾问协助核实。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
    except InvalidOrderActionError as e:
        msg = await lang_format(llm, e.user_reason, last_user_msg, default_lang)
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }

    # Determine which actions require HITL approval (configurable via DB).
    # Falls back to requiring HITL for all writes if rules_service is absent.
    hitl_actions: list[str] = ["cancel_order", "initiate_refund", "exchange_order", "request_rush"]
    if rules_service:
        try:
            configured = await rules_service.get(RulesKey.HITL_REQUIRED_ACTIONS)
            if isinstance(configured, list):
                hitl_actions = [str(a) for a in configured]
        except Exception:
            _logger.warning("order_write_node: failed to load HITL actions from rules — using default", exc_info=True)

    action_labels = {
        "cancel_order": "取消婚纱订单",
        "initiate_refund": "申请退款",
        "exchange_order": "申请换货",
        "request_rush": f"申请{'特急' if extraction.rush_level == 'super_rush' else '加急'}制作",
    }

    if extraction.action not in hitl_actions:
        # Action is not in the HITL list — execute directly without human approval.
        try:
            result = await order_service.execute(action_request, user_id)
            final_msg = await lang_format(llm, strip_thinking(result.message), last_user_msg, default_lang)
            return {
                "messages": [AIMessage(content=final_msg)],
                "awaiting_order_id": "",
                "pending_action": {},
                "order_context": extract_order_context(result.order),
            }
        except InvalidOrderActionError as e:
            msg = await lang_format(llm, e.user_reason, last_user_msg, default_lang)
            return {"messages": [AIMessage(content=msg)], "awaiting_order_id": "", "pending_action": {}}
        except (OrderNotFoundError, OrderAccessDeniedError) as e:
            msg = await lang_format(llm, str(e), last_user_msg, default_lang)
            return {"messages": [AIMessage(content=msg)], "awaiting_order_id": "", "pending_action": {}}

    # Compute days to wedding for AI analysis hint.
    # Prefer the freshly-validated order (no extra DB call); fall back to whatever
    # order_context is already in the state (set by a prior order_read turn).
    order_ctx = extract_order_context(validated_order) if validated_order else (state.get("order_context") or {})
    wedding_date_str = order_ctx.get("wedding_date")
    days_to_wedding: int | None = None
    if wedding_date_str:
        try:
            from datetime import date as _dt_date, datetime, timezone
            _wds = str(wedding_date_str)
            if "T" in _wds or " " in _wds:
                # Full ISO datetime — parse with timezone awareness
                _wdt = datetime.fromisoformat(_wds.replace("Z", "+00:00"))
                if _wdt.tzinfo is None:
                    _wdt = _wdt.replace(tzinfo=timezone.utc)
                _today = datetime.now(timezone.utc)
            else:
                # Date-only string "YYYY-MM-DD" — compare as dates to avoid tz issues
                _wdt = datetime.combine(_dt_date.fromisoformat(_wds), datetime.min.time(), timezone.utc)
                _today = datetime.now(timezone.utc)
            diff = _wdt - _today
            days_to_wedding = max(0, diff.days)
        except Exception:
            pass

    pending = {
        "action": extraction.action,
        "order_id": extraction.order_id,
        "user_id": user_id,
        "rush_level": extraction.rush_level,
        "action_label": action_labels.get(extraction.action, extraction.action),
        "ai_analysis": _build_ai_analysis(extraction.action, order_ctx, days_to_wedding),
    }
    approval: dict = interrupt(pending)

    if not approval.get("approved"):
        msg = await lang_format(
            llm,
            "操作已取消。如有其他需要，欢迎随时联系我们。祝您婚礼顺利！💕",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }

    try:
        result = await order_service.execute(action_request, user_id)
        final_msg = await lang_format(llm, strip_thinking(result.message), last_user_msg, default_lang)
        return {
            "messages": [AIMessage(content=final_msg)],
            "awaiting_order_id": "",
            "pending_action": {},
            "order_context": extract_order_context(result.order),
        }
    except OrderNotFoundError as e:
        msg = await lang_format(
            llm,
            f"未找到订单 {e.order_id}，请确认订单号是否正确。\n"
            "可在购买确认短信或个人中心「我的订单」中查找。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
    except OrderAccessDeniedError:
        msg = await lang_format(
            llm,
            "抱歉，该订单与您的账号不匹配，无法操作。\n"
            "请确认您使用的是下单时的账号，或联系专属顾问协助核实。",
            last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
    except InvalidOrderActionError as e:
        msg = await lang_format(llm, e.user_reason, last_user_msg, default_lang)
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
    except Exception:
        _logger.exception("order_write_node unexpected error")
        msg = await lang_format(
            llm, "处理订单时遇到问题，请稍后重试或联系您的专属顾问。", last_user_msg, default_lang,
        )
        return {
            "messages": [AIMessage(content=msg)],
            "awaiting_order_id": "",
            "pending_action": {},
        }
