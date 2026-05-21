from __future__ import annotations

import json
import re

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


def _extract_ssl(url: str) -> tuple[str, str | None]:
    """Extract sslmode from URL and return (cleaned_url, ssl_value).

    asyncpg uses the ssl= kwarg rather than a URL query parameter.
    We also auto-enable ssl='require' for hosted providers (Supabase, RDS, etc.)
    so callers don't need to remember the extra parameter.
    """
    ssl_value: str | None = None

    # Parse explicit sslmode= from query string
    match = re.search(r'[?&]sslmode=([^&]+)', url)
    if match:
        sslmode = match.group(1)
        # Remove sslmode param from URL
        url = re.sub(r'[?&]sslmode=[^&]*', '', url)
        url = re.sub(r'\?$', '', url)  # clean trailing ?
        if sslmode in ('require', 'verify-ca', 'verify-full'):
            ssl_value = 'require'
        elif sslmode == 'disable':
            ssl_value = None
        else:
            ssl_value = sslmode
    else:
        # Auto-detect cloud providers that require SSL
        cloud_patterns = ('supabase.co', 'amazonaws.com', 'rds.', 'neon.tech', 'railway.app')
        if any(p in url for p in cloud_patterns):
            ssl_value = 'require'

    return url, ssl_value


async def create_db_pool(settings: Settings) -> asyncpg.Pool:
    # asyncpg expects a standard postgresql:// URL, not postgresql+asyncpg://
    url = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")

    # Extract SSL mode from URL or auto-detect for cloud providers
    url, ssl_value = _extract_ssl(url)

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=url,
        ssl=ssl_value,  # type: ignore[arg-type]
        min_size=2,
        max_size=settings.POSTGRES_POOL_SIZE,
        command_timeout=30,
        init=_init_connection,
    )
    return pool
