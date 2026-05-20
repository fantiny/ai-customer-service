"""PGSessionRepository — persists workspace sessions to PostgreSQL.

Implements ISessionRepository using the workspace_sessions table created
in Phase 0 migration.  History is stored as JSONB so it survives restarts.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from ...domain.entities import SessionRecord
from ...use_cases.interfaces import ISessionRepository

logger = logging.getLogger(__name__)


def _row_to_record(row: asyncpg.Record) -> SessionRecord:
    def _parse_dt(v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v))

    history_raw = row["history"]
    history: list[dict] = (
        json.loads(history_raw) if isinstance(history_raw, str) else list(history_raw or [])
    )

    pending_raw = row["pending_action"]
    pending: dict = (
        json.loads(pending_raw) if isinstance(pending_raw, str) else dict(pending_raw or {})
    )

    order_raw = row["order_context"]
    order_ctx: dict = (
        json.loads(order_raw) if isinstance(order_raw, str) else dict(order_raw or {})
    )

    return SessionRecord(
        session_id=row["session_id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        mode=row["mode"],
        escalation_reason=row["escalation_reason"],
        assigned_agent_id=row["assigned_agent_id"],
        pending_action=pending,
        order_context=order_ctx,
        history=history,
        created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
        first_response_at=_parse_dt(row["first_response_at"]),
        resolved_at=_parse_dt(row["resolved_at"]),
    )


class PGSessionRepository(ISessionRepository):
    """PostgreSQL-backed workspace session store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, session: SessionRecord) -> None:
        """Upsert a session record (insert or full update)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_sessions (
                    session_id, user_id, thread_id, mode,
                    escalation_reason, assigned_agent_id,
                    pending_action, order_context, history,
                    first_response_at, resolved_at,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6,
                    $7::jsonb, $8::jsonb, $9::jsonb,
                    $10, $11,
                    $12, NOW()
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    mode                = EXCLUDED.mode,
                    escalation_reason   = EXCLUDED.escalation_reason,
                    assigned_agent_id   = EXCLUDED.assigned_agent_id,
                    pending_action      = EXCLUDED.pending_action,
                    order_context       = EXCLUDED.order_context,
                    history             = EXCLUDED.history,
                    first_response_at   = EXCLUDED.first_response_at,
                    resolved_at         = EXCLUDED.resolved_at,
                    updated_at          = NOW()
                """,
                session.session_id,
                session.user_id,
                session.thread_id,
                session.mode,
                session.escalation_reason,
                session.assigned_agent_id,
                json.dumps(session.pending_action),
                json.dumps(session.order_context),
                json.dumps(session.history),
                session.first_response_at,
                session.resolved_at,
                session.created_at,
            )

    async def get(self, session_id: str) -> SessionRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workspace_sessions WHERE session_id = $1",
                session_id,
            )
        return _row_to_record(row) if row else None

    async def get_active(self) -> list[SessionRecord]:
        """Return all sessions whose mode is ai, hitl_pending, or human."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workspace_sessions
                WHERE mode IN ('ai', 'hitl_pending', 'human')
                ORDER BY updated_at DESC
                """
            )
        return [_row_to_record(r) for r in rows]

    async def list_by_user(self, user_id: str, limit: int = 20) -> list[dict]:
        """Return lightweight session summaries for a given user, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    session_id, mode, created_at, updated_at,
                    jsonb_array_length(history) AS msg_count,
                    history->0  AS first_msg,
                    history->-1 AS last_msg
                FROM workspace_sessions
                WHERE user_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
        result = []
        for r in rows:
            first_content = ""
            last_content = ""
            try:
                if r["first_msg"]:
                    fm = r["first_msg"] if isinstance(r["first_msg"], dict) else json.loads(r["first_msg"])
                    first_content = fm.get("content", "")[:60]
            except Exception:
                pass
            try:
                if r["last_msg"]:
                    lm = r["last_msg"] if isinstance(r["last_msg"], dict) else json.loads(r["last_msg"])
                    last_content = lm.get("content", "")[:80]
            except Exception:
                pass
            result.append({
                "session_id": r["session_id"],
                "mode": r["mode"],
                "msg_count": r["msg_count"] or 0,
                "first_content": first_content,
                "last_content": last_content,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            })
        return result

    async def delete(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM workspace_sessions WHERE session_id = $1",
                session_id,
            )
