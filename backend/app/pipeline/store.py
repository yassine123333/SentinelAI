"""
Pipeline run persistence — MongoDB.

Collections:
  pipeline_runs: one document per pipeline run
    Fields: run_id, user_id, raw_query, asset, timeframe, risk_focus,
            status, created_at, updated_at, completed_at,
            state_snapshot, error_message

Security:
  - All queries use Motor parameterized form (dicts with ObjectId/string values).
  - No string concatenation in query predicates.
  - get_run_for_user() enforces ownership: user_id must match unless admin role.
  - Admin bypass only possible with explicit is_admin=True flag checked by caller.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION = "pipeline_runs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Create ────────────────────────────────────────────────────────────────────

async def create_run(
    db,
    run_id: str,
    user_id: str,
    raw_query: str,
) -> dict[str, Any]:
    """Insert a new pending pipeline run document. Returns the inserted document."""
    doc: dict[str, Any] = {
        "run_id": run_id,
        "user_id": user_id,
        "raw_query": raw_query[:500],
        "asset": None,
        "timeframe": None,
        "risk_focus": None,
        "status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
        "completed_at": None,
        "state_snapshot": {},
        "error_message": None,
    }
    await db[COLLECTION].insert_one(doc)
    logger.info("pipeline_run created run_id=%s user_id=%s", run_id, user_id)
    return doc


# ── Update ────────────────────────────────────────────────────────────────────

async def update_run_status(
    db,
    run_id: str,
    status: str,
    asset: str | None = None,
    timeframe: str | None = None,
    risk_focus: str | None = None,
) -> None:
    """Update the status (and optional routing fields) of a run."""
    update: dict[str, Any] = {
        "$set": {
            "status": status,
            "updated_at": _now(),
        }
    }
    if asset:
        update["$set"]["asset"] = asset
    if timeframe:
        update["$set"]["timeframe"] = timeframe
    if risk_focus:
        update["$set"]["risk_focus"] = risk_focus
    if status in {"done", "failed"}:
        update["$set"]["completed_at"] = _now()

    await db[COLLECTION].update_one({"run_id": run_id}, update)


async def save_state_snapshot(
    db,
    run_id: str,
    status: str,
    state_snapshot: dict[str, Any],
    error_message: str | None = None,
) -> None:
    """Persist the full state snapshot after pipeline completion."""
    # Strip non-serialisable values
    clean_snapshot = _clean_snapshot(state_snapshot)
    update: dict[str, Any] = {
        "$set": {
            "status": status,
            "updated_at": _now(),
            "state_snapshot": clean_snapshot,
            "asset": clean_snapshot.get("asset"),
            "timeframe": clean_snapshot.get("timeframe"),
            "risk_focus": clean_snapshot.get("risk_focus"),
        }
    }
    if error_message:
        update["$set"]["error_message"] = error_message[:2000]
    if status in {"done", "failed"}:
        update["$set"]["completed_at"] = _now()

    await db[COLLECTION].update_one({"run_id": run_id}, update)


def _clean_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove bytes and other non-JSON-serialisable values from snapshot."""
    clean: dict[str, Any] = {}
    for k, v in snapshot.items():
        if k in {"pdf_bytes"}:
            continue  # PDF stored separately (GridFS / returned directly)
        if isinstance(v, bytes):
            continue
        clean[k] = v
    return clean


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_run(db, run_id: str) -> dict[str, Any] | None:
    """Fetch a run by run_id. Returns None if not found."""
    return await db[COLLECTION].find_one({"run_id": run_id}, {"_id": 0})


async def get_run_for_user(
    db,
    run_id: str,
    user_id: str,
    is_admin: bool = False,
) -> dict[str, Any] | None:
    """
    Fetch a run with ownership enforcement.
    Admins may access any run (is_admin=True).
    Regular users may only access their own (user_id must match).
    """
    query: dict[str, Any] = {"run_id": run_id}
    if not is_admin:
        query["user_id"] = user_id    # ownership check
    return await db[COLLECTION].find_one(query, {"_id": 0})


async def list_runs_for_user(
    db,
    user_id: str,
    limit: int = 20,
    skip: int = 0,
) -> list[dict[str, Any]]:
    """List a user's pipeline runs, newest first, without state_snapshot."""
    cursor = (
        db[COLLECTION]
        .find({"user_id": user_id}, {"_id": 0, "state_snapshot": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(min(limit, 50))
    )
    return await cursor.to_list(length=min(limit, 50))


async def list_all_runs(
    db,
    limit: int = 50,
    skip: int = 0,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Admin: list all pipeline runs across all users."""
    query: dict[str, Any] = {}
    if status_filter:
        query["status"] = status_filter
    cursor = (
        db[COLLECTION]
        .find(query, {"_id": 0, "state_snapshot": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(min(limit, 100))
    )
    return await cursor.to_list(length=min(limit, 100))


# ── PDF bytes store/retrieve (GridFS-like via separate collection) ─────────────

async def store_pdf(db, run_id: str, pdf_bytes: bytes) -> None:
    """Store PDF bytes for a completed run (upsert)."""
    await db["pipeline_pdfs"].update_one(
        {"run_id": run_id},
        {"$set": {"run_id": run_id, "pdf_bytes": pdf_bytes, "stored_at": _now()}},
        upsert=True,
    )


async def get_pdf(db, run_id: str) -> bytes | None:
    """Retrieve PDF bytes for a run. Returns None if not stored."""
    doc = await db["pipeline_pdfs"].find_one({"run_id": run_id})
    if doc:
        return doc.get("pdf_bytes")
    return None
