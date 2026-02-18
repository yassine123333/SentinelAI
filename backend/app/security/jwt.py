"""
JWT token creation and verification.

Tokens
------
  Access token  — HS256, 1-hour TTL (per presentation spec)
                  Payload: sub (user_id), email, role, type="access"

  Refresh token — HS256, 7-day TTL
                  Payload: sub (user_id), jti (UUID), type="refresh"
                  jti is stored in MongoDB; absent jti = revoked token.

Security notes
--------------
  - Signature verified on every request (no unsigned JWT accepted)
  - Short access-token TTL mitigates replay risk
  - Refresh token jti stored server-side enables instant revocation
  - All timestamps use timezone-aware UTC datetimes
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config.settings import get_settings


# ── Token payload models ───────────────────────────────────────────────────────

class AccessTokenPayload(BaseModel):
    sub: str                    # user_id (MongoDB ObjectId as str)
    email: str
    role: str
    type: Literal["access"] = "access"
    iat: datetime
    exp: datetime


class RefreshTokenPayload(BaseModel):
    sub: str                    # user_id
    jti: str                    # unique token id — stored in MongoDB
    type: Literal["refresh"] = "refresh"
    iat: datetime
    exp: datetime


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str, role: str) -> str:
    """Return a signed HS256 access token valid for ACCESS_TOKEN_EXPIRE_MINUTES."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub":   user_id,
        "email": email,
        "role":  role,
        "type":  "access",
        "iat":   now,
        "exp":   now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """
    Return (signed_token, jti).
    The caller must persist jti in MongoDB to enable revocation.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub":  user_id,
        "jti":  jti,
        "type": "refresh",
        "iat":  now,
        "exp":  now + timedelta(days=settings.refresh_token_expire_days),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti


# ── Token verification ─────────────────────────────────────────────────────────

class TokenVerificationError(Exception):
    """Raised when a token is invalid, expired, or has the wrong type."""


def decode_access_token(token: str) -> AccessTokenPayload:
    """
    Decode and validate an access token.
    Raises TokenVerificationError on any failure.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenVerificationError(f"Invalid or expired access token: {exc}") from exc

    if raw.get("type") != "access":
        raise TokenVerificationError("Token type mismatch — expected 'access'.")

    return AccessTokenPayload(
        sub=raw["sub"],
        email=raw["email"],
        role=raw["role"],
        type="access",
        iat=datetime.fromtimestamp(raw["iat"], tz=timezone.utc),
        exp=datetime.fromtimestamp(raw["exp"], tz=timezone.utc),
    )


def decode_refresh_token(token: str) -> RefreshTokenPayload:
    """
    Decode and validate a refresh token.
    Raises TokenVerificationError on any failure.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenVerificationError(f"Invalid or expired refresh token: {exc}") from exc

    if raw.get("type") != "refresh":
        raise TokenVerificationError("Token type mismatch — expected 'refresh'.")

    return RefreshTokenPayload(
        sub=raw["sub"],
        jti=raw["jti"],
        type="refresh",
        iat=datetime.fromtimestamp(raw["iat"], tz=timezone.utc),
        exp=datetime.fromtimestamp(raw["exp"], tz=timezone.utc),
    )
