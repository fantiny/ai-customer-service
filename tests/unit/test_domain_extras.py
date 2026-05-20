"""Tests for domain/entities.py and domain/exceptions.py missing coverage."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from ai_customer_service.domain.entities import (
    Agent,
    BusinessProfile,
    ContactConfig,
    HandoffConfig,
    IntentDefinition,
    OrderActionRequest,
    ProductInfo,
    SafetyConfig,
    SessionRecord,
    Ticket,
    UrgencyConfig,
    WeddingMeta,
)
from ai_customer_service.domain.exceptions import (
    HITLRequiredError,
    InvalidOrderActionError,
    OrderAccessDeniedError,
    OrderNotFoundError,
    SafetyViolationError,
)


# ── WeddingMeta ───────────────────────────────────────────────────────────────


def test_validate_date_string_accepts_date_object():
    """Line 62: isinstance(v, _date) → converts to isoformat."""
    today = date.today()
    meta = WeddingMeta(wedding_date=today)  # type: ignore[arg-type]
    assert meta.wedding_date == today.isoformat()


def test_validate_date_string_rejects_invalid_string():
    """Lines 66-71: invalid string silently cleared."""
    meta = WeddingMeta(wedding_date="not-a-date")
    assert meta.wedding_date is None


def test_validate_date_string_accepts_none():
    meta = WeddingMeta(wedding_date=None)
    assert meta.wedding_date is None


def test_validate_date_string_accepts_empty():
    meta = WeddingMeta(wedding_date="")
    assert meta.wedding_date is None


def test_validate_date_string_accepts_valid_iso():
    meta = WeddingMeta(wedding_date="2026-12-25")
    assert meta.wedding_date == "2026-12-25"


def test_wedding_date_as_date_returns_none_when_absent():
    meta = WeddingMeta()
    assert meta.wedding_date_as_date() is None


def test_wedding_date_as_date_returns_date_when_valid():
    meta = WeddingMeta(wedding_date="2026-12-25")
    result = meta.wedding_date_as_date()
    assert result == date(2026, 12, 25)


def test_wedding_date_as_date_returns_none_after_invalid_cleared():
    """Lines 79-80: after bad string is cleared → returns None."""
    meta = WeddingMeta(wedding_date="garbage")
    assert meta.wedding_date is None
    assert meta.wedding_date_as_date() is None


# ── ProductInfo.to_context_str ────────────────────────────────────────────────


def _make_product(purchase_url: str = "") -> ProductInfo:
    return ProductInfo(
        product_id="WD-P001",
        name="鱼尾婚纱",
        style="鱼尾",
        price=5000.0,
        deposit_rate=0.3,
        production_days=45,
        rush_available=True,
        stock_type="custom",
        colors=["白色", "香槟色"],
        tags=["浪漫"],
        description="经典鱼尾款婚纱",
        occasions=["婚礼"],
        purchase_url=purchase_url,
    )


def test_to_context_str_without_url():
    product = _make_product()
    s = product.to_context_str()
    assert "WD-P001" in s
    assert "购买链接" not in s


def test_to_context_str_with_url():
    """Lines 121-125: url_line included when purchase_url is set."""
    product = _make_product(purchase_url="https://shop.example.com/dress")
    s = product.to_context_str()
    assert "购买链接：https://shop.example.com/dress" in s


def test_to_context_str_rush_not_available():
    product = _make_product()
    p2 = product.model_copy(update={"rush_available": False})
    s = p2.to_context_str()
    assert "不支持加急" in s


# ── OrderActionRequest.rush_level ─────────────────────────────────────────────


def test_rush_level_returns_empty_when_not_set():
    """Line 152: rush_level property returns "" when not in extra."""
    req = OrderActionRequest(action="request_rush", order_id="ORD-001")
    assert req.rush_level == ""


def test_rush_level_returns_value_when_set():
    req = OrderActionRequest(
        action="request_rush",
        order_id="ORD-001",
        extra={"rush_level": "super_rush"},
    )
    assert req.rush_level == "super_rush"


# ── SessionRecord ─────────────────────────────────────────────────────────────


def _make_session() -> SessionRecord:
    return SessionRecord(
        session_id="sess-1",
        user_id="user-1",
        thread_id="thr-1",
        mode="ai",
    )


def test_add_message_appends_to_history():
    """Lines 200-206: add_message() appends entry and returns it."""
    sess = _make_session()
    entry = sess.add_message("user", "hello")
    assert entry["role"] == "user"
    assert entry["content"] == "hello"
    assert "timestamp" in entry
    assert sess.history == [entry]


def test_add_message_accepts_custom_timestamp():
    sess = _make_session()
    entry = sess.add_message("bot", "reply", timestamp="2026-01-01T00:00:00")
    assert entry["timestamp"] == "2026-01-01T00:00:00"


def test_is_urgent_false_when_no_order_context():
    """Line 218: no wedding_date → False."""
    sess = _make_session()
    assert sess.is_urgent() is False


def test_is_urgent_false_when_no_wedding_date():
    sess = _make_session()
    sess.order_context = {"order_id": "ORD-1"}
    assert sess.is_urgent() is False


def test_is_urgent_true_when_wedding_within_threshold():
    """Lines 216-224: wedding_date within 14 days → True."""
    sess = _make_session()
    soon = (date.today() + timedelta(days=7)).isoformat()
    sess.order_context = {"wedding_date": soon}
    assert sess.is_urgent() is True


def test_is_urgent_false_when_wedding_past():
    sess = _make_session()
    past = (date.today() - timedelta(days=1)).isoformat()
    sess.order_context = {"wedding_date": past}
    assert sess.is_urgent() is False


def test_is_urgent_false_when_wedding_far_future():
    sess = _make_session()
    far = (date.today() + timedelta(days=30)).isoformat()
    sess.order_context = {"wedding_date": far}
    assert sess.is_urgent() is False


def test_is_urgent_false_on_bad_date_string():
    sess = _make_session()
    sess.order_context = {"wedding_date": "not-a-date"}
    assert sess.is_urgent() is False


def test_to_socket_dict_includes_is_urgent():
    """Line 232: to_socket_dict() calls is_urgent() and includes result."""
    sess = _make_session()
    d = sess.to_socket_dict()
    assert "is_urgent" in d
    assert d["session_id"] == "sess-1"
    assert d["mode"] == "ai"


# ── Ticket.close_report ───────────────────────────────────────────────────────


def test_close_report_returns_empty_when_no_resolution():
    """Line 284: resolution is None → {}."""
    ticket = Ticket(ticket_id="T1", session_id="S1", user_id="U1")
    assert ticket.close_report() == {}


def test_close_report_parses_valid_json():
    """Lines 285-289: valid JSON parsed correctly."""
    data = {"resolution_type": "refund", "sentiment": "negative"}
    ticket = Ticket(
        ticket_id="T1", session_id="S1", user_id="U1",
        resolution=json.dumps(data),
    )
    assert ticket.close_report() == data


def test_close_report_returns_empty_on_invalid_json():
    """Lines 289-290: invalid JSON → {}."""
    ticket = Ticket(
        ticket_id="T1", session_id="S1", user_id="U1",
        resolution="not-json{{{",
    )
    assert ticket.close_report() == {}


# ── BusinessProfile convenience methods ──────────────────────────────────────


def _make_profile() -> BusinessProfile:
    intents = (
        IntentDefinition(
            intent_id="product",
            display_name="商品",
            description="商品咨询",
            handler_node="product_node",
            is_continuation_node=False,
        ),
        IntentDefinition(
            intent_id="order_read",
            display_name="查询",
            description="订单查询",
            handler_node="order_read_node",
            is_continuation_node=True,
        ),
    )
    return BusinessProfile(
        business_id="test_biz",
        business_name="测试店铺",
        intents=intents,
    )


def test_get_intent_returns_matching():
    """Line 468: get_intent returns the matching IntentDefinition."""
    profile = _make_profile()
    intent = profile.get_intent("product")
    assert intent is not None
    assert intent.intent_id == "product"


def test_get_intent_returns_none_for_missing():
    profile = _make_profile()
    assert profile.get_intent("nonexistent") is None


def test_continuation_node_ids():
    """Line 473: continuation_node_ids returns frozenset of continuation nodes."""
    profile = _make_profile()
    ids = profile.continuation_node_ids()
    assert "order_read_node" in ids
    assert "product_node" not in ids


def test_intent_to_node_map():
    """Line 477: intent_to_node_map maps intent_id → handler_node."""
    profile = _make_profile()
    mapping = profile.intent_to_node_map()
    assert mapping["product"] == "product_node"
    assert mapping["order_read"] == "order_read_node"


# ── Exceptions ────────────────────────────────────────────────────────────────


def test_order_not_found_error():
    err = OrderNotFoundError("ORD-999")
    assert "ORD-999" in str(err)
    assert err.order_id == "ORD-999"


def test_order_access_denied_error():
    err = OrderAccessDeniedError("ORD-1", "user-x")
    assert "user-x" in str(err)
    assert "ORD-1" in str(err)


def test_invalid_order_action_error_attributes():
    err = InvalidOrderActionError("cancel_order", "订单已发货无法取消")
    assert err.action == "cancel_order"
    assert err.user_reason == "订单已发货无法取消"
    assert "cancel_order" in str(err)


def test_safety_violation_error():
    """Lines 32-33: SafetyViolationError stores reason."""
    err = SafetyViolationError("prompt injection detected")
    assert err.reason == "prompt injection detected"
    assert "Safety check failed" in str(err)


def test_hitl_required_error():
    """Lines 40-41: HITLRequiredError stores pending_action."""
    action = {"action": "cancel_order", "order_id": "ORD-1"}
    err = HITLRequiredError(action)
    assert err.pending_action == action
    assert "Human-in-the-loop" in str(err)
