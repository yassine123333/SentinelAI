"""
Pipeline API routes.

Endpoints:
  POST   /api/v1/query                        — Submit a new analysis query
  GET    /api/v1/pipeline/{run_id}/status     — Poll run status (lightweight)
  GET    /api/v1/report/{run_id}              — Full JSON report
  GET    /api/v1/report/{run_id}/pdf          — Download PDF report

Security:
  - All endpoints require valid JWT (Bearer token)
  - Ownership check: users may only access their own runs (get_run_for_user)
  - Admin role bypasses ownership check (is_admin flag)
  - Rate limiting:
      POST /query: 10/minute per IP (global) + 50/hour per user (per-user guard)
      GET  endpoints: 60/minute per IP (generous for polling)
  - NoSQL injection: all DB queries use parameterised Motor form
  - Pipeline run_id uses secrets.token_urlsafe (128-bit entropy)
  - Background task: pipeline runs async without blocking the HTTP response
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_current_user
from app.db.mongodb import get_db
from app.models.pipeline import (
    QueryRequest,
    QueryResponse,
    PipelineStatusResponse,
    ReportResponse,
    UserRunItem,
)
from app.pipeline import store as pipeline_store
from app.pipeline.graph import run_pipeline
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Per-user rate limit helper ─────────────────────────────────────────────────
# slowapi key_func for per-user limiting on POST /query.
# Falls back to IP address for unauthenticated requests (which will fail
# the JWT check anyway — this just prevents key errors).

limiter = Limiter(key_func=get_remote_address)


def _user_key(request: Request) -> str:
    """Return user_id from state if set (by dependency), else fall back to IP."""
    uid = getattr(request.state, "pipeline_user_id", None)
    if uid:
        return f"user:{uid}"
    return get_remote_address(request)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _run_pipeline_bg(
    run_id: str,
    user_id: str,
    raw_query: str,
    asset_hint: str | None,
    timeframe_hint: str | None,
    risk_focus_hint: str | None,
) -> None:
    """
    Background task: update status to 'running', execute the pipeline,
    persist the final state.  Never raises — errors are persisted to DB.
    """
    db = get_db()
    try:
        await pipeline_store.update_run_status(db, run_id, "running")

        initial_state: PipelineState = {
            "run_id": run_id,
            "user_id": user_id,
            "raw_query": raw_query,
            # Hints passed to node_intake (Agent 01) so it can guide extraction
            "asset_hint": asset_hint or None,
            "timeframe_hint": timeframe_hint or None,
            "risk_focus_hint": risk_focus_hint or None,
            # These will be overwritten by node_intake with parsed values
            "asset": asset_hint or "",
            "timeframe": timeframe_hint or "",
            "risk_focus": risk_focus_hint or "",
            "keywords": [],
            "routing_confidence": 0.0,
            "geopolitical": {},
            "sentiment": {},
            "asset_analyst": {},
            "critic": {},
            "critic_attempt": 1,  # CriticInput.attempt requires ge=1
            "synthesis": {},
            "pdf_bytes": None,
            "status": "running",
            "started_at": _now().isoformat(),
            "error_message": None,
            "reasoning_trace": [],
        }

        final_state = await run_pipeline(initial_state, db)

        # Determine terminal status
        final_status = final_state.get("status", "done")
        if final_status not in {"done", "failed"}:
            final_status = "done"

        # Persist PDF bytes separately (binary, excluded from state_snapshot)
        pdf_bytes: bytes | None = final_state.get("pdf_bytes")
        if pdf_bytes:
            await pipeline_store.store_pdf(db, run_id, pdf_bytes)

        await pipeline_store.save_state_snapshot(
            db,
            run_id=run_id,
            status=final_status,
            state_snapshot=dict(final_state),
            error_message=final_state.get("error_message"),
        )

        logger.info(
            "pipeline run completed run_id=%s user_id=%s status=%s",
            run_id, user_id, final_status,
        )
    except Exception as exc:
        logger.error(
            "pipeline background task unhandled error run_id=%s: %s",
            run_id, exc, exc_info=True,
        )
        try:
            db = get_db()
            await pipeline_store.save_state_snapshot(
                db,
                run_id=run_id,
                status="failed",
                state_snapshot={},
                error_message=f"Unhandled background error: {exc!s}"[:2000],
            )
        except Exception:
            pass  # DB may be unavailable — best-effort


def _build_report_response(run: dict) -> ReportResponse:
    """Convert a MongoDB pipeline_runs document to a ReportResponse."""
    snap: dict = run.get("state_snapshot", {})
    synthesis: dict = snap.get("synthesis", {})
    critic: dict = snap.get("critic", {})

    # Check if a PDF was stored
    # We don't fetch binary here — just signal availability
    pdf_available = False  # updated by the endpoint

    return ReportResponse(
        run_id=run["run_id"],
        asset=run.get("asset"),
        status=run.get("status", "pending"),
        executive_summary=synthesis.get("executive_summary"),
        verdict=synthesis.get("verdict") or critic.get("verdict"),
        overall_confidence=critic.get("overall_confidence"),
        dashboard_payload=synthesis.get("dashboard_payload"),
        narrative_sections=(
            synthesis.get("narrative_sections")
            if isinstance(synthesis.get("narrative_sections"), dict)
            else None
        ),
        key_risks=synthesis.get("key_risks"),
        key_opportunities=synthesis.get("key_opportunities"),
        reasoning_trace=synthesis.get("reasoning_trace"),
        critic={
            "verdict": critic.get("verdict"),
            "overall_confidence": critic.get("overall_confidence"),
            "checks_passed": critic.get("checks_passed"),
            "checks_total": critic.get("checks_total"),
            "retry_count": snap.get("critic_attempt", 0),
        } if critic else None,
        created_at=run["created_at"],
        completed_at=run.get("completed_at"),
        pdf_available=pdf_available,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "/history",
    response_model=list[UserRunItem],
    summary="List the authenticated user's recent pipeline runs",
    description=(
        "Returns up to 20 of the user's most recent pipeline runs (newest first), "
        "without state_snapshot. Use this to populate the Recent Analyses panel."
    ),
)
@limiter.limit("30/minute")
async def list_user_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    skip: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> list[UserRunItem]:
    user_id: str = current_user["user_id"]

    runs = await pipeline_store.list_runs_for_user(
        db, user_id=user_id, limit=limit, skip=skip
    )

    return [
        UserRunItem(
            run_id=r["run_id"],
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


@router.post(
    "/query",
    response_model=QueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a new analysis query",
    description=(
        "Starts a new pipeline run for the authenticated user. "
        "Returns immediately with run_id — poll /pipeline/{run_id}/status for progress."
    ),
)
@limiter.limit("50/hour", key_func=_user_key)        # 50/hr per user
@limiter.limit("10/minute", key_func=get_remote_address)  # 10/min per IP (global guard)
async def submit_query(
    request: Request,
    body: QueryRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> QueryResponse:
    user_id: str = current_user["user_id"]

    # Expose user_id to key_func for per-user limiting
    request.state.pipeline_user_id = user_id

    # Generate a unique run_id with 128-bit entropy
    run_id = secrets.token_urlsafe(16)

    # Create the pending run document in MongoDB
    doc = await pipeline_store.create_run(
        db=db,
        run_id=run_id,
        user_id=user_id,
        raw_query=body.raw_query,
    )

    logger.info(
        "pipeline query submitted run_id=%s user_id=%s asset_hint=%s",
        run_id, user_id, body.asset_hint,
    )

    # Kick off the full pipeline as a background task
    background_tasks.add_task(
        _run_pipeline_bg,
        run_id=run_id,
        user_id=user_id,
        raw_query=body.raw_query,
        asset_hint=body.asset_hint,
        timeframe_hint=body.timeframe_hint,
        risk_focus_hint=body.risk_focus_hint,
    )

    return QueryResponse(
        run_id=run_id,
        status="pending",
        created_at=doc["created_at"],
    )


@router.get(
    "/pipeline/{run_id}/status",
    response_model=PipelineStatusResponse,
    summary="Poll pipeline run status",
    description="Lightweight poll endpoint — returns only status fields, not the full report.",
)
@limiter.limit("60/minute")
async def get_run_status(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> PipelineStatusResponse:
    user_id: str = current_user["user_id"]
    is_admin: bool = current_user.get("role") == "admin"

    run = await pipeline_store.get_run_for_user(
        db, run_id=run_id, user_id=user_id, is_admin=is_admin
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found or access denied.",
        )

    return PipelineStatusResponse(
        run_id=run["run_id"],
        status=run.get("status", "pending"),
        asset=run.get("asset"),
        timeframe=run.get("timeframe"),
        risk_focus=run.get("risk_focus"),
        created_at=run["created_at"],
        updated_at=run["updated_at"],
        completed_at=run.get("completed_at"),
        error_message=run.get("error_message"),
    )


@router.get(
    "/report/{run_id}",
    response_model=ReportResponse,
    summary="Get full JSON report for a completed run",
    description=(
        "Returns the full synthesis output including dashboard payload, narrative sections, "
        "key risks/opportunities, and the critic verdict. "
        "Returns 404 if the run does not exist or is not owned by the caller. "
        "Returns 202 if the run is still in progress."
    ),
)
@limiter.limit("60/minute")
async def get_report(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> ReportResponse:
    user_id: str = current_user["user_id"]
    is_admin: bool = current_user.get("role") == "admin"

    run = await pipeline_store.get_run_for_user(
        db, run_id=run_id, user_id=user_id, is_admin=is_admin
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found or access denied.",
        )

    if run.get("status") in {"pending", "running"}:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail=f"Pipeline run is still in progress (status={run.get('status')}). "
                   "Poll /pipeline/{run_id}/status and retry when status=done.",
        )

    response = _build_report_response(run)

    # Check if a PDF is stored
    pdf_doc = await db["pipeline_pdfs"].find_one({"run_id": run_id}, {"_id": 0, "run_id": 1})
    response = response.model_copy(update={"pdf_available": pdf_doc is not None})

    return response


@router.get(
    "/report/{run_id}/pdf",
    summary="Download PDF report",
    description=(
        "Returns the PDF binary for a completed run. "
        "Content-Type: application/pdf. "
        "Returns 404 if PDF was not generated (WeasyPrint unavailable or run failed)."
    ),
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF report binary",
        },
        404: {"description": "PDF not found for this run"},
    },
)
@limiter.limit("20/minute")
async def get_report_pdf(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> Response:
    user_id: str = current_user["user_id"]
    is_admin: bool = current_user.get("role") == "admin"

    # Ownership check first
    run = await pipeline_store.get_run_for_user(
        db, run_id=run_id, user_id=user_id, is_admin=is_admin
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found or access denied.",
        )

    if run.get("status") not in {"done", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Pipeline run is still in progress.",
        )

    pdf_bytes = await pipeline_store.get_pdf(db, run_id)
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF report not available for this run. "
                   "PDF generation may have failed or WeasyPrint is not installed.",
        )

    asset = run.get("asset", "report")
    filename = f"sentinelai_{asset}_{run_id[:8]}.pdf".lower()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",  # don't cache financial reports
        },
    )
