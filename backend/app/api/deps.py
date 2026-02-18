"""
FastAPI dependency injection.

Provides reusable dependencies for:
  - Database handle (get_db)
  - Current authenticated user (get_current_user)
  - Role-based guards  (require_admin)
"""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.mongodb import get_db
from app.security.jwt import TokenVerificationError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> dict:
    """
    Extract and verify the JWT access token from the Authorization header.

    Returns a dict with keys: user_id, email, role.
    Raises HTTP 401 on missing/invalid/expired token.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return {
        "user_id": payload.sub,
        "email":   payload.email,
        "role":    payload.role,
    }


async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Guard: only admin role may proceed."""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


def get_refresh_token_from_cookie(
    refresh_token: str | None = Cookie(None),
) -> str:
    """Extract the refresh token from the HttpOnly cookie."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie is missing.",
        )
    return refresh_token
