from __future__ import annotations

import functools
import logging
from datetime import date
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, create_model

from ..state import CustomerServiceState

logger = logging.getLogger(__name__)

# ── Hardcoded fallback (used when BusinessProfile is not injected) ─────────────
ROUTER_SYSTEM_PROMPT = """你是一个婚纱电商客服意图分类器。分析用户最近的消息，将其准确分类为以下七种意图之一：

**product** — 用户咨询具体商品或想要推荐：
- 推荐婚纱款式、问某款婚纱价格
- 询问某款婚纱特点、面料、颜色、适合场合
- 问"有没有便宜的"、"哪款最受欢迎"等商品筛选问题

**faq** — 用户咨询通用政策或业务知识（非特定商品）：
- 退换货政策、售后保障
- 量体方法、如何保养
- 定制流程、生产周期、付款方式
- 配送时间、试穿预约、配件搭配

**order_read** — 用户要查询某笔订单的信息（只读，无需修改）：
- 查询订单状态或生产进度
- 查询物流/快递单号
- 问"我的订单到哪了"

**order_write** — 用户要对【已有订单】执行写操作（需审批）：
- 取消订单
- 申请退款
- 对【已下单的婚纱】申请加急制作（用户已有订单，想让现有订单加急）

注意：若用户尚未下单，只是询问"加急是否可行"或"新购时能加急吗"，应分类为 faq；若是在选购商品时问某款婚纱能否加急，应分类为 product。

**aftersales** — 用户反映商品或服务质量问题：
- 收到的婚纱有质量问题（破损、做工问题、颜色不符）
- 尺寸不合适、与描述不符
- 对服务不满意的投诉

**measurement_guide** — 用户需要量体引导或提供定制尺寸数据：
- 明确要做定制款婚纱，需要提供身材数据
- 主动说出"我的身高/胸围/腰围/臀围是…"（要收集全部数据）
- 问"怎么量体"（若只是咨询方法不含具体数字 → faq；若同时提供数字 → measurement_guide）
- 要"开始量体"/"帮我记录尺寸"

**general** — 其他所有情况：
- 问候、感谢、闲聊
- 婚礼当天紧急求助（建议拨打热线）
- 超出婚纱业务的话题

分类原则：
- order_write 只适用于【已有订单】的写操作；仅查询信息选 order_read
- 询问加急是否可行、加急费用等（无现有订单语境）→ faq；在选购时问能否加急 → product；对现有订单申请加急 → order_write
- 仅描述质量问题、未要求退款时选 aftersales；明确要求退款时选 order_write
- 问商品推荐选 product；问政策、流程选 faq
- 仅问量体方法（不含实际数字）选 faq；开始实际提供尺寸数据时选 measurement_guide

仅返回 JSON，不要解释。"""

# Public fallback model (used when no BusinessProfile injected).
# Keeping the name "IntentClassification" stable so external callers and tests
# can rely on `schema.__name__ == "IntentClassification"` for matching.
class IntentClassification(BaseModel):
    intent: Literal[
        "product", "faq", "order_read", "order_write", "aftersales", "general",
        "measurement_guide",
    ] = Field(description="用户意图分类")
    confidence: float = Field(ge=0.0, le=1.0, description="分类置信度")


# Private alias used inside router_node (keeps the implementation name readable)
_FallbackIntentClassification = IntentClassification


# ── Dynamic model builder ──────────────────────────────────────────────────────

@functools.lru_cache(maxsize=16)
def _build_intent_model(intent_ids: tuple[str, ...]) -> type[BaseModel]:
    """Build a Pydantic model with a dynamic Literal[intent_ids] field.

    Cached by intent_ids tuple so we don't recreate on every request.
    The model is used with llm.with_structured_output() to ensure only
    valid intent_ids can be returned by the LLM.
    """
    return create_model(
        "DynamicIntentClassification",
        intent=(Literal[intent_ids], Field(description="用户意图分类")),  # type: ignore[valid-type]
        confidence=(float, Field(ge=0.0, le=1.0, description="分类置信度")),
    )


def _build_router_prompt(profile: object) -> str:
    """Build a router system prompt from BusinessProfile.intents.

    Each intent's description is included verbatim so the LLM has the full
    context needed to route accurately.  If a DB prompt exists for router_node
    it will override this generated version (prompt_repo takes precedence).
    """
    lines = [
        f"你是「{profile.business_name}」的客服意图分类器。",  # type: ignore[attr-defined]
        "分析用户最近的消息，将其准确分类为以下意图之一：",
        "",
    ]
    for intent in profile.intents:  # type: ignore[attr-defined]
        lines.append(f"**{intent.intent_id}** — {intent.description}")
        lines.append("")
    lines.append("仅返回 JSON，不要解释。")
    return "\n".join(lines)


def _compute_is_urgent(order_context: dict, profile: object | None) -> bool:
    """Generic urgency check driven by BusinessProfile.urgency_config.

    Falls back to the legacy wedding_date / 14-day check when no profile is
    injected (startup probe, tests without DI).
    """
    if profile is None:
        # Legacy fallback: wedding_date within 14 days
        wedding_date_str = order_context.get("wedding_date")
        if not wedding_date_str:
            return False
        try:
            return 0 <= (date.fromisoformat(str(wedding_date_str)) - date.today()).days <= 14
        except ValueError:
            return False

    uc = profile.urgency_config  # type: ignore[attr-defined]
    if not uc.enabled:
        return False
    deadline_str = order_context.get(uc.deadline_field)
    if not deadline_str:
        return False
    try:
        deadline_dt = date.fromisoformat(str(deadline_str))
        days_remaining = (deadline_dt - date.today()).days
        return 0 <= days_remaining <= uc.urgent_days_threshold
    except (ValueError, TypeError):
        return False


async def router_node(state: CustomerServiceState, config: RunnableConfig) -> dict:
    """Classify the user's intent using structured LLM output.

    When a BusinessProfile is injected, the intent list and router prompt are
    generated dynamically from profile.intents.  Otherwise falls back to the
    hardcoded wedding-dress defaults.
    """
    llm = config["configurable"]["llm"]
    prompt_repo = config["configurable"].get("prompt_repo")
    handler = config["configurable"].get("langfuse_handler")
    callbacks = [handler] if handler else []
    profile = config["configurable"].get("business_profile")

    # ── Build intent model and system prompt ───────────────────────────────────
    if profile is not None and profile.intents:
        intent_ids = tuple(i.intent_id for i in profile.intents)
        intent_model = _build_intent_model(intent_ids)
        # DB prompt takes priority over generated prompt
        active_prompt = None
        if prompt_repo:
            active_prompt = await prompt_repo.get_active_prompt("router_node")
        if not active_prompt:
            active_prompt = _build_router_prompt(profile)
        fallback_intent = profile.fallback_intent_id
    else:
        intent_model = _FallbackIntentClassification
        active_prompt = ROUTER_SYSTEM_PROMPT
        if prompt_repo:
            _db = await prompt_repo.get_active_prompt("router_node")
            if _db:
                active_prompt = _db
        fallback_intent = "general"

    # Force function_calling — avoids <think> tag interference on reasoning models
    classifier = llm.with_structured_output(intent_model, method="function_calling")
    recent_messages = state["messages"][-6:]

    try:
        result = await classifier.ainvoke(
            [SystemMessage(content=active_prompt), *recent_messages],
            config={"callbacks": callbacks},
        )
    except Exception:
        logger.warning("router_node: structured output failed, falling back to %r", fallback_intent)
        result = None

    # ── Urgency detection ──────────────────────────────────────────────────────
    order_context: dict = state.get("order_context") or {}
    is_urgent = _compute_is_urgent(order_context, profile)

    if result is None:
        return {"intent": fallback_intent, "is_urgent": is_urgent, "low_confidence": True}

    CONFIDENCE_THRESHOLD = 0.55

    if result.confidence < CONFIDENCE_THRESHOLD:
        logger.debug(
            "Low-confidence intent=%s conf=%.2f → fallback to %r",
            result.intent, result.confidence, fallback_intent,
        )
        return {"intent": fallback_intent, "is_urgent": is_urgent, "low_confidence": True}

    return {"intent": result.intent, "is_urgent": is_urgent, "low_confidence": False}
