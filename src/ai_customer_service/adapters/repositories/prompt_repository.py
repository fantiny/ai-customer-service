"""PromptRepository — versioned prompt store with 5-minute TTL cache.

Active prompts are cached per node_name. Calling publish_prompt() rotates
versions (old → inactive, new → active) and clears the cache entry so the
next request picks up the new content immediately.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_CACHE_TTL = 300.0  # 5 minutes


class PromptRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._cache: dict[str, tuple[str | None, float]] = {}  # node_name → (content, expire_at)

    async def get_active_prompt(self, node_name: str) -> str | None:
        """Return the active prompt content for a node, or None if none published."""
        now = time.monotonic()
        if node_name in self._cache:
            content, expire = self._cache[node_name]
            if now < expire:
                return content

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM node_prompts WHERE node_name = $1 AND active = true",
                node_name,
            )
        content = row["content"] if row else None
        self._cache[node_name] = (content, now + _CACHE_TTL)
        return content

    async def publish_prompt(self, node_name: str, content: str) -> tuple[str, int]:
        """Publish a new prompt version, deactivating the previous one. Returns (prompt_id, version)."""
        prompt_id = f"pmt-{uuid.uuid4().hex[:10]}"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE node_prompts SET active = false WHERE node_name = $1 AND active = true",
                    node_name,
                )
                row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM node_prompts WHERE node_name = $1",
                    node_name,
                )
                next_ver = row["next_ver"]
                await conn.execute(
                    """
                    INSERT INTO node_prompts (prompt_id, node_name, version, content, active)
                    VALUES ($1, $2, $3, $4, true)
                    """,
                    prompt_id, node_name, next_ver, content,
                )
        self._cache.pop(node_name, None)
        logger.info("Published prompt for node=%s version=%d id=%s", node_name, next_ver, prompt_id)
        return prompt_id, next_ver

    async def get_history(self, node_name: str) -> list[dict]:
        """Return all prompt versions for a node, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT prompt_id, node_name, version, active, created_at, content
                FROM node_prompts WHERE node_name = $1 ORDER BY version DESC
                """,
                node_name,
            )
        return [
            {
                "prompt_id": r["prompt_id"],
                "node_name": r["node_name"],
                "version": r["version"],
                "active": r["active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "content": r["content"] or "",
            }
            for r in rows
        ]

    async def activate_version(self, node_name: str, prompt_id: str) -> tuple[str, int]:
        """Re-activate an old prompt version by publishing its content as a new version."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM node_prompts WHERE node_name = $1 AND prompt_id = $2",
                node_name, prompt_id,
            )
        if not row:
            raise ValueError(f"prompt_id={prompt_id} not found for node={node_name}")
        return await self.publish_prompt(node_name, row["content"])

    async def list_nodes(self) -> list[dict]:
        """Return all nodes that have at least one prompt, with active version info."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT node_name,
                       MAX(version) FILTER (WHERE active) AS active_version,
                       LEFT(MAX(content) FILTER (WHERE active), 120) AS preview
                FROM node_prompts
                GROUP BY node_name
                ORDER BY node_name
                """
            )
        return [
            {
                "node_name": r["node_name"],
                "version": r["active_version"] or 0,
                "preview": r["preview"] or "",
            }
            for r in rows
        ]
