"""
Admin API routes — restricted to users with role=admin.

Endpoints:
  GET  /api/v1/admin/runs                   — Paginated list of all pipeline runs
  GET  /api/v1/admin/runs/{run_id}          — Full run detail (with state_snapshot)
  GET  /api/v1/admin/runs/{run_id}/state    — Raw state snapshot for debugging
  POST /api/v1/admin/runs/{run_id}/cancel   — Mark a stalled run as failed

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
