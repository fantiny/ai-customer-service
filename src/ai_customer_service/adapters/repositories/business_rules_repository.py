"""BusinessRulesRepository — key/value config store with TTL in-memory cache.

Rules are stored as JSONB in the `business_rules` table.  A 60-second TTL
cache prevents hot-path DB round-trips while still allowing near-instant
propagation after an API update.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_CACHE_TTL = 60.0  # seconds


class BusinessRulesRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._cache: dict[str, tuple[Any, float]] = {}  # key → (value, expire_at)

    async def get(self, key: str, default: Any = None) -> Any:
        """Return the rule value, using cache when still fresh."""
        now = time.monotonic()
        if key in self._cache:
            value, expire = self._cache[key]
            if now < expire:
                return value

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT rule_value FROM business_rules WHERE rule_key = $1", key
            )
        if row is None:
            return default

        raw = row["rule_value"]
        # JSONB codec decodes to Python objects; strings are already decoded.
        # If the codec is absent (direct connection), fall back to json.loads.
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                value = raw  # Store as-is (e.g. plain string values)
        else:
            value = raw
        self._cache[key] = (value, now + _CACHE_TTL)
        return value

    async def set(self, key: str, value: Any, description: str | None = None) -> None:
        """Upsert a rule value and invalidate the cache entry."""
        json_val = json.dumps(value)
        async with self._pool.acquire() as conn:
            # Read old value for audit log
            old_row = await conn.fetchrow(
                "SELECT rule_value FROM business_rules WHERE rule_key = $1", key
            )
            old_value = str(old_row["rule_value"]) if old_row else None

            await conn.execute(
                """
                INSERT INTO business_rules (rule_key, rule_value, description, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW())
                ON CONFLICT (rule_key) DO UPDATE
                    SET rule_value  = EXCLUDED.rule_value,
                        description = COALESCE(EXCLUDED.description, business_rules.description),
                        updated_at  = NOW()
                """,
                key, json_val, description,
            )
            await conn.execute(
                """
                INSERT INTO rule_audit_log (rule_key, operation, old_value, new_value)
                VALUES ($1, 'set', $2, $3)
                """,
                key, old_value, json_val,
            )
        self._cache.pop(key, None)
        logger.info("business_rule updated: %s = %s", key, value)

    async def delete(self, key: str) -> None:
        """Delete a rule and log the removal."""
        async with self._pool.acquire() as conn:
            old_row = await conn.fetchrow(
                "SELECT rule_value FROM business_rules WHERE rule_key = $1", key
            )
            old_value = str(old_row["rule_value"]) if old_row else None
            await conn.execute("DELETE FROM business_rules WHERE rule_key = $1", key)
            if old_row:
                await conn.execute(
                    """
                    INSERT INTO rule_audit_log (rule_key, operation, old_value, new_value)
                    VALUES ($1, 'delete', $2, NULL)
                    """,
                    key, old_value,
                )
        self._cache.pop(key, None)
        logger.info("business_rule deleted: %s", key)

    async def get_history(self, key: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent audit log entries for a rule key."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT log_id, operation, old_value, new_value, changed_at
                FROM rule_audit_log
                WHERE rule_key = $1
                ORDER BY changed_at DESC
                LIMIT $2
                """,
                key, limit,
            )
        return [
            {
                "log_id": r["log_id"],
                "operation": r["operation"],
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "changed_at": r["changed_at"].isoformat(),
            }
            for r in rows
        ]

    async def get_all(self) -> dict[str, Any]:
        """Return all rules as a dict (bypasses cache for admin reads)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT rule_key, rule_value, description FROM business_rules ORDER BY rule_key")
        result = {}
        for row in rows:
            raw = row["rule_value"]
            # JSONB codec may return already-decoded objects; guard against re-decoding.
            if isinstance(raw, str):
                try:
                    val = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    val = raw
            else:
                val = raw
            result[row["rule_key"]] = {
                "value": val,
                "description": row["description"],
            }
        return result
