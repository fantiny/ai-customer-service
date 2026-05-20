"""Unit tests for faq_node — knowledge_type-based reliability.

Scenarios covered:
- policy_docs only → strict mode, LLM answer returned
- knowledge_docs only → flexible mode, LLM answer returned
- both types co-exist → policy_ctx + knowledge appendix, strict mode (fixes the elif bug)
- no docs + policy keyword → seamless handoff (request_human=True, no LLM)
- no docs + general question → LLM uses general knowledge, no handoff
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.domain.entities import Document
from ai_customer_service.graph.nodes.faq_node import faq_node
from ai_customer_service.graph.state import CustomerServiceState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(message: str) -> CustomerServiceState:
    return CustomerServiceState(
        messages=[HumanMessage(content=message)],
        thread_id="t1",
        user_id="u1",
        intent="faq",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )


def _policy_doc(title: str = "退款政策", content: str = "退款30天") -> Document:
    return Document(
        doc_id="p1",
        content=content,
        metadata={"knowledge_type": "business_policy", "title": title},
        score=0.9,
    )


def _knowledge_doc(title: str = "面料保养", content: str = "蕾丝需干洗") -> Document:
    return Document(
        doc_id="k1",
        content=content,
        metadata={"knowledge_type": "industry_knowledge", "title": title},
        score=0.8,
    )


def _config(llm, docs: list) -> dict:
    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=docs)
    return {
        "configurable": {
            "llm": llm,
            "faq_service": faq_service,
            "langfuse_handler": None,
        }
    }


def _mock_llm(reply: str = "好的，为您解答。") -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=reply))
    return llm


# ── Strict-only (policy_docs only) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_policy_only_strict_mode_returns_answer():
    """With policy docs, LLM is called and answer returned (strict mode)."""
    llm = _mock_llm("退款政策：30天内可退款。")
    state = _make_state("退货政策是什么？")
    config = _config(llm, [_policy_doc()])

    result = await faq_node(state, config=config)

    assert result["messages"][0].content == "退款政策：30天内可退款。"
    assert isinstance(result["messages"][0], AIMessage)
    # LLM was called (strict mode still calls LLM, just with tighter instruction)
    llm.ainvoke.assert_awaited_once()
    # No handoff
    assert not result.get("request_human")


@pytest.mark.asyncio
async def test_policy_only_context_contains_doc_title():
    """Policy doc title appears in the system prompt context."""
    captured_prompt: list[str] = []

    async def fake_invoke(messages, **kwargs):
        captured_prompt.append(messages[0].content)  # system message
        return AIMessage(content="answer")

    llm = MagicMock()
    llm.ainvoke = fake_invoke

    state = _make_state("退款政策？")
    config = _config(llm, [_policy_doc(title="退款政策", content="30天退款")])

    await faq_node(state, config=config)

    assert "退款政策" in captured_prompt[0]
    assert "30天退款" in captured_prompt[0]
    assert "仅基于上方资料" in captured_prompt[0]  # strict instruction present


# ── Knowledge-only (industry_knowledge only) ──────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_only_flexible_mode_returns_answer():
    """With only industry_knowledge docs, flexible mode, LLM answer returned."""
    llm = _mock_llm("蕾丝面料建议干洗。")
    state = _make_state("婚纱怎么保养？")
    config = _config(llm, [_knowledge_doc()])

    result = await faq_node(state, config=config)

    assert result["messages"][0].content == "蕾丝面料建议干洗。"
    assert not result.get("request_human")


@pytest.mark.asyncio
async def test_knowledge_only_uses_flexible_instruction():
    """Flexible instruction (not strict) injected when only industry_knowledge docs."""
    captured_prompt: list[str] = []

    async def fake_invoke(messages, **kwargs):
        captured_prompt.append(messages[0].content)
        return AIMessage(content="ok")

    llm = MagicMock()
    llm.ainvoke = fake_invoke

    state = _make_state("婚纱面料有哪些？")
    config = _config(llm, [_knowledge_doc()])

    await faq_node(state, config=config)

    assert "可结合行业通用知识" in captured_prompt[0]   # flexible instruction
    assert "仅基于上方资料" not in captured_prompt[0]   # strict NOT present


# ── Mixed (both types co-exist) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mixed_docs_strict_mode_includes_both():
    """BUG FIX: both policy and knowledge docs → context includes both, strict mode."""
    captured_prompt: list[str] = []

    async def fake_invoke(messages, **kwargs):
        captured_prompt.append(messages[0].content)
        return AIMessage(content="综合回答")

    llm = MagicMock()
    llm.ainvoke = fake_invoke

    policy = _policy_doc(title="退款政策", content="退款条款详情")
    knowledge = _knowledge_doc(title="面料保养", content="蕾丝需干洗")

    state = _make_state("退款政策和婚纱保养？")
    config = _config(llm, [policy, knowledge])

    result = await faq_node(state, config=config)

    # Both doc contents appear in system prompt
    assert "退款条款详情" in captured_prompt[0]
    assert "蕾丝需干洗" in captured_prompt[0]
    # Knowledge doc is labelled as reference
    assert "参考：面料保养" in captured_prompt[0]
    # Strict mode instruction applied (policy takes precedence)
    assert "仅基于上方资料" in captured_prompt[0]
    # No handoff
    assert not result.get("request_human")
    assert result["messages"][0].content == "综合回答"


@pytest.mark.asyncio
async def test_mixed_docs_knowledge_not_silently_dropped():
    """Regression: knowledge_docs must not be silently dropped when policy_docs exist.

    Before the fix, the `elif` caused knowledge_docs to be discarded whenever
    policy_docs were present.  This test fails if the elif is re-introduced.
    """
    context_seen: list[str] = []

    async def fake_invoke(messages, **kwargs):
        context_seen.append(messages[0].content)
        return AIMessage(content="ok")

    llm = MagicMock()
    llm.ainvoke = fake_invoke

    policy = _policy_doc(title="P政策", content="POLICY_CONTENT")
    know = _knowledge_doc(title="K知识", content="KNOWLEDGE_CONTENT")

    state = _make_state("问题")
    config = _config(llm, [policy, know])

    await faq_node(state, config=config)

    system_msg = context_seen[0]
    assert "POLICY_CONTENT" in system_msg, "Policy doc must appear in context"
    assert "KNOWLEDGE_CONTENT" in system_msg, "Knowledge doc must NOT be silently dropped"


# ── No docs + policy keyword → handoff ───────────────────────────────────────

@pytest.mark.asyncio
async def test_no_docs_policy_keyword_triggers_handoff():
    """No retrieval results + policy keyword → request_human=True without LLM call."""
    llm = _mock_llm("should not be called")
    state = _make_state("你们的退货政策是什么？")
    config = _config(llm, [])

    result = await faq_node(state, config=config)

    assert result.get("request_human") is True
    assert result["handoff_context"]["reason"] == "policy_no_doc"
    # LLM should NOT be called — handoff happens before LLM
    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_docs_refund_keyword_triggers_handoff():
    """'退款' is a policy keyword → handoff when no docs found."""
    llm = _mock_llm()
    state = _make_state("退款要多久？")
    config = _config(llm, [])

    result = await faq_node(state, config=config)

    assert result.get("request_human") is True
    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_docs_handoff_context_contains_user_question():
    """handoff_context carries the original user question for the human agent."""
    llm = _mock_llm()
    state = _make_state("换货的条件是什么？")
    config = _config(llm, [])

    result = await faq_node(state, config=config)

    assert result["handoff_context"]["user_question"] == "换货的条件是什么？"


# ── No docs + general question → flexible LLM ────────────────────────────────

@pytest.mark.asyncio
async def test_no_docs_general_question_uses_llm():
    """No docs, non-policy question → LLM answers using general knowledge (no handoff)."""
    llm = _mock_llm("鱼尾裙是一种流行婚纱款式。")
    state = _make_state("鱼尾婚纱适合什么身材？")
    config = _config(llm, [])

    result = await faq_node(state, config=config)

    assert not result.get("request_human")
    # LLM answer returned (content matches mock return value)
    assert result["messages"][0].content == "鱼尾裙是一种流行婚纱款式。"
    # LLM was called
    llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_docs_general_question_no_handoff_context():
    """General knowledge questions do not set handoff_context."""
    llm = _mock_llm("蕾丝是常见婚纱面料。")
    state = _make_state("婚纱面料有哪些种类？")
    config = _config(llm, [])

    result = await faq_node(state, config=config)

    assert not result.get("request_human")
    assert "handoff_context" not in result or not result.get("handoff_context")


# ── retrieved_docs metadata ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieved_docs_populated_for_workspace():
    """retrieved_docs contains metadata for agent workspace display."""
    llm = _mock_llm("answer")
    state = _make_state("退款政策？")
    config = _config(llm, [
        _policy_doc(title="退款政策"),
        _knowledge_doc(title="面料保养"),
    ])

    result = await faq_node(state, config=config)

    docs = result.get("retrieved_docs", [])
    assert len(docs) == 2
    titles = {d["title"] for d in docs}
    assert "退款政策" in titles
    assert "面料保养" in titles


# ── Legacy tests (preserved for backwards compatibility) ──────────────────────

@pytest.mark.asyncio
async def test_faq_node_retrieves_and_generates(mock_llm, mock_retriever):
    """Original test: basic retrieval + LLM call."""
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="7天无理由退货。"))
    state = _make_state("退货政策是什么？")
    faq_service = MagicMock()
    faq_service.retrieve = mock_retriever.retrieve
    config = {
        "configurable": {
            "llm": mock_llm,
            "faq_service": faq_service,
            "langfuse_handler": None,
        }
    }

    result = await faq_node(state, config=config)

    faq_service.retrieve.assert_awaited_once_with("退货政策是什么？")
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert "retrieved_docs" in result


@pytest.mark.asyncio
async def test_faq_node_handles_empty_retrieval(mock_llm):
    """Original test: empty retrieval + non-policy query → LLM still called."""
    faq_service = MagicMock()
    faq_service.retrieve = AsyncMock(return_value=[])
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="暂无相关信息"))

    state = _make_state("这是一个冷门问题")
    config = {
        "configurable": {
            "llm": mock_llm,
            "faq_service": faq_service,
            "langfuse_handler": None,
        }
    }

    result = await faq_node(state, config=config)
    assert isinstance(result["messages"][0], AIMessage)
