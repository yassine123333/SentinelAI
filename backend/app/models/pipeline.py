"""
Pipeline API models — Pydantic v2.

Schemas for the pipeline REST API layer:
  QueryRequest         — POST /api/v1/query   (incoming request body)
  QueryResponse        — 202 Accepted response with run_id
  PipelineStatusResponse — GET /api/v1/pipeline/{run_id}/status
  ReportResponse       — GET /api/v1/report/{run_id}  (JSON report)
  AdminRunItem         — single run summary for admin list endpoint
  AdminRunListResponse — paginated admin run list

Security:
  - raw_query max 500 chars, injection-checked
  - asset_hint enforces ticker whitelist regex [A-Z0-9^=.-]{1,12}
  - timeframe and risk_focus validated against allowed values
  - All validators raise ValueError to return HTTP 422 automatically
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Shared validation constants ───────────────────────────────────────────────

_TICKER_RE = re.compile(r"^[A-Z0-9\^=\.\-]{1,12}$")

_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|"
    r"<\|im_end\|>|</s>|act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE | re.DOTALL,
)

_ALLOWED_TIMEFRAMES = {
    "1d", "1w", "1m", "3m", "6m", "1y", "ytd", "short", "medium", "long",
}

_ALLOWED_RISK_FOCUSES = {
    "geopolitical", "technical", "fundamental", "macro",
    "volatility", "sentiment", "credit", "liquidity", "regulatory",
    "operational", "currency", "commodity", "general",
}


def _no_injection(v: str) -> str:
    if _INJECTION_RE.search(v[:2000]):
        raise ValueError("Input contains a forbidden pattern.")
    return v


# ── Request schemas ───────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """
    POST /api/v1/query — submit a new pipeline analysis request.

    All free-text fields are injection-checked.
    Structured fields use whitelist validation.
    """

    raw_query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language query, e.g. 'Analyse gold amid rising geopolitical risk'",
        examples=["What is the risk outlook for BTC-USD over the next 30 days?"],
    )
    asset_hint: str | None = Field(
        default=None,
        description="Optional explicit ticker override, e.g. 'GC=F', 'BTC-USD', '^GSPC'",
        examples=["BTC-USD"],
    )
    timeframe_hint: str | None = Field(
        default=None,
        description=f"Optional timeframe override. Allowed: {sorted(_ALLOWED_TIMEFRAMES)}",
        examples=["1m"],
    )
    risk_focus_hint: str | None = Field(
        default=None,
        description=f"Optional risk focus override. Allowed: {sorted(_ALLOWED_RISK_FOCUSES)}",
        examples=["geopolitical"],
    )

    @field_validator("raw_query")
    @classmethod
    def validate_raw_query(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("raw_query must be at least 3 characters.")
        return _no_injection(v)

    @field_validator("asset_hint")
    @classmethod
    def validate_asset_hint(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError(
                f"asset_hint '{v}' does not match ticker format [A-Z0-9^=.-]{{1,12}}. "
                "Examples: GC=F, BTC-USD, ^GSPC, AAPL, BRN=F"
            )
        return v

    @field_validator("timeframe_hint")
    @classmethod
    def validate_timeframe_hint(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _ALLOWED_TIMEFRAMES:
            raise ValueError(
                f"timeframe_hint '{v}' is not allowed. "
                f"Must be one of: {sorted(_ALLOWED_TIMEFRAMES)}"
            )
        return v

    @field_validator("risk_focus_hint")
    @classmethod
    def validate_risk_focus_hint(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in _ALLOWED_RISK_FOCUSES:
            raise ValueError(
                f"risk_focus_hint '{v}' is not allowed. "
                f"Must be one of: {sorted(_ALLOWED_RISK_FOCUSES)}"
            )
        return v


# ── Response schemas ──────────────────────────────────────────────────────────

class QueryResponse(BaseModel):
    """202 Accepted — pipeline run started."""

    run_id: str = Field(..., description="Unique identifier for this pipeline run")
    status: Literal["pending"] = "pending"
    message: str = Field(
        default="Pipeline run started. Poll /api/v1/pipeline/{run_id}/status for updates.",
        description="Human-readable status message",
    )
    created_at: datetime


class PipelineStatusResponse(BaseModel):
    """GET /api/v1/pipeline/{run_id}/status — lightweight poll endpoint."""

    run_id: str
    status: Literal["pending", "running", "done", "failed"]
    asset: str | None = None
    timeframe: str | None = None
    risk_focus: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class ReportResponse(BaseModel):
    """
    GET /api/v1/report/{run_id} — full JSON report.

    Contains the complete synthesis output: dashboard payload, narrative
    sections, key risks/opportunities, and the critic verdict.
    """

    run_id: str
    asset: str | None = None
    status: str

    # Synthesis output (None until pipeline is done)
    executive_summary: str | None = None
    verdict: str | None = None
    overall_confidence: float | None = None

    dashboard_payload: dict[str, Any] | None = None
    narrative_sections: dict[str, str] | None = None
    key_risks: list[str] | None = None
    key_opportunities: list[str] | None = None
    reasoning_trace: str | None = None

    # Critic meta
    critic: dict[str, Any] | None = None

    created_at: datetime
    completed_at: datetime | None = None

    # True if a PDF is available at /api/v1/report/{run_id}/pdf
    pdf_available: bool = False


class AdminRunItem(BaseModel):
    """Single pipeline run summary for admin list view."""

    run_id: str
    user_id: str
    raw_query: str
    asset: str | None = None
    timeframe: str | None = None
    risk_focus: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None


class AdminRunListResponse(BaseModel):
    """Paginated admin run list."""

    items: list[AdminRunItem]
    total_returned: int
    skip: int
    limit: int


class UserRunItem(BaseModel):
    """
    Single pipeline run summary for the authenticated user's history.
    Excludes user_id and state_snapshot — user already owns the session context.
    """

    run_id: str
    raw_query: str
    asset: str | None = None
    timeframe: str | None = None
    risk_focus: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
