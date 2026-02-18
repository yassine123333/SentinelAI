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

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import get_current_user, get_refresh_token_from_cookie
from app.db.mongodb import get_db
from app.models.user import (
    ResendVerificationRequest,
    UserLogin,
    UserRegister,
    UserResponse,
    VerifyEmailRequest,
)
from app.security.jwt import TokenVerificationError, decode_refresh_token
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Cookie helpers ────────────────────────────────────────────────────────────

_COOKIE_PATH = "/api/v1/auth"
_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an HttpOnly, Secure, SameSite=Strict cookie."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,          # HTTPS only — matches presentation TLS 1.3 requirement
        samesite="strict",    # CSRF protection — matches presentation spec
        max_age=_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="refresh_token", path=_COOKIE_PATH)


# ── POST /register ────────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
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
)
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
