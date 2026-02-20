"""
Application settings — loaded from environment variables / .env file.
Uses pydantic-settings for type-safe, validated configuration.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    brevo_sender_email: str = "skyrexcgaming@gmail.com"
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

    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a Python list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — reads .env once at startup."""
    return Settings()
