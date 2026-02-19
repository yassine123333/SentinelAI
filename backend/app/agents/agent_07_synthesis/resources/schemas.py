"""
Pydantic schemas for Agent 07 — Report Synthesis.

Defines:
  - Upstream agent output shapes re-exported from Agent 06 (single source of truth)
  - SynthesisInput  : full validated pipeline bundle Agent 07 receives
  - DashboardPayload: structured JSON payload for the React frontend
  - NarrativeSections: five prose sections produced by Gemini
  - _LLMNarrativeOutput: internal schema for parsing the Gemini response
  - SynthesisOutput : final report bundle Agent 07 returns
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Re-export upstream schemas from the critic (single source of truth) ────────
from app.agents.agent_06_critic.schemas import (
    AssetAnalystOutput,
    CriticOutput,
    GeopoliticalOutput,
    QuantRiskOutput,
    SentimentOutput,
)

__all__ = [
    # re-exported
    "GeopoliticalOutput",
    "SentimentOutput",
    "AssetAnalystOutput",
    "QuantRiskOutput",
    "CriticOutput",
    # synthesis-specific
    "SynthesisInput",
    "RiskGauge",
    "ScenarioProbabilities",
    "AgentConfidenceBar",
    "DashboardPayload",
    "NarrativeSections",
    "SynthesisOutput",
]

# ── Injection guard applied to free-text fields ────────────────────────────────
_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|<\|im_end\|>|</s>|"
    r"\[\[|\]\]|\{\{|\}\}|act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE,
)


def _no_injection(v: str) -> str:
    if _INJECTION_RE.search(v):
        raise ValueError("Forbidden pattern detected — possible prompt injection.")
    return v


# ── Synthesis Input ────────────────────────────────────────────────────────────

class SynthesisInput(BaseModel):
    """Full pipeline bundle that Agent 07 receives."""
    query_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Alphanumeric pipeline run identifier",
    )
    asset: str = Field(
        ...,
        min_length=1,
        max_length=12,
        pattern=r"^[A-Z0-9\^=\.\-]{1,12}$",
        description="Ticker symbol",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Original user query — sanitized before LLM insertion",
    )
    geopolitical: GeopoliticalOutput
    sentiment: SentimentOutput
    asset_analyst: AssetAnalystOutput
    quant_risk: QuantRiskOutput
    critic: CriticOutput

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        return _no_injection(v)


# ── Dashboard Sub-Models ───────────────────────────────────────────────────────

class RiskGauge(BaseModel):
    """Composite risk score for the frontend gauge widget."""
    score: float = Field(..., ge=0.0, le=1.0, description="0 = no risk, 1 = extreme risk")
    level: Literal["low", "medium", "high", "extreme"]
    label: str = Field(..., description="Human-readable label, e.g. 'High Risk'")


class ScenarioProbabilities(BaseModel):
    """Bull / base / bear scenario probabilities — sum to 1.0."""
    bull: float = Field(..., ge=0.0, le=1.0)
    base: float = Field(..., ge=0.0, le=1.0)
    bear: float = Field(..., ge=0.0, le=1.0)


class AgentConfidenceBar(BaseModel):
    """Single bar in the per-agent confidence chart."""
    agent_id: str
    agent_label: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class DashboardPayload(BaseModel):
    """
    Structured JSON payload consumed directly by the React frontend.
    All values are computed deterministically — no LLM involvement.
    """
    meta: dict[str, Any] = Field(
        description="query_id, asset, verdict, overall_confidence, timestamp"
    )
    risk_gauge: RiskGauge
    scenario_probabilities: ScenarioProbabilities
    agent_confidence_chart: list[AgentConfidenceBar]
    key_risks: list[str] = Field(default_factory=list)
    key_opportunities: list[str] = Field(default_factory=list)
    geopolitical: dict[str, Any] = Field(
        description="stability_score, risk_summary, key_events_count, confidence"
    )
    sentiment: dict[str, Any] = Field(
        description="score, fear_greed_index, label, confidence"
    )
    asset: dict[str, Any] = Field(
        description="ticker, current_price, price_trend, key_patterns, confidence"
    )
    quant_risk: dict[str, Any] = Field(
        description="volatility_30d, var_95, risk_level, monte_carlo_scenarios, confidence"
    )
    critic: dict[str, Any] = Field(
        description="verdict, overall_confidence, checks_passed, checks_total"
    )


# ── Narrative Sections ─────────────────────────────────────────────────────────

class NarrativeSections(BaseModel):
    """Five prose paragraphs produced by Gemini 2.5 Flash Standard mode."""
    geopolitical_context: str = Field(
        ..., min_length=100, max_length=1500,
        description="Macro/geopolitical drivers and their market relevance",
    )
    market_sentiment: str = Field(
        ..., min_length=100, max_length=1500,
        description="Investor sentiment, fear/greed dynamics, news signals",
    )
    asset_analysis: str = Field(
        ..., min_length=100, max_length=1500,
        description="Asset-specific technical and fundamental context",
    )
    risk_assessment: str = Field(
        ..., min_length=100, max_length=1500,
        description="Quantitative risk metrics, volatility, VaR, GARCH context",
    )
    scenario_outlook: str = Field(
        ..., min_length=100, max_length=1500,
        description="Probability-weighted bull/base/bear scenario synthesis",
    )


# ── Internal: LLM output schema ───────────────────────────────────────────────

class _LLMNarrativeOutput(BaseModel):
    """Internal schema for parsing the raw Gemini JSON response."""
    executive_summary: str = Field(..., min_length=50, max_length=500)
    narrative_sections: NarrativeSections
    key_risks: list[str] = Field(..., min_length=1, max_length=8)
    key_opportunities: list[str] = Field(default_factory=list, max_length=8)
    reasoning_trace: str = Field(..., min_length=100)


# ── Synthesis Output ───────────────────────────────────────────────────────────

class SynthesisOutput(BaseModel):
    """Full report bundle returned by Agent 07."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    query_id: str
    asset: str
    verdict: str = Field(description="Critic verdict: PASS or FAIL")
    executive_summary: str = Field(description="1–2 sentence TL;DR of the full report")
    narrative_sections: NarrativeSections
    key_risks: list[str]
    key_opportunities: list[str]
    dashboard_payload: DashboardPayload
    # Excluded from JSON serialization — returned as raw bytes for HTTP response
    pdf_bytes: Optional[bytes] = Field(default=None, exclude=True)
    reasoning_trace: str = Field(..., min_length=100)
    timestamp: str

    @field_validator("timestamp")
    @classmethod
    def coerce_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).isoformat()
        return v
