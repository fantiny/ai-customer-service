"""Authentication providers for external data sources.

All providers expose the same interface: get_auth_headers() → dict.
The authenticated HTTP client calls this before every request,
so token-refresh logic (OAuth2) is fully transparent to callers.
"""
from __future__ import annotations

import asyncio
import base64
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx


class IAuthProvider(ABC):
    """Contract: return ready-to-use HTTP headers that carry credentials."""

    @abstractmethod
    async def get_auth_headers(self) -> dict[str, str]:
        """Return header dict to inject into every outgoing request."""

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description (for logs / health checks)."""


# ── No-auth ──────────────────────────────────────────────────────────────────

class NoAuthProvider(IAuthProvider):
    """Used for internal data sources that need no HTTP authentication."""

    async def get_auth_headers(self) -> dict[str, str]:
        return {}

    def describe(self) -> str:
        return "none"


# ── API-Key ───────────────────────────────────────────────────────────────────

class ApiKeyAuthProvider(IAuthProvider):
    """Sends a static API key in a request header (default: X-API-Key).

    Some providers use X-Auth-Token, Authorization: ApiKey xxx, etc.
    Configure `header_name` accordingly.
    """

    def __init__(self, api_key: str, header_name: str = "X-API-Key") -> None:
        if not api_key:
            raise ValueError("ApiKeyAuthProvider: api_key must not be empty")
        self._api_key = api_key
        self._header_name = header_name

    async def get_auth_headers(self) -> dict[str, str]:
        return {self._header_name: self._api_key}

    def describe(self) -> str:
        return f"api_key(header={self._header_name})"


# ── Bearer Token ──────────────────────────────────────────────────────────────

class BearerTokenAuthProvider(IAuthProvider):
    """Sends a static Bearer token in the Authorization header.

    Suitable for long-lived personal access tokens (GitHub PAT, Shopify private
    app token, etc.).  Use OAuth2 provider for tokens that expire.
    """

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenAuthProvider: token must not be empty")
        self._token = token

    async def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def describe(self) -> str:
        return "bearer_token"


# ── Basic Auth ────────────────────────────────────────────────────────────────

class BasicAuthProvider(IAuthProvider):
    """HTTP Basic Authentication (RFC 7617).

    Encodes `username:password` in base64 and sends it in the
    Authorization header.  Suitable for legacy APIs and internal services.
    """

    def __init__(self, username: str, password: str) -> None:
        if not username:
            raise ValueError("BasicAuthProvider: username must not be empty")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._header_value = f"Basic {encoded}"

    async def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": self._header_value}

    def describe(self) -> str:
        return "basic_auth"


# ── OAuth2 Client Credentials ─────────────────────────────────────────────────

class OAuth2ClientCredentialsProvider(IAuthProvider):
    """OAuth 2.0 Client Credentials flow (RFC 6749 §4.4).

    - Fetches a token from `token_url` using client_id + client_secret.
    - Caches the token and automatically refreshes it 60 s before expiry.
    - Thread-safe: uses asyncio.Lock so concurrent requests don't trigger
      simultaneous refresh.

    Suitable for machine-to-machine APIs: Shopify Admin, WooCommerce REST,
    NetSuite SuiteQL, Salesforce Connected App, etc.
    """

    _EXPIRY_BUFFER = 60  # refresh this many seconds before actual expiry

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        if not token_url or not client_id or not client_secret:
            raise ValueError(
                "OAuth2ClientCredentialsProvider: token_url, client_id, "
                "and client_secret are all required"
            )
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._extra_params = extra_params or {}
        self._access_token: str = ""
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_auth_headers(self) -> dict[str, str]:
        token = await self._get_valid_token()
        return {"Authorization": f"Bearer {token}"}

    async def _get_valid_token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        async with self._lock:
            # Double-check after acquiring lock
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            await self._refresh_token()
        return self._access_token

    async def _refresh_token(self) -> None:
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            data["scope"] = self._scope
        data.update(self._extra_params)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self._token_url, data=data)
            resp.raise_for_status()
            body = resp.json()

        self._access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        self._expires_at = time.monotonic() + expires_in - self._EXPIRY_BUFFER

    def describe(self) -> str:
        return f"oauth2_client_credentials(url={self._token_url}, scope={self._scope!r})"


# ── Factory helper ────────────────────────────────────────────────────────────

def build_auth_provider(
    auth_type: str,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
    bearer_token: str = "",
    oauth2_token_url: str = "",
    oauth2_client_id: str = "",
    oauth2_client_secret: str = "",
    oauth2_scope: str = "",
    basic_username: str = "",
    basic_password: str = "",
) -> IAuthProvider:
    """Construct the right IAuthProvider from flat config values.

    auth_type: "none" | "api_key" | "bearer" | "oauth2" | "basic"
    """
    match auth_type.lower():
        case "none" | "":
            return NoAuthProvider()
        case "api_key":
            return ApiKeyAuthProvider(api_key=api_key, header_name=api_key_header)
        case "bearer":
            return BearerTokenAuthProvider(token=bearer_token)
        case "oauth2":
            return OAuth2ClientCredentialsProvider(
                token_url=oauth2_token_url,
                client_id=oauth2_client_id,
                client_secret=oauth2_client_secret,
                scope=oauth2_scope,
            )
        case "basic":
            return BasicAuthProvider(username=basic_username, password=basic_password)
        case _:
            raise ValueError(
                f"Unknown auth_type {auth_type!r}. "
                "Valid options: none, api_key, bearer, oauth2, basic"
            )
