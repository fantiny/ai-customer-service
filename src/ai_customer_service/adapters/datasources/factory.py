"""DataSourceFactory — builds the right data source implementation from config.

All wiring decisions (internal DB vs external API, which auth type to use)
live here. The rest of the application only sees the abstract interfaces.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import asyncpg

from ...use_cases.interfaces import IOrderRepository
from ..repositories.order_repository import OrderRepository
from .auth.providers import IAuthProvider, build_auth_provider
from .documents.syncer import DocumentSyncer
from .orders.rest_api import RESTAPIOrderRepository

logger = logging.getLogger(__name__)

AuthType = Literal["none", "api_key", "bearer", "oauth2", "basic"]
SourceType = Literal["internal_db", "rest_api"]


@dataclass
class DataSourceConfig:
    """Fully resolved configuration for one external data source.

    Construct via :py:meth:`DataSourceConfig.from_settings_prefix` or
    by passing values directly in tests.
    """

    source_type: SourceType = "internal_db"
    base_url: str = ""
    auth_type: AuthType = "none"

    # API key
    api_key: str = ""
    api_key_header: str = "X-API-Key"

    # Bearer
    bearer_token: str = ""

    # OAuth2 client credentials
    oauth2_token_url: str = ""
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_scope: str = ""

    # Basic
    basic_username: str = ""
    basic_password: str = ""

    # HTTP timeout in seconds
    timeout: float = 30.0

    @classmethod
    def from_settings_prefix(cls, settings: object, prefix: str) -> "DataSourceConfig":
        """Build a DataSourceConfig by reading attributes named {PREFIX}_FIELD
        from a Settings object.

        Example: prefix="ORDER" → reads ORDER_SOURCE_TYPE, ORDER_SOURCE_URL, …

        This avoids tight coupling between DataSourceConfig and
        infrastructure.config.Settings — tests can pass any object with the
        right attributes.
        """

        def get(suffix: str, default: object = "") -> object:
            attr = f"{prefix}_SOURCE_{suffix}"
            return getattr(settings, attr, default)

        return cls(
            source_type=get("TYPE", "internal_db"),          # type: ignore[arg-type]
            base_url=get("URL", ""),                          # type: ignore[arg-type]
            auth_type=get("AUTH", "none"),                    # type: ignore[arg-type]
            api_key=get("API_KEY", ""),                       # type: ignore[arg-type]
            api_key_header=get("API_KEY_HEADER", "X-API-Key"),# type: ignore[arg-type]
            bearer_token=get("BEARER_TOKEN", ""),             # type: ignore[arg-type]
            oauth2_token_url=get("OAUTH2_TOKEN_URL", ""),     # type: ignore[arg-type]
            oauth2_client_id=get("OAUTH2_CLIENT_ID", ""),     # type: ignore[arg-type]
            oauth2_client_secret=get("OAUTH2_CLIENT_SECRET", ""),  # type: ignore[arg-type]
            oauth2_scope=get("OAUTH2_SCOPE", ""),             # type: ignore[arg-type]
            basic_username=get("BASIC_USER", ""),             # type: ignore[arg-type]
            basic_password=get("BASIC_PASS", ""),             # type: ignore[arg-type]
            timeout=float(get("TIMEOUT", 30.0)),              # type: ignore[arg-type]
        )

    def build_auth_provider(self) -> IAuthProvider:
        return build_auth_provider(
            auth_type=self.auth_type,
            api_key=self.api_key,
            api_key_header=self.api_key_header,
            bearer_token=self.bearer_token,
            oauth2_token_url=self.oauth2_token_url,
            oauth2_client_id=self.oauth2_client_id,
            oauth2_client_secret=self.oauth2_client_secret,
            oauth2_scope=self.oauth2_scope,
            basic_username=self.basic_username,
            basic_password=self.basic_password,
        )


class DataSourceFactory:
    """Single point of truth for constructing data source adapters.

    Usage in Container::

        order_repo = DataSourceFactory.build_order_repo(order_cfg, db_pool)
        product_syncer = DataSourceFactory.build_document_syncer(
            product_cfg, db_pool, category="product_catalog"
        )
    """

    @staticmethod
    def build_order_repo(
        config: DataSourceConfig,
        db_pool: asyncpg.Pool,
    ) -> IOrderRepository:
        if config.source_type == "internal_db":
            logger.info("OrderRepository: using internal PostgreSQL")
            return OrderRepository(db_pool)

        if not config.base_url:
            raise ValueError(
                "ORDER_SOURCE_URL must be set when ORDER_SOURCE_TYPE=rest_api"
            )
        auth = config.build_auth_provider()
        logger.info(
            "OrderRepository: using external REST API (%s, auth=%s)",
            config.base_url,
            auth.describe(),
        )
        return RESTAPIOrderRepository(
            base_url=config.base_url,
            auth_provider=auth,
            timeout=config.timeout,
        )

    @staticmethod
    def build_document_syncer(
        config: DataSourceConfig,
        db_pool: asyncpg.Pool,
        category: str,
    ) -> DocumentSyncer | None:
        """Return a DocumentSyncer if source_type == 'rest_api', else None.

        When None is returned the container skips the sync step and uses
        whatever documents are already in the local faq_documents table.
        """
        if config.source_type == "internal_db":
            return None

        if not config.base_url:
            raise ValueError(
                f"{category.upper()}_SOURCE_URL must be set when "
                f"{category.upper()}_SOURCE_TYPE=rest_api"
            )
        auth = config.build_auth_provider()
        return DocumentSyncer(
            base_url=config.base_url,
            auth_provider=auth,
            db_pool=db_pool,
            category=category,
            timeout=config.timeout,
        )
