from __future__ import annotations

from typing import Any

from ...infrastructure.config import Settings


def build_langfuse_handler(
    settings: Settings,
    session_id: str,
    user_id: str,
    trace_name: str = "customer_service",
) -> Any | None:
    """Build a per-request Langfuse CallbackHandler.

    Returns None when Langfuse is disabled or credentials are missing,
    so callers can safely use `callbacks = [h for h in [handler] if h]`.
    """
    if not settings.LANGFUSE_ENABLED:
        return None
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None

    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
        )
    except ImportError:
        return None
