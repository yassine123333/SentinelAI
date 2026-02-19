"""
init_db.py — MongoDB migration / index creation script.

Run once before first deployment (or after a fresh database wipe):

    cd backend
    python app/db/init_db.py

What it does:
  1. Connects to the MongoDB instance specified in .env
  2. Creates the `sentinelai` database (implicitly, on first write)
  3. Creates the `users` collection with all required indexes
  4. Creates the `refresh_tokens` collection with a TTL index for
     automatic cleanup of expired tokens

After running this script the database structure is visible in
MongoDB Compass — connect to the URI in .env and browse the
`sentinelai` database.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── Allow running directly from backend/ ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, IndexModel, TEXT

from app.config.settings import get_settings


async def init() -> None:
    settings = get_settings()
    print(f"Connecting to MongoDB at {settings.mongodb_uri} …")
    client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=5_000)

    try:
        await client.admin.command("ping")
        print(f"Connected.  Database: {settings.mongodb_db}")
    except Exception as exc:
        print(f"ERROR: Cannot reach MongoDB — {exc}")
        print("Make sure MongoDB is running and MONGODB_URI in .env is correct.")
        sys.exit(1)

    db = client[settings.mongodb_db]

    # ── users collection ──────────────────────────────────────────────────────
    users = db["users"]

    users_indexes = [
        # Unique email lookup — case-insensitive collation applied at query level
        IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
        # Fast token lookup for email verification
        IndexModel(
            [("email_verification_token", ASCENDING)],
            sparse=True,
            name="email_verification_token_sparse",
        ),
        # Sort / filter by creation date
        IndexModel([("created_at", ASCENDING)], name="created_at_asc"),
        # Text index for admin user search
        IndexModel(
            [("fullname", TEXT), ("email", TEXT)],
            name="fulltext_search",
        ),
    ]

    existing = await users.index_information()
    for idx in users_indexes:
        name = idx.document.get("name")  # type: ignore[attr-defined]
        if name not in existing:
            await users.create_indexes([idx])
            print(f"  [users] Created index: {name}")
        else:
            print(f"  [users] Index already exists: {name}")

    # ── refresh_tokens collection ─────────────────────────────────────────────
    tokens = db["refresh_tokens"]

    tokens_indexes = [
        # Unique JTI (JWT token identifier) — used for replay prevention
        IndexModel([("jti", ASCENDING)], unique=True, name="jti_unique"),
        # Look up tokens by user
        IndexModel([("user_id", ASCENDING)], name="user_id_asc"),
        # TTL index — MongoDB auto-deletes documents when expires_at is reached
        IndexModel(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="refresh_token_ttl",
        ),
    ]

    existing_t = await tokens.index_information()
    for idx in tokens_indexes:
        name = idx.document.get("name")  # type: ignore[attr-defined]
        if name not in existing_t:
            await tokens.create_indexes([idx])
            print(f"  [refresh_tokens] Created index: {name}")
        else:
            print(f"  [refresh_tokens] Index already exists: {name}")

    # ── pipeline_runs collection ──────────────────────────────────────────────
    runs = db["pipeline_runs"]

    runs_indexes = [
        # Primary lookup by run_id (unique — used in ownership check)
        IndexModel([("run_id", ASCENDING)], unique=True, name="run_id_unique"),
        # All runs for a user, newest first
        IndexModel(
            [("user_id", ASCENDING), ("created_at", ASCENDING)],
            name="user_runs_by_date",
        ),
        # Status filter for admin dashboard
        IndexModel([("status", ASCENDING)], name="status_asc"),
        # Ownership enforcement compound index: run_id + user_id
        IndexModel(
            [("run_id", ASCENDING), ("user_id", ASCENDING)],
            name="run_ownership",
        ),
    ]

    existing_r = await runs.index_information()
    for idx in runs_indexes:
        name = idx.document.get("name")  # type: ignore[attr-defined]
        if name not in existing_r:
            await runs.create_indexes([idx])
            print(f"  [pipeline_runs] Created index: {name}")
        else:
            print(f"  [pipeline_runs] Index already exists: {name}")

    # ── pipeline_pdfs collection ──────────────────────────────────────────────
    pdfs = db["pipeline_pdfs"]

    pdfs_indexes = [
        # Unique run_id for upsert-safe PDF storage
        IndexModel([("run_id", ASCENDING)], unique=True, name="pdf_run_id_unique"),
        # TTL: auto-delete PDFs after 30 days (2_592_000 seconds)
        IndexModel(
            [("stored_at", ASCENDING)],
            expireAfterSeconds=2_592_000,
            name="pdf_ttl_30d",
        ),
    ]

    existing_p = await pdfs.index_information()
    for idx in pdfs_indexes:
        name = idx.document.get("name")  # type: ignore[attr-defined]
        if name not in existing_p:
            await pdfs.create_indexes([idx])
            print(f"  [pipeline_pdfs] Created index: {name}")
        else:
            print(f"  [pipeline_pdfs] Index already exists: {name}")

    # ── Validator schema (schema validation in MongoDB) ───────────────────────
    await db.command(
        "collMod",
        "users",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["fullname", "email", "hashed_password", "role",
                             "is_verified", "created_at"],
                "properties": {
                    "fullname":        {"bsonType": "string"},
                    "email":           {"bsonType": "string"},
                    "hashed_password": {"bsonType": "string"},
                    "role":            {"bsonType": "string", "enum": ["analyst", "admin"]},
                    "is_verified":     {"bsonType": "bool"},
                    "created_at":      {"bsonType": "date"},
                },
            }
        },
        validationLevel="moderate",   # warn only — does not block reads
        validationAction="warn",
    )
    print("  [users] JSON schema validator applied.")

    client.close()
    print("\nMigration complete. Open MongoDB Compass and connect to:")
    print(f"  {settings.mongodb_uri}")
    print(f"  Database: {settings.mongodb_db}")
    print("  Collections: users, refresh_tokens, pipeline_runs, pipeline_pdfs")


if __name__ == "__main__":
    asyncio.run(init())
