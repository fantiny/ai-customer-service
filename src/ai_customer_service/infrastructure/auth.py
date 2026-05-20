"""JWT authentication — industry-standard Bearer token verification.

Supports three modes:
  1. Open / guest mode  — JWT_SECRET and JWT_JWKS_URL are both empty.
                          Any connection is accepted; user_id comes from the
                          client-supplied payload (development / testing).
  2. HS256 symmetric    — JWT_SECRET is set.  Tokens are minted and verified
                          with a shared secret.  Good for self-hosted setups.
  3. RS256 / ES256 JWKS — JWT_JWKS_URL points to a JWKS endpoint.  Tokens are
                          issued by a third-party IdP (Auth0, Keycloak, Cognito,
                          Authing, Casdoor …) and verified with the IdP's public
                          key fetched from the JWKS endpoint.

Standard JWT claims used:
  sub   — user ID (required)
  name  — display name (optional)
  email — email (optional)
  iat   — issued-at (standard)
  exp   — expiration (enforced when present)
  iss   — issuer (verified when JWT_ISSUER is configured)
  aud   — audience (verified when JWT_AUDIENCE is configured)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

# JWKS key cache — refreshed at most once per hour
_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600  # seconds


@dataclass
class AuthUser:
    """Identity extracted from a verified JWT (or created for guest sessions)."""
    user_id: str
    name: str = ""
    email: str = ""
    is_guest: bool = False
    raw_claims: dict = field(default_factory=dict)


class AuthError(Exception):
    """Raised when a token is missing (and required) or fails verification."""
    def __init__(self, message: str, code: str = "invalid_token") -> None:
        super().__init__(message)
        self.code = code


# ── Public API ────────────────────────────────────────────────────────────────

def verify_token(token: str, settings: Settings | None = None) -> AuthUser:
    """Verify *token* and return an :class:`AuthUser`.

    Raises :class:`AuthError` if the token is invalid or expired.
    Never returns a guest user — call ``resolve_identity`` for that.
    """
    s = settings or get_settings()
    if s.JWT_JWKS_URL:
        claims = _verify_rs256(token, s)
    elif s.JWT_SECRET:
        claims = _verify_hs256(token, s)
    else:
        # No auth configured — treat any non-empty string as opaque user_id
        claims = {"sub": token}

    user_id = claims.get("sub") or ""
    if not user_id:
        raise AuthError("JWT missing 'sub' claim", code="missing_sub")

    return AuthUser(
        user_id=user_id,
        name=claims.get("name") or claims.get("preferred_username") or "",
        email=claims.get("email") or "",
        is_guest=False,
        raw_claims=claims,
    )


def resolve_identity(
    token: str | None,
    guest_id: str | None = None,
    settings: Settings | None = None,
) -> AuthUser:
    """Best-effort identity resolution.

    • token present  → verify; raise AuthError on failure.
    • token absent + JWT_REQUIRED=True → raise AuthError.
    • token absent + JWT_REQUIRED=False → return guest AuthUser.
    """
    s = settings or get_settings()

    if token:
        return verify_token(token, s)

    if s.JWT_REQUIRED:
        raise AuthError("Authentication required", code="unauthenticated")

    gid = guest_id or f"guest-anon"
    return AuthUser(user_id=gid, name="访客", is_guest=True)


def create_token(
    user_id: str,
    name: str = "",
    email: str = "",
    expires_in: int = 86400,
    extra_claims: dict | None = None,
    settings: Settings | None = None,
) -> str:
    """Mint a signed HS256 JWT.  Only works when JWT_SECRET is configured.

    Primarily used by the development token generator and test helpers.
    In production, tokens are issued by your IdP — not by this service.
    """
    s = settings or get_settings()
    if not s.JWT_SECRET:
        raise RuntimeError("JWT_SECRET must be set to mint tokens")

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub":   user_id,
        "iat":   now,
        "exp":   now + expires_in,
        **({"iss": s.JWT_ISSUER}   if s.JWT_ISSUER   else {}),
        **({"aud": s.JWT_AUDIENCE} if s.JWT_AUDIENCE else {}),
        **({"name": name}  if name  else {}),
        **({"email": email} if email else {}),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, s.JWT_SECRET, algorithm="HS256")


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_auth_user(
    authorization: str | None = None,
    settings: Settings | None = None,
) -> AuthUser | None:
    """FastAPI dependency that extracts the caller's identity from the
    ``Authorization: Bearer <token>`` header.

    Returns ``None`` when no token is present and JWT is not required.
    Raises ``HTTPException(401)`` when the token is present but invalid,
    or when JWT_REQUIRED=True and no token is present.
    """
    from fastapi import HTTPException

    s = settings or get_settings()
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    try:
        return resolve_identity(token, settings=s)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ── Internal helpers ──────────────────────────────────────────────────────────

def _verify_hs256(token: str, s: Settings) -> dict:
    opts: dict[str, Any] = {"verify_exp": True}
    kwargs: dict[str, Any] = {"algorithms": [s.JWT_ALGORITHM]}
    if s.JWT_ISSUER:
        kwargs["issuer"] = s.JWT_ISSUER
    if s.JWT_AUDIENCE:
        kwargs["audience"] = s.JWT_AUDIENCE
    try:
        return jwt.decode(token, s.JWT_SECRET, **kwargs, options=opts)
    except ExpiredSignatureError as exc:
        raise AuthError("Token has expired", code="token_expired") from exc
    except JWTClaimsError as exc:
        raise AuthError(f"Token claims invalid: {exc}", code="invalid_claims") from exc
    except JWTError as exc:
        raise AuthError(f"Token verification failed: {exc}", code="invalid_token") from exc


def _verify_rs256(token: str, s: Settings) -> dict:
    """Verify an RS256/ES256 token using keys fetched from the JWKS endpoint."""
    global _jwks_cache, _jwks_fetched_at

    # Refresh JWKS cache if stale
    if not _jwks_cache or (time.time() - _jwks_fetched_at) > _JWKS_TTL:
        _jwks_cache = _fetch_jwks(s.JWT_JWKS_URL)
        _jwks_fetched_at = time.time()

    kwargs: dict[str, Any] = {"algorithms": [s.JWT_ALGORITHM]}
    if s.JWT_ISSUER:
        kwargs["issuer"] = s.JWT_ISSUER
    if s.JWT_AUDIENCE:
        kwargs["audience"] = s.JWT_AUDIENCE
    try:
        return jwt.decode(token, _jwks_cache, **kwargs)
    except ExpiredSignatureError as exc:
        raise AuthError("Token has expired", code="token_expired") from exc
    except JWTClaimsError as exc:
        raise AuthError(f"Token claims invalid: {exc}", code="invalid_claims") from exc
    except JWTError as exc:
        # Key may have rotated — clear cache and retry once
        logger.warning("JWKS verify failed (%s), clearing cache and retrying", exc)
        _jwks_cache = _fetch_jwks(s.JWT_JWKS_URL)
        _jwks_fetched_at = time.time()
        try:
            return jwt.decode(token, _jwks_cache, **kwargs)
        except JWTError as exc2:
            raise AuthError(f"Token verification failed: {exc2}", code="invalid_token") from exc2


def _fetch_jwks(url: str) -> dict:
    import urllib.request
    import json as _json
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _json.loads(resp.read())
        logger.info("JWKS keys loaded from %s (%d keys)", url, len(data.get("keys", [])))
        return data
    except Exception as exc:
        raise AuthError(f"Failed to fetch JWKS from {url}: {exc}", code="jwks_error") from exc
