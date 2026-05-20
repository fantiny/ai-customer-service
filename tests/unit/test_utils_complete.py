"""Tests for graph/nodes/_utils.py — full branch coverage."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from ai_customer_service.graph.nodes._utils import (
    _detect_language,
    _is_chinese,
    build_handoff_message,
    check_sentiment_escalation,
    extract_order_context,
    get_default_lang,
    get_handoff_suggestion,
    lang_format,
    llm_invoke_with_retry,
    make_lang_rule,
    resolve_node_prompt,
    strip_thinking,
)


# ── _detect_language ──────────────────────────────────────────────────────────


def test_detect_language_empty_returns_none():
    assert _detect_language("") is None


def test_detect_language_very_short_returns_none():
    assert _detect_language("ab") is None


def test_detect_language_hiragana_returns_ja():
    """Line 30: hiragana/katakana > 15% → ja."""
    assert _detect_language("こんにちは、よろしくお願いします") == "ja"


def test_detect_language_katakana_returns_ja():
    """Katakana also triggers Japanese detection."""
    assert _detect_language("アリガトウ ゴザイマス") == "ja"


def test_detect_language_hangul_returns_ko():
    """Line 32: hangul > 15% → ko."""
    assert _detect_language("안녕하세요 감사합니다") == "ko"


def test_detect_language_chinese_returns_zh():
    """Lines 35-36: CJK > 15% → zh-CN."""
    assert _detect_language("这是一条中文消息，测试语言检测功能") == "zh-CN"


def test_detect_language_english_returns_en():
    """Lines 37-38: latin > 40% → en."""
    result = _detect_language("Hello, how can I help you today with your order?")
    assert result == "en"


def test_detect_language_mixed_no_match_returns_none():
    # Very mixed text that doesn't hit any threshold
    result = _detect_language("123 456 789")
    assert result is None


# ── _is_chinese ───────────────────────────────────────────────────────────────


def test_is_chinese_empty_returns_true():
    """Line 123: empty text → True (no translation needed)."""
    assert _is_chinese("") is True


def test_is_chinese_hiragana_returns_false():
    """Line 126: contains hiragana → False."""
    assert _is_chinese("こんにちは") is False


def test_is_chinese_hangul_returns_false():
    """Line 129: contains hangul → False."""
    assert _is_chinese("안녕하세요") is False


def test_is_chinese_cjk_dominant_returns_true():
    """Line 131-132: CJK > 30% → True."""
    assert _is_chinese("这是中文消息") is True


def test_is_chinese_latin_dominant_returns_false():
    assert _is_chinese("Hello there, how are you?") is False


# ── make_lang_rule ────────────────────────────────────────────────────────────


def test_make_lang_rule_contains_lang():
    rule = make_lang_rule("zh-CN", "缘梦婚纱")
    assert "zh-CN" in rule
    assert "缘梦婚纱" in rule


def test_make_lang_rule_uses_default_params():
    rule = make_lang_rule()
    assert "zh-CN" in rule


# ── strip_thinking ────────────────────────────────────────────────────────────


def test_strip_thinking_removes_complete_block():
    text = "Start <think>internal reasoning</think> End"
    assert strip_thinking(text) == "Start  End"


def test_strip_thinking_removes_unclosed_block():
    text = "Before <think>not closed"
    assert strip_thinking(text) == "Before"


def test_strip_thinking_removes_minimax_tool_call():
    text = "Reply <minimax:tool_call>tool data</minimax:tool_call> done"
    assert "minimax" not in strip_thinking(text)


def test_strip_thinking_passthrough_clean_text():
    text = "Hello, this is a normal reply."
    assert strip_thinking(text) == text


# ── get_default_lang ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_default_lang_no_rules_service():
    """Lines 68-70: no rules_service → falls back to configurable or zh-CN."""
    config = {"configurable": {}}
    lang = await get_default_lang(config)
    assert lang == "zh-CN"


@pytest.mark.asyncio
async def test_get_default_lang_from_configurable():
    """configurable.default_language used when no rules_service."""
    config = {"configurable": {"default_language": "en"}}
    lang = await get_default_lang(config)
    assert lang == "en"


@pytest.mark.asyncio
async def test_get_default_lang_with_rules_service():
    """Lines 67-72: rules_service.get_language() returns the configured lang."""
    rules = MagicMock()
    rules.get_language = AsyncMock(return_value="zh-CN")
    config = {"configurable": {"rules_service": rules}}
    lang = await get_default_lang(config)
    assert lang == "zh-CN"


@pytest.mark.asyncio
async def test_get_default_lang_rules_returns_none_falls_back():
    """rules_service.get_language() returning None → falls back to configurable."""
    rules = MagicMock()
    rules.get_language = AsyncMock(return_value=None)
    config = {"configurable": {"rules_service": rules, "default_language": "en"}}
    lang = await get_default_lang(config)
    assert lang == "en"


@pytest.mark.asyncio
async def test_get_default_lang_overrides_with_detected():
    """Line 77: detected language differs from configured → use detected."""
    config = {"configurable": {}}
    # Japanese text should override zh-CN default
    lang = await get_default_lang(config, last_user_text="こんにちは、お願いします")
    assert lang == "ja"


# ── lang_format ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lang_format_chinese_fast_path():
    """Lines 95-99: Chinese user + Chinese default → return zh_text unchanged, no LLM call."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    result = await lang_format(llm, "中文回复", "你好", default_lang="zh-CN")
    assert result == "中文回复"
    llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_lang_format_calls_llm_for_non_chinese():
    """Lines 100-112: non-Chinese user → call LLM for translation."""
    llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Hello, this is a translated reply"
    llm.ainvoke = AsyncMock(return_value=mock_response)
    result = await lang_format(
        llm, "中文回复", "Hello, how are you?", default_lang="zh-CN"
    )
    assert result == "Hello, this is a translated reply"
    llm.ainvoke.assert_called_once()


# ── build_handoff_message ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_handoff_message_from_rules_service():
    """Lines 173-180: rules_service has the key → use it."""
    rules = MagicMock()
    rules.get = AsyncMock(return_value="专属顾问马上为您服务")
    config = {"configurable": {"rules_service": rules}}
    msg = await build_handoff_message(config, "handoff.policy_no_doc")
    assert "专属顾问" in msg


@pytest.mark.asyncio
async def test_build_handoff_message_rules_with_business_name():
    """Lines 173-178: template has {business_name} placeholder."""
    rules = MagicMock()
    rules.get = AsyncMock(return_value="{business_name}的顾问为您服务")
    profile = MagicMock()
    profile.business_name = "测试店铺"
    config = {"configurable": {"rules_service": rules, "business_profile": profile}}
    msg = await build_handoff_message(config, "handoff.x")
    assert "测试店铺" in msg


@pytest.mark.asyncio
async def test_build_handoff_message_rules_empty_fallback_to_profile():
    """Lines 185-189: rules empty → profile handoff_config used."""
    from ai_customer_service.domain.entities import HandoffConfig
    rules = MagicMock()
    rules.get = AsyncMock(return_value="")
    hc = HandoffConfig(
        notify_customer=True,
        notification_template="来自{business_name}的顾问正在接入",
    )
    profile = MagicMock()
    profile.business_name = "缘梦婚纱"
    profile.handoff_config = hc
    config = {"configurable": {"rules_service": rules, "business_profile": profile}}
    msg = await build_handoff_message(config, "handoff.x")
    assert "缘梦婚纱" in msg


@pytest.mark.asyncio
async def test_build_handoff_message_silent_handoff():
    """Lines 188-189: notify_customer=False → silent_handoff_message."""
    from ai_customer_service.domain.entities import HandoffConfig
    rules = MagicMock()
    rules.get = AsyncMock(return_value="")
    hc = HandoffConfig(
        notify_customer=False,
        silent_handoff_message="转接中",
    )
    profile = MagicMock()
    profile.handoff_config = hc
    config = {"configurable": {"rules_service": rules, "business_profile": profile}}
    msg = await build_handoff_message(config, "handoff.x")
    assert msg == "转接中"


@pytest.mark.asyncio
async def test_build_handoff_message_hardcoded_fallback():
    """Line 192: no rules_service, no profile → hardcoded fallback."""
    config = {"configurable": {}}
    msg = await build_handoff_message(config, "handoff.x")
    assert "专属顾问" in msg


@pytest.mark.asyncio
async def test_build_handoff_message_rules_exception_falls_back():
    """rules_service raises → graceful fallback."""
    rules = MagicMock()
    rules.get = AsyncMock(side_effect=RuntimeError("DB down"))
    config = {"configurable": {"rules_service": rules}}
    msg = await build_handoff_message(config, "handoff.x")
    assert msg  # Should still return the hardcoded fallback


# ── get_handoff_suggestion ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_handoff_suggestion_from_rules_service():
    """Lines 210-215: rules_service has key → return it."""
    rules = MagicMock()
    rules.get = AsyncMock(return_value="请优先了解客户的换货需求")
    config = {"configurable": {"rules_service": rules}}
    suggestion = await get_handoff_suggestion(config, "policy_no_doc")
    assert "换货" in suggestion


@pytest.mark.asyncio
async def test_get_handoff_suggestion_rules_empty_fallback():
    """rules_service returns empty → fallback to _FALLBACK_SUGGESTIONS."""
    rules = MagicMock()
    rules.get = AsyncMock(return_value="")
    config = {"configurable": {"rules_service": rules}}
    suggestion = await get_handoff_suggestion(config, "product_unavailable")
    assert suggestion  # hardcoded fallback


@pytest.mark.asyncio
async def test_get_handoff_suggestion_no_rules_service():
    config = {"configurable": {}}
    suggestion = await get_handoff_suggestion(config, "explicit_request")
    assert "客户" in suggestion


@pytest.mark.asyncio
async def test_get_handoff_suggestion_unknown_reason():
    config = {"configurable": {}}
    suggestion = await get_handoff_suggestion(config, "unknown_reason_xyz")
    assert suggestion  # should return generic "请继续为客户提供服务"


# ── llm_invoke_with_retry ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_invoke_with_retry_success_first_attempt():
    llm = MagicMock()
    expected = MagicMock()
    llm.ainvoke = AsyncMock(return_value=expected)
    result = await llm_invoke_with_retry(llm, ["msg"], max_retries=3)
    assert result is expected
    assert llm.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_llm_invoke_with_retry_retries_on_rate_limit():
    """Lines 234-244: transient error causes retry with backoff."""
    llm = MagicMock()
    expected = MagicMock()
    # Fail with 429 twice, succeed on third
    llm.ainvoke = AsyncMock(
        side_effect=[
            RuntimeError("429 rate_limit"),
            RuntimeError("429 rate_limit"),
            expected,
        ]
    )
    with patch("ai_customer_service.graph.nodes._utils._asyncio.sleep", new_callable=AsyncMock):
        result = await llm_invoke_with_retry(llm, ["msg"], max_retries=3, base_delay=0.01)
    assert result is expected
    assert llm.ainvoke.call_count == 3


@pytest.mark.asyncio
async def test_llm_invoke_with_retry_raises_non_transient_immediately():
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=ValueError("invalid request"))
    with pytest.raises(ValueError):
        await llm_invoke_with_retry(llm, ["msg"], max_retries=3, base_delay=0.01)
    assert llm.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_llm_invoke_with_retry_exhausts_retries_and_raises():
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("timeout error"))
    with pytest.raises(RuntimeError):
        with patch("ai_customer_service.graph.nodes._utils._asyncio.sleep", new_callable=AsyncMock):
            await llm_invoke_with_retry(llm, ["msg"], max_retries=2, base_delay=0.01)
    assert llm.ainvoke.call_count == 2


# ── extract_order_context ─────────────────────────────────────────────────────


def test_extract_order_context_returns_empty_for_none():
    """Line 256-257: order is None → {}."""
    result = extract_order_context(None)
    assert result == {}


def test_extract_order_context_builds_dict_from_order():
    """Lines 258-275: builds full context dict from Order object."""
    from ai_customer_service.domain.entities import (
        Order, OrderItem, OrderStatus, WeddingMeta,
    )
    from ai_customer_service.domain.value_objects import ProductionStage
    from datetime import datetime, timezone, timezone

    order = Order(
        order_id="ORD-001",
        user_id="user-1",
        status=OrderStatus.CONFIRMED,
        items=[OrderItem(product_id="WD-P001", name="鱼尾婚纱", quantity=1, unit_price=5000.0)],
        total=5000.0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(
            is_custom=True,
            is_rush=False,
            dress_style="鱼尾",
            color="白色",
            production_stage=ProductionStage.CUTTING,
            wedding_date="2026-12-25",
        ),
    )
    ctx = extract_order_context(order)
    assert ctx["order_id"] == "ORD-001"
    assert ctx["status"] == "confirmed"
    assert ctx["total"] == 5000.0
    assert ctx["is_custom"] is True
    assert ctx["production_stage"] == "cutting"
    assert ctx["wedding_date"] == "2026-12-25"
    assert len(ctx["items"]) == 1
    assert ctx["items"][0]["name"] == "鱼尾婚纱"
    assert ctx["rush_level"] == "none"  # RushLevel.NONE → "none" (default)


# ── check_sentiment_escalation ────────────────────────────────────────────────


def test_check_sentiment_escalation_no_negative():
    """Lines 293-304: no negative keyword → count=0, no escalation."""
    state = {
        "messages": [HumanMessage(content="谢谢你的帮助！")],
        "negative_turns": 0,
    }
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 0
    assert escalate is False


def test_check_sentiment_escalation_increments_on_negative():
    state = {
        "messages": [HumanMessage(content="太差了，我要投诉！")],
        "negative_turns": 2,
    }
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 3
    assert escalate is False  # 3 < 4


def test_check_sentiment_escalation_triggers_at_threshold():
    state = {
        "messages": [HumanMessage(content="强烈不满！")],
        "negative_turns": 3,
    }
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 4
    assert escalate is True  # 4 >= 4


def test_check_sentiment_escalation_urgent_uses_lower_threshold():
    state = {
        "messages": [HumanMessage(content="退款！")],
        "negative_turns": 1,
        "is_urgent": True,
    }
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 2
    assert escalate is True  # 2 >= urgent_threshold(2)


def test_check_sentiment_escalation_resets_on_positive():
    state = {
        "messages": [HumanMessage(content="谢谢")],
        "negative_turns": 5,
    }
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 0  # reset on non-negative message


def test_check_sentiment_escalation_no_messages():
    state = {"messages": [], "negative_turns": 0}
    count, escalate = check_sentiment_escalation(state, threshold=4, urgent_threshold=2)
    assert count == 0
    assert escalate is False


# ── resolve_node_prompt ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_node_prompt_no_repo():
    """No prompt_repo → return default."""
    result = await resolve_node_prompt(None, "faq_node", "default prompt")
    assert result == "default prompt"


@pytest.mark.asyncio
async def test_resolve_node_prompt_repo_returns_none():
    """DB returns None → fallback to default."""
    repo = MagicMock()
    repo.get_active_prompt = AsyncMock(return_value=None)
    result = await resolve_node_prompt(repo, "faq_node", "default prompt")
    assert result == "default prompt"


@pytest.mark.asyncio
async def test_resolve_node_prompt_returns_db_prompt():
    """Lines 331-342: DB prompt exists and has all placeholders."""
    repo = MagicMock()
    repo.get_active_prompt = AsyncMock(return_value="DB prompt with {lang_rule}")
    result = await resolve_node_prompt(repo, "faq_node", "default", ("{lang_rule}",))
    assert result == "DB prompt with {lang_rule}"


@pytest.mark.asyncio
async def test_resolve_node_prompt_appends_missing_placeholder():
    """DB prompt missing required placeholder → appended."""
    repo = MagicMock()
    repo.get_active_prompt = AsyncMock(return_value="DB prompt without placeholder")
    result = await resolve_node_prompt(repo, "faq_node", "default", ("{lang_rule}",))
    assert "{lang_rule}" in result


@pytest.mark.asyncio
async def test_resolve_node_prompt_repo_exception_falls_back():
    """Exception from repo → return default."""
    repo = MagicMock()
    repo.get_active_prompt = AsyncMock(side_effect=RuntimeError("DB error"))
    result = await resolve_node_prompt(repo, "faq_node", "fallback default")
    assert result == "fallback default"
