"""
Admin API routes — restricted to users with role=admin.

Endpoints:
  GET  /api/v1/admin/runs                   — Paginated list of all pipeline runs
  GET  /api/v1/admin/runs/{run_id}          — Full run detail (with state_snapshot)
  GET  /api/v1/admin/runs/{run_id}/state    — Raw state snapshot for debugging
  POST /api/v1/admin/runs/{run_id}/cancel   — Mark a stalled run as failed

  SOC Security Dashboard:
  GET  /api/v1/admin/soc/status             — Daemon status + blocked IP count
  GET  /api/v1/admin/soc/blocked            — All permanently blocked IPs
  GET  /api/v1/admin/soc/ip/{ip}            — Full state + history for one IP
  GET  /api/v1/admin/soc/audit              — Recent audit log (last 100 events)
  POST /api/v1/admin/soc/unblock/{ip}       — Manually unblock an IP

Security:
  - All routes require JWT with role=admin (enforced by require_admin dependency)
  - NoSQL injection prevention: all queries use Motor parameterised form
  - Rate limiting: 30/minute per IP (admins don't need bulk access)
  - Structured audit logging on every admin action
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import require_admin
from app.db.mongodb import get_db
from app.models.pipeline import AdminRunItem, AdminRunListResponse
from app.pipeline import store as pipeline_store

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "/runs",
    response_model=AdminRunListResponse,
    summary="[Admin] List all pipeline runs",
    description=(
        "Returns a paginated list of all pipeline runs across all users. "
        "Supports optional filtering by status. "
        "state_snapshot is excluded from list results for performance."
    ),
)
@limiter.limit("30/minute")
async def admin_list_runs(
    request: Request,
    status_filter: str | None = Query(
        default=None,
        description="Filter by run status: pending, running, done, failed",
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=50, ge=1, le=100, description="Max records to return"),
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> AdminRunListResponse:
    # Validate status_filter against allowed values to prevent injection
    allowed_statuses = {"pending", "running", "done", "failed"}
    if status_filter and status_filter not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status_filter must be one of {sorted(allowed_statuses)}",
        )

    runs = await pipeline_store.list_all_runs(
        db,
        limit=limit,
        skip=skip,
        status_filter=status_filter,
    )

    logger.info(
        "admin list_runs user_id=%s status_filter=%s skip=%d limit=%d returned=%d",
        admin_user["user_id"], status_filter, skip, limit, len(runs),
    )

    items = [
        AdminRunItem(
            run_id=r["run_id"],
            user_id=r["user_id"],
            raw_query=r.get("raw_query", ""),
            asset=r.get("asset"),
            timeframe=r.get("timeframe"),
            risk_focus=r.get("risk_focus"),
            status=r.get("status", "pending"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            completed_at=r.get("completed_at"),
            error_message=r.get("error_message"),
        )
        for r in runs
    ]

    return AdminRunListResponse(
        items=items,
        total_returned=len(items),
        skip=skip,
        limit=limit,
    )


@router.get(
    "/runs/{run_id}",
    summary="[Admin] Get full run detail",
    description=(
        "Returns the full pipeline run document including state_snapshot. "
        "Use /runs/{run_id}/state to get the raw snapshot separately."
    ),
)
@limiter.limit("30/minute")
async def admin_get_run(
    request: Request,
    run_id: str,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    # Admin bypass — no user_id ownership check
    run = await pipeline_store.get_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run '{run_id}' not found.",
        )

    logger.info(
        "admin get_run user_id=%s run_id=%s",
        admin_user["user_id"], run_id,
    )

    # Return full document — convert datetime to isoformat for JSON serialisation
    return _serialize_run(run)


@router.get(
    "/runs/{run_id}/state",
    summary="[Admin] Get raw state snapshot",
    description=(
        "Returns only the state_snapshot field for debugging pipeline internals. "
        "This includes all intermediate agent outputs."
    ),
)
@limiter.limit("30/minute")
async def admin_get_run_state(
    request: Request,
    run_id: str,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    run = await pipeline_store.get_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run '{run_id}' not found.",
        )

    logger.info(
        "admin get_run_state user_id=%s run_id=%s",
        admin_user["user_id"], run_id,
    )

    snapshot = run.get("state_snapshot", {})
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "state_snapshot": snapshot,
    }


@router.post(
    "/runs/{run_id}/cancel",
    summary="[Admin] Cancel / mark stalled run as failed",
    description=(
        "Force-marks a pending or running pipeline run as failed. "
        "Use this to clean up stalled runs. "
        "Does NOT terminate a running background task — only updates the DB record."
    ),
)
@limiter.limit("10/minute")
async def admin_cancel_run(
    request: Request,
    run_id: str,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    run = await pipeline_store.get_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run '{run_id}' not found.",
        )

    current_status = run.get("status", "pending")
    if current_status in {"done", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is already in terminal state '{current_status}'.",
        )

    await pipeline_store.save_state_snapshot(
        db,
        run_id=run_id,
        status="failed",
        state_snapshot=run.get("state_snapshot", {}),
        error_message=f"Cancelled by admin {admin_user['user_id']}",
    )

    logger.warning(
        "admin cancel_run admin_user_id=%s run_id=%s previous_status=%s",
        admin_user["user_id"], run_id, current_status,
    )

    return {
        "run_id": run_id,
        "previous_status": current_status,
        "new_status": "failed",
        "cancelled_by": admin_user["user_id"],
    }


# ── SOC Security Dashboard Endpoints ─────────────────────────────────────────


@router.get(
    "/soc/status",
    summary="[Admin] SOC daemon status",
    description="Returns daemon configuration, blocked IP count, and live queue size.",
)
@limiter.limit("60/minute")
async def soc_status(
    request: Request,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    from app.security.daemon import get_daemon
    from app.security.blocker import get_status as blocker_status
    import asyncio

    daemon = get_daemon()
    blocked_count = await db.soc_blocked_ips.count_documents({})
    monitored_count = await db.soc_ip_states.count_documents({"level": {"$gt": 0}})
    audit_count = await db.soc_audit_log.count_documents({})

    from app.security.collectors import _request_queue
    return {
        "daemon_running": daemon._running,
        "poll_interval_seconds": daemon._running and 10,
        "blocked_ips_total": blocked_count,
        "monitored_ips_total": monitored_count,
        "audit_events_total": audit_count,
        "queue_size": _request_queue.qsize(),
        "blocker": blocker_status(),
    }


@router.get(
    "/soc/blocked",
    summary="[Admin] List all permanently blocked IPs",
    description="Returns all IPs in the hard-block list with reasons and timestamps.",
)
@limiter.limit("30/minute")
async def soc_blocked_ips(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    docs = (
        await db.soc_blocked_ips.find({}, {"_id": 0})
        .sort("blocked_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    total = await db.soc_blocked_ips.count_documents({})
    return {"total": total, "skip": skip, "limit": limit, "items": _serialize_run(docs)}


@router.get(
    "/soc/ip/{ip}",
    summary="[Admin] Full SOC state for one IP",
    description="Returns intervention level, violation history, and all audit events for a given IP.",
)
@limiter.limit("60/minute")
async def soc_ip_detail(
    request: Request,
    ip: str,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    state = await db.soc_ip_states.find_one({"ip": ip}, {"_id": 0})
    audit = (
        await db.soc_audit_log.find({"ip": ip}, {"_id": 0})
        .sort("ts", -1)
        .limit(50)
        .to_list(50)
    )
    level_names = {0: "CLEAN", 1: "MONITORING", 2: "CHALLENGED", 3: "SUSPENDED", 4: "BLOCKED"}
    if state:
        state["level_name"] = level_names.get(state.get("level", 0), "UNKNOWN")
    return {
        "ip": ip,
        "state": _serialize_run(state) if state else None,
        "audit_events": _serialize_run(audit),
    }


@router.get(
    "/soc/audit",
    summary="[Admin] Recent SOC audit log",
    description=(
        "Returns the most recent SOC audit events (Groq reasoning chains + actions). "
        "Each entry includes the full findings, LLM decision, and action taken."
    ),
)
@limiter.limit("30/minute")
async def soc_audit_log(
    request: Request,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None, description="Filter by event type, e.g. ESCALATION_BLOCKED"),
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    query: dict = {}
    if event_type:
        query["event_type"] = event_type
    docs = (
        await db.soc_audit_log.find(query, {"_id": 0})
        .sort("ts", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    total = await db.soc_audit_log.count_documents(query)
    return {"total": total, "skip": skip, "limit": limit, "items": _serialize_run(docs)}


@router.post(
    "/soc/unblock/{ip}",
    summary="[Admin] Manually unblock an IP",
    description=(
        "Removes an IP from the permanent block list and resets its intervention state to CLEAN. "
        "Does NOT remove Azure NSG or Nginx rules — those must be cleaned up manually."
    ),
)
@limiter.limit("10/minute")
async def soc_unblock_ip(
    request: Request,
    ip: str,
    admin_user: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    from app.security.daemon import get_daemon

    # Remove from MongoDB
    await db.soc_blocked_ips.delete_one({"ip": ip})
    await db.soc_ip_states.update_one(
        {"ip": ip},
        {"$set": {"level": 0, "suspended": False, "captcha_required": False}},
    )

    # Remove from in-memory sets
    daemon = get_daemon()
    daemon._hard_blocked.discard(ip)
    from app.security.blocker import _blocked_ips
    _blocked_ips.discard(ip)

    logger.warning(
        "soc_unblock admin_user_id=%s ip=%s", admin_user["user_id"], ip
    )
    return {
        "unblocked": ip,
        "note": "IP unblocked in MongoDB and memory. Remove NSG/Nginx rules manually if applied.",
        "unblocked_by": admin_user["user_id"],
    }


# ── Serialization helper ───────────────────────────────────────────────────────

def _serialize_run(run: dict) -> dict:
    """Convert MongoDB document fields to JSON-serialisable types."""
    import copy
    from datetime import datetime

    result = copy.deepcopy(run)

    def _convert(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(i) for i in obj]
        if isinstance(obj, bytes):
            return "<binary>"
        return obj

    return _convert(result)
