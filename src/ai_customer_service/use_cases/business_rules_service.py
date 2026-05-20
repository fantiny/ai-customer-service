from __future__ import annotations

import logging
from typing import Any

from ..adapters.repositories.business_rules_repository import BusinessRulesRepository
from .interfaces import IBusinessRulesService

_logger = logging.getLogger(__name__)


class BusinessRulesService(IBusinessRulesService):
    """Thin use-case wrapper around the business_rules key-value store."""

    def __init__(self, repo: BusinessRulesRepository) -> None:
        self._repo = repo

    async def get(self, key: str, default: Any = None) -> Any:
        try:
            result = await self._repo.get(key)
            return result if result is not None else default
        except Exception:
            _logger.warning("business_rules lookup failed for key %r — returning default", key, exc_info=True)
            return default

    async def get_language(self) -> str:
        lang = await self.get("default_language")
        return str(lang) if lang else "zh"
