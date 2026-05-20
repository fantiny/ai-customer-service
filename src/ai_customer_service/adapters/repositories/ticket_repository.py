"""PGTicketRepository — persists tickets and status events to PostgreSQL.

Implements ITicketRepository using the `tickets` table and writes immutable
audit records to `status_events` on every transition.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from ...domain.entities import StatusEvent, Ticket
from ...use_cases.interfaces import IStatusEventRepository, ITicketRepository

logger = logging.getLogger(__name__)


def _row_to_ticket(row: asyncpg.Record) -> Ticket:
    def _dt(v: Any) -> datetime | None:
        if v is None:
            return None
        return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))

    keys = row.keys()

    def _col(name: str, default=None):
        return row[name] if name in keys else default

    return Ticket(
        ticket_id=row["ticket_id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        status=row["status"],
        category=row["category"],
        assigned_agent_id=row["assigned_agent_id"],
        tags=list(row["tags"] or []),
        summary=row["summary"],
        resolution=row["resolution"],
        sentiment=row["sentiment"],
        rating=_col("rating"),
        sla_deadline=_dt(row["sla_deadline"]),
        created_at=_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_dt(row["updated_at"]) or datetime.now(timezone.utc),
        resolved_at=_dt(row["resolved_at"]),
        report_resolution_type=_col("report_resolution_type"),
        report_sentiment_start=_col("report_sentiment_start"),
        report_key_issues=list(_col("report_key_issues") or []),
        report_ai_quality=_col("report_ai_quality"),
    )


class PGTicketRepository(ITicketRepository):
    """PostgreSQL-backed ticket store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── ITicketRepository ─────────────────────────────────────────────────────

    async def create(self, ticket: Ticket) -> Ticket:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tickets (
                    ticket_id, session_id, user_id, status,
                    category, assigned_agent_id, tags,
                    summary, resolution, sentiment, rating,
                    report_resolution_type, report_sentiment_start,
                    report_key_issues, report_ai_quality,
                    sla_deadline, resolved_at, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7,
                    $8, $9, $10, $11,
                    $12, $13, $14, $15,
                    $16, $17, $18, NOW()
                )
                ON CONFLICT (ticket_id) DO NOTHING
                """,
                ticket.ticket_id, ticket.session_id, ticket.user_id, ticket.status,
                ticket.category, ticket.assigned_agent_id, ticket.tags,
                ticket.summary, ticket.resolution, ticket.sentiment, ticket.rating,
                ticket.report_resolution_type, ticket.report_sentiment_start,
                ticket.report_key_issues or [], ticket.report_ai_quality,
                ticket.sla_deadline, ticket.resolved_at, ticket.created_at,
            )
        return ticket

    async def update(self, ticket: Ticket) -> Ticket:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tickets SET
                    status                  = $2,
                    category                = $3,
                    assigned_agent_id       = $4,
                    tags                    = $5,
                    summary                 = $6,
                    resolution              = $7,
                    sentiment               = $8,
                    rating                  = $9,
                    report_resolution_type  = $10,
                    report_sentiment_start  = $11,
                    report_key_issues       = $12,
                    report_ai_quality       = $13,
                    sla_deadline            = $14,
                    resolved_at             = $15,
                    updated_at              = NOW()
                WHERE ticket_id = $1
                """,
                ticket.ticket_id,
                ticket.status, ticket.category, ticket.assigned_agent_id,
                ticket.tags, ticket.summary, ticket.resolution,
                ticket.sentiment, ticket.rating,
                ticket.report_resolution_type, ticket.report_sentiment_start,
                ticket.report_key_issues or [], ticket.report_ai_quality,
                ticket.sla_deadline, ticket.resolved_at,
            )
        return ticket

    async def get(self, ticket_id: str) -> Ticket | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1", ticket_id
            )
        return _row_to_ticket(row) if row else None

    async def get_by_session(self, session_id: str) -> Ticket | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tickets WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
                session_id,
            )
        return _row_to_ticket(row) if row else None

    async def list_open(self) -> list[Ticket]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tickets
                WHERE status IN ('open', 'in_progress', 'pending_reply')
                ORDER BY created_at ASC
                """
            )
        return [_row_to_ticket(r) for r in rows]

    async def list_all(
        self,
        status: str | None = None,
        date_from: str | None = None,
        limit: int = 50,
    ) -> list[Ticket]:
        """Extended query for the history API (Phase 6+)."""
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if status:
            conditions.append(f"status = ${idx}")
            args.append(status)
            idx += 1
        if date_from:
            conditions.append(f"created_at >= ${idx}")
            args.append(date_from)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        args.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM tickets {where} ORDER BY created_at DESC LIMIT ${idx}",
                *args,
            )
        return [_row_to_ticket(r) for r in rows]


# ── Status events (write + read) ──────────────────────────────────────────────

class StatusEventRepository(IStatusEventRepository):
    """Append-only audit log for session/ticket status transitions."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, event: StatusEvent) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO status_events
                    (event_id, session_id, ticket_id, from_status, to_status, actor, note, occurred_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.event_id,
                event.session_id,
                event.ticket_id,
                event.from_status,
                event.to_status,
                event.actor,
                event.note,
                event.occurred_at,
            )

    async def list_for_session(self, session_id: str) -> list[StatusEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM status_events
                WHERE session_id = $1
                ORDER BY occurred_at ASC
                """,
                session_id,
            )
        return [
            StatusEvent(
                event_id=r["event_id"],
                session_id=r["session_id"],
                ticket_id=r["ticket_id"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                actor=r["actor"],
                note=r["note"],
                occurred_at=r["occurred_at"],
            )
            for r in rows
        ]
