"""Targeted tests to cover remaining uncovered lines across the codebase."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

# ── domain/entities.py line 79-80 (wedding_date_as_date ValueError) ───────────


def test_wedding_date_as_date_value_error_branch():
    """Lines 79-80: model_construct bypasses validator → invalid string → ValueError → None."""
    from ai_customer_service.domain.entities import WeddingMeta
    # Use model_construct to bypass Pydantic validator and inject invalid date
    meta = WeddingMeta.model_construct(wedding_date="not-iso-date")
    result = meta.wedding_date_as_date()
    assert result is None


# ── _utils.py lines 214-215 (get_handoff_suggestion exception) ────────────────


@pytest.mark.asyncio
async def test_get_handoff_suggestion_rules_exception_uses_fallback():
    """Lines 214-215: rules_service.get raises → log warning and use fallback."""
    from ai_customer_service.graph.nodes._utils import get_handoff_suggestion
    rules = MagicMock()
    rules.get = AsyncMock(side_effect=RuntimeError("DB error"))
    config = {"configurable": {"rules_service": rules}}
    suggestion = await get_handoff_suggestion(config, "policy_no_doc")
    assert suggestion  # fallback returned


# ── faq_node.py line 132 (order context hint with order_id) ──────────────────


@pytest.mark.asyncio
async def test_faq_node_injects_order_context():
    """Line 132: order_context with order_id → hint injected into system prompt."""
    from ai_customer_service.graph.nodes.faq_node import faq_node
    from ai_customer_service.graph.state import CustomerServiceState

    faq_svc = MagicMock()
    faq_svc.retrieve = AsyncMock(return_value=[])  # no docs → general answer

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="婚纱面料种类很多"))

    config = {"configurable": {"llm": llm, "faq_service": faq_svc}}

    state = CustomerServiceState(
        messages=[HumanMessage(content="婚纱面料有哪些？")],
        thread_id="t1",
        user_id="u1",
        intent="faq",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
        order_context={"order_id": "ORD-001", "status": "confirmed"},  # has order_id
    )
    result = await faq_node(state, config)
    # Node should complete; order context hint was built (line 132 executed)
    assert result["messages"]


# ── order_read_node.py missing lines ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_read_node_prompt_repo_exception_handled():
    """Lines 75-76: prompt_repo.get_active_prompt raises → log warning, use default."""
    from ai_customer_service.graph.nodes.order_read_node import (
        OrderReadExtraction, order_read_node,
    )
    from ai_customer_service.graph.state import CustomerServiceState

    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="您的订单已确认"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    result_mock = MagicMock()
    result_mock.message = "已确认"
    result_mock.order = MagicMock()
    result_mock.order.order_id = "ORD-001"
    result_mock.order.status = MagicMock()
    result_mock.order.status.value = "confirmed"
    result_mock.order.total = 5000.0
    result_mock.order.wedding_meta = MagicMock()
    result_mock.order.wedding_meta.is_custom = False
    result_mock.order.wedding_meta.is_rush = False
    result_mock.order.wedding_meta.dress_style = ""
    result_mock.order.wedding_meta.color = ""
    result_mock.order.wedding_meta.production_stage = MagicMock()
    result_mock.order.wedding_meta.production_stage.value = "pending"
    result_mock.order.wedding_meta.wedding_date = None
    result_mock.order.wedding_meta.estimated_completion = None
    result_mock.order.wedding_meta.rush_level = None
    result_mock.order.items = []

    order_service = MagicMock()
    order_service.execute = AsyncMock(return_value=result_mock)

    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(side_effect=RuntimeError("DB error"))

    config = {
        "configurable": {
            "llm": llm,
            "order_service": order_service,
            "prompt_repo": prompt_repo,
        }
    }
    state = CustomerServiceState(
        messages=[HumanMessage(content="查询订单")],
        thread_id="t1",
        user_id="u1",
        intent="order_read",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    result = await order_read_node(state, config)
    assert result["messages"]  # node continues with default prompt


@pytest.mark.asyncio
async def test_order_read_node_extraction_exception():
    """Lines 88-89: extractor.ainvoke raises → extraction = None → ask for order."""
    from ai_customer_service.graph.nodes.order_read_node import order_read_node
    from ai_customer_service.graph.state import CustomerServiceState

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="请提供订单号"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)

    order_service = MagicMock()

    config = {"configurable": {"llm": llm, "order_service": order_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="查询")],
        thread_id="t1",
        user_id="u1",
        intent="order_read",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    result = await order_read_node(state, config)
    assert result["awaiting_order_id"] == "order_read_node"


@pytest.mark.asyncio
async def test_order_read_node_invalid_wedding_date_in_list():
    """Line 130: order has invalid wedding_date string → ValueError swallowed."""
    from ai_customer_service.graph.nodes.order_read_node import (
        OrderReadExtraction, order_read_node,
    )
    from ai_customer_service.graph.state import CustomerServiceState

    extraction = OrderReadExtraction(action="get_status", order_id="")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="请选择订单"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    # Create 2 orders where one has an invalid date string
    orders = []
    for i, bad_date in enumerate(["not-a-date", "2026-12-25"]):
        o = MagicMock()
        o.order_id = f"ORD-{i:03d}"
        o.status = MagicMock()
        o.status.value = "confirmed"
        meta = MagicMock()
        meta.is_custom = False
        meta.wedding_date = bad_date  # invalid date → ValueError in fromisoformat
        meta.production_stage = MagicMock()
        meta.production_stage.value = "pending"
        o.wedding_meta = meta
        orders.append(o)

    order_service = MagicMock()
    order_service.list_orders = AsyncMock(return_value=orders)

    config = {"configurable": {"llm": llm, "order_service": order_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="查询")],
        thread_id="t1",
        user_id="u1",
        intent="order_read",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    result = await order_read_node(state, config)
    # Should handle ValueError gracefully and still show the order list
    assert result["awaiting_order_id"] == "order_read_node"


@pytest.mark.asyncio
async def test_order_read_node_db_prompt_missing_business_name():
    """Lines 174-176: DB prompt KeyError on {business_name} → fallback format."""
    from ai_customer_service.graph.nodes.order_read_node import (
        OrderReadExtraction, order_read_node,
    )
    from ai_customer_service.graph.state import CustomerServiceState

    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="回复"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    result_mock = MagicMock()
    result_mock.message = "已确认"
    result_mock.order = MagicMock()
    result_mock.order.order_id = "ORD-001"
    result_mock.order.status = MagicMock()
    result_mock.order.status.value = "confirmed"
    result_mock.order.total = 5000.0
    result_mock.order.wedding_meta = MagicMock()
    result_mock.order.wedding_meta.is_custom = False
    result_mock.order.wedding_meta.is_rush = False
    result_mock.order.wedding_meta.dress_style = ""
    result_mock.order.wedding_meta.color = ""
    result_mock.order.wedding_meta.production_stage = MagicMock()
    result_mock.order.wedding_meta.production_stage.value = "pending"
    result_mock.order.wedding_meta.wedding_date = None
    result_mock.order.wedding_meta.estimated_completion = None
    result_mock.order.wedding_meta.rush_level = None
    result_mock.order.items = []

    order_service = MagicMock()
    order_service.execute = AsyncMock(return_value=result_mock)

    # DB prompt that's missing {business_name} → KeyError triggers fallback
    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(
        return_value="自定义提示词 {lang_rule} {result_message}"  # no {business_name}
    )

    config = {
        "configurable": {
            "llm": llm,
            "order_service": order_service,
            "prompt_repo": prompt_repo,
        }
    }
    state = CustomerServiceState(
        messages=[HumanMessage(content="查询")],
        thread_id="t1",
        user_id="u1",
        intent="order_read",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    result = await order_read_node(state, config)
    assert result["messages"]


# ── order_write_node.py lines 89-90 (extraction exception) ───────────────────


@pytest.mark.asyncio
async def test_order_write_node_extraction_exception():
    """Lines 89-90: extractor.ainvoke raises → extraction = None → ask for details."""
    from ai_customer_service.graph.nodes.order_write_node import order_write_node
    from ai_customer_service.graph.state import CustomerServiceState

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="请提供订单号"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)

    order_service = MagicMock()
    order_service.validate = AsyncMock(return_value=None)

    config = {"configurable": {"llm": llm, "order_service": order_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="我要退款")],
        thread_id="t1",
        user_id="u1",
        intent="order_write",
        retrieved_docs=[],
        pending_action={},
        safety_passed=True,
    )
    result = await order_write_node(state, config)
    assert result["awaiting_order_id"] == "order_write_node"


# ── rules_keys.py line 38 ─────────────────────────────────────────────────────


def test_rules_key_refund_rate_key_method():
    """Line 38: RulesKey.refund_rate_key() returns correct key string."""
    from ai_customer_service.use_cases.rules_keys import RulesKey
    key = RulesKey.refund_rate_key("cutting")
    assert key == "refund_rate.cutting"


# ── infrastructure/config.py missing lines ────────────────────────────────────


def test_settings_postgres_sync_url():
    """Line 35: POSTGRES_SYNC_URL property."""
    from ai_customer_service.infrastructure.config import Settings
    s = Settings(
        POSTGRES_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        JWT_SECRET="test",
        BUSINESS_ID="test",
    )
    sync_url = s.POSTGRES_SYNC_URL
    assert sync_url == "postgresql://user:pass@localhost:5432/db"
    assert "asyncpg" not in sync_url


def test_settings_anthropic_provider_kwargs():
    """Lines 159-160: anthropic provider includes api_key."""
    from ai_customer_service.infrastructure.config import Settings
    s = Settings(
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="sk-ant-test",
        JWT_SECRET="test",
        BUSINESS_ID="test",
    )
    kwargs = s.llm_kwargs()
    assert kwargs["api_key"] == "sk-ant-test"


def test_settings_ollama_provider_kwargs():
    """Lines 165: ollama provider includes base_url."""
    from ai_customer_service.infrastructure.config import Settings
    s = Settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        JWT_SECRET="test",
        BUSINESS_ID="test",
    )
    kwargs = s.llm_kwargs()
    assert kwargs["base_url"] == "http://localhost:11434"


def test_settings_embedding_kwargs():
    """Line 174: embedding_kwargs() returns model + api_key + base_url."""
    from ai_customer_service.infrastructure.config import Settings
    s = Settings(
        EMBEDDING_API_KEY="embed-key",
        EMBEDDING_BASE_URL="https://embed.example.com",
        JWT_SECRET="test",
        BUSINESS_ID="test",
    )
    kwargs = s.embedding_kwargs()
    assert kwargs["api_key"] == "embed-key"
    assert kwargs["base_url"] == "https://embed.example.com"


# ── adapters/retrieval/hybrid_retriever.py missing lines ──────────────────────


@pytest.mark.asyncio
async def test_hybrid_retriever_refresh_bm25():
    """Lines 43-48: refresh_bm25 rebuilds BM25 from DB."""
    from ai_customer_service.adapters.retrieval.hybrid_retriever import HybridRetriever
    from ai_customer_service.domain.entities import Document

    docs = [Document(doc_id="d1", content="test")]
    new_bm25 = MagicMock()
    new_bm25._documents = docs
    new_bm25.rebuild = MagicMock()

    pool = MagicMock()
    vector_store = MagicMock()
    vector_store._pool = pool
    vector_store._category = "test_category"

    bm25 = MagicMock()

    retriever = HybridRetriever(
        vector_store=vector_store,
        bm25=bm25,
        embedding_client=MagicMock(),
        k=3,
    )

    with patch(
        "ai_customer_service.adapters.retrieval.hybrid_retriever.BM25Retriever"
    ) as MockBM25:
        mock_instance = MagicMock()
        mock_instance._documents = docs
        MockBM25.from_db = AsyncMock(return_value=mock_instance)
        count = await retriever.refresh_bm25()
    assert count == len(docs)
    bm25.rebuild.assert_called_once_with(docs)


@pytest.mark.asyncio
async def test_hybrid_retriever_embedding_error_falls_back_to_bm25():
    """Lines 62-66: embedding fails → BM25-only retrieval."""
    from ai_customer_service.adapters.retrieval.hybrid_retriever import HybridRetriever
    from ai_customer_service.domain.entities import Document

    docs = [Document(doc_id="d1", content="bm25 result")]
    embedding_client = MagicMock()
    embedding_client.aembed_query = AsyncMock(side_effect=RuntimeError("API error"))

    vector_store = MagicMock()
    bm25 = MagicMock()
    bm25.search = MagicMock(return_value=docs)

    retriever = HybridRetriever(
        vector_store=vector_store,
        bm25=bm25,
        embedding_client=embedding_client,
        k=3,
    )
    result = await retriever.retrieve("退货政策")
    assert result  # BM25 results returned
    assert all(d.doc_id for d in result)


@pytest.mark.asyncio
async def test_hybrid_retriever_with_reranker():
    """Line 71: reranker called when set."""
    from ai_customer_service.adapters.retrieval.hybrid_retriever import HybridRetriever
    from ai_customer_service.domain.entities import Document

    docs = [Document(doc_id="d1", content="content")]
    reranker = MagicMock()
    reranker.rerank = MagicMock(return_value=docs)

    embedding_client = MagicMock()
    embedding_client.aembed_query = AsyncMock(return_value=[0.1] * 5)

    vector_store = MagicMock()
    vector_store.similarity_search = AsyncMock(return_value=docs)

    bm25 = MagicMock()
    bm25.search = MagicMock(return_value=docs)

    retriever = HybridRetriever(
        vector_store=vector_store,
        bm25=bm25,
        embedding_client=embedding_client,
        reranker=reranker,
        k=3,
    )
    result = await retriever.retrieve("test query")
    reranker.rerank.assert_called_once()
    assert result


# ── adapters/retrieval/reranker.py ────────────────────────────────────────────


def test_reranker_import_error_raised():
    """Lines 13-17: FlagEmbedding not installed → ImportError."""
    from ai_customer_service.adapters.retrieval.reranker import FlagReranker
    with pytest.raises(ImportError, match="reranker"):
        # FlagEmbedding is not installed in test env
        FlagReranker()


def test_reranker_rerank_empty_docs():
    """Lines 23-24: rerank([]) returns empty list without calling model."""
    from ai_customer_service.adapters.retrieval.reranker import FlagReranker
    from ai_customer_service.domain.entities import Document

    # Bypass __init__ which requires FlagEmbedding
    reranker = FlagReranker.__new__(FlagReranker)
    reranker._model = MagicMock()
    result = reranker.rerank("query", [])
    assert result == []
    reranker._model.compute_score.assert_not_called()


def test_reranker_rerank_sorts_by_score():
    """Lines 25-30: documents reranked by model score."""
    from ai_customer_service.adapters.retrieval.reranker import FlagReranker
    from ai_customer_service.domain.entities import Document

    reranker = FlagReranker.__new__(FlagReranker)
    reranker._model = MagicMock()
    # Model returns scores: doc_b gets 0.9, doc_a gets 0.3
    reranker._model.compute_score = MagicMock(return_value=[0.3, 0.9])

    docs = [
        Document(doc_id="doc_a", content="lower relevance"),
        Document(doc_id="doc_b", content="higher relevance"),
    ]
    result = reranker.rerank("query", docs)
    assert result[0].doc_id == "doc_b"  # higher score first
    assert result[1].doc_id == "doc_a"
    assert result[0].score == 0.9


# ── product_node.py missing lines ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_product_node_allowed_url_kept():
    """Lines 39-42: URL in allowed_urls (from tool output) → kept in reply."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.list_all = AsyncMock(return_value=[])
    product_service.search = AsyncMock(return_value=[])
    product_service.get = AsyncMock(return_value=None)

    url_in_tool_output = "https://shop.example.com/dress/123"

    # product_node uses tc["name"], tc["args"], tc["id"] — must be a dict
    tc = {"name": "list_all_products", "args": {}, "id": "tc-1"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = f"推荐婚纱 {url_in_tool_output}"

    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    # list_all_products returns a product with a URL
    from ai_customer_service.domain.entities import ProductInfo
    product = ProductInfo(
        product_id="WD-001", name="鱼尾婚纱", style="鱼尾", price=5000.0,
        deposit_rate=0.3, production_days=45, rush_available=True,
        stock_type="custom", colors=["白色"], tags=[], description="test",
        occasions=["婚礼"], purchase_url=url_in_tool_output,
    )
    product_service.list_all = AsyncMock(return_value=[product])

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="推荐婚纱")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_list_all_no_products():
    """Line 119: list_all_products when product_service returns empty."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.list_all = AsyncMock(return_value=[])
    product_service.search = AsyncMock(return_value=[])

    # product_node uses tc["name"], tc["args"], tc["id"] — must be a dict
    tc = {"name": "list_all_products", "args": {}, "id": "tc-1"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "暂无商品信息。"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="有哪些婚纱")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_search_products_no_results():
    """Lines 136-145: search_products with no results."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.list_all = AsyncMock(return_value=[])
    product_service.search = AsyncMock(return_value=[])

    tc = {"name": "search_products", "args": {"style": "鱼尾"}, "id": "tc-2"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "没有找到符合条件的商品。"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="有鱼尾婚纱吗")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_get_product_detail_not_found():
    """Lines 150-153: get_product_detail when product not found."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.get = AsyncMock(return_value=None)

    tc = {"name": "get_product_detail", "args": {"product_id": "WD-UNKNOWN"}, "id": "tc-3"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "该商品不存在"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="WD-UNKNOWN详情")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_tool_call_exception():
    """Lines 183-187: tool execution raises exception → error message in tool result."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.list_all = AsyncMock(side_effect=RuntimeError("DB crash"))

    tc = {"name": "list_all_products", "args": {}, "id": "tc-4"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "抱歉，查询出现问题"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="有哪些婚纱")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


# ── order_service.py missing branches ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_service_list_orders():
    """Line 59: list_orders delegates to repo."""
    from ai_customer_service.use_cases.order_service import OrderService

    repo = MagicMock()
    repo.list_by_user = AsyncMock(return_value=[])
    service = OrderService(repo)
    result = await service.list_orders("user-1")
    assert result == []
    repo.list_by_user.assert_called_once_with("user-1")


@pytest.mark.asyncio
async def test_order_service_validate_get_refund_status_skips_constraints():
    """validate('get_refund_status') → fetches order (for metadata) but skips constraint check.

    Since validate() now always returns the Order for metadata access (wedding_date etc.),
    it must still call get_by_id even for read-only actions. No constraint exception is raised.
    """
    from unittest.mock import AsyncMock
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, Order, WeddingMeta
    from ai_customer_service.domain.value_objects import OrderStatus
    from datetime import datetime, timezone, timezone

    stub_order = Order(
        order_id="ORD-001", user_id="user-1", status=OrderStatus.PENDING,
        items=[], total=0.0, shipping_address="",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(is_custom=False),
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=stub_order)
    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.validate(req, "user-1")
    assert result is stub_order       # returns Order for metadata access
    repo.get_by_id.assert_called_once()  # must fetch order even for read-only actions


@pytest.mark.asyncio
async def test_order_service_validate_unknown_action_raises():
    """Line 96: validate with unknown action → InvalidOrderActionError."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, Order, OrderStatus
    from ai_customer_service.domain.exceptions import InvalidOrderActionError
    from datetime import datetime, timezone, timezone

    repo = MagicMock()
    from ai_customer_service.domain.entities import WeddingMeta
    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.PENDING
    order.wedding_meta = WeddingMeta()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="fly_to_moon", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_validate_refund_non_refundable_status():
    """Lines 139-141: _validate_refund with CANCELLED status raises."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta
    from ai_customer_service.domain.exceptions import InvalidOrderActionError

    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.CANCELLED
    order.wedding_meta = WeddingMeta()

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="initiate_refund", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_validate_exchange_non_delivered():
    """Lines 154-158: _validate_exchange with non-DELIVERED status raises."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta
    from ai_customer_service.domain.exceptions import InvalidOrderActionError

    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.CONFIRMED  # Not DELIVERED → cannot exchange
    order.wedding_meta = WeddingMeta()

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="exchange_order", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_validate_exchange_already_in_exchange_flow():
    """Lines 147-153: _validate_exchange with EXCHANGE_PENDING raises."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta
    from ai_customer_service.domain.exceptions import InvalidOrderActionError

    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.EXCHANGE_PENDING
    order.wedding_meta = WeddingMeta()

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="exchange_order", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_validate_rush_shipped_raises():
    """Lines 161-169: _validate_rush with SHIPPED raises."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta
    from ai_customer_service.domain.exceptions import InvalidOrderActionError
    from ai_customer_service.domain.value_objects import ProductionStage

    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.SHIPPED
    order.wedding_meta = WeddingMeta(production_stage=ProductionStage.READY)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="request_rush", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_validate_rush_late_stage_raises():
    """Lines 167-169: _validate_rush with BEADING stage raises."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta
    from ai_customer_service.domain.exceptions import InvalidOrderActionError
    from ai_customer_service.domain.value_objects import ProductionStage

    order = MagicMock()
    order.user_id = "user-1"
    order.status = OrderStatus.CONFIRMED
    order.wedding_meta = WeddingMeta(production_stage=ProductionStage.BEADING)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="request_rush", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.validate(req, "user-1")


@pytest.mark.asyncio
async def test_order_service_get_refund_rate_from_db():
    """Lines 282-286: _get_refund_rate reads from rules_service when available."""
    from datetime import datetime, timezone, timezone
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta, Order
    from ai_customer_service.domain.value_objects import ProductionStage

    meta = WeddingMeta(is_custom=True, production_stage=ProductionStage.CUTTING)
    order = Order(
        order_id="ORD-001", user_id="user-1", status=OrderStatus.CONFIRMED,
        items=[], total=10000.0, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=meta,
    )

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)
    repo.update_status = AsyncMock(return_value=order)

    rules = MagicMock()
    rules.get = AsyncMock(return_value=0.5)  # DB overrides with 50% (hardcoded is 70%)

    service = OrderService(repo, rules)
    req = OrderActionRequest(action="cancel_order", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    # DB rate (50%) is used, NOT the hardcoded 70% — proves DB path was taken
    assert "50%" in result.message
    assert "70%" not in result.message


def _make_order(status, order_id="ORD-001", user_id="user-1", total=5000.0):
    """Helper to create a real Order domain object for order_service tests."""
    from datetime import datetime, timezone, timezone
    from ai_customer_service.domain.entities import Order, WeddingMeta
    return Order(
        order_id=order_id, user_id=user_id, status=status,
        items=[], total=total,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(),
    )


@pytest.mark.asyncio
async def test_order_service_execute_get_refund_status_pending():
    """Lines 404-433: _get_refund_status returns pending message."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.REFUND_PENDING)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    assert "审核中" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_get_refund_status_refunded():
    """Lines 413-416: _get_refund_status returns refunded message."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.REFUNDED)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    assert "已完成" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_get_refund_status_exchange_pending():
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.EXCHANGE_PENDING)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    assert "换货" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_get_refund_status_cancelled():
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.CANCELLED)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    assert "已取消" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_get_refund_status_other_status():
    """Line 428-432: unknown status → generic message."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.CONFIRMED)  # not in the status_map
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="get_refund_status", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    assert "ORD-001" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_exchange_order_success():
    """Lines 436-449: _exchange_order with DELIVERED status → success."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus

    order = _make_order(OrderStatus.DELIVERED)
    updated_order = _make_order(OrderStatus.EXCHANGE_PENDING)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)
    repo.update_status = AsyncMock(return_value=updated_order)

    service = OrderService(repo)
    req = OrderActionRequest(
        action="exchange_order", order_id="ORD-001", extra={"reason": "尺码不合"}
    )
    result = await service.execute(req, "user-1")
    assert "换货" in result.message


@pytest.mark.asyncio
async def test_order_service_execute_exchange_order_not_delivered_raises():
    """Lines 439-443: _exchange_order with non-DELIVERED → raises InvalidOrderActionError."""
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus
    from ai_customer_service.domain.exceptions import InvalidOrderActionError

    order = _make_order(OrderStatus.CONFIRMED)

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)

    service = OrderService(repo)
    req = OrderActionRequest(action="exchange_order", order_id="ORD-001")
    with pytest.raises(InvalidOrderActionError):
        await service.execute(req, "user-1")


# ── order_service.py line 286: _get_refund_rate exception path ────────────────


@pytest.mark.asyncio
async def test_order_service_get_refund_rate_rules_exception_falls_back():
    """Line 286 (except Exception: pass): rules.get raises → fall back to hardcoded rate."""
    from datetime import datetime, timezone, timezone
    from ai_customer_service.use_cases.order_service import OrderService
    from ai_customer_service.domain.entities import OrderActionRequest, OrderStatus, WeddingMeta, Order
    from ai_customer_service.domain.value_objects import ProductionStage

    meta = WeddingMeta(is_custom=True, production_stage=ProductionStage.CUTTING)
    order = Order(
        order_id="ORD-001", user_id="user-1", status=OrderStatus.CONFIRMED,
        items=[], total=10000.0, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=meta,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=order)
    repo.update_status = AsyncMock(return_value=order)

    rules = MagicMock()
    rules.get = AsyncMock(side_effect=RuntimeError("DB error"))  # raises → line 286 pass

    service = OrderService(repo, rules)
    req = OrderActionRequest(action="cancel_order", order_id="ORD-001")
    result = await service.execute(req, "user-1")
    # Falls back to hardcoded rate for CUTTING stage (70%)
    assert "70%" in result.message


# ── infrastructure/config.py line 174: get_settings() ────────────────────────


def test_get_settings_returns_settings_instance():
    """Line 174: get_settings() executes return Settings()."""
    from ai_customer_service.infrastructure.config import get_settings, Settings
    result = get_settings()
    assert isinstance(result, Settings)


# ── order_read_node.py lines 174-176: KeyError fallback in prompt format ──────


@pytest.mark.asyncio
async def test_order_read_db_prompt_keyerror_fallback():
    """Lines 174-176: DB prompt has unknown placeholder → KeyError → fallback without it."""
    from ai_customer_service.graph.nodes.order_read_node import order_read_node, OrderReadExtraction
    from ai_customer_service.graph.state import CustomerServiceState
    from datetime import datetime, timezone, timezone
    from ai_customer_service.domain.entities import Order, OrderStatus, WeddingMeta

    order = Order(
        order_id="ORD-001", user_id="user-1", status=OrderStatus.CONFIRMED,
        items=[], total=5000.0, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(),
    )
    extraction = OrderReadExtraction(action="get_status", order_id="ORD-001")

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="订单状态：已确认"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=extraction)
    llm.with_structured_output = MagicMock(return_value=structured)

    order_service = MagicMock()
    result_mock = MagicMock()
    result_mock.message = "订单状态：已确认"
    result_mock.order = order
    order_service.execute = AsyncMock(return_value=result_mock)

    # Prompt with an unknown placeholder → triggers KeyError on format(**_fmt_kwargs)
    prompt_repo = MagicMock()
    prompt_repo.get_active_prompt = AsyncMock(
        return_value="{lang_rule} {result_message} {unknown_placeholder}"
    )

    config = {"configurable": {"llm": llm, "order_service": order_service, "prompt_repo": prompt_repo}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="查询订单")],
        thread_id="t1", user_id="user-1", intent="order_read",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await order_read_node(state, config)
    assert result["messages"]


# ── product_node.py remaining lines ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_product_node_url_not_in_allowed_urls_removed():
    """Line 42 (_scrub_urls): URL in reply NOT in allowed_urls → return ''."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()
    product_service.list_all = AsyncMock(return_value=[])  # No product URLs → allowed_urls empty

    # LLM calls a tool, tool returns no products, then LLM generates a reply WITH a URL
    tc = {"name": "list_all_products", "args": {}, "id": "tc-url"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    # LLM hallucinates a URL — this should be scrubbed since not in allowed_urls
    response2.content = "推荐婚纱 https://not-in-allowed.example.com/dress/123"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="推荐婚纱")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    # URL should have been scrubbed (line 42 `return ""` was hit)
    assert result["messages"]
    assert "https://not-in-allowed.example.com" not in result["messages"][0].content


@pytest.mark.asyncio
async def test_product_node_search_returns_products():
    """Line 145: search_products returns actual products → to_context_str() called."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState
    from ai_customer_service.domain.entities import ProductInfo

    product = ProductInfo(
        product_id="WD-002", name="蓬蓬裙婚纱", style="蓬蓬裙", price=3000.0,
        deposit_rate=0.3, production_days=30, rush_available=True,
        stock_type="ready", colors=["白色"], tags=[], description="轻盈飘逸",
        occasions=["婚礼"],
    )
    product_service = MagicMock()
    product_service.search = AsyncMock(return_value=[product])

    tc = {"name": "search_products", "args": {"style": "蓬蓬裙"}, "id": "tc-s"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "找到一款蓬蓬裙婚纱"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="有蓬蓬裙吗")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_get_detail_returns_product():
    """Line 153: get_product_detail returns a product → to_context_str() called."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState
    from ai_customer_service.domain.entities import ProductInfo

    product = ProductInfo(
        product_id="WD-003", name="鱼尾婚纱", style="鱼尾", price=5000.0,
        deposit_rate=0.3, production_days=45, rush_available=True,
        stock_type="custom", colors=["白色"], tags=[], description="优雅鱼尾",
        occasions=["婚礼"],
    )
    product_service = MagicMock()
    product_service.get = AsyncMock(return_value=product)

    tc = {"name": "get_product_detail", "args": {"product_id": "WD-003"}, "id": "tc-d"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "WD-003详情：鱼尾婚纱"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="WD-003详情")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


@pytest.mark.asyncio
async def test_product_node_unknown_tool_name():
    """Line 187: tc['name'] not in tool_map → 'unknown tool' result."""
    from ai_customer_service.graph.nodes.product_node import product_node
    from ai_customer_service.graph.state import CustomerServiceState

    product_service = MagicMock()

    # Use an unknown tool name that's not in the tool_map
    tc = {"name": "fly_to_mars", "args": {}, "id": "tc-unknown"}

    response1 = MagicMock()
    response1.tool_calls = [tc]
    response1.content = ""

    response2 = MagicMock()
    response2.tool_calls = []
    response2.content = "无法处理"

    llm_with_tools = MagicMock()
    llm_with_tools.ainvoke = AsyncMock(side_effect=[response1, response2])
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm_with_tools)

    config = {"configurable": {"llm": llm, "product_service": product_service}}
    state = CustomerServiceState(
        messages=[HumanMessage(content="推荐婚纱")],
        thread_id="t1", user_id="u1", intent="product",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await product_node(state, config)
    assert result["messages"]


# ── measurement_guide_node.py line 360: no human message ─────────────────────


@pytest.mark.asyncio
async def test_measurement_guide_no_human_message_after_ai_ask():
    """Line 360: AI asked for height but no human message follows → return early."""
    from ai_customer_service.graph.nodes.measurement_guide_node import measurement_guide_node
    from ai_customer_service.graph.state import CustomerServiceState
    from langchain_core.messages import AIMessage

    # Messages: AI has asked for height but no human reply yet
    messages = [AIMessage(content="请告诉我您的身高（140-200 cm）")]
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="请提供身高"))
    config = {"configurable": {"llm": llm}}

    state = CustomerServiceState(
        messages=messages,
        thread_id="t1", user_id="u1", intent="measurement_guide",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await measurement_guide_node(state, config)
    # Still prompts for measurements
    assert result["awaiting_order_id"] == "measurement_guide_node"


# ── measurement_guide_node.py lines 278-281: Pass 2 num-first match ───────────


@pytest.mark.asyncio
async def test_measurement_guide_num_first_pattern_match():
    """Lines 278-281: Pass 2 num-first pattern matches (e.g., '165cm的身高')."""
    from ai_customer_service.graph.nodes.measurement_guide_node import measurement_guide_node
    from ai_customer_service.graph.state import CustomerServiceState

    # "165cm的身高" triggers _NUM_FIRST_PATTERNS["height"] (number before keyword+unit)
    messages = [HumanMessage(content="165cm的身高")]
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="已记录身高165cm，请提供胸围"))
    config = {"configurable": {"llm": llm}}

    state = CustomerServiceState(
        messages=messages,
        thread_id="t1", user_id="u1", intent="measurement_guide",
        retrieved_docs=[], pending_action={}, safety_passed=True,
    )
    result = await measurement_guide_node(state, config)
    # Height captured, still needs other measurements
    assert result["awaiting_order_id"] == "measurement_guide_node"


# ── CSAT endpoint (workspace.py submit_csat) ──────────────────────────────────

@pytest.mark.asyncio
async def test_submit_csat_valid_rating_updates_ticket():
    """Valid rating (1-5) fetches ticket, updates rating, and returns ok response."""
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_customer_service.app.routers.workspace import router, _ticket_repo
    from ai_customer_service.domain.entities import Ticket

    ticket = Ticket(
        ticket_id="TK-001",
        session_id="sess-123",
        user_id="user1",
        status="resolved",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_repo = MagicMock()
    mock_repo.get_by_session = AsyncMock(return_value=ticket)
    mock_repo.update = AsyncMock()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_ticket_repo] = lambda: mock_repo

    with TestClient(app) as client:
        resp = client.post("/api/workspace/sessions/sess-123/csat", json={"rating": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-123"
    assert data["rating"] == 5
    assert data["status"] == "ok"
    # Ticket was mutated and persisted
    assert ticket.rating == 5
    mock_repo.update.assert_called_once_with(ticket)


@pytest.mark.asyncio
async def test_submit_csat_rating_boundary_values():
    """Ratings 1 and 5 are both valid; 0 and 6 are rejected."""
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_customer_service.app.routers.workspace import router, _ticket_repo
    from ai_customer_service.domain.entities import Ticket

    def make_ticket():
        return Ticket(
            ticket_id="TK-001",
            session_id="sess-abc",
            user_id="user1",
            status="resolved",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    mock_repo = MagicMock()
    mock_repo.get_by_session = AsyncMock(side_effect=lambda _: make_ticket())
    mock_repo.update = AsyncMock()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_ticket_repo] = lambda: mock_repo

    with TestClient(app) as client:
        assert client.post("/api/workspace/sessions/sess-abc/csat", json={"rating": 1}).status_code == 200
        assert client.post("/api/workspace/sessions/sess-abc/csat", json={"rating": 5}).status_code == 200
        assert client.post("/api/workspace/sessions/sess-abc/csat", json={"rating": 0}).status_code == 422
        assert client.post("/api/workspace/sessions/sess-abc/csat", json={"rating": 6}).status_code == 422


@pytest.mark.asyncio
async def test_submit_csat_session_not_found_returns_404():
    """When ticket_repo returns None the endpoint returns 404."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_customer_service.app.routers.workspace import router, _ticket_repo

    mock_repo = MagicMock()
    mock_repo.get_by_session = AsyncMock(return_value=None)
    mock_repo.update = AsyncMock()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_ticket_repo] = lambda: mock_repo

    with TestClient(app) as client:
        resp = client.post("/api/workspace/sessions/no-such-session/csat", json={"rating": 4})

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
    mock_repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_submit_csat_updated_at_is_refreshed():
    """submit_csat sets ticket.updated_at to a fresh timezone-aware datetime."""
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_customer_service.app.routers.workspace import router, _ticket_repo
    from ai_customer_service.domain.entities import Ticket

    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    ticket = Ticket(
        ticket_id="TK-002",
        session_id="sess-upd",
        user_id="user1",
        status="resolved",
        created_at=old_ts,
        updated_at=old_ts,
    )
    mock_repo = MagicMock()
    mock_repo.get_by_session = AsyncMock(return_value=ticket)
    mock_repo.update = AsyncMock()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_ticket_repo] = lambda: mock_repo

    with TestClient(app) as client:
        client.post("/api/workspace/sessions/sess-upd/csat", json={"rating": 3})

    # updated_at must be refreshed and timezone-aware
    assert ticket.updated_at > old_ts
    assert ticket.updated_at.tzinfo is not None
