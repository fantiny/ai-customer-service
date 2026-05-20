from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from datetime import date as _date

from pydantic import BaseModel, Field, field_validator

from .value_objects import MessageRole, OrderStatus, ProductionStage, RushLevel


class Message(BaseModel):
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    thread_id: str
    user_id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price: float


class WeddingMeta(BaseModel):
    """Wedding dress specific details embedded in Order."""
    dress_style: str = ""
    color: str = "ivory_white"
    is_custom: bool = False
    bust: float | None = None      # cm
    waist: float | None = None     # cm
    hips: float | None = None      # cm
    height: float | None = None    # cm
    wedding_date: str | None = None          # YYYY-MM-DD — validated by field_validator below
    production_stage: ProductionStage = ProductionStage.PENDING
    is_rush: bool = False
    rush_level: RushLevel = RushLevel.NONE
    estimated_completion: str | None = None  # YYYY-MM-DD
    alteration_notes: str = ""

    @field_validator("wedding_date", "estimated_completion", mode="before")
    @classmethod
    def _validate_date_str(cls, v: Any) -> str | None:
        """Ensure date strings are YYYY-MM-DD.  Silently clears malformed values
        rather than raising so existing seed data with bad dates doesn't break startup.
        Returns None for blank/null inputs.
        """
        if v is None or v == "":
            return None
        if isinstance(v, _date):
            return v.isoformat()
        try:
            _date.fromisoformat(str(v))
            return str(v)
        except (ValueError, TypeError):
            import logging
            logging.getLogger(__name__).warning(
                "WeddingMeta: invalid date string %r — field cleared", v
            )
            return None

    def wedding_date_as_date(self) -> _date | None:
        """Return wedding_date parsed to a stdlib date, or None if absent/invalid."""
        if not self.wedding_date:
            return None
        try:
            return _date.fromisoformat(self.wedding_date)
        except ValueError:
            return None


class Order(BaseModel):
    order_id: str
    user_id: str
    status: OrderStatus
    items: list[OrderItem]
    total: float
    created_at: datetime
    updated_at: datetime
    shipping_address: str = ""
    tracking_number: str = ""
    wedding_meta: WeddingMeta = Field(default_factory=WeddingMeta)


class Document(BaseModel):
    doc_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0


class ProductInfo(BaseModel):
    """Domain entity for a wedding dress product."""
    product_id: str
    name: str
    style: str
    price: float
    deposit_rate: float
    production_days: int
    rush_available: bool
    stock_type: str          # "ready" | "custom"
    colors: list[str]
    tags: list[str]
    description: str
    occasions: list[str]
    active: bool = True
    purchase_url: str = ""   # official store link; empty = not configured

    def to_context_str(self) -> str:
        deposit = round(self.price * self.deposit_rate)
        rush = "支持加急" if self.rush_available else "不支持加急"
        stock = "现货可售" if self.stock_type == "ready" else "定制款"
        url_line = f"购买链接：{self.purchase_url}\n" if self.purchase_url else ""
        return (
            f"【{self.product_id}】{self.name}\n"
            f"款式：{self.style} | 价格：¥{self.price:,.0f} | 定金：¥{deposit:,.0f}\n"
            f"生产周期：{self.production_days}天 | {rush} | {stock}\n"
            f"可选颜色：{'、'.join(self.colors)}\n"
            f"适合场合：{'、'.join(self.occasions)}\n"
            f"{url_line}"
            f"商品描述：{self.description}"
        )


class OrderActionRequest(BaseModel):
    """Structured output from LLM for order action extraction.

    ``extra`` is a catch-all dict for action-specific parameters.  Use the
    typed property accessors below rather than indexing ``extra`` directly so
    that the data contract is visible at the call site.
    """
    action: str  # cancel_order | initiate_refund | request_rush | get_status | …
    order_id: str
    extra: dict[str, Any] = Field(default_factory=dict)

    # ── Typed accessors for known extra fields ────────────────────────────────

    @property
    def rush_level(self) -> str:
        """Rush level for request_rush actions.  Empty string when not set."""
        return self.extra.get("rush_level", "")


class OrderActionResult(BaseModel):
    message: str
    order: Order | None = None
    success: bool = True


# ── Workspace / Ticketing domain entities ─────────────────────────────────────

class SessionRecord(BaseModel):
    """Single source of truth for a workspace session — both in-memory and persisted.

    Durable fields (persisted to workspace_sessions table):
        session_id, user_id, thread_id, mode, escalation_reason,
        assigned_agent_id, pending_action, order_context, history,
        created_at, updated_at, first_response_at, resolved_at

    Transient fields (in-memory only — NOT saved to DB):
        socket_id         : customer's current socket connection id
        hitl_pending_since: when this session entered hitl_pending mode

    History format: each entry is {"role": str, "content": str, "timestamp": str (ISO)}
    Valid roles: "user" | "bot" | "agent" | "system"
    """
    session_id: str
    user_id: str
    thread_id: str
    mode: str = "ai"                  # "ai" | "hitl_pending" | "human"
    escalation_reason: str | None = None
    assigned_agent_id: str | None = None
    pending_action: dict[str, Any] = Field(default_factory=dict)
    order_context: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None

    # ── Transient (not persisted) ─────────────────────────────────────────────
    socket_id: str | None = Field(default=None, exclude=True)
    hitl_pending_since: datetime | None = Field(default=None, exclude=True)
    last_intent: str | None = Field(default=None, exclude=True)

    def add_message(
        self, role: str, content: str, timestamp: str | None = None
    ) -> dict[str, Any]:
        """Append a message to history and return the new entry."""
        entry: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }
        self.history.append(entry)
        return entry

    def is_urgent(self, urgent_days_threshold: int = 14) -> bool:
        """Return True when the wedding date is within urgent_days_threshold days.

        The threshold defaults to 14 for backwards compatibility, but callers
        with access to BusinessProfile.urgency_config should pass
        profile.urgency_config.urgent_days_threshold so that the workspace
        badge agrees with the graph's urgency detection.
        """
        from datetime import date as _date
        wedding_date_str = self.order_context.get("wedding_date") if self.order_context else None
        if not wedding_date_str:
            return False
        try:
            wedding_dt = _date.fromisoformat(str(wedding_date_str))
            return 0 <= (wedding_dt - _date.today()).days <= urgent_days_threshold
        except (ValueError, TypeError):
            return False

    def to_socket_dict(self, urgent_days_threshold: int = 14) -> dict[str, Any]:
        """Serialise for socket.io emission to workspace agents.

        Pass urgent_days_threshold from BusinessProfile.urgency_config so the
        workspace urgency badge uses the same threshold as the graph router.
        """
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "mode": self.mode,
            "history": self.history,
            "pending_action": self.pending_action,
            "order_context": self.order_context,
            "escalation_reason": self.escalation_reason,
            "assigned_agent_id": self.assigned_agent_id,
            "is_urgent": self.is_urgent(urgent_days_threshold),
            "last_intent": self.last_intent,
        }


class Ticket(BaseModel):
    """A complete customer service interaction ticket.

    One ticket is created per customer session (1-to-1 initially).
    Status follows the lifecycle: open → in_progress → pending_reply
    → resolved → closed.
    """
    ticket_id: str
    session_id: str
    user_id: str
    status: str = "open"              # open|in_progress|pending_reply|resolved|closed
    category: str | None = None       # high-level category (质量投诉/订单操作/咨询/其他)
    assigned_agent_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    summary: str | None = None        # AI-generated handoff summary shown to agent on takeover
    # resolution stores the LLM-generated close report as a raw JSON string.
    # Use close_report() for safe dict access; prefer the structured report_*
    # columns for SQL queries rather than parsing this field.
    resolution: str | None = None
    sentiment: str | None = None      # final customer sentiment: positive|neutral|negative
    rating: int | None = None         # CSAT: 1–5 stars submitted by customer after resolution
    sla_deadline: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    # ── Structured close-report fields (queryable SQL columns) ────────────────
    report_resolution_type: str | None = None   # refund/cancel/info/escalated/other
    report_sentiment_start: str | None = None   # customer sentiment at session start
    report_key_issues: list[str] = Field(default_factory=list)
    report_ai_quality: str | None = None        # good/fair/poor — AI handling assessment

    def close_report(self) -> dict[str, Any]:
        """Parse and return the raw JSON close report, or an empty dict if absent/invalid.

        Prefer the structured ``report_*`` columns for queries; use this only
        when you need the full LLM output that may contain keys not yet mapped
        to dedicated columns.
        """
        if not self.resolution:
            return {}
        import json as _json
        try:
            return _json.loads(self.resolution)
        except (ValueError, TypeError):
            return {}


class Agent(BaseModel):
    """Customer service agent identity and availability."""
    agent_id: str
    name: str
    status: str = "offline"           # "online" | "offline" | "busy"
    current_session_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusEvent(BaseModel):
    """Immutable audit record of a session or ticket status transition."""
    event_id: str
    session_id: str
    ticket_id: str | None = None
    from_status: str
    to_status: str
    actor: str                        # "ai" | agent_id | "system"
    note: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionMessage(BaseModel):
    """A single chat message persisted to the session_messages table.

    Every message in every session — user, bot, agent, system — gets its own
    row here. This is the canonical audit store; workspace_sessions.history is
    the hot-cache counterpart for the live session panel.
    """
    message_id: str
    session_id: str
    ticket_id: str | None = None
    role: str                         # "user" | "bot" | "agent" | "system"
    content: str
    agent_id: str | None = None       # populated when role == "agent"
    node_name: str | None = None      # LangGraph node that produced this reply
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Generic business profile entities ────────────────────────────────────────
# These are frozen dataclasses (not Pydantic models) because they are immutable
# configuration objects loaded once at startup and passed through the graph's
# configurable dict.  Pydantic BaseModel is reserved for mutable domain objects
# that need validation on construction from untrusted input (DB rows, API payloads).


@dataclass(frozen=True)
class SafetyConfig:
    """Safety detection configuration — all thresholds and keywords come from
    the business profile rather than being hardcoded in node files.

    ``escalation_keywords`` are matched case-insensitively against user input.
    They may be plain strings or simple regex patterns (re.search semantics).
    Prompt injection detection patterns are NOT stored here — they are a
    universal security baseline kept hardcoded in safety_check_node.
    """
    escalation_keywords: tuple[str, ...] = field(default_factory=tuple)
    max_input_length: int = 2000
    # Negative-sentiment turns before silent human-transfer trigger, by intent_id
    escalation_thresholds: dict[str, int] = field(default_factory=dict)
    # Override for all intents when is_urgent is True
    urgent_escalation_threshold: int = 2


@dataclass(frozen=True)
class UrgencyConfig:
    """Defines what "urgent" means for a business.

    ``deadline_field`` is the key in ``order_context`` that holds the relevant
    deadline (e.g. ``"wedding_date"`` for bridal, ``"delivery_date"`` for food).
    When the deadline is within ``urgent_days_threshold`` days, ``is_urgent``
    is set to True in the graph state.
    """
    enabled: bool = False
    deadline_field: str = "deadline_date"
    urgent_days_threshold: int = 14


@dataclass(frozen=True)
class ContactConfig:
    """Business contact information injected into node prompts via placeholders."""
    hotline: str = ""
    website: str = ""
    email: str = ""


@dataclass(frozen=True)
class HandoffConfig:
    """Configurable behaviour for seamless AI → human handoff.

    When AI cannot reliably answer (missing product service, no policy docs),
    it escalates to a human agent instead of issuing a cold refusal.  All
    customer-facing copy and language choices are configured here so operators
    can tune the handoff experience without touching code.

    Priority for customer-facing message:
    1. business_rules key (e.g. ``handoff.policy_no_doc``)
    2. ``notification_template`` (this config)
    3. Node-level hardcoded fallback constant

    Fields:
        notify_customer: Whether to send a message to the customer about the
            handoff.  Set to False for silent escalation (e.g. monitoring mode).
        notification_template: Template shown to the customer.  Supports
            ``{business_name}`` placeholder.
        silent_handoff_message: Message sent when notify_customer is False
            (may be empty to send nothing at all).
        handoff_language: BCP-47 override for handoff message language.
            None = follow conversation language detection.
    """
    notify_customer: bool = True
    notification_template: str = "关于这个问题我帮您连线专属顾问，稍等一下～"
    silent_handoff_message: str = ""
    handoff_language: str | None = None


@dataclass(frozen=True)
class IntentDefinition:
    """Full definition of a single routing intent.

    ``handler_node`` must match a key in ``_BUILTIN_NODE_REGISTRY`` in
    ``graph/builder.py``.  The ``description`` is used verbatim by the router
    LLM to decide when to route to this intent.
    """
    intent_id: str
    display_name: str
    description: str
    handler_node: str
    requires_confirmation: bool = False
    # True means safety_check_node can route directly here without going
    # through router_node (multi-turn continuation, e.g. order_read/write)
    is_continuation_node: bool = False
    # Per-intent negative-turn escalation threshold; None = use safety_config default
    negative_turns_threshold: int | None = None


@dataclass(frozen=True)
class BusinessProfile:
    """Complete business configuration — the single source of truth for all
    business-specific behaviour in the graph layer.

    Loaded once at startup by ``BusinessProfileService``, then injected into
    every graph invocation via ``config["configurable"]["business_profile"]``.
    Nodes read from this object instead of hardcoding business-specific values.

    All fields are frozen (immutable); changes require a service restart.  Use
    ``BusinessProfileService.invalidate()`` + ``reload()`` for hot-updates
    (requires graph recompilation).
    """
    business_id: str
    business_name: str
    business_type: str = "ecommerce"

    intents: tuple[IntentDefinition, ...] = field(default_factory=tuple)
    safety_config: SafetyConfig = field(default_factory=SafetyConfig)
    urgency_config: UrgencyConfig = field(default_factory=UrgencyConfig)
    contact_config: ContactConfig = field(default_factory=ContactConfig)
    handoff_config: HandoffConfig = field(default_factory=HandoffConfig)

    # Feature flags
    order_enabled: bool = True
    product_enabled: bool = True
    faq_enabled: bool = True
    aftersales_enabled: bool = True

    # Document category tags used to scope retrieval to this business's documents.
    # Must match the ``metadata->>'category'`` values stored in faq_documents.
    faq_category: str = "wedding_dress_faq"
    product_catalog_category: str = "product_catalog"

    # Intent to fall back to when router confidence is below threshold
    fallback_intent_id: str = "general"

    # ── Convenience accessors ─────────────────────────────────────────────────

    def get_intent(self, intent_id: str) -> IntentDefinition | None:
        return next((i for i in self.intents if i.intent_id == intent_id), None)

    def continuation_node_ids(self) -> frozenset[str]:
        """Handler node names that safety_check_node should route to directly
        (multi-turn continuation) without going through router_node."""
        return frozenset(i.handler_node for i in self.intents if i.is_continuation_node)

    def intent_to_node_map(self) -> dict[str, str]:
        """Mapping intent_id → handler_node for use in route_after_router."""
        return {i.intent_id: i.handler_node for i in self.intents}
