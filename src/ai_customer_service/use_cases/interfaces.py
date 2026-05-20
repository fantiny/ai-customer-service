from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..domain.entities import (
    Agent,
    BusinessProfile,
    Conversation,
    Document,
    Order,
    OrderActionRequest,
    OrderActionResult,
    ProductInfo,
    SessionMessage,
    SessionRecord,
    StatusEvent,
    Ticket,
)
from ..domain.value_objects import OrderStatus


class IVectorStore(ABC):
    @abstractmethod
    async def similarity_search(self, query: str, k: int) -> list[Document]:
        """Return top-k documents by semantic similarity to query."""

    @abstractmethod
    async def upsert(self, documents: list[Document], embeddings: list[list[float]]) -> None:
        """Insert or update documents with their pre-computed embeddings."""


class IOrderRepository(ABC):
    @abstractmethod
    async def get_by_id(self, order_id: str) -> Order:
        """Raise OrderNotFoundError if not found."""

    @abstractmethod
    async def list_by_user(self, user_id: str, limit: int = 10) -> list[Order]:
        """Return up to *limit* recent orders for a user, ordered by created_at DESC."""

    @abstractmethod
    async def update_status(self, order_id: str, status: OrderStatus) -> Order:
        """Update order status and return the updated order."""

    @abstractmethod
    async def create(self, order: Order) -> Order:
        """Persist a new order."""


class IDigestRepository(ABC):
    """Data-access contract for daily KPI digest generation and retrieval.

    Separates raw SQL from the KPI-computation logic in DigestService so that
    the use-case layer stays free of asyncpg and is testable with mocks.
    """

    @abstractmethod
    async def fetch_ticket_rows(
        self, day_start: datetime, day_end: datetime
    ) -> list[dict[str, Any]]:
        """Return raw ticket fields needed for KPI computation for the given window."""

    @abstractmethod
    async def count_messages(self, day_start: datetime, day_end: datetime) -> int:
        """Count session_messages rows created within [day_start, day_end)."""

    @abstractmethod
    async def count_open_tickets(self) -> int:
        """Return current count of tickets with status in (open, in_progress, pending_reply)."""

    @abstractmethod
    async def save(
        self,
        digest_id: str,
        report_date: date,
        metrics_json: str,
        summary_md: str,
    ) -> None:
        """Upsert a daily digest row (idempotent — safe to call on regeneration)."""

    @abstractmethod
    async def get(self, report_date: date) -> dict[str, Any] | None:
        """Return stored metrics + summary for a date, or None if not found."""

    @abstractmethod
    async def list_recent(self, limit: int) -> list[dict[str, Any]]:
        """Return up to *limit* most recent digest summaries, newest first."""


class IMessageRepository(ABC):
    """Canonical per-message audit store backed by ``session_messages``.

    Single read/write source for conversation history.
    """

    @abstractmethod
    async def save(self, msg: SessionMessage) -> None:
        """Persist a single message; silently ignore duplicate message_id."""

    @abstractmethod
    async def get_by_thread_id(
        self,
        thread_id: str,
        exclude_system: bool = True,
    ) -> Conversation | None:
        """Return full conversation for *thread_id* via workspace_sessions JOIN.

        Returns ``None`` when the thread has no associated workspace session.
        """


class IOrderService(ABC):
    """Use-case interface for order business logic.

    Graph nodes and other callers depend on this interface, never on
    ``OrderService`` directly, so the service can be mocked in tests.
    """

    @abstractmethod
    async def list_orders(self, user_id: str) -> list[Order]:
        """Return up to 10 recent orders for the given user."""

    @abstractmethod
    async def execute(self, request: OrderActionRequest, user_id: str) -> OrderActionResult:
        """Execute the requested order action and return a result."""

    @abstractmethod
    async def validate(self, request: OrderActionRequest, user_id: str) -> Order:
        """Pre-validate a write action without executing it.

        Raises the same domain exceptions as execute() when the action is
        not feasible, so callers can surface errors BEFORE triggering HITL.
        Only checks domain constraints; does NOT mutate any data.

        Returns the fetched Order so callers can access metadata (e.g. wedding_date)
        without an additional DB round-trip.
        """


class IEmbeddingClient(ABC):
    @abstractmethod
    async def aembed_query(self, text: str) -> list[float]:
        """Embed a single query string."""

    @abstractmethod
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents."""


# ── Workspace / Ticketing interfaces ──────────────────────────────────────────

class IStatusEventRepository(ABC):
    """Append-only audit log of session and ticket status transitions."""

    @abstractmethod
    async def record(self, event: StatusEvent) -> None:
        """Persist a single status event."""

    @abstractmethod
    async def list_for_session(self, session_id: str) -> list[StatusEvent]:
        """Return all events for a session in chronological order."""


class ISessionManager(ABC):
    """In-memory hot-cache for active workspace sessions.

    Decouples ``WorkspaceService`` from the concrete ``WorkspaceSessionManager``
    and its socket-layer internals, eliminating the use_cases → app layer violation.
    """

    @abstractmethod
    def create(self, user_id: str, socket_id: str) -> SessionRecord:
        """Create a fresh session with generated IDs and register it in memory."""

    @abstractmethod
    def get(self, session_id: str) -> SessionRecord | None:
        """Return the in-memory session or None."""

    @abstractmethod
    def get_by_socket(self, socket_id: str) -> SessionRecord | None:
        """Look up a session by its socket connection ID."""

    @abstractmethod
    def restore(self, record: SessionRecord, socket_id: str | None = None) -> None:
        """Load a persisted session back into the in-memory cache (startup / reconnect)."""

    @abstractmethod
    def remove(self, session_id: str) -> None:
        """Evict a session from the in-memory cache."""

    @abstractmethod
    def agent_queue(self) -> list[dict]:
        """Return sessions in HITL or human mode, sorted by urgency."""

    @abstractmethod
    def all_sessions(self) -> list[dict]:
        """Return all active sessions (for monitoring)."""

class ISessionRepository(ABC):
    @abstractmethod
    async def save(self, session: SessionRecord) -> None:
        """Persist or update a workspace session record."""

    @abstractmethod
    async def get(self, session_id: str) -> SessionRecord | None:
        """Return None if session_id not found."""

    @abstractmethod
    async def get_active(self) -> list[SessionRecord]:
        """Return all sessions with mode in ('ai', 'hitl_pending', 'human')."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Remove a session record."""


class ITicketRepository(ABC):
    @abstractmethod
    async def create(self, ticket: Ticket) -> Ticket:
        """Persist a new ticket and return it."""

    @abstractmethod
    async def update(self, ticket: Ticket) -> Ticket:
        """Update an existing ticket and return it."""

    @abstractmethod
    async def get(self, ticket_id: str) -> Ticket | None:
        """Return None if ticket_id not found."""

    @abstractmethod
    async def get_by_session(self, session_id: str) -> Ticket | None:
        """Return the ticket associated with a session, or None."""

    @abstractmethod
    async def list_open(self) -> list[Ticket]:
        """Return all tickets with status in ('open', 'in_progress', 'pending_reply')."""


class IAgentRepository(ABC):
    @abstractmethod
    async def save(self, agent: Agent) -> Agent:
        """Persist or update an agent record and return it."""

    @abstractmethod
    async def get(self, agent_id: str) -> Agent | None:
        """Return None if agent_id not found."""

    @abstractmethod
    async def list_online(self) -> list[Agent]:
        """Return all agents with status 'online'."""

    @abstractmethod
    async def set_status(self, agent_id: str, status: str) -> None:
        """Update an agent's status in-place (e.g. 'online' → 'offline')."""


@dataclass
class UserMessageResult:
    """Return value of IWorkspaceService.handle_user_message().

    Fields are the exact keys that socket_server.py emits in the 'new_message'
    socket event — defining them here removes the implicit dict[str, Any] contract
    and makes the shape visible to type checkers and consumers.
    """
    role: str                            # always "user"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None             # non-None means session not found


class IWorkspaceService(ABC):
    """Business logic layer for the human-agent workspace.

    Decouples socket_server.py from direct state mutation and enables
    testable, persistence-backed workspace operations.
    """

    @abstractmethod
    async def join_customer(
        self,
        user_id: str,
        socket_id: str,
        session_id: str | None,
    ) -> SessionRecord:
        """Register or restore a customer session. Returns the SessionRecord."""

    @abstractmethod
    async def join_agent(self, agent_id: str, name: str) -> Agent:
        """Register an agent as online. Returns the Agent."""

    @abstractmethod
    async def handle_user_message(self, session_id: str, content: str) -> UserMessageResult:
        """Process an incoming user message. Returns typed result for socket emission."""

    @abstractmethod
    async def handle_agent_reply(
        self, session_id: str, agent_id: str, content: str
    ) -> None:
        """Record and broadcast an agent reply."""

    @abstractmethod
    async def transfer_to_human(
        self, session_id: str, reason: str | None
    ) -> SessionRecord:
        """Escalate session to human mode. Returns updated SessionRecord."""

    @abstractmethod
    async def transfer_to_ai(
        self, session_id: str, agent_id: str
    ) -> SessionRecord:
        """Return session to AI mode. Returns updated SessionRecord."""

    @abstractmethod
    async def resolve_ticket(
        self,
        session_id: str,
        agent_id: str,
        resolution: str | None,
    ) -> Ticket:
        """Close the ticket associated with the session. Returns the resolved Ticket."""

    @abstractmethod
    async def leave_agent(self, agent_id: str) -> None:
        """Mark an agent as offline (called on socket disconnect)."""

    @abstractmethod
    async def claim_session(
        self,
        session_id: str,
        agent_id: str,
    ) -> Ticket:
        """Assign an agent to a session's ticket. Returns the updated Ticket."""

    # ── Persistence helpers (called by socket_server after graph runs) ────────

    @abstractmethod
    async def record_bot_message(
        self,
        session_id: str,
        content: str,
        node_name: str | None = None,
        role: str = "bot",
    ) -> None:
        """Persist a bot/system reply to the canonical message store.

        node_name: LangGraph intent node (e.g. 'faq_node') — used for analytics.
        role:      'bot' for AI replies, 'system' for internal workspace notes.
        Sets first_response_at on the session if this is the first bot reply.
        """

    @abstractmethod
    async def update_order_context(
        self, session_id: str, order_context: dict
    ) -> None:
        """Store order context fetched this turn (for the workspace side panel)."""

    @abstractmethod
    async def record_hitl_state(
        self, session_id: str, pending_action: dict | None
    ) -> None:
        """Persist pending HITL state after a LangGraph interrupt()."""

    @abstractmethod
    async def load_active_sessions(self) -> int:
        """Restore active sessions from DB into the in-memory cache on startup.

        Returns the number of sessions restored.
        """

    @abstractmethod
    async def submit_rating(self, session_id: str, rating: int) -> None:
        """Store a customer CSAT rating (1–5) on the session ticket."""

    @abstractmethod
    async def auto_categorize_if_needed(
        self, session_id: str, first_message: str
    ) -> None:
        """Classify the ticket category from the first user message if unset."""


class IProductService(ABC):
    """Use-case interface for the product catalog. Nodes never see the repository."""

    @abstractmethod
    async def list_all(self) -> list[ProductInfo]:
        """Return all active products."""

    @abstractmethod
    async def search(
        self,
        style: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        stock_type: str | None = None,
        rush_only: bool = False,
        limit: int = 20,
    ) -> list[ProductInfo]:
        """Return filtered products. All params optional."""

    @abstractmethod
    async def get(self, product_id: str) -> ProductInfo | None:
        """Return a single product or None."""


class IFAQService(ABC):
    """Use-case interface for knowledge-base retrieval."""

    @abstractmethod
    async def retrieve(self, query: str) -> list[Document]:
        """Return top-k relevant FAQ / policy documents."""


class IBusinessRulesService(ABC):
    """Use-case interface for dynamic business configuration."""

    @abstractmethod
    async def get(self, key: str, default: Any = None) -> Any:
        """Return the value for a config key, or default if absent."""

    @abstractmethod
    async def get_language(self) -> str:
        """Return the configured default_language value."""


class IBusinessProfileRepository(ABC):
    """Persistence interface for BusinessProfile loading."""

    @abstractmethod
    async def get(self, business_id: str) -> BusinessProfile:
        """Load and return the BusinessProfile for business_id.

        Raises ValueError if the profile does not exist or is inactive.
        """


@dataclass
class WorkflowStep:
    """A single step in a business workflow."""
    step: int
    instruction: str
    action: str | None = None    # Optional tool action (e.g. "create_ticket")
    condition: str | None = None # Optional condition expression


@dataclass
class WorkflowDefinition:
    """A complete workflow loaded from the business_workflows table."""
    workflow_id: str
    business_id: str
    display_name: str
    trigger_intent: str
    trigger_keywords: list[str]
    steps: list[WorkflowStep]
    is_active: bool = True
    sort_order: int = 0


class IWorkflowRepository(ABC):
    """Persistence interface for business workflow definitions."""

    @abstractmethod
    async def get_workflows(
        self,
        business_id: str,
        trigger_intent: str | None = None,
    ) -> list[WorkflowDefinition]:
        """Return active workflows for a business, optionally filtered by trigger intent."""

    @abstractmethod
    async def get_workflow(
        self,
        workflow_id: str,
        business_id: str,
    ) -> WorkflowDefinition | None:
        """Return a specific workflow by ID, or None if not found."""
