"""
User data models (Pydantic v2).

Schemas:
  UserRegister       — POST /auth/register  (incoming request body)
  UserLogin          — POST /auth/login     (incoming request body)
  UserResponse       — returned to the client (no password, no internal fields)
  TokenResponse      — access token + basic user info on login / refresh
  VerifyEmailRequest — POST /auth/verify-email
  ResendVerificationRequest — POST /auth/resend-verification
  UserInDB           — full document shape stored in MongoDB
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# ── Validation constants ──────────────────────────────────────────────────────

# Ticker symbol whitelist — per presentation spec: [A-Z0-9^=.-]{1,12}
_TICKER_RE = re.compile(r"^[A-Z0-9\^=\.\-]{1,12}$")

# Password strength: ≥8 chars, upper, lower, digit, special
_PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};:'\",.<>?/\\|`~]).{8,}$"
)

# Fullname: letters, spaces, hyphens, apostrophes only
_FULLNAME_RE = re.compile(r"^[\w\s\-\'\.]{2,100}$", re.UNICODE)

# Prompt-injection guard (same pattern family as agent_06 schemas)
_INJECTION_RE = re.compile(
    r"(ignore\s+previous|disregard\s+all|system\s*:|<\|im_end\|>|</s>|\[\[|\]\])",
    re.IGNORECASE,
)

MAX_TICKERS = 20


def _no_injection(v: str) -> str:
    if _INJECTION_RE.search(v):
        raise ValueError("Input contains a forbidden pattern.")
    return v


# ── Request schemas ───────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    """
    Registration request — all fields are validated server-side.
    confirm_password is cross-validated against password.
    """

    fullname: str = Field(..., min_length=2, max_length=100,
                          description="User's full name")
    email: EmailStr = Field(..., description="Valid email address (becomes username)")
    password: str = Field(..., min_length=8, max_length=128,
                          description="Strong password (≥8 chars, upper/lower/digit/special)")
    confirm_password: str = Field(..., description="Must match password exactly")
    ticker_preferences: list[str] = Field(
        default_factory=list,
        max_length=MAX_TICKERS,
        description=f"Up to {MAX_TICKERS} ticker symbols, e.g. GC=F, BTC-USD, SPY",
    )

    @field_validator("fullname")
    @classmethod
    def validate_fullname(cls, v: str) -> str:
        v = v.strip()
        if not _FULLNAME_RE.match(v):
            raise ValueError(
                "Full name may only contain letters, spaces, hyphens, apostrophes, or dots."
            )
        return _no_injection(v)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be at least 8 characters and include an uppercase letter, "
                "a lowercase letter, a digit, and a special character."
            )
        return v

    @field_validator("ticker_preferences", mode="before")
    @classmethod
    def validate_tickers(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("ticker_preferences must be a list.")
        result: list[str] = []
        for raw in v:
            ticker = str(raw).strip().upper()
            if not _TICKER_RE.match(ticker):
                raise ValueError(
                    f"Invalid ticker '{raw}'. "
                    "Tickers must match [A-Z0-9^=.-]{{1,12}} (e.g. GC=F, BTC-USD, ^GSPC)."
                )
            result.append(ticker)
        return result

    @model_validator(mode="after")
    def passwords_match(self) -> "UserRegister":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class UserLogin(BaseModel):
    """Login request."""
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    """Email verification — token from the verification email."""
    token: str = Field(..., min_length=32, max_length=128)


class ResendVerificationRequest(BaseModel):
    """Resend verification email."""
    email: EmailStr


class UpdateTickerPreferences(BaseModel):
    """Patch endpoint to update ticker preferences."""
    ticker_preferences: list[str] = Field(..., max_length=MAX_TICKERS)

    @field_validator("ticker_preferences", mode="before")
    @classmethod
    def validate_tickers(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("ticker_preferences must be a list.")
        result: list[str] = []
        for raw in v:
            ticker = str(raw).strip().upper()
            if not _TICKER_RE.match(ticker):
                raise ValueError(f"Invalid ticker '{raw}'.")
            result.append(ticker)
        return result


# ── Response schemas ──────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    """
    Safe user representation returned to the client.
    Never includes hashed_password or internal tokens.
    """
    id: str = Field(..., alias="_id")
    fullname: str
    email: str
    role: Literal["analyst", "admin"]
    is_verified: bool
    ticker_preferences: list[str]
    created_at: datetime

    model_config = {"populate_by_name": True}


class TokenResponse(BaseModel):
    """Returned on successful login or token refresh."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int           # seconds until access token expires
    user: UserResponse


# ── Database document shape ───────────────────────────────────────────────────

class UserInDB(BaseModel):
    """
    Full user document as stored in MongoDB.
    Only used internally — never serialised to the API response.
    """
    fullname: str
    email: str
    hashed_password: str
    role: Literal["analyst", "admin"] = "analyst"
    is_verified: bool = False
    ticker_preferences: list[str] = Field(default_factory=list)

    # Email verification
    email_verification_token: str | None = None   # SHA-256 hex of the raw token
    email_verification_expires: datetime | None = None

    # Audit fields
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_login: datetime | None = None
