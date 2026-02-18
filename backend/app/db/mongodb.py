"""
MongoDB async client (Motor).

Provides a module-level client and database handle that are initialised
once at FastAPI startup via lifespan and closed on shutdown.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config.settings import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    """Open the Motor connection pool. Called once at FastAPI startup."""
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5_000,
        maxPoolSize=100,          # cap per presentation spec
        minPoolSize=5,
    )
    _db = _client[settings.mongodb_db]
    # Force a connection to catch mis-configuration early
    await _client.admin.command("ping")
    logger.info("MongoDB connected — db=%s", settings.mongodb_db)


async def close_db() -> None:
    """Close the Motor connection pool. Called once at FastAPI shutdown."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed.")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database handle (raises if not initialised)."""
    if _db is None:
        raise RuntimeError(
            "Database not initialised. "
            "Ensure connect_db() is called during application startup."
        )
    return _db
