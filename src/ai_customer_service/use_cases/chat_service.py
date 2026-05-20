from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage

from ..adapters.observability.langfuse_handler import build_langfuse_handler
from ..domain.entities import Conversation
from ..infrastructure.config import Settings
from .interfaces import IMessageRepository

logger = logging.getLogger(__name__)

# Type alias: callable that returns the full LangGraph invocation config
GraphConfigFactory = Callable[[str, str, Any], dict]


@dataclass
class ChatResponse:
    thread_id: str
    reply: str | None
    status: str  # "complete" | "interrupted" | "error"
    pending_action: dict | None = None
    order_context: dict | None = None   # populated when an order was fetched this turn
    request_human: bool = False         # True when customer explicitly requested human agent
    intent: str | None = None           # LangGraph node/intent that produced the reply
    reply_sources: list = None          # Sources used by unified_agent_node tools (workspace-only)

    def __post_init__(self) -> None:
        if self.reply_sources is None:
            self.reply_sources = []


class ChatService:
    """Orchestrates conversation flow via the compiled LangGraph.

    Single write path
    ─────────────────
    History is read exclusively from ``IMessageRepository.get_by_thread_id()``,
    which queries the ``session_messages`` table through a ``workspace_sessions``
    JOIN.  The legacy ``conversations`` table is no longer written to or read
    from by this service.

    graph_config_factory is a callable(thread_id, user_id, langfuse_handler) -> dict
    that builds the full RunnableConfig passed to graph.ainvoke().
    This keeps ChatService decoupled from the Container.
    """

    def __init__(
        self,
        graph: Any,
        message_repo: IMessageRepository,
        settings: Settings,
        graph_config_factory: GraphConfigFactory,
    ) -> None:
        self._graph = graph
        self._message_repo = message_repo
        self._settings = settings
        self._config_factory = graph_config_factory

    async def send_message(
        self,
        thread_id: str,
        user_id: str,
        message: str,
        extra_config: dict | None = None,
    ) -> ChatResponse:
        """Send a message and return the AI response.

        *extra_config* is merged into ``config["configurable"]`` before graph
        invocation.  Use it to inject per-request callbacks (e.g. a
        ``progress_callback`` for streaming tool-call progress events) without
        modifying the shared ``graph_config_factory``.
        """
        handler = build_langfuse_handler(
            self._settings, session_id=thread_id, user_id=user_id
        )
        config = self._config_factory(thread_id, user_id, handler)
        if extra_config:
            config["configurable"].update(extra_config)

        result = await self._graph.ainvoke(
            {
                "messages": [HumanMessage(content=message)],
                "thread_id": thread_id,
                "user_id": user_id,
            },
            config=config,
        )
        return self._parse_result(result, thread_id)

    async def resume_hitl(
        self, thread_id: str, user_id: str, approval: dict
    ) -> ChatResponse:
        from langgraph.types import Command

        handler = build_langfuse_handler(
            self._settings,
            session_id=thread_id,
            user_id=user_id,
            trace_name="customer_service_hitl_resume",
        )
        config = self._config_factory(thread_id, user_id, handler)
        result = await self._graph.ainvoke(Command(resume=approval), config=config)
        return self._parse_result(result, thread_id)

    async def get_history(self, thread_id: str) -> Conversation | None:
        """Return conversation history from the canonical ``session_messages`` store.

        Delegates to ``IMessageRepository.get_by_thread_id()`` which resolves
        the thread via a ``workspace_sessions`` JOIN.  Returns ``None`` when no
        workspace session is associated with *thread_id*.
        """
        return await self._message_repo.get_by_thread_id(thread_id)

    @staticmethod
    def new_thread_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _parse_result(result: dict, thread_id: str) -> ChatResponse:
        if "__interrupt__" in result:
            interrupt_data = result["__interrupt__"]
            pending = interrupt_data[0].value if interrupt_data else {}
            return ChatResponse(
                thread_id=thread_id,
                reply=None,
                status="interrupted",
                pending_action=pending,
            )
        messages = result.get("messages", [])
        ai_messages = [m for m in messages if isinstance(m, AIMessage)]
        reply = ai_messages[-1].content if ai_messages else "无法处理您的请求，请稍后重试。"
        order_context = result.get("order_context") or None
        request_human = bool(result.get("request_human", False))
        intent = result.get("intent") or None
        reply_sources = list(result.get("reply_sources") or [])
        return ChatResponse(
            thread_id=thread_id,
            reply=reply,
            status="complete",
            order_context=order_context,
            request_human=request_human,
            intent=intent,
            reply_sources=reply_sources,
        )
