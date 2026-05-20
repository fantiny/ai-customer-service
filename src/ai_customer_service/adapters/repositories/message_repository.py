"""MessageRepository — persists every chat message to the session_messages table.

This is the canonical per-message audit store.  workspace_sessions.history is
the hot-cache used for live session display; session_messages is what drives
analytics, conversation replay, and business reporting.

get_by_thread_id() resolves thread_id → session_id via the workspace_sessions
JOIN so that ChatService can read conversation history without touching the
legacy ``conversations`` table (now deprecated and removed from production code).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import asyncpg

from ...domain.entities import Conversation, Message, SessionMessage
from ...domain.value_objects import MessageRole
from ...use_cases.interfaces import IMessageRepository

logger = logging.getLogger(__name__)

# Map session_messages.role strings to domain MessageRole.
# "bot" and "agent" both surface as ASSISTANT in the customer-facing API.
_ROLE_MAP: dict[str, MessageRole] = {
    "user":   MessageRole.USER,
    "bot":    MessageRole.ASSISTANT,
    "agent":  MessageRole.ASSISTANT,
    "system": MessageRole.SYSTEM,
}


class MessageRepository(IMessageRepository):
    """PostgreSQL-backed, append-only message store.

    Implements ``IMessageRepository`` — the single canonical source for
    conversation history (backed by the session_messages table).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, msg: SessionMessage) -> None:
        """Persist a single message; silently ignore duplicate message_id."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO session_messages
                        (message_id, session_id, ticket_id, role, content,
                         agent_id, node_name, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    msg.message_id,
                    msg.session_id,
                    msg.ticket_id,
                    msg.role,
                    msg.content,
                    msg.agent_id,
                    msg.node_name,
                    msg.created_at,
                )
        except Exception:
            logger.warning(
                "Failed to persist message %s session=%s",
                msg.message_id, msg.session_id,
                exc_info=True,
            )

    async def list_for_session(
        self,
        session_id: str,
        exclude_system: bool = False,
    ) -> list[SessionMessage]:
        """Return all messages for a session in chronological order."""
        where_extra = "AND role != 'system'" if exclude_system else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM session_messages
                WHERE session_id = $1 {where_extra}
                ORDER BY created_at ASC
                """,
                session_id,
            )
        return [_row_to_msg(r) for r in rows]

    async def count_by_role(self, session_id: str) -> dict[str, int]:
        """Return message count per role for a session."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, COUNT(*) AS cnt
                FROM session_messages
                WHERE session_id = $1
                GROUP BY role
                """,
                session_id,
            )
        return {r["role"]: r["cnt"] for r in rows}

    # ── Analytics queries ─────────────────────────────────────────────────────

    async def daily_volume(
        self, days: int = 7
    ) -> list[dict[str, Any]]:
        """Return daily message + session counts for the last N days."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    DATE(created_at AT TIME ZONE 'UTC') AS day,
                    COUNT(DISTINCT session_id) AS sessions,
                    COUNT(*) FILTER (WHERE role = 'user') AS user_msgs,
                    COUNT(*) FILTER (WHERE role IN ('bot', 'agent')) AS reply_msgs
                FROM session_messages
                WHERE created_at >= NOW() - ($1 || ' days')::interval
                GROUP BY day
                ORDER BY day ASC
                """,
                str(days),
            )
        return [
            {
                "date": str(r["day"]),
                "sessions": r["sessions"],
                "user_messages": r["user_msgs"],
                "reply_messages": r["reply_msgs"],
            }
            for r in rows
        ]

    async def get_by_thread_id(
        self,
        thread_id: str,
        exclude_system: bool = True,
    ) -> Conversation | None:
        """Return conversation history for a thread via workspace_sessions JOIN.

        Returns ``None`` when no workspace session exists for *thread_id*
        (e.g. the thread was started before the workspace layer existed, or
        was never associated with a session).
        """
        where_extra = "AND sm.role != 'system'" if exclude_system else ""
        async with self._pool.acquire() as conn:
            ws_row = await conn.fetchrow(
                "SELECT session_id, user_id FROM workspace_sessions WHERE thread_id = $1",
                thread_id,
            )
            if ws_row is None:
                return None

            session_id: str = ws_row["session_id"]
            user_id: str = ws_row["user_id"]

            msg_rows = await conn.fetch(
                f"""
                SELECT sm.role, sm.content, sm.created_at
                FROM session_messages sm
                WHERE sm.session_id = $1 {where_extra}
                ORDER BY sm.created_at ASC
                """,
                session_id,
            )

        messages = [
            Message(
                role=_ROLE_MAP.get(r["role"], MessageRole.ASSISTANT),
                content=r["content"],
                timestamp=r["created_at"],
            )
            for r in msg_rows
        ]
        return Conversation(thread_id=thread_id, user_id=user_id, messages=messages)

    async def avg_bot_response_ms(self, days: int = 7) -> int:
        """Return average bot response latency in milliseconds.

        Computed as the median milliseconds between a 'user' message and the
        immediately following 'bot' message in the same session, within the
        last N days.  Returns 0 if there are no qualifying pairs.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH ordered AS (
                    SELECT
                        session_id,
                        role,
                        created_at,
                        LEAD(role)        OVER (PARTITION BY session_id ORDER BY created_at) AS next_role,
                        LEAD(created_at)  OVER (PARTITION BY session_id ORDER BY created_at) AS next_ts
                    FROM session_messages
                    WHERE created_at >= NOW() - ($1 || ' days')::interval
                      AND role IN ('user', 'bot')
                )
                SELECT COALESCE(
                    AVG(EXTRACT(EPOCH FROM (next_ts - created_at)) * 1000)::BIGINT,
                    0
                ) AS avg_ms
                FROM ordered
                WHERE role = 'user' AND next_role = 'bot'
                  AND next_ts - created_at BETWEEN INTERVAL '0' AND INTERVAL '5 minutes'
                """,
                str(days),
            )
        return int(row["avg_ms"]) if row else 0

    async def node_distribution(self, days: int = 7) -> list[dict[str, Any]]:
        """Return count of bot messages grouped by generating node (intent)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    COALESCE(node_name, 'unknown') AS node,
                    COUNT(*) AS cnt
                FROM session_messages
                WHERE role = 'bot'
                  AND created_at >= NOW() - ($1 || ' days')::interval
                GROUP BY node
                ORDER BY cnt DESC
                """,
                str(days),
            )
        return [{"node": r["node"], "count": r["cnt"]} for r in rows]

    async def escalation_by_node(self, days: int = 7) -> list[dict[str, Any]]:
        """Return count of human-escalation events grouped by the last bot node before escalation.

        Joins session_messages to workspace_sessions to find sessions that were
        escalated to a human agent (assigned_agent_id IS NOT NULL), then finds
        the last bot message node in those sessions within the window.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH escalated_sessions AS (
                    SELECT session_id
                    FROM workspace_sessions
                    WHERE assigned_agent_id IS NOT NULL
                      AND updated_at >= NOW() - ($1 || ' days')::interval
                ),
                last_bot_node AS (
                    SELECT DISTINCT ON (sm.session_id)
                        sm.session_id,
                        COALESCE(sm.node_name, 'unknown') AS node
                    FROM session_messages sm
                    JOIN escalated_sessions es ON sm.session_id = es.session_id
                    WHERE sm.role = 'bot'
                      AND sm.node_name IS NOT NULL
                    ORDER BY sm.session_id, sm.created_at DESC
                )
                SELECT node, COUNT(*) AS cnt
                FROM last_bot_node
                GROUP BY node
                ORDER BY cnt DESC
                """,
                str(days),
            )
        return [{"node": r["node"], "count": int(r["cnt"])} for r in rows]


def _row_to_msg(row: asyncpg.Record) -> SessionMessage:
    def _dt(v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v))

    return SessionMessage(
        message_id=row["message_id"],
        session_id=row["session_id"],
        ticket_id=row["ticket_id"],
        role=row["role"],
        content=row["content"],
        agent_id=row["agent_id"],
        node_name=row["node_name"],
        created_at=_dt(row["created_at"]),
    )
