"""DigestRepository — PostgreSQL implementation of IDigestRepository.

Encapsulates all raw SQL for the daily digest feature so that DigestService
(use-case layer) stays free of asyncpg and is testable with mocks.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import asyncpg

from ...use_cases.interfaces import IDigestRepository


class DigestRepository(IDigestRepository):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── IDigestRepository ─────────────────────────────────────────────────────

    async def fetch_ticket_rows(
        self, day_start: datetime, day_end: datetime
    ) -> list[dict[str, Any]]:
        """Return raw ticket columns needed for KPI computation."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT status, assigned_agent_id, rating,
                       report_resolution_type, report_sentiment_start,
                       report_ai_quality, report_key_issues,
                       created_at, resolved_at
                FROM tickets
                WHERE created_at >= $1 AND created_at < $2
                """,
                day_start, day_end,
            )
        return [dict(r) for r in rows]

    async def count_messages(self, day_start: datetime, day_end: datetime) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM session_messages WHERE created_at >= $1 AND created_at < $2",
                day_start, day_end,
            ) or 0

    async def count_open_tickets(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM tickets WHERE status IN ('open','in_progress','pending_reply')"
            ) or 0

    async def save(
        self,
        digest_id: str,
        report_date: date,
        metrics_json: str,
        summary_md: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_digests (digest_id, report_date, metrics, summary_md)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (report_date) DO UPDATE
                    SET metrics    = EXCLUDED.metrics,
                        summary_md = EXCLUDED.summary_md,
                        created_at = NOW()
                """,
                digest_id, report_date, metrics_json, summary_md,
            )

    async def get(self, report_date: date) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metrics, summary_md, created_at FROM daily_digests WHERE report_date = $1",
                report_date,
            )
        if not row:
            return None
        return {
            "metrics": json.loads(row["metrics"]),
            "summary_md": row["summary_md"],
            "generated_at": row["created_at"].isoformat(),
        }

    async def list_recent(self, limit: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT digest_id, report_date, summary_md, created_at
                FROM daily_digests
                ORDER BY report_date DESC
                LIMIT $1
                """,
                limit,
            )
        return [
            {
                "digest_id": r["digest_id"],
                "report_date": r["report_date"].isoformat(),
                "summary_md": r["summary_md"],
                "generated_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
