"""
Application settings — loaded from environment variables / .env file.
Uses pydantic-settings for type-safe, validated configuration.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_JWT_WEAK_DEFAULTS = {"change-me-in-production", "secret", "changeme", ""}


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────────────────
    debug: bool = False
    frontend_url: str = "http://localhost:5173"

    # ── MongoDB ───────────────────────────────────────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "sentinelai"

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60   # 1 h — per presentation spec
    refresh_token_expire_days: int = 7

    # ── Brevo ─────────────────────────────────────────────────────────────────
    brevo_api_key: str = ""
    brevo_sender_email: str = "noreply@sentinelai.com"
    brevo_sender_name: str = "SentinelAI"

    # ── reCAPTCHA ─────────────────────────────────────────────────────────────
    recaptcha_secret_key: str = ""

    # ── Cloudflare Turnstile ──────────────────────────────────────────────────
    turnstile_secret_key: str = ""

    # ── Cookie security ───────────────────────────────────────────────────────
    # Set to false in local dev (HTTP). Must be true in production (HTTPS).
    cookie_secure: bool = True

    # ── AI (Groq) ─────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    # Legacy field — kept so old imports don't crash
    gemini_api_key: str = ""

    # ── CORS (comma-separated) ────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """
        Enforce minimum security requirements.
        In production (debug=False) any weak or missing secret is a fatal error.
        In development a warning is emitted so developers see the gap clearly.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # ── JWT secret strength ───────────────────────────────────────────────
        if self.jwt_secret_key in _JWT_WEAK_DEFAULTS:
            msg = (
                "JWT_SECRET_KEY is set to a known-weak default. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(64))\""
            )
            if not self.debug:
                errors.append(msg)
            else:
                warnings.append(msg)
        elif len(self.jwt_secret_key) < 32:
            msg = "JWT_SECRET_KEY is shorter than 32 characters — use at least 64 hex chars."
            if not self.debug:
                errors.append(msg)
            else:
                warnings.append(msg)

        # ── Turnstile secret (bot protection) ─────────────────────────────────
        if not self.turnstile_secret_key:
            msg = (
                "TURNSTILE_SECRET_KEY is not set — bot/CAPTCHA protection is DISABLED. "
                "Set it to your Cloudflare Turnstile secret key."
            )
            if not self.debug:
                errors.append(msg)
            else:
                warnings.append(msg)

        # ── Cookie secure flag in production ──────────────────────────────────
        if not self.debug and not self.cookie_secure:
            errors.append(
                "COOKIE_SECURE=false in production! Refresh tokens will be sent over HTTP. "
                "Set COOKIE_SECURE=true (requires HTTPS)."
            )

        # ── Emit warnings in dev ──────────────────────────────────────────────
        for w in warnings:
            logger.warning("[SECURITY WARNING] %s", w)

        # ── Abort in production if any critical secrets are missing ───────────
        if errors:
            for e in errors:
                logger.critical("[SECURITY FATAL] %s", e)
            print(
                "\n\033[31m[FATAL] SentinelAI refused to start: insecure configuration detected.\n"
                + "\n".join(f"  • {e}" for e in errors)
                + "\n\033[0m",
                file=sys.stderr,
            )
            sys.exit(1)

        return self

    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a validated Python list (https-only in prod)."""
        from urllib.parse import urlparse
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if not self.debug:
            for origin in origins:
                parsed = urlparse(origin)
                if parsed.scheme not in ("https",) or not parsed.netloc:
                    logger.warning(
                        "[SECURITY WARNING] CORS origin '%s' is not a valid HTTPS URL — "
                        "rejected in production mode.", origin
                    )
            origins = [
                o for o in origins
                if urlparse(o).scheme == "https" and urlparse(o).netloc
            ]
        return origins


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — reads .env once at startup."""
    return Settings()
