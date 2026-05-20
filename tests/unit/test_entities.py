"""Unit tests for domain entities.

Covers:
- SessionRecord.to_socket_dict() includes last_intent field (F4)
- SessionRecord.last_intent transient field defaults to None
- SessionRecord.is_urgent() logic
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from ai_customer_service.domain.entities import SessionRecord


def _make_session(**kwargs) -> SessionRecord:
    defaults = dict(
        session_id="sess-1",
        user_id="user-1",
        thread_id="thread-1",
        mode="ai",
        history=[],
    )
    defaults.update(kwargs)
    return SessionRecord(**defaults)


# ── F4: last_intent on SessionRecord ─────────────────────────────────────────

def test_to_socket_dict_includes_last_intent_when_set():
    """to_socket_dict() must include last_intent when it is set."""
    sess = _make_session()
    sess.last_intent = "order_read"
    d = sess.to_socket_dict()
    assert "last_intent" in d
    assert d["last_intent"] == "order_read"


def test_to_socket_dict_includes_last_intent_none_by_default():
    """to_socket_dict() returns last_intent=None when never set."""
    sess = _make_session()
    d = sess.to_socket_dict()
    assert "last_intent" in d
    assert d["last_intent"] is None


def test_last_intent_transient_not_persisted():
    """last_intent is excluded from Pydantic model serialisation (transient)."""
    sess = _make_session()
    sess.last_intent = "faq"
    # model_dump() should not contain last_intent (it has exclude=True)
    data = sess.model_dump()
    assert "last_intent" not in data


def test_last_intent_can_be_set_and_read():
    """last_intent attribute is mutable and readable."""
    sess = _make_session()
    assert sess.last_intent is None
    sess.last_intent = "product"
    assert sess.last_intent == "product"


# ── SessionRecord.is_urgent() ─────────────────────────────────────────────────

def test_is_urgent_true_within_threshold():
    """is_urgent returns True when wedding is within 14 days."""
    wedding = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    sess = _make_session(order_context={"wedding_date": wedding})
    assert sess.is_urgent(14) is True


def test_is_urgent_false_beyond_threshold():
    """is_urgent returns False when wedding is more than 14 days away."""
    wedding = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    sess = _make_session(order_context={"wedding_date": wedding})
    assert sess.is_urgent(14) is False


def test_is_urgent_false_no_wedding_date():
    """is_urgent returns False when order_context has no wedding_date."""
    sess = _make_session(order_context={})
    assert sess.is_urgent() is False


# ── to_socket_dict() structure ────────────────────────────────────────────────

def test_to_socket_dict_contains_required_keys():
    """to_socket_dict() must contain all required workspace payload keys."""
    sess = _make_session()
    d = sess.to_socket_dict()
    for key in ("session_id", "user_id", "thread_id", "mode", "history",
                "pending_action", "order_context", "is_urgent", "last_intent"):
        assert key in d, f"Missing key: {key}"
