"""BusinessProfileService — loads and caches BusinessProfile configuration.

The profile is loaded once at application startup via ``load()``.  Because
``BusinessProfile`` is a frozen dataclass, it is safe to share across
async coroutines without any additional locking.

Hot-reload notes:
  Changing the graph topology (which nodes are registered) requires a full
  service restart because LangGraph graphs are compiled to a static structure
  at startup.  Prompt and business-rule changes (stored in separate tables)
  take effect immediately via their own TTL caches — no restart needed.

  If a profile's *content* (keywords, thresholds, contact info) needs to
  change without restarting, call ``invalidate(business_id)`` followed by
  ``load(business_id)`` and re-inject the new profile into the graph
  configurable.  Graph topology changes always require a restart.
"""
from __future__ import annotations

import logging

from ..domain.entities import BusinessProfile
from ..use_cases.interfaces import IBusinessProfileRepository

logger = logging.getLogger(__name__)


class BusinessProfileService:
    """Thin service wrapper around IBusinessProfileRepository with memory cache."""

    def __init__(self, repo: IBusinessProfileRepository) -> None:
        self._repo = repo
        self._cache: dict[str, BusinessProfile] = {}

    async def load(self, business_id: str) -> BusinessProfile:
        """Return the BusinessProfile, loading from DB on first call per id."""
        if business_id not in self._cache:
            profile = await self._repo.get(business_id)
            self._cache[business_id] = profile
            logger.info(
                "BusinessProfile loaded: id=%r name=%r intents=%d",
                profile.business_id,
                profile.business_name,
                len(profile.intents),
            )
        return self._cache[business_id]

    def invalidate(self, business_id: str) -> None:
        """Evict cached profile so the next ``load()`` re-fetches from DB."""
        self._cache.pop(business_id, None)
        logger.info("BusinessProfile cache invalidated: id=%r", business_id)

    def get_cached(self, business_id: str) -> BusinessProfile | None:
        """Return cached profile without hitting the DB, or None if not loaded."""
        return self._cache.get(business_id)
