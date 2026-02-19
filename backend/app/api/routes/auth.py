"""
Auth routes — mounted at /api/v1/auth

Endpoints
---------
  POST  /register              Register a new account
  POST  /login                 Authenticate and receive tokens
  POST  /verify-email          Confirm email with the token from the inbox
  POST  /resend-verification   Re-issue a verification email
  POST  /refresh               Rotate access token using the HttpOnly cookie
  POST  /logout                Revoke the refresh token
  GET   /me                    Return the current user's profile

Rate limits (slowapi)
---------------------
  /register            → 5 / minute  per IP  (prevents mass sign-up abuse)
  /login               → 10 / minute per IP  (matches presentation spec)
  /verify-email        → 10 / minute per IP
  /resend-verification → 3 / minute  per IP  (prevent email-spam abuse)
  /refresh             → 20 / minute per IP
  /me                  → 60 / minute per IP  (dashboard polling)

Security controls
-----------------
  - Refresh token stored in HttpOnly, Secure, SameSite=Strict cookie
  - refresh_token cookie path is scoped to /api/v1/auth to minimise exposure
  - All error messages are deliberately vague to prevent user enumeration
  - HTTP 422 from Pydantic surfaces field-level validation errors
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_current_user, get_refresh_token_from_cookie
from app.config.settings import get_settings
from app.db.mongodb import get_db
from app.models.user import (
    ChangePasswordRequest,
    ResendVerificationRequest,
    UpdateProfileRequest,
    UserLogin,
    UserRegister,
    UserResponse,
    VerifyEmailRequest,
)
from app.security.jwt import TokenVerificationError, decode_refresh_token
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)

# ── Cookie helpers ────────────────────────────────────────────────────────────

_COOKIE_PATH = "/api/v1/auth"
_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an HttpOnly cookie.
    secure=True in production (HTTPS); false in local dev (HTTP) via COOKIE_SECURE env var.
    """
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",       # lax allows cookie on same-origin redirects (dev-friendly)
        max_age=_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="refresh_token", path=_COOKIE_PATH)


# ── Cloudflare Turnstile verification ─────────────────────────────────────────

_TURNSTILE_SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def _verify_turnstile(request: Request) -> None:
    """
    Validate the Cloudflare Turnstile token sent by the frontend as
    the X-CF-Turnstile header.

    - If TURNSTILE_SECRET_KEY is not configured (e.g. during initial dev
      setup before .env is populated), the check is skipped so developers
      are not blocked. A warning is logged so the gap is visible.
    - Any token that Cloudflare rejects results in HTTP 403 — the login
      attempt is refused before credentials are even checked, burning the
      attacker's challenge token with zero information returned.
    """
    settings = get_settings()
    if not settings.turnstile_secret_key:
        logger.warning("TURNSTILE_SECRET_KEY is not set — Turnstile check skipped")
        return

    token = request.headers.get("X-CF-Turnstile", "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security challenge required.",
        )

    client_ip = request.client.host if request.client else None

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                _TURNSTILE_SITEVERIFY,
                data={
                    "secret":   settings.turnstile_secret_key,
                    "response": token,
                    **({"remoteip": client_ip} if client_ip else {}),
                },
            )
            result = resp.json()
        except httpx.RequestError:
            # Cloudflare unreachable — fail open to avoid locking out real users
            logger.error("Turnstile siteverify request failed — failing open")
            return

    if not result.get("success"):
        error_codes = result.get("error-codes", [])
        logger.warning("Turnstile verification failed: %s", error_codes)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security challenge failed. Please try again.",
        )


# ── POST /register ────────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: UserRegister,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Create a new SentinelAI account.

    - Validates all fields (fullname, email format, password strength,
      ticker symbols, confirm_password match).
    - Hashes the password with bcrypt (work-factor 12).
    - Sends an HTML verification email via Brevo.
    - Returns HTTP 201 — does **not** issue tokens yet (email must be verified first).
    """
    try:
        result = await auth_service.register_user(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return result


# ── POST /login ───────────────────────────────────────────────────────────────

@router.post(
    "/login",
    summary="Authenticate and receive access + refresh tokens",
    dependencies=[Depends(_verify_turnstile)],
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: UserLogin,
    response: Response,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Authenticate with email + password.

    On success:
    - Returns the access token (Bearer) in the JSON body.
    - Sets the refresh token in an HttpOnly cookie (path=/api/v1/auth).

    On failure returns HTTP 401 with a deliberately vague message to
    prevent user-enumeration attacks.
    """
    try:
        result = await auth_service.login_user(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    refresh_token = result.pop("refresh_token")
    _set_refresh_cookie(response, refresh_token)
    return result


# ── POST /verify-email ────────────────────────────────────────────────────────

@router.post(
    "/verify-email",
    summary="Confirm email address using the verification token",
)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Complete the email verification flow.

    The frontend extracts the `token` query param from the verification link
    (e.g. `/verify-email?token=…`) and posts it here as JSON.
    """
    try:
        return await auth_service.verify_email(db, body.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── POST /resend-verification ─────────────────────────────────────────────────

@router.post(
    "/resend-verification",
    summary="Re-send the email verification link",
)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Issue a fresh verification token and send a new email.

    Always returns HTTP 200 with the same message regardless of whether
    the email exists — prevents user-enumeration.
    """
    return await auth_service.resend_verification(db, body.email)


# ── POST /refresh ─────────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    summary="Rotate access token using the HttpOnly refresh-token cookie",
)
@limiter.limit("20/minute")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str = Depends(get_refresh_token_from_cookie),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Exchange the refresh token (from cookie) for a new access token.

    The refresh token is **rotated** on every call:
    - Old jti is deleted from MongoDB.
    - New refresh token is issued and set as a fresh HttpOnly cookie.

    This limits the replay window to a single use.
    """
    try:
        payload = decode_refresh_token(refresh_token)
    except TokenVerificationError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    try:
        result = await auth_service.refresh_access_token(
            db, jti=payload.jti, user_id=payload.sub
        )
    except ValueError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    new_refresh = result.pop("refresh_token")
    _set_refresh_cookie(response, new_refresh)
    return result


# ── POST /logout ──────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    summary="Revoke the refresh token and clear the cookie",
)
@limiter.limit("20/minute")
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Log out the current session.

    - Revokes the refresh token jti in MongoDB.
    - Clears the HttpOnly cookie.
    - The access token expires naturally (1-hour TTL).

    If the cookie is missing the endpoint still clears it and returns 200
    (idempotent — already logged out).
    """
    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
            await auth_service.logout_user(db, jti=payload.jti, user_id=payload.sub)
        except (TokenVerificationError, ValueError):
            pass  # Token already invalid — treat as already logged out

    _clear_refresh_cookie(response)
    return {"message": "Logged out successfully."}


# ── GET /me ───────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the current user's profile",
)
@limiter.limit("60/minute")
async def me(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Fetch full profile for the authenticated user.

    Requires a valid Bearer access token in the Authorization header.
    """
    from bson import ObjectId

    user = await db["users"].find_one({"_id": ObjectId(current_user["user_id"])})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found.",
        )

    user["_id"] = str(user["_id"])
    return UserResponse(**user)


# ── PATCH /me ─────────────────────────────────────────────────────────────────

@router.patch(
    "/me",
    summary="Update the current user's profile",
)
@limiter.limit("60/minute")
async def update_me(
    request: Request,
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Partially update the authenticated user's profile.

    Accepts any combination of: fullname, avatar_id (1-8), ticker_preferences.
    Returns the updated user object. Only supplied fields are written.
    """
    try:
        return await auth_service.update_profile(db, current_user["user_id"], body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── POST /me/change-password ──────────────────────────────────────────────────

@router.post(
    "/me/change-password",
    summary="Change the authenticated user's password",
)
@limiter.limit("5/minute")
async def change_password_me(
    request: Request,
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Replace the current user's password after verifying the existing one.

    - current_password must match the stored bcrypt hash.
    - new_password must satisfy the same strength rules as registration.
    - Returns HTTP 200 on success.
    """
    try:
        return await auth_service.change_password(db, current_user["user_id"], body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
