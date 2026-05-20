from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from ..infrastructure.auth import AuthError, AuthUser, resolve_identity
from ..infrastructure.config import get_settings
from ..infrastructure.container import Container
from ..use_cases.chat_service import ChatService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_chat_service(request: Request) -> ChatService:
    return get_container(request).chat_service


async def get_current_user(
    authorization: str | None = Header(None, description="Bearer JWT token"),
) -> AuthUser:
    """FastAPI dependency — extract and verify the caller's identity.

    Accepts:  Authorization: Bearer <jwt>

    • JWT configured + valid token  → returns AuthUser with real identity.
    • JWT configured + invalid/expired → raises HTTP 401.
    • JWT not configured (open mode)  → returns guest AuthUser (no token needed).
    • JWT_REQUIRED=True + no token   → raises HTTP 401.
    """
    settings = get_settings()
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip() or None

    try:
        return resolve_identity(token, settings=settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def require_user(
    user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Like get_current_user but always rejects guests (is_guest=True)."""
    if user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_id(
    user: AuthUser = Depends(get_current_user),
) -> str:
    """Backward-compatible: return just the user_id string."""
    return user.user_id
