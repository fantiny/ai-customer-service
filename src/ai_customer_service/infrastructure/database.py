from __future__ import annotations

import json

import asyncpg

from .config import Settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so asyncpg returns dicts instead of strings."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def create_db_pool(settings: Settings) -> asyncpg.Pool:
    # asyncpg expects a standard postgresql:// URL, not postgresql+asyncpg://
    url = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")
    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=url,
        min_size=2,
        max_size=settings.POSTGRES_POOL_SIZE,
        command_timeout=30,
        init=_init_connection,
    )
    return pool
