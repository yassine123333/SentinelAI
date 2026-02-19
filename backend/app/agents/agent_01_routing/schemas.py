"""
Pydantic schemas for Agent 01 — Intake & Routing.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Injection guard ────────────────────────────────────────────────────────────
_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|<\|im_end\|>|"
    r"</s>|act\s+as\s+.*(different|new)\s+(ai|llm|model)|"
    r"\$\{|`.*`|\bexec\b|\beval\b|\bdrop\s+table\b)",
    re.IGNORECASE | re.DOTALL,
)

# ── Ticker whitelist ───────────────────────────────────────────────────────────
_TICKER_RE = re.compile(r"^[A-Z0-9\^=\.\-]{1,12}$")


def _check_injection(v: str) -> str:
    if _INJECTION_RE.search(v):
        raise ValueError("Forbidden pattern detected in query — possible injection attempt.")
    return v


class RoutingInput(BaseModel):
    """Validated query bundle entering the pipeline."""
    raw_query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural-language risk query from the user",
    )
    asset_hint: str | None = Field(
        default=None,
        max_length=12,
        pattern=r"^[A-Z0-9\^=\.\-]{1,12}$",
        description="Optional explicit ticker override from the UI",
    )
    timeframe_hint: str | None = Field(
        default=None,
        max_length=40,
        description="Optional explicit time horizon override",
    )
    risk_focus_hint: str | None = Field(
        default=None,
        max_length=80,
        description="Optional explicit risk focus override",
    )

    @field_validator("raw_query")
    @classmethod
    def no_injection(cls, v: str) -> str:
        return _check_injection(v)

    @field_validator("risk_focus_hint")
    @classmethod
    def no_injection_focus(cls, v: str | None) -> str | None:
        if v:
            return _check_injection(v)
        return v


class RoutingOutput(BaseModel):
    """Normalised routing decision produced by Agent 01."""
    asset: str = Field(
        ..., pattern=r"^[A-Z0-9\^=\.\-]{1,12}$",
        description="Resolved ticker symbol",
    )
    timeframe: str = Field(..., description="Resolved time horizon, e.g. '30 days'")
    risk_focus: str = Field(..., description="Resolved risk focus, e.g. 'volatility'")
    keywords: list[str] = Field(
        default_factory=list,
        description="Extracted search keywords for downstream agents",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    routing_source: Literal["hint_override", "extracted", "default"] = "extracted"
