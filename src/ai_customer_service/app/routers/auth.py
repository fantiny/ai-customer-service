"""Authentication endpoints.

POST /api/auth/token   — Issue a signed HS256 JWT (dev/testing only).
GET  /api/auth/me      — Return the caller's identity from their Bearer token.
GET  /api/auth/jwks    — (optional) Serve this service's public JWKS if RS256 is used.

In production, tokens should be issued by your IdP (Auth0, Keycloak, Authing,
Casdoor, etc.).  This endpoint is intentionally simple and is only useful when
JWT_SECRET is configured (HS256 mode).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...infrastructure.auth import AuthUser, create_token
from ...infrastructure.config import get_settings
from ..dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    """Body for the dev token endpoint."""
    user_id: str = Field(..., description="Subject / user identifier (maps to JWT 'sub')")
    name: str = Field("", description="Display name (maps to JWT 'name')")
    email: str = Field("", description="Email (maps to JWT 'email')")
    expires_in: int = Field(86400, ge=60, le=2592000, description="Token lifetime in seconds (default: 24h)")
    extra_claims: dict = Field(default_factory=dict, description="Additional claims to embed")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Issue a test JWT (HS256, requires JWT_SECRET)",
    description=(
        "Issues a signed HS256 JWT for development and testing. "
        "**Only available when JWT_SECRET is configured.** "
        "In production, use your IdP (Auth0, Keycloak, Authing, etc.) to issue tokens."
    ),
)
async def issue_token(body: TokenRequest) -> JSONResponse:
    settings = get_settings()
    if not settings.JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Token issuance is not available: JWT_SECRET is not configured. "
                "Set JWT_SECRET in your .env to enable HS256 token minting, "
                "or use an external IdP (Auth0, Keycloak, Authing…) to issue tokens."
            ),
        )
    token = create_token(
        user_id=body.user_id,
        name=body.name,
        email=body.email,
        expires_in=body.expires_in,
        extra_claims=body.extra_claims,
        settings=settings,
    )
    return JSONResponse(content={
        "access_token": token,
        "token_type": "bearer",
        "expires_in": body.expires_in,
        "user_id": body.user_id,
    })


@router.get(
    "/me",
    summary="Return the caller's verified identity",
    description="Validates the Bearer token and returns the extracted claims.",
)
async def get_me(user: AuthUser = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse(content={
        "user_id":    user.user_id,
        "name":       user.name,
        "email":      user.email,
        "is_guest":   user.is_guest,
        "claims":     user.raw_claims,
    })
