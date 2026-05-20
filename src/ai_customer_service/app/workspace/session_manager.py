"""WorkspaceSessionManager — in-memory hot-cache for active customer sessions.

Implements ISessionManager.  Each session is stored as a ``SessionRecord``
(the domain entity), which is also the durable DB record.  There is only one
representation — no ``SessionInfo`` / ``ChatMsg`` conversion dance.

Thread-safety: Socket.io events are serialised per asyncio event loop; no
additional locking is required.

History format: each entry in ``session.history`` is a plain dict:
    {"role": str, "content": str, "timestamp": str (ISO-8601)}
Valid roles: "user" | "bot" | "agent" | "system"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from ...domain.entities import SessionRecord
from ...use_cases.interfaces import ISessionManager

# Session mode type alias — shared across layers.
SessionMode = Literal["ai", "hitl_pending", "human"]


class WorkspaceSessionManager(ISessionManager):
    """Central in-memory registry of all active chat sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    # ── ISessionManager ───────────────────────────────────────────────────────

    def create(self, user_id: str, socket_id: str) -> SessionRecord:
        """Create a fresh session, register it, and return the record."""
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=f"sess-{uuid.uuid4().hex[:8]}",
            thread_id=str(uuid.uuid4()),
            user_id=user_id,
            mode="ai",
            socket_id=socket_id,
            created_at=now,
            updated_at=now,
        )
        self._sessions[record.session_id] = record
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def get_by_socket(self, socket_id: str) -> SessionRecord | None:
        for s in self._sessions.values():
            if s.socket_id == socket_id:
                return s
        return None

    def restore(self, record: SessionRecord, socket_id: str | None = None) -> None:
        """Load a persisted session back into the in-memory cache.

        Called at startup (bulk restore from DB) and on customer reconnect.
        If *socket_id* is given it is attached as the transient socket pointer.
        """
        if socket_id is not None:
            record.socket_id = socket_id
        self._sessions[record.session_id] = record

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def agent_queue(self) -> list[dict[str, Any]]:
        """Sessions awaiting agent action (HITL or human modes), urgent-first."""
        sessions = [
            s.to_socket_dict()
            for s in self._sessions.values()
            if s.mode in ("hitl_pending", "human")
        ]
        # Sort: is_urgent=True appears first in the queue.
        sessions.sort(key=lambda s: not s.get("is_urgent", False))
        return sessions

    def all_sessions(self) -> list[dict[str, Any]]:
        return [s.to_socket_dict() for s in self._sessions.values()]
