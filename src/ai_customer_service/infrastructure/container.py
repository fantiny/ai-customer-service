from __future__ import annotations

from typing import Any

import asyncpg
import redis.asyncio as aioredis

from ..adapters.datasources.factory import DataSourceConfig, DataSourceFactory
from ..adapters.llm.embedding_client import LangChainEmbeddingClient
from ..adapters.llm.factory import LLMFactory
from ..use_cases.interfaces import IEmbeddingClient
from ..adapters.observability.langfuse_handler import build_langfuse_handler
from ..adapters.repositories.product_repository import ProductRepository
from ..adapters.repositories.agent_repository import PGAgentRepository
from ..adapters.repositories.business_profile_repository import BusinessProfileRepository
from ..adapters.repositories.business_rules_repository import BusinessRulesRepository
from ..adapters.repositories.digest_repository import DigestRepository
from ..adapters.repositories.message_repository import MessageRepository
from ..adapters.repositories.prompt_repository import PromptRepository
from ..adapters.repositories.session_repository import PGSessionRepository
from ..adapters.repositories.ticket_repository import PGTicketRepository, StatusEventRepository
from ..adapters.repositories.faq_document_repository import FAQDocumentRepository
from ..adapters.repositories.workflow_repository import WorkflowRepository
from ..adapters.retrieval.bm25_retriever import BM25Retriever
from ..adapters.retrieval.hybrid_retriever import HybridRetriever
from ..adapters.retrieval.pgvector_store import PGVectorStore
from ..graph.builder import build_graph
from ..infrastructure.config import Settings
from ..infrastructure.database import create_db_pool
from ..infrastructure.redis_client import create_redis_pool
from ..use_cases.business_profile_service import BusinessProfileService
from ..use_cases.business_rules_service import BusinessRulesService
from ..use_cases.chat_service import ChatService
from ..use_cases.digest_service import DigestService
from ..use_cases.faq_service import FAQService
from ..use_cases.interfaces import IOrderRepository
from ..use_cases.order_service import OrderService
from ..use_cases.product_service import ProductService


class Container:
    """Manual dependency injection container.

    Initializes all components in dependency order at application startup.
    Provides a graph_config_factory so ChatService remains decoupled from Container.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_pool: asyncpg.Pool | None = None
        self._redis: aioredis.Redis | None = None
        self._chat_service: ChatService | None = None
        self._llm: Any = None
        self._product_retriever: HybridRetriever | None = None
        self._faq_retriever: HybridRetriever | None = None
        self._order_repo: IOrderRepository | None = None
        self._order_service: OrderService | None = None
        self._session_repo: PGSessionRepository | None = None
        self._ticket_repo: PGTicketRepository | None = None
        self._event_repo: StatusEventRepository | None = None
        self._agent_repo: PGAgentRepository | None = None
        self._rules_repo: BusinessRulesRepository | None = None
        self._prompt_repo: PromptRepository | None = None
        self._message_repo: MessageRepository | None = None
        self._digest_repo: DigestRepository | None = None
        self._digest_service: DigestService | None = None
        self._workflow_repo: WorkflowRepository | None = None
        self._faq_doc_repo: FAQDocumentRepository | None = None
        self._admin_graph: Any = None
        self._graph: Any = None
        self._product_repo: ProductRepository | None = None
        self._product_service: ProductService | None = None
        self._faq_service: FAQService | None = None
        self._rules_service: BusinessRulesService | None = None
        self._embedding_client: IEmbeddingClient | None = None
        self._profile_repo: BusinessProfileRepository | None = None
        self._profile_service: BusinessProfileService | None = None
        self._business_profile: Any = None  # BusinessProfile domain entity

    async def initialize(self) -> None:
        settings = self._settings

        # 1. Infrastructure connections
        self._db_pool = await create_db_pool(settings)
        self._redis = await create_redis_pool(settings)

        # 2. Checkpointer
        # Try Redis Stack first; fall back to PostgreSQL if RediSearch unavailable.
        try:
            from langgraph.checkpoint.redis import AsyncRedisSaver
            checkpointer = AsyncRedisSaver(settings.REDIS_URL)
            await checkpointer.asetup()
            self._checkpointer = checkpointer
        except Exception:
            import logging
            logging.getLogger(__name__).info(
                "Redis Stack unavailable; using PostgreSQL checkpointer."
            )
            # Use psycopg3 connection pool directly — avoids context-manager dance
            import psycopg
            from psycopg_pool import AsyncConnectionPool
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            self._pg_pool_checkpointer = AsyncConnectionPool(
                settings.POSTGRES_SYNC_URL,
                min_size=1,
                max_size=5,
                open=False,
                kwargs={"autocommit": True},   # required for CREATE INDEX CONCURRENTLY
            )
            await self._pg_pool_checkpointer.open()
            self._checkpointer = AsyncPostgresSaver(self._pg_pool_checkpointer)
            await self._checkpointer.setup()

        # 3. LLM (shared base instance; callbacks added per-request)
        self._llm = LLMFactory.build(settings)

        # 4. Embedding client (wrapped in IEmbeddingClient adapter for type safety)
        embedding_client = LangChainEmbeddingClient(LLMFactory.build_embedding_client(settings))
        self._embedding_client = embedding_client

        # 5. Optional reranker (shared by both retrievers)
        reranker = None
        if settings.RERANKER_ENABLED:
            from ..adapters.retrieval.reranker import FlagReranker
            reranker = FlagReranker(settings.RERANKER_MODEL)

        # 6. Product catalog retriever (category: product_catalog)
        bm25_product = await BM25Retriever.from_db(
            self._db_pool, category="product_catalog"
        )
        vector_product = PGVectorStore(
            self._db_pool, category="product_catalog"
        )
        self._product_retriever = HybridRetriever(
            vector_store=vector_product,
            bm25=bm25_product,
            embedding_client=embedding_client,
            reranker=reranker,
            k=settings.RETRIEVAL_K,
        )

        # 7. FAQ / policy retriever (category: wedding_dress_faq)
        bm25_faq = await BM25Retriever.from_db(
            self._db_pool, category="wedding_dress_faq"
        )
        vector_faq = PGVectorStore(
            self._db_pool, category="wedding_dress_faq"
        )
        self._faq_retriever = HybridRetriever(
            vector_store=vector_faq,
            bm25=bm25_faq,
            embedding_client=embedding_client,
            reranker=reranker,
            k=settings.RETRIEVAL_K,
            min_vector_score=0.55,
        )

        # 8. Data sources (config-driven: internal DB or external REST API)
        order_cfg = DataSourceConfig.from_settings_prefix(settings, "ORDER")
        self._order_repo = DataSourceFactory.build_order_repo(order_cfg, self._db_pool)

        # Document sync: pull from external source on startup when configured
        product_cfg = DataSourceConfig.from_settings_prefix(settings, "PRODUCT")
        product_syncer = DataSourceFactory.build_document_syncer(
            product_cfg, self._db_pool, category="product_catalog"
        )
        if product_syncer:
            await product_syncer.sync()

        faq_cfg = DataSourceConfig.from_settings_prefix(settings, "FAQ")
        faq_syncer = DataSourceFactory.build_document_syncer(
            faq_cfg, self._db_pool, category="wedding_dress_faq"
        )
        if faq_syncer:
            await faq_syncer.sync()

        # Product repository — structured DB-first catalog (no hallucination)
        self._product_repo = ProductRepository(self._db_pool)

        # Session, ticket, event, agent, rules, prompt, and message repositories
        self._session_repo = PGSessionRepository(self._db_pool)
        self._ticket_repo = PGTicketRepository(self._db_pool)
        self._event_repo = StatusEventRepository(self._db_pool)
        self._agent_repo = PGAgentRepository(self._db_pool)
        self._rules_repo = BusinessRulesRepository(self._db_pool)
        self._prompt_repo = PromptRepository(self._db_pool)
        # MessageRepository is the single write path for conversation history;
        # ConversationRepository has been removed (table deprecated, file deleted).
        self._message_repo = MessageRepository(self._db_pool)
        self._digest_repo = DigestRepository(self._db_pool)
        self._digest_service = DigestService(self._digest_repo)
        self._workflow_repo = WorkflowRepository(self._db_pool)
        self._faq_doc_repo = FAQDocumentRepository(self._db_pool)

        # 9. Use case services
        self._product_service = ProductService(self._product_repo)
        self._faq_service = FAQService(self._faq_retriever)
        self._rules_service = BusinessRulesService(self._rules_repo)
        self._order_service = OrderService(self._order_repo, self._rules_repo)

        # 10. Load business profile (must be before build_graph — profile drives topology)
        self._profile_repo = BusinessProfileRepository(self._db_pool)
        self._profile_service = BusinessProfileService(self._profile_repo)
        business_id = getattr(settings, "BUSINESS_ID", "wedding_dress")
        self._business_profile = await self._profile_service.load(business_id)

        # Rebuild retrievers now that we have the profile's category config.
        # This replaces the hardcoded category strings used above during initial
        # construction (steps 6 and 7) with the values from the loaded profile.
        faq_cat = self._business_profile.faq_category
        prod_cat = self._business_profile.product_catalog_category
        if faq_cat != "wedding_dress_faq":
            bm25_faq = await BM25Retriever.from_db(self._db_pool, category=faq_cat)
            vector_faq = PGVectorStore(self._db_pool, category=faq_cat)
            self._faq_retriever = HybridRetriever(
                vector_store=vector_faq,
                bm25=bm25_faq,
                embedding_client=embedding_client,
                reranker=reranker,
                k=settings.RETRIEVAL_K,
                min_vector_score=0.55,
            )
        if prod_cat != "product_catalog":
            bm25_product = await BM25Retriever.from_db(self._db_pool, category=prod_cat)
            vector_product = PGVectorStore(self._db_pool, category=prod_cat)
            self._product_retriever = HybridRetriever(
                vector_store=vector_product,
                bm25=bm25_product,
                embedding_client=embedding_client,
                reranker=reranker,
                k=settings.RETRIEVAL_K,
            )

        # 11. Compile customer graph with the loaded business profile
        self._graph = build_graph(self._business_profile, self._checkpointer)

        # 11b. Compile admin graph (ReAct agent with config tools)
        from ..graph.admin_graph import build_admin_graph, build_admin_tools
        admin_tools = build_admin_tools(
            rules_repo=self._rules_repo,
            faq_doc_repo=self._faq_doc_repo,
            prompt_repo=self._prompt_repo,
            db_pool=self._db_pool,
            business_profile=self._business_profile,
        )
        self._admin_graph = build_admin_graph(self._llm, admin_tools, self._checkpointer)

        # 12. Chat service — reads history from session_messages via message_repo
        self._chat_service = ChatService(
            graph=self._graph,
            message_repo=self._message_repo,
            settings=settings,
            graph_config_factory=self._make_graph_config,
        )

    def _make_graph_config(
        self, thread_id: str, user_id: str, langfuse_handler: Any
    ) -> dict:
        """Build the RunnableConfig passed to graph.ainvoke() for each request."""
        return {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "llm": self._llm,
                "product_service": self._product_service,
                "faq_service": self._faq_service,
                "rules_service": self._rules_service,
                "order_service": self._order_service,
                "prompt_repo": self._prompt_repo,
                "langfuse_handler": langfuse_handler,
                # 静态默认语言（可被 business_rules.default_language 动态覆盖）
                "default_language": self._settings.DEFAULT_LANGUAGE,
                # Generic business configuration (loaded at startup, immutable per request)
                "business_profile": self._business_profile,
                # Workflow repository for structured service flows (aftersales, returns, etc.)
                "workflow_repo": self._workflow_repo,
            }
        }

    @property
    def db_pool(self) -> asyncpg.Pool:
        assert self._db_pool is not None, "Container not initialized"
        return self._db_pool

    @property
    def product_repo(self) -> ProductRepository:
        assert self._product_repo is not None, "Container not initialized"
        return self._product_repo

    @property
    def llm(self) -> Any:
        assert self._llm is not None, "Container not initialized"
        return self._llm

    @property
    def embedding_client(self) -> IEmbeddingClient:
        assert self._embedding_client is not None, "Container not initialized"
        return self._embedding_client

    @property
    def chat_service(self) -> ChatService:
        assert self._chat_service is not None, "Container not initialized"
        return self._chat_service

    @property
    def session_repo(self) -> PGSessionRepository:
        assert self._session_repo is not None, "Container not initialized"
        return self._session_repo

    @property
    def ticket_repo(self) -> PGTicketRepository:
        assert self._ticket_repo is not None, "Container not initialized"
        return self._ticket_repo

    @property
    def event_repo(self) -> StatusEventRepository:
        assert self._event_repo is not None, "Container not initialized"
        return self._event_repo

    @property
    def agent_repo(self) -> PGAgentRepository:
        assert self._agent_repo is not None, "Container not initialized"
        return self._agent_repo

    @property
    def rules_repo(self) -> BusinessRulesRepository:
        assert self._rules_repo is not None, "Container not initialized"
        return self._rules_repo

    @property
    def prompt_repo(self) -> PromptRepository:
        assert self._prompt_repo is not None, "Container not initialized"
        return self._prompt_repo

    @property
    def message_repo(self) -> MessageRepository:
        assert self._message_repo is not None, "Container not initialized"
        return self._message_repo

    @property
    def faq_service(self) -> FAQService:
        assert self._faq_service is not None, "Container not initialized"
        return self._faq_service

    @property
    def faq_doc_repo(self) -> FAQDocumentRepository:
        assert self._faq_doc_repo is not None, "Container not initialized"
        return self._faq_doc_repo

    @property
    def admin_graph(self) -> Any:
        assert self._admin_graph is not None, "Container not initialized"
        return self._admin_graph

    @property
    def digest_service(self) -> DigestService:
        assert self._digest_service is not None, "Container not initialized"
        return self._digest_service

    async def refresh_retrievers(self) -> dict:
        """Rebuild all in-memory BM25 indexes from the current DB state.

        Call this after new documents are embedded (e.g. post embed-all) so
        BM25 sees new documents without a process restart.
        """
        faq_count = await self._faq_retriever.refresh_bm25()
        product_count = await self._product_retriever.refresh_bm25()
        return {"faq_docs": faq_count, "product_docs": product_count}

    async def close(self) -> None:
        if self._db_pool:
            await self._db_pool.close()
        if self._redis:
            await self._redis.aclose()
