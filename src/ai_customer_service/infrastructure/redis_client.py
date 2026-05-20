from __future__ import annotations

import redis.asyncio as aioredis

from .config import Settings


async def create_redis_pool(settings: Settings) -> aioredis.Redis:
    client: aioredis.Redis = await aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=False,  # langgraph-checkpoint-redis expects bytes
        max_connections=20,
    )
    return client
