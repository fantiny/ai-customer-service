"""PGAgentRepository — persists customer-service agent identity and status.

Implements IAgentRepository using the `agents` table created in Phase 0.
current_session_ids is derived at query time from the tickets table rather
than stored as a column, keeping the schema normalised.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg

from ...domain.entities import Agent
from ...use_cases.interfaces import IAgentRepository

logger = logging.getLogger(__name__)


def _row_to_agent(row: asyncpg.Record, session_ids: list[str] | None = None) -> Agent:
    return Agent(
        agent_id=row["agent_id"],
        name=row["name"],
        status=row["status"],
        current_session_ids=session_ids or [],
        created_at=row["created_at"] or datetime.now(timezone.utc),
    )


class PGAgentRepository(IAgentRepository):
    """PostgreSQL-backed agent store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── IAgentRepository ──────────────────────────────────────────────────────

    async def save(self, agent: Agent) -> Agent:
        """Upsert agent record (status + name)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agents (agent_id, name, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (agent_id) DO UPDATE
                    SET name       = EXCLUDED.name,
                        status     = EXCLUDED.status,
                        updated_at = NOW()
                """,
                agent.agent_id,
                agent.name,
                agent.status,
                agent.created_at,
            )
        return agent

    async def get(self, agent_id: str) -> Agent | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agents WHERE agent_id = $1", agent_id
            )
            if not row:
                return None
            # Derive current sessions from open tickets assigned to this agent
            session_rows = await conn.fetch(
                """
                SELECT session_id FROM tickets
                WHERE assigned_agent_id = $1
                  AND status NOT IN ('resolved', 'closed')
                """,
                agent_id,
            )
        session_ids = [r["session_id"] for r in session_rows]
        return _row_to_agent(row, session_ids)

    async def list_online(self) -> list[Agent]:
        """Return all agents currently marked online."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agents WHERE status = 'online' ORDER BY name"
            )
        return [_row_to_agent(r) for r in rows]

    # ── Extended helpers ──────────────────────────────────────────────────────

    async def set_status(self, agent_id: str, status: str) -> None:
        """Quickly flip online / offline / busy without a full entity round-trip."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE agents SET status = $2, updated_at = NOW() WHERE agent_id = $1",
                agent_id,
                status,
            )

    async def list_all(self) -> list[Agent]:
        """Return all agents regardless of status."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM agents ORDER BY name")
        return [_row_to_agent(r) for r in rows]
