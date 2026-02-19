"""
Auth service — business logic for registration, login, and email verification.

Security design
---------------
  - Passwords:   bcrypt (work-factor 12) — never stored in plaintext
  - Verification token: secrets.token_urlsafe(32) raw token → SHA-256 hex
    stored in DB so a DB breach cannot be used to verify other accounts
  - Refresh tokens: JWT jti persisted in MongoDB for instant revocation;
    TTL index auto-purges expired rows
  - Timing-safe: email existence checked after password verification
    to prevent user enumeration via response-time differences on login
  - All DB writes use Motor async — no blocking I/O on the event loop
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.settings import get_settings
from app.models.user import (
    ChangePasswordRequest,
    UpdateProfileRequest,
    UserInDB,
    UserLogin,
    UserRegister,
)
from app.security.email import send_verification_email
from app.security.jwt import create_access_token, create_refresh_token
from app.security.password import hash_password, verify_password

logger = logging.getLogger(__name__)

_VERIFICATION_TOKEN_TTL_HOURS = 24
_REFRESH_TOKEN_COOKIE = "refresh_token"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    """SHA-256 hex digest of *raw*.  Used for verification-token storage."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Registration ──────────────────────────────────────────────────────────────

async def register_user(db: AsyncIOMotorDatabase, data: UserRegister) -> dict:
    """
    Create a new unverified user and dispatch the verification email.

    Returns a plain dict suitable for a JSON success response.
    Raises ValueError for business-rule violations (duplicate email, etc.).
    """
    email_lower = data.email.lower()

    # Duplicate-email check (index will also enforce this, but we want
    # a friendly error before hitting the DB constraint)
    existing = await db["users"].find_one({"email": email_lower}, {"_id": 1})
    if existing:
        raise ValueError("An account with this email address already exists.")

    # Generate verification token
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    token_expires = _now() + timedelta(hours=_VERIFICATION_TOKEN_TTL_HOURS)

    user_doc = UserInDB(
        fullname=data.fullname.strip(),
        email=email_lower,
        hashed_password=hash_password(data.password),
        ticker_preferences=data.ticker_preferences,
        email_verification_token=token_hash,
        email_verification_expires=token_expires,
    ).model_dump()

    result = await db["users"].insert_one(user_doc)
    user_id = str(result.inserted_id)

    logger.info("register user_id=%s email=%s", user_id, email_lower)

    # Fire-and-forget style — errors are logged but don't fail registration
    try:
        await send_verification_email(
            to_email=email_lower,
            to_name=data.fullname.strip(),
            raw_token=raw_token,
        )
    except Exception as exc:
        logger.error(
            "Failed to send verification email user_id=%s: %s", user_id, exc
        )

    return {
        "message": (
            "Registration successful. "
            "Please check your inbox and verify your email within 24 hours."
        ),
        "user_id": user_id,
    }


# ── Email verification ────────────────────────────────────────────────────────

async def verify_email(db: AsyncIOMotorDatabase, raw_token: str) -> dict:
    """
    Validate *raw_token*, mark the user as verified, and clear the token.

    Raises ValueError if the token is invalid or expired.
    """
    token_hash = _hash_token(raw_token)
    now = _now()

    user = await db["users"].find_one(
        {
            "email_verification_token": token_hash,
            "email_verification_expires": {"$gt": now},
            "is_verified": False,
        }
    )

    if not user:
        raise ValueError(
            "Verification link is invalid or has expired. "
            "Request a new one via /auth/resend-verification."
        )

    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "is_verified": True,
                "updated_at": now,
            },
            "$unset": {
                "email_verification_token": "",
                "email_verification_expires": "",
            },
        },
    )

    logger.info("email_verified user_id=%s", str(user["_id"]))
    return {"message": "Email verified successfully. You can now log in."}


# ── Resend verification ───────────────────────────────────────────────────────

async def resend_verification(db: AsyncIOMotorDatabase, email: str) -> dict:
    """
    Issue a fresh verification token and re-send the email.

    We always return the same success message to avoid leaking whether
    the email is registered (prevents user enumeration).
    """
    email_lower = email.lower()
    user = await db["users"].find_one(
        {"email": email_lower, "is_verified": False},
        {"fullname": 1},
    )

    if not user:
        # Return the same message even if not found or already verified
        return {
            "message": (
                "If an unverified account exists for this email, "
                "a new verification link has been sent."
            )
        }

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    token_expires = _now() + timedelta(hours=_VERIFICATION_TOKEN_TTL_HOURS)

    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "email_verification_token": token_hash,
                "email_verification_expires": token_expires,
                "updated_at": _now(),
            }
        },
    )

    try:
        await send_verification_email(
            to_email=email_lower,
            to_name=user["fullname"],
            raw_token=raw_token,
        )
    except Exception as exc:
        logger.error("resend_verification email send failed: %s", exc)

    logger.info("resend_verification user_id=%s", str(user["_id"]))
    return {
        "message": (
            "If an unverified account exists for this email, "
            "a new verification link has been sent."
        )
    }


# ── Login ─────────────────────────────────────────────────────────────────────

async def login_user(db: AsyncIOMotorDatabase, data: UserLogin) -> dict:
    """
    Authenticate credentials and issue access + refresh tokens.

    Returns a dict with:
      access_token, token_type, expires_in, refresh_token, user (safe subset)

    Raises ValueError for invalid credentials or unverified email.
    """
    settings = get_settings()
    email_lower = data.email.lower()

    user = await db["users"].find_one({"email": email_lower})

    # Always run verify_password (even on not-found) to prevent timing attacks
    dummy_hash = "$2b$12$" + "x" * 53
    stored_hash = user["hashed_password"] if user else dummy_hash
    password_ok = verify_password(data.password, stored_hash)

    if not user or not password_ok:
        raise ValueError("Invalid email or password.")

    if not user["is_verified"]:
        raise ValueError(
            "Email address not verified. "
            "Please check your inbox or use /auth/resend-verification."
        )

    user_id = str(user["_id"])

    # Access token
    access_token = create_access_token(
        user_id=user_id,
        email=email_lower,
        role=user.get("role", "analyst"),
    )

    # Refresh token — store jti in MongoDB for revocation support
    refresh_token, jti = create_refresh_token(user_id)
    expires_at = _now() + timedelta(days=settings.refresh_token_expire_days)

    await db["refresh_tokens"].insert_one(
        {
            "jti":        jti,
            "user_id":    user_id,
            "created_at": _now(),
            "expires_at": expires_at,
        }
    )

    # Update last_login timestamp
    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login": _now(), "updated_at": _now()}},
    )

    logger.info("login user_id=%s", user_id)

    return {
        "access_token":  access_token,
        "token_type":    "bearer",
        "expires_in":    settings.access_token_expire_minutes * 60,
        "refresh_token": refresh_token,   # caller sets this as HttpOnly cookie
        "user": {
            "_id":                str(user["_id"]),
            "fullname":           user["fullname"],
            "email":              user["email"],
            "role":               user.get("role", "analyst"),
            "is_verified":        user["is_verified"],
            "ticker_preferences": user.get("ticker_preferences", []),
            "created_at":         user["created_at"],
        },
    }


# ── Token refresh ─────────────────────────────────────────────────────────────

async def refresh_access_token(
    db: AsyncIOMotorDatabase, jti: str, user_id: str
) -> dict:
    """
    Validate the refresh token's jti against the DB and issue a new access token.
    Rotates the refresh token (old jti deleted, new one issued).

    Raises ValueError if the jti is not found (revoked or expired).
    """
    settings = get_settings()
    now = _now()

    # Atomic find-and-delete: ensures only ONE concurrent request can consume a JTI.
    # Prevents race conditions (e.g. React StrictMode double-mount sending two
    # simultaneous /refresh requests with the same cookie).
    token_doc = await db["refresh_tokens"].find_one_and_delete(
        {"jti": jti, "user_id": user_id, "expires_at": {"$gt": now}}
    )
    if not token_doc:
        raise ValueError("Refresh token is invalid or has been revoked.")

    user = await db["users"].find_one(
        {"_id": ObjectId(user_id)},
        {"email": 1, "role": 1, "is_verified": 1},
    )
    if not user or not user.get("is_verified"):
        raise ValueError("User account is not active.")

    new_access = create_access_token(
        user_id=user_id,
        email=user["email"],
        role=user.get("role", "analyst"),
    )
    new_refresh, new_jti = create_refresh_token(user_id)
    new_expires = now + timedelta(days=settings.refresh_token_expire_days)

    await db["refresh_tokens"].insert_one(
        {
            "jti":        new_jti,
            "user_id":    user_id,
            "created_at": now,
            "expires_at": new_expires,
        }
    )

    logger.info("token_refresh user_id=%s old_jti=%s new_jti=%s", user_id, jti, new_jti)

    return {
        "access_token":  new_access,
        "token_type":    "bearer",
        "expires_in":    settings.access_token_expire_minutes * 60,
        "refresh_token": new_refresh,
    }


# ── Profile update ────────────────────────────────────────────────────────────

async def update_profile(
    db: AsyncIOMotorDatabase, user_id: str, data: UpdateProfileRequest
) -> dict:
    """
    Partially update a user's profile (fullname, avatar_id, ticker_preferences).
    Only fields explicitly supplied in the request body are written.
    Returns the updated user dict (same shape as the login user payload).
    Raises ValueError if nothing to update or user not found.
    """
    updates: dict = {}
    if data.fullname is not None:
        updates["fullname"] = data.fullname
    if data.avatar_id is not None:
        updates["avatar_id"] = data.avatar_id
    if data.ticker_preferences is not None:
        updates["ticker_preferences"] = data.ticker_preferences

    if not updates:
        raise ValueError("No fields to update.")

    updates["updated_at"] = _now()

    result = await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": updates},
    )
    if result.matched_count == 0:
        raise ValueError("User not found.")

    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    logger.info("profile_update user_id=%s fields=%s", user_id, list(updates.keys()))

    return {
        "_id":                str(user["_id"]),
        "fullname":           user["fullname"],
        "email":              user["email"],
        "role":               user.get("role", "analyst"),
        "is_verified":        user["is_verified"],
        "ticker_preferences": user.get("ticker_preferences", []),
        "avatar_id":          user.get("avatar_id"),
        "created_at":         user["created_at"],
        "last_login":         user.get("last_login"),
    }


# ── Password change ────────────────────────────────────────────────────────────

async def change_password(
    db: AsyncIOMotorDatabase, user_id: str, data: ChangePasswordRequest
) -> dict:
    """
    Validate the current password and replace it with the new one.
    Raises ValueError if the current password is wrong.
    """
    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise ValueError("User account not found.")

    if not verify_password(data.current_password, user["hashed_password"]):
        raise ValueError("Current password is incorrect.")

    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "hashed_password": hash_password(data.new_password),
                "updated_at": _now(),
            }
        },
    )

    logger.info("password_changed user_id=%s", user_id)
    return {"message": "Password updated successfully."}


# ── Logout ────────────────────────────────────────────────────────────────────

async def logout_user(db: AsyncIOMotorDatabase, jti: str, user_id: str) -> dict:
    """
    Revoke the refresh token by deleting its jti from MongoDB.
    The access token will expire naturally (1-hour TTL).
    """
    result = await db["refresh_tokens"].delete_one({"jti": jti, "user_id": user_id})
    logger.info(
        "logout user_id=%s jti=%s deleted=%d", user_id, jti, result.deleted_count
    )
    return {"message": "Logged out successfully."}
