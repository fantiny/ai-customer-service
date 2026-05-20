"""Measurement Guide Node — interactive body-measurement collection for custom dresses.

Flow:
  1. First turn: explain what measurements are needed + provide how-to tips.
  2. Subsequent turns: parse measurements from user replies; validate ranges;
     ask for remaining ones.
  3. When all four measurements are collected and valid: present a structured
     confirmation card and offer to proceed to order.

Multi-turn continuation: sets ``awaiting_order_id = "measurement_guide_node"``
until all measurements are confirmed, so the safety_check_node will route
subsequent messages here directly (bypassing the router).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import CustomerServiceState
from ._utils import build_handoff_message, get_handoff_suggestion, strip_thinking

logger = logging.getLogger(__name__)

# ── Measurement validation ranges (cm) ───────────────────────────────────────
_VALID_RANGES = {
    "height": (140, 200),   # cm
    "bust":   (70,  130),   # cm
    "waist":  (50,  110),   # cm
    "hips":   (70,  140),   # cm
}

_FIELD_LABELS = {
    "height": "身高",
    "bust":   "胸围",
    "waist":  "腰围",
    "hips":   "臀围",
}

_FIELD_ORDER = ["height", "bust", "waist", "hips"]

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM = """\
你是缘梦婚纱的专属量体顾问。你的任务是引导客户提供定制婚纱所需的准确体型数据。

## 你的职责
1. 耐心、专业地引导客户逐步提供四项数据：身高、胸围、腰围、臀围（单位：厘米）。
2. 每次只专注于收集下一个缺失的数据，不要一次问多项。
3. 当客户提供数据时，先确认是否合理（见合理范围），再继续下一项。
4. 提供简洁实用的量体方法提示，帮助客户自测准确数据。
5. 所有四项数据确认后，生成一张结构化确认卡，并询问是否继续选款/下单。

## 合理范围（单位：厘米）
- 身高：140–200 cm
- 胸围：70–130 cm
- 腰围：50–110 cm
- 臀围：70–140 cm

## 量体方法简介（客户问时使用）
- **身高**：赤脚站立靠墙，在头顶最高处做标记，卷尺垂直量至地面。
- **胸围**：水平绕胸部最丰满处一圈（不要捆紧，保持自然呼吸）。
- **腰围**：水平绕腰部最细处一圈（通常在肚脐上方约 3 cm）。
- **臀围**：水平绕臀部最丰满处一圈（通常在脚踝上方约 20 cm）。

## 当前已收集的数据
{collected_summary}

## 当前需要收集的项目
{next_field_hint}

## 输出规范
- 语气温柔亲切，像好闺蜜一样
- 每次回复简洁（2–4 句话）
- 数据确认后加一个鼓励的表情
- 若客户提供的数字不在合理范围，礼貌指出并请重新确认
- 四项全部收集完毕时，输出以下格式的确认卡（用三行破折号包裹）：

---
📏 **量体数据确认卡**
· 身高：{height} cm
· 胸围：{bust} cm
· 腰围：{waist} cm
· 臀围：{hips} cm

*数据已记录，请您核对无误后告知我，我将为您推荐最合适的款式！*
---
"""


# ── Node ─────────────────────────────────────────────────────────────────────

async def measurement_guide_node(
    state: CustomerServiceState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Interactively collect and validate body measurements for custom dress orders."""
    cfg = config.get("configurable", config)
    llm = cfg.get("llm")
    profile = cfg.get("business_profile")
    if llm is None:
        return {
            "messages": [AIMessage(content="量体服务暂时不可用，请稍后再试。")],
            "awaiting_order_id": "",
        }

    messages = state.get("messages", [])

    # ── Extract measurements already mentioned in the conversation ────────────
    collected = _extract_measurements_from_history(messages)

    # ── Contextual bare-number capture ────────────────────────────────────────
    # When the AI has already asked for a specific field and the user replies with
    # a bare number (e.g., "165" after AI asked for height), the keyword-based
    # extraction above won't match.  Here we infer the field from the last AI
    # message and try to assign a bare number from the last human message.
    collected = _try_contextual_bare_number(messages, collected)

    # ── Validate ranges ───────────────────────────────────────────────────────
    validated = {}
    invalid_fields = {}
    for field, value in collected.items():
        lo, hi = _VALID_RANGES[field]
        if lo <= value <= hi:
            validated[field] = value
        else:
            invalid_fields[field] = value

    # ── Build prompt context ──────────────────────────────────────────────────
    if validated:
        collected_lines = [f"· {_FIELD_LABELS[f]}：{validated[f]} cm" for f in _FIELD_ORDER if f in validated]
        collected_summary = "\n".join(collected_lines) if collected_lines else "（暂无）"
    else:
        collected_summary = "（暂无，刚开始收集）"

    missing = [f for f in _FIELD_ORDER if f not in validated]
    if missing:
        next_field = missing[0]
        lo, hi = _VALID_RANGES[next_field]
        next_field_hint = f"{_FIELD_LABELS[next_field]}（合理范围：{lo}–{hi} cm）"
    else:
        next_field = None
        next_field_hint = "全部收集完毕！"

    system_content = _SYSTEM.format(
        collected_summary=collected_summary,
        next_field_hint=next_field_hint,
        height=validated.get("height", "？"),
        bust=validated.get("bust", "？"),
        waist=validated.get("waist", "？"),
        hips=validated.get("hips", "？"),
    )

    # If there were invalid fields, add a note
    invalid_note = ""
    if invalid_fields:
        parts = [f"{_FIELD_LABELS[f]} {v} cm 不在合理范围" for f, v in invalid_fields.items()]
        invalid_note = f"\n\n⚠️ 请注意：以下数据可能有误，请重新确认：{'; '.join(parts)}"

    # ── Build message history for LLM (last 10 messages) ─────────────────────
    recent = messages[-10:] if len(messages) > 10 else messages
    llm_messages = [SystemMessage(content=system_content), *recent]

    # ── LLM call ──────────────────────────────────────────────────────────────
    try:
        response = await llm.ainvoke(llm_messages)
        reply = strip_thinking(response.content)
        if invalid_note:
            reply = reply + invalid_note
    except Exception:
        logger.exception("measurement_guide_node LLM error")
        reply = "量体引导服务出现问题，请稍后重试，或联系人工客服协助。"
        return {
            "messages": [AIMessage(content=reply)],
            "awaiting_order_id": "",
        }

    # ── Determine if we should continue or finish ─────────────────────────────
    all_done = len(validated) == 4

    if all_done:
        # All measurements collected — stop continuation routing
        return {
            "messages": [AIMessage(content=reply)],
            "awaiting_order_id": "",   # conversation complete
        }
    else:
        # Continue collecting in subsequent turns
        return {
            "messages": [AIMessage(content=reply)],
            "awaiting_order_id": "measurement_guide_node",
        }


# ── Measurement extraction ────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r'(\d{2,3})(?:\s*(?:cm|厘米|公分))?')

# Keyword patterns to identify which measurement a number refers to
# Two separate pattern dicts — applied in priority order (keyword-first wins).
# keyword-FIRST: only allow whitespace / light punctuation between keyword and number.
# number-FIRST:  require a unit marker OR direct adjacency to avoid false positives
#   like "165 胸围88" → bust=165.
_KW_FIRST_PATTERNS: dict[str, re.Pattern[str]] = {
    "height": re.compile(r'(?:身高|高度)[\s：:是]*(\d{2,3})', re.IGNORECASE),
    "bust":   re.compile(r'(?:胸围|上围)[\s：:是]*(\d{2,3})', re.IGNORECASE),
    "waist":  re.compile(r'腰围[\s：:是]*(\d{2,3})', re.IGNORECASE),
    "hips":   re.compile(r'(?:臀围|下围)[\s：:是]*(\d{2,3})', re.IGNORECASE),
}

# number-FIRST patterns (only used when keyword-first didn't match for that field)
# Require unit (cm/厘米) OR direct adjacency (number immediately before keyword, no space)
_NUM_FIRST_PATTERNS: dict[str, re.Pattern[str]] = {
    "height": re.compile(
        r'(\d{2,3})\s*(?:cm|厘米|公分)\s*的?\s*身高'   # unit required
        r'|(\d{2,3})身高',                               # direct adjacency
        re.IGNORECASE,
    ),
    "bust": re.compile(
        r'(\d{2,3})\s*(?:cm|厘米)\s*的?\s*胸围'
        r'|(\d{2,3})(?:胸围|上围)',
        re.IGNORECASE,
    ),
    "waist": re.compile(
        r'(\d{2,3})\s*(?:cm|厘米)\s*的?\s*腰围'
        r'|(\d{2,3})腰围',
        re.IGNORECASE,
    ),
    "hips": re.compile(
        r'(\d{2,3})\s*(?:cm|厘米)\s*的?\s*(?:臀围|下围)'
        r'|(\d{2,3})(?:臀围|下围)',
        re.IGNORECASE,
    ),
}



def _extract_measurements_from_history(messages: list) -> dict[str, float]:
    """Scan the conversation history for measurement values.

    Only looks at human (user) messages.  Returns the *last* value seen for
    each field — later messages override earlier ones (user corrections).

    Two-pass extraction per message:
      Pass 1 — keyword-first patterns (high precision, wins if matched).
      Pass 2 — number-first patterns (only for fields not yet found in this msg).
    This prevents "165cm胸围88cm" from making bust=165 via the num-first pattern
    when the keyword-first pattern would correctly extract bust=88.
    """
    collected: dict[str, float] = {}

    for msg in messages:
        if getattr(msg, "type", None) != "human":
            continue
        text: str = msg.content or ""

        # Pass 1: keyword-first (most reliable)
        for field, pattern in _KW_FIRST_PATTERNS.items():
            m = pattern.search(text)
            if m:
                value_str = next((g for g in m.groups() if g is not None), None)
                if value_str:
                    try:
                        collected[field] = float(value_str)
                    except ValueError:  # pragma: no cover
                        pass

        # Pass 2: number-first (only for fields not matched above in this msg)
        for field, pattern in _NUM_FIRST_PATTERNS.items():
            if field in collected:
                continue  # already captured by keyword-first
            m = pattern.search(text)
            if m:
                value_str = next((g for g in m.groups() if g is not None), None)
                if value_str:
                    try:
                        collected[field] = float(value_str)
                    except ValueError:  # pragma: no cover
                        pass

    # Pass 3: positional fallback — "165 88 68 92" (4 bare numbers in one message)
    if len(collected) < 4:
        for msg in messages[-3:]:
            if getattr(msg, "type", None) != "human":
                continue
            text = msg.content or ""
            nums = _NUMBER_RE.findall(text)
            if len(nums) == 4:
                candidates = [float(n) for n in nums]
                if (140 <= candidates[0] <= 200 and
                        70 <= candidates[1] <= 130 and
                        50 <= candidates[2] <= 110 and
                        70 <= candidates[3] <= 140):
                    for i, field in enumerate(_FIELD_ORDER):
                        if field not in collected:
                            collected[field] = candidates[i]

    return collected


# ── Keyword hints used to detect which field the last AI message asked for ───
_FIELD_ASK_KEYWORDS: dict[str, list[str]] = {
    "height": ["身高", "高度", "多高"],
    "bust":   ["胸围", "上围", "胸部"],
    "waist":  ["腰围", "腰部", "腰"],
    "hips":   ["臀围", "下围", "臀部"],
}


def _try_contextual_bare_number(
    messages: list,
    already_collected: dict[str, float],
) -> dict[str, float]:
    """When the AI asked for a specific field and the user replied with just a
    bare number, assign that number to the field the AI was asking about.

    Strategy:
    1. Find the last AI message and detect which measurement field it was asking for
       (by checking for field-specific keywords).
    2. Find the last human message and extract a single bare 2-3 digit number.
    3. If that number fits the valid range of the target field and the field is
       not yet collected, add it to the result.

    This covers the common case: AI asks "请告诉我您的身高", user replies "165".
    """
    result = dict(already_collected)

    # Find the last AI message
    last_ai_text: str = ""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai":
            last_ai_text = msg.content or ""
            break

    if not last_ai_text:
        return result

    # Determine which field the AI was asking about
    target_field: str | None = None
    for field, keywords in _FIELD_ASK_KEYWORDS.items():
        if any(kw in last_ai_text for kw in keywords):
            target_field = field
            break

    if target_field is None or target_field in result:
        return result  # Field already collected or unclear which was asked

    # Find the last human message
    last_human_text: str = ""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "human":
            last_human_text = msg.content or ""
            break

    if not last_human_text:
        return result

    # Extract bare 2-3 digit number from the human message (ignore multi-word replies)
    bare_nums = re.findall(r'\b(\d{2,3})\b', last_human_text)
    if len(bare_nums) != 1:
        return result  # Ambiguous or no bare number

    try:
        value = float(bare_nums[0])
    except ValueError:  # pragma: no cover
        return result

    lo, hi = _VALID_RANGES[target_field]
    if lo <= value <= hi:
        result[target_field] = value

    return result
