"""
persistence.py — MongoDB-backed SOC state storage.

Collections (auto-created with indexes):
  soc_ip_states   — per-IP intervention level + violation history
  soc_blocked_ips — permanent block list (survives restarts)
  soc_audit_log   — full reasoning chains for human audit (30-day TTL)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class InterventionLevel(IntEnum):
    CLEAN = 0
    MONITORING = 1
    CHALLENGED = 2   # CAPTCHA required on next request
    SUSPENDED = 3    # Sessions invalidated
    BLOCKED = 4      # Hard block: NSG + Nginx


def _db():
    """Return the active Motor database handle (sync accessor)."""
    from app.db.mongodb import get_db
    return get_db()


# ── Index Setup ───────────────────────────────────────────────────────────────

async def create_indexes() -> None:
    """Ensure all SOC collections have proper indexes. Safe to call multiple times."""
    db = _db()
    try:
        await db.soc_ip_states.create_index("ip", unique=True)
        await db.soc_blocked_ips.create_index("ip", unique=True)
        await db.soc_audit_log.create_index([("ip", 1), ("ts", -1)])
        await db.soc_audit_log.create_index(
            "ts", expireAfterSeconds=30 * 24 * 3600  # 30-day TTL
        )
        await db.soc_events.create_index(
            "ts", expireAfterSeconds=3600  # 1-hour TTL for raw events
        )
        logger.info("SOC: MongoDB indexes ensured.")
    except Exception as exc:
        logger.error("SOC: failed to create indexes: %s", exc)


# ── Blocked IPs ───────────────────────────────────────────────────────────────

async def load_blocked_ips() -> set[str]:
    """Load permanently blocked IPs from MongoDB on startup."""
    db = _db()
    try:
        docs = await db.soc_blocked_ips.find({}, {"ip": 1}).to_list(None)
        ips = {d["ip"] for d in docs if "ip" in d}
        logger.info("SOC: loaded %d blocked IPs from MongoDB.", len(ips))
        return ips
    except Exception as exc:
        logger.error("SOC: failed to load blocked IPs: %s", exc)
        return set()


async def persist_blocked_ip(ip: str, reason: str) -> None:
    """Upsert a permanently blocked IP into MongoDB."""
    db = _db()
    try:
        await db.soc_blocked_ips.update_one(
            {"ip": ip},
            {
                "$set": {
                    "ip": ip,
                    "reason": reason[:300],
                    "blocked_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    except Exception as exc:
        logger.error("SOC: failed to persist blocked IP %s: %s", ip, exc)


# ── IP State Machine ──────────────────────────────────────────────────────────

async def get_ip_state(ip: str) -> dict[str, Any]:
    """Get the current intervention state for an IP. Returns defaults if unknown."""
    db = _db()
    try:
        doc = await db.soc_ip_states.find_one({"ip": ip})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as exc:
        logger.error("SOC: failed to get IP state for %s: %s", ip, exc)
    return {
        "ip": ip,
        "level": int(InterventionLevel.CLEAN),
        "violations": 0,
    }


async def update_ip_state(ip: str, level: InterventionLevel, reason: str) -> None:
    """Increment violations and update intervention level for an IP."""
    db = _db()
    now = datetime.now(timezone.utc)
    try:
        await db.soc_ip_states.update_one(
            {"ip": ip},
            {
                "$set": {
                    "ip": ip,
                    "level": int(level),
                    "last_seen": now,
                    "last_reason": reason[:300],
                },
                "$inc": {"violations": 1},
                "$push": {
                    "history": {
                        "$each": [{"level": int(level), "reason": reason[:200], "ts": now}],
                        "$slice": -20,  # keep last 20 events per IP
                    }
                },
            },
            upsert=True,
        )
    except Exception as exc:
        logger.error("SOC: failed to update IP state for %s: %s", ip, exc)


# ── Audit Logging ─────────────────────────────────────────────────────────────

async def log_audit_event(
    ip: str,
    event_type: str,
    findings: dict[str, Any],
    decision: dict[str, Any],
    action: dict[str, Any],
) -> None:
    """Persist a full SOC reasoning chain for human audit."""
    db = _db()
    try:
        await db.soc_audit_log.insert_one(
            {
                "ip": ip,
                "event_type": event_type,
                "ts": datetime.now(timezone.utc),
                "findings": findings,
                "decision": decision,
                "action": action,
            }
        )
    except Exception as exc:
        logger.error("SOC: failed to write audit log for %s: %s", ip, exc)


# ── Intervention Flags ────────────────────────────────────────────────────────

async def set_captcha_required(ip: str, required: bool) -> None:
    """Set or clear the CAPTCHA challenge flag for an IP."""
    db = _db()
    try:
        await db.soc_ip_states.update_one(
            {"ip": ip},
            {
                "$set": {
                    "captcha_required": required,
                    "captcha_since": datetime.now(timezone.utc) if required else None,
                }
            },
            upsert=True,
        )
    except Exception as exc:
        logger.error("SOC: failed to set captcha flag for %s: %s", ip, exc)


async def set_suspended(ip: str, suspended: bool) -> None:
    """Set or clear the session suspension flag for an IP."""
    db = _db()
    try:
        await db.soc_ip_states.update_one(
            {"ip": ip},
            {
                "$set": {
                    "suspended": suspended,
                    "suspended_since": datetime.now(timezone.utc) if suspended else None,
                }
            },
            upsert=True,
        )
    except Exception as exc:
        logger.error("SOC: failed to set suspension for %s: %s", ip, exc)


async def get_ip_flags(ip: str) -> dict[str, bool]:
    """
    Fast lookup of enforcement flags for an IP.
    Used by FastAPI middleware for request-time gating.
    Returns: {blocked, suspended, captcha_required}
    """
    db = _db()
    try:
        doc = await db.soc_ip_states.find_one(
            {"ip": ip},
            {"level": 1, "suspended": 1, "captcha_required": 1},
        )
        if not doc:
            return {"blocked": False, "suspended": False, "captcha_required": False}
        level = InterventionLevel(doc.get("level", 0))
        return {
            "blocked": level >= InterventionLevel.BLOCKED,
            "suspended": doc.get("suspended", False),
            "captcha_required": doc.get("captcha_required", False),
        }
    except Exception as exc:
        logger.error("SOC: failed to get flags for %s: %s", ip, exc)
        return {"blocked": False, "suspended": False, "captcha_required": False}
