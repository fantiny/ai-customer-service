"""Shared utilities for graph nodes."""
from __future__ import annotations

import asyncio as _asyncio
import logging
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities import Order

_logger = logging.getLogger(__name__)


def _detect_language(text: str) -> str | None:
    """Heuristic language detection from message text. Returns BCP-47 tag or None."""
    if not text or len(text.strip()) < 3:
        return None

    # Count character script blocks
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    hiragana = sum(1 for c in text if '぀' <= c <= 'ゟ')
    katakana = sum(1 for c in text if '゠' <= c <= 'ヿ')
    hangul = sum(1 for c in text if '가' <= c <= '힣')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = max(len(text), 1)

    if (hiragana + katakana) / total > 0.15:
        return "ja"
    if hangul / total > 0.15:
        return "ko"
    if cjk / total > 0.15:
        return "zh-CN"
    if latin / total > 0.4:
        # Simple English heuristic — could expand for other Latin-script langs
        return "en"
    return None

# ── 多语言规则 ─────────────────────────────────────────────────────────────────

def make_lang_rule(default_lang: str = "zh-CN", business_name: str = "缘梦婚纱") -> str:
    """生成嵌入 system prompt 的语言规则文本。

    default_lang 来自后台配置（business_rules.default_language 或 .env DEFAULT_LANGUAGE）。
    business_name 来自 BusinessProfile，用于指导 LLM 保留店铺名原文。
    """
    return (
        "【语言规则 — 最高优先级】\n"
        f"- 系统配置的默认语言：{default_lang}\n"
        "- 检测客户最后一条消息所使用的语言，用完全相同的语言回复\n"
        f"- 若无法判断客户语言，使用默认语言 {default_lang} 回复\n"
        f"- 店铺名「{business_name}」及商品型号保留原文，其余内容完整翻译"
    )


async def get_default_lang(config: dict, last_user_text: str | None = None) -> str:
    """从 business_rules 或 configurable 获取当前默认语言（带 60s 缓存）。

    优先级：
    1. 从 last_user_text 自动检测（当结果与配置不同时覆盖配置）
    2. business_rules.default_language
    3. configurable.default_language
    4. "zh-CN"
    """
    rules_service = config["configurable"].get("rules_service")
    if rules_service is not None:
        configured_lang = await rules_service.get_language()
        if not configured_lang:
            configured_lang = config["configurable"].get("default_language", "zh-CN")
    else:
        configured_lang = config["configurable"].get("default_language", "zh-CN")

    if last_user_text:
        detected = _detect_language(last_user_text)
        if detected and detected != configured_lang:
            return detected

    return configured_lang


async def lang_format(
    llm: object,
    zh_text: str,
    last_user_msg: str,
    default_lang: str = "zh-CN",
    business_name: str = "缘梦婚纱",
) -> str:
    """将一条中文客服回复转换为目标语言版本。

    目标语言：客户消息语言 > 默认语言（default_lang）。
    若客户使用中文且默认语言也是中文，直接返回原文（零 LLM 调用）。
    business_name 用于指导 LLM 保留店铺名原文不翻译。
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # 局部导入避免循环

    # 快速通道：用户说中文 且 默认语言是中文 → 无需翻译
    if _is_chinese(last_user_msg) and default_lang.lower().startswith("zh"):
        return zh_text

    default_hint = f"若无法判断客户语言，使用 {default_lang} 回复。"
    system = (
        "你是多语言客服翻译助手。\n"
        f"将以下中文客服回复翻译成客户消息所用的语言。{default_hint}\n"
        f"店铺名「{business_name}」保留原文，其余完整翻译。\n"
        "只输出翻译结果，不要任何解释。\n\n"
        f"原文（中文）：\n{zh_text}"
    )
    result = await llm.ainvoke(  # type: ignore[attr-defined]
        [SystemMessage(content=system), HumanMessage(content=last_user_msg)]
    )
    return strip_thinking(result.content)


def _is_chinese(text: str) -> bool:
    """快速判断文本是否以中文为主（直接跳过 LLM 翻译）。

    规则：
    - 含平假名/片假名 → 日文，返回 False
    - 含韩文字母 → 韩文，返回 False
    - CJK 汉字占比 > 30% 且无上述符号 → 中文，返回 True
    """
    if not text:
        return True
    # 日文假名 (hiragana U+3040-U+309F, katakana U+30A0-U+30FF)
    if any("぀" <= c <= "ヿ" for c in text):
        return False
    # 韩文字母 (hangul syllables U+AC00-U+D7A3)
    if any("가" <= c <= "힣" for c in text):
        return False
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return cjk / len(text) > 0.3


def strip_thinking(text: str) -> str:
    """Remove internal model artifacts that must never be shown to customers.

    Strips:
    - <think>...</think> reasoning blocks (DeepSeek, Qwen, etc.)
    - <minimax:tool_call>...</minimax:tool_call> XML tool calls (MiniMax M2)
    Handles both complete and unclosed/truncated tags.
    """
    # Remove complete <think>...</think> blocks (including multiline)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove any leftover unclosed <think> block
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    # Remove MiniMax-specific XML tool call blocks
    text = re.sub(r"<minimax:tool_call>.*?</minimax:tool_call>", "", text, flags=re.DOTALL)
    text = re.sub(r"<minimax:tool_call>.*", "", text, flags=re.DOTALL)
    return text.strip()


async def build_handoff_message(config: dict, rules_key: str) -> str:
    """Return the customer-facing message for a seamless AI → human handoff.

    Priority:
    1. ``business_rules`` entry at ``rules_key`` (e.g. ``"handoff.policy_no_doc"``)
    2. ``BusinessProfile.handoff_config.notification_template``
    3. Hardcoded fallback constant

    Args:
        config: LangGraph RunnableConfig dict (the full config, not configurable).
        rules_key: Key to look up in business_rules (e.g. ``"handoff.policy_no_doc"``).

    Returns:
        The message string to send to the customer.
    """
    cfg = config.get("configurable", config)

    # 1. business_rules key
    rules_service = cfg.get("rules_service")
    if rules_service is not None:
        try:
            template = await rules_service.get(rules_key, "")
            if template:
                profile = cfg.get("business_profile")
                bname = profile.business_name if profile else ""
                return template.format(business_name=bname) if bname else template
        except Exception:
            _logger.warning("build_handoff_message: rules lookup failed for key %r", rules_key, exc_info=True)

    # 2. profile handoff_config
    profile = cfg.get("business_profile")
    if profile is not None:
        hc = profile.handoff_config
        if hc.notify_customer and hc.notification_template:
            return hc.notification_template.format(business_name=profile.business_name)
        if not hc.notify_customer:
            return hc.silent_handoff_message

    # 3. hardcoded fallback
    return "关于这个问题我来帮您连线专属顾问，马上为您处理～"


async def get_handoff_suggestion(config: dict, reason: str) -> str:
    """Return the suggested action string for the human agent receiving the handoff.

    Reads from business_rules key ``"handoff.suggestion.{reason}"``.
    Falls back to a generic suggestion based on reason type.
    """
    _FALLBACK_SUGGESTIONS: dict[str, str] = {
        "product_unavailable": "请为客户介绍符合需求的商品，重点了解款式偏好和预算范围",
        "policy_no_doc":       "请核实相关政策并告知客户具体条款，建议查阅内部政策手册",
        "explicit_request":    "客户主动要求人工服务，请继续接待",
    }

    cfg = config.get("configurable", config)
    rules_service = cfg.get("rules_service")
    if rules_service is not None:
        try:
            suggestion = await rules_service.get(f"handoff.suggestion.{reason}", "")
            if suggestion:
                return suggestion
        except Exception:
            _logger.warning("get_handoff_suggestion: rules lookup failed for reason %r", reason, exc_info=True)

    return _FALLBACK_SUGGESTIONS.get(reason, "请继续为客户提供服务")


# Negative-emotion keywords shared by aftersales_node and general_node.
# Listed here to avoid drift between the two copies.
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "投诉", "愤怒", "强烈不满", "退款", "索赔", "差评",
    "太差了", "不可接受", "要投诉",
)


async def llm_invoke_with_retry(llm, messages, *, max_retries: int = 3, base_delay: float = 1.0):
    """Invoke LLM with exponential backoff on transient errors (rate limit, timeout).

    Retries on: 429, RateLimitError, TimeoutError, ConnectionError.
    Raises immediately on: authentication errors, invalid request errors.
    """
    for attempt in range(max_retries):
        try:
            return await llm.ainvoke(messages)
        except Exception as exc:
            exc_str = str(exc).lower()
            is_transient = any(k in exc_str for k in ("429", "rate_limit", "timeout", "connection", "overloaded"))
            if not is_transient or attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            _logger.warning("LLM transient error (attempt %d/%d), retrying in %.1fs: %s", attempt+1, max_retries, delay, exc_str[:80])
            await _asyncio.sleep(delay)


# ── Shared order context extraction ──────────────────────────────────────────

def extract_order_context(order: "Order | None") -> dict:
    """Build the order_context dict from a domain Order object.

    Called by both order_read_node (after query) and order_write_node (after
    mutation) so that state["order_context"] is always up-to-date and
    downstream nodes (faq_node, aftersales_node) inject accurate information.
    """
    if order is None:
        return {}
    m = order.wedding_meta
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "total": float(order.total),
        "is_custom": m.is_custom,
        "is_rush": m.is_rush,
        "dress_style": m.dress_style,
        "color": m.color,
        "production_stage": m.production_stage.value,
        "wedding_date": m.wedding_date,
        "estimated_completion": m.estimated_completion,
        "rush_level": m.rush_level.value if m.rush_level else None,
        "items": [
            {"name": i.name, "quantity": i.quantity, "unit_price": i.unit_price}
            for i in order.items
        ],
    }


# ── Shared sentiment escalation check ────────────────────────────────────────

def check_sentiment_escalation(
    state: dict,
    *,
    threshold: int,
    urgent_threshold: int,
) -> tuple[int, bool]:
    """Detect negative emotion in the last human message and decide whether to escalate.

    Returns (new_negative_turns, should_escalate).

    Extracted from aftersales_node and general_node to eliminate duplication.
    Both nodes call this with their own thresholds and act on the result.
    """
    last_user_msg: str = ""
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", None) == "human" or getattr(msg, "role", None) == "user":
            last_user_msg = msg.content or ""
            break

    is_negative = any(kw in last_user_msg for kw in NEGATIVE_KEYWORDS)
    current = state.get("negative_turns", 0)
    new_count = current + 1 if is_negative else 0

    effective_threshold = urgent_threshold if state.get("is_urgent") else threshold
    return new_count, new_count >= effective_threshold


# ── DB prompt override with required-placeholder guard ───────────────────────

async def resolve_node_prompt(
    prompt_repo,
    node_name: str,
    default_prompt: str,
    required_placeholders: tuple[str, ...] = ("{lang_rule}",),
) -> str:
    """Return the active prompt for a node, preferring the DB version.

    If the DB prompt exists but is missing required placeholders, appends them.
    Falls back to default_prompt when the repo is unavailable or returns nothing.

    This eliminates the 4-copy pattern across faq_node, product_node,
    general_node, and aftersales_node:
        if prompt_repo:
            db = await prompt_repo.get_active_prompt(node_name)
            if db:
                prompt = db
                if "{lang_rule}" not in prompt:
                    prompt += "\\n{lang_rule}"
    """
    if not prompt_repo:
        return default_prompt
    try:
        db_prompt = await prompt_repo.get_active_prompt(node_name)
    except Exception:
        _logger.warning("resolve_node_prompt: failed to load prompt for %r", node_name, exc_info=True)
        return default_prompt
    if not db_prompt:
        return default_prompt
    result = db_prompt
    for placeholder in required_placeholders:
        if placeholder not in result:
            result = result + f"\n{placeholder}"
    return result
