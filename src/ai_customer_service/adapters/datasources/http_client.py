"""Authenticated async HTTP client shared by all external data sources.

Wraps httpx.AsyncClient with:
- Automatic auth header injection via IAuthProvider
- Configurable base URL
- Consistent error handling
- Optional request/response logging
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .auth.providers import IAuthProvider

logger = logging.getLogger(__name__)


class AuthedHTTPClient:
    """Thin async HTTP wrapper that injects auth before each request.

    Usage::

        async with AuthedHTTPClient(base_url, auth_provider) as client:
            data = await client.get("/orders/123")
    """

    def __init__(
        self,
        base_url: str,
        auth_provider: IAuthProvider,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_provider = auth_provider
        self._timeout = timeout
        self._default_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(default_headers or {}),
        }

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, json: Any = None) -> Any:
        return await self._request("PATCH", path, json=json)

    async def put(self, path: str, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        auth_headers = await self._auth_provider.get_auth_headers()
        headers = {**self._default_headers, **auth_headers}
        url = f"{self._base_url}/{path.lstrip('/')}"

        logger.debug("%s %s (auth=%s)", method, url, self._auth_provider.describe())

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                method, url, headers=headers, params=params, json=json
            )

        if response.status_code == 401:
            raise PermissionError(
                f"Authentication failed for {url} "
                f"(auth={self._auth_provider.describe()}). "
                "Check credentials in configuration."
            )
        if response.status_code == 403:
            raise PermissionError(
                f"Forbidden: insufficient permissions to access {url}."
            )
        if response.status_code == 404:
            return None  # caller handles "not found" semantics
        if response.status_code == 429:
            raise RuntimeError(
                f"Rate-limited by external API at {url}. "
                "Consider reducing request frequency."
            )

        response.raise_for_status()

        if not response.content:
            return None
        return response.json()
