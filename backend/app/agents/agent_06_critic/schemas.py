"""
Pydantic schemas for Agent 06 — Critic & Verifier.

Defines:
  - Upstream agent output shapes (Agents 02–05)
  - CriticInput  : full pipeline bundle Agent 06 receives
  - CriticOutput : verdict + reasoning trace Agent 06 returns
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Injection guard applied to all free-text fields ──────────────────────────
_INJECTION_RE = re.compile(
    r"(ignore\s+previous|disregard\s+all|system\s*:|<\|im_end\|>|</s>|\[\[|\]\]|\{\{|\}\})",
    re.IGNORECASE,
)


def _no_injection(v: str) -> str:
    if _INJECTION_RE.search(v):
        raise ValueError("Forbidden pattern detected — possible prompt injection.")
    return v


# ── Upstream Agent Output Schemas ─────────────────────────────────────────────

class GeopoliticalOutput(BaseModel):
    """Output shape produced by Agent 02."""
    agent_id: Literal["agent_02"] = "agent_02"
    stability_score: float = Field(..., ge=0.0, le=100.0,
                                   description="0 = active war / crisis, 100 = fully stable")
    key_events: list[dict[str, Any]] = Field(default_factory=list)
    macro_indicators: list[dict[str, Any]] = Field(default_factory=list)
    risk_summary: str = Field(..., max_length=3000)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("risk_summary")
    @classmethod
    def sanitize(cls, v: str) -> str:
        return _no_injection(v)


class SentimentOutput(BaseModel):
    """Output shape produced by Agent 03."""
    agent_id: Literal["agent_03"] = "agent_03"
    sentiment_score: float = Field(..., ge=-1.0, le=1.0,
                                   description="-1 = extreme fear, +1 = extreme greed")
    fear_greed_index: float = Field(..., ge=0.0, le=100.0,
                                    description="CNN-style Fear & Greed Index 0–100")
    news_signals: list[dict[str, Any]] = Field(default_factory=list)
    social_signals: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class AssetAnalystOutput(BaseModel):
    """Output shape produced by Agent 04."""
    agent_id: Literal["agent_04"] = "agent_04"
    asset: str = Field(..., max_length=20)
    current_price: float = Field(..., gt=0)
    price_trend: Literal["bullish", "bearish", "neutral"]
    key_patterns: list[str] = Field(default_factory=list)
    short_term_outlook: str = Field(..., max_length=2000)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("short_term_outlook")
    @classmethod
    def sanitize(cls, v: str) -> str:
        return _no_injection(v)


class QuantRiskOutput(BaseModel):
    """Output shape produced by Agent 05."""
    agent_id: Literal["agent_05"] = "agent_05"
    volatility_30d: float = Field(..., ge=0.0,
                                  description="Annualised 30-day vol, e.g. 0.18 = 18 %")
    var_95: float = Field(..., ge=0.0, le=1.0,
                          description="1-day 95 % Value-at-Risk as a decimal, e.g. 0.032 = 3.2 %")
    monte_carlo_scenarios: dict[str, Any] = Field(default_factory=dict,
                                                  description="bull / base / bear probabilities")
    garch_forecast: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "extreme"]
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


# ── Critic Input ──────────────────────────────────────────────────────────────

class CriticInput(BaseModel):
    """Full pipeline bundle that Agent 06 receives."""
    query_id: str = Field(..., min_length=1, max_length=64,
                          pattern=r"^[a-zA-Z0-9_\-]+$",
                          description="Alphanumeric pipeline run identifier")
    asset: str = Field(
        ...,
        min_length=1,
        max_length=12,
        pattern=r"^[A-Z0-9\^=\.\-]{1,12}$",
        description="Ticker symbol — regex whitelist per presentation: [A-Z0-9^=.-]{1,12}",
    )
    attempt: int = Field(default=1, ge=1, le=3,
                         description="1 = first run, 2/3 = retry after correction")
    geopolitical: GeopoliticalOutput
    sentiment: SentimentOutput
    asset_analyst: AssetAnalystOutput
    quant_risk: QuantRiskOutput


# ── Critic Output ─────────────────────────────────────────────────────────────

class CheckResult(BaseModel):
    """Result of a single validation check."""
    check_name: str
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    details: str
    affected_agents: list[str] = Field(default_factory=list)


class RetryInstruction(BaseModel):
    """Actionable correction for a specific agent that failed validation."""
    agent_id: str
    reason: str
    specific_corrections: list[str] = Field(..., min_length=1)
    priority: Literal["critical", "high", "medium"]


class CriticOutput(BaseModel):
    """Full verdict returned by Agent 06."""
    query_id: str
    verdict: Literal["PASS", "FAIL"]
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    checks: list[CheckResult]
    retry_instructions: list[RetryInstruction] = Field(default_factory=list)
    reasoning_trace: str = Field(..., min_length=100,
                                 description="Full chain-of-thought from the LLM — must be ≥ 100 chars")
    flagged_claims: list[str] = Field(default_factory=list)
    sources_verified: int = Field(..., ge=0)
    sources_total: int = Field(..., ge=0)
    timestamp: str

    @field_validator("timestamp")
    @classmethod
    def coerce_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).isoformat()
        return v
