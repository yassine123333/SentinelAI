"""
Pydantic schemas for Agent 04 — Universal Asset Engine.

These models define:
  - What Agent 04 reads from the pipeline state (Agent04Input)
  - What each internal layer produces
  - What Agent 04 writes back to the pipeline state (Agent04Output)

Agent 05 (Critic) consumes Agent04Output directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DataQuality(str, Enum):
    """Overall quality verdict on the fetched price series."""
    OK = "ok"
    SPARSE = "sparse"        # fewer than MIN_REQUIRED_BARS bars
    GAPPED = "gapped"        # one or more large missing-day gaps
    SUSPECT = "suspect"      # outliers / probable split artefacts detected
    FAILED = "failed"        # yfinance returned nothing usable


class VolatilityRegime(str, Enum):
    """Qualitative label derived from GARCH conditional volatility."""
    LOW = "low"          # annualised vol < 15 %
    NORMAL = "normal"    # 15 % – 30 %
    ELEVATED = "elevated"  # 30 % – 50 %
    EXTREME = "extreme"  # > 50 %


class RiskRating(str, Enum):
    """Combined risk rating emitted by the LLM interpretation step."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ModelAgreement(str, Enum):
    """Whether Chronos-2 and GARCH point in the same direction."""
    AGREE_BULLISH = "agree_bullish"
    AGREE_BEARISH = "agree_bearish"
    AGREE_NEUTRAL = "agree_neutral"
    CONFLICT = "conflict"     # one bullish, one bearish / high-uncertainty


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class Agent04Input(BaseModel):
    """Fields read from the LangGraph pipeline state by Agent 04."""

    ticker: str = Field(
        ...,
        description=(
            "Exchange-standard ticker resolved by Agent 01, e.g. 'CL=F', "
            "'GC=F', 'BTC-USD', '^GSPC', 'AAPL'."
        ),
    )
    asset_name: str = Field(
        ...,
        description="Human-readable asset label, e.g. 'Brent Crude Oil'.",
    )
    lookback_days: int = Field(
        default=90,
        ge=30,
        le=365,
        description="Number of calendar days of historical OHLCV to fetch.",
    )
    forecast_horizon: int = Field(
        default=30,
        ge=7,
        le=90,
        description="Number of trading days to project forward.",
    )


# ---------------------------------------------------------------------------
# Layer 1 — Data Fetch
# ---------------------------------------------------------------------------


class OHLCVBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class DataFetchResult(BaseModel):
    ticker: str
    asset_name: str
    bars: list[OHLCVBar]
    close_prices: list[float] = Field(
        description="Ordered closing prices; index 0 is oldest."
    )
    trading_days: int
    quality: DataQuality
    quality_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable notes from the validation step.",
    )

    # Supplementary context — may be empty if unavailable
    vix_current: Optional[float] = Field(
        None, description="Most recent VIX close."
    )
    ovx_current: Optional[float] = Field(
        None, description="Most recent OVX close (energy assets only)."
    )

    # Error path
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Layer 2 — Chronos-2
# ---------------------------------------------------------------------------


class ChronosForecastPath(BaseModel):
    """A single simulated forward path from Chronos-2."""
    values: list[float] = Field(
        description="Projected prices, length == forecast_horizon."
    )


class ChronosResult(BaseModel):
    ticker: str
    forecast_horizon: int
    num_samples: int = Field(description="Always 100.")

    # Aggregate statistics across the 100 paths
    median_path: list[float]
    p10_path: list[float] = Field(description="10th-percentile (downside).")
    p90_path: list[float] = Field(description="90th-percentile (upside).")

    # Terminal-day summary (horizon endpoint)
    median_terminal: float
    p10_terminal: float
    p90_terminal: float
    forecast_spread_pct: float = Field(
        description=(
            "( p90_terminal − p10_terminal ) / current_price × 100. "
            "Wider = higher forecast uncertainty."
        )
    )

    # Signal passed to the LLM and Agent 05
    uncertainty_score: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Normalised uncertainty: spread_pct mapped to [0, 1] using "
            "asset-class heuristics."
        ),
    )
    directional_bias: str = Field(
        description=(
            "One of: 'bullish', 'bearish', 'neutral' — "
            "based on median_terminal vs current_price."
        )
    )

    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Layer 3 — GARCH + Monte Carlo
# ---------------------------------------------------------------------------


class GARCHParams(BaseModel):
    omega: float
    alpha: float   # ARCH coefficient
    beta: float    # GARCH coefficient
    persistence: float = Field(description="alpha + beta; near 1 = long memory.")


class GARCHResult(BaseModel):
    ticker: str

    # Model fit
    params: GARCHParams
    model_converged: bool
    aic: float
    bic: float

    # Volatility surface
    current_annualised_vol: float = Field(
        description="Current conditional volatility, annualised (%)."
    )
    vol_regime: VolatilityRegime = Field(
        description=(
            "Qualitative regime label. Accounts for both the current vol level "
            "and the persistence parameter — near-IGARCH processes are elevated "
            "by one tier regardless of spot vol."
        )
    )
    vol_forecast_daily: list[float] = Field(
        description=(
            "GARCH-projected daily conditional vol (%) for each forecast day."
        )
    )
    igarch_warning: bool = Field(
        default=False,
        description=(
            "True when α+β ≥ 0.98, indicating near-Integrated GARCH behaviour: "
            "volatility shocks are effectively permanent and variance is "
            "non-stationary. The regime label has been elevated one tier to "
            "reflect this structural instability."
        ),
    )

    error: Optional[str] = None


class MonteCarloResult(BaseModel):
    ticker: str
    num_simulations: int = Field(description="Always 5 000.")
    forecast_horizon: int

    # Scenario distribution at terminal day
    mean_return_pct: float
    median_return_pct: float
    p5_return_pct: float   = Field(description="5th-percentile (left tail).")
    p95_return_pct: float  = Field(description="95th-percentile (right tail).")

    # Drawdown statistics (worst intra-path drawdown across horizon)
    prob_drawdown_5pct: float  = Field(description="P(max drawdown ≥ 5%).")
    prob_drawdown_10pct: float = Field(description="P(max drawdown ≥ 10%).")
    prob_drawdown_20pct: float = Field(description="P(max drawdown ≥ 20%).")

    # Upside statistics
    prob_gain_5pct: float  = Field(description="P(terminal gain ≥ 5%).")
    prob_gain_10pct: float = Field(description="P(terminal gain ≥ 10%).")

    error: Optional[str] = None


# ---------------------------------------------------------------------------
# LLM Interpretation
# ---------------------------------------------------------------------------


class LLMInterpretation(BaseModel):
    """Output of Gemini 2.5 Flash thinking-mode reasoning step."""

    model_agreement: ModelAgreement
    risk_rating: RiskRating

    key_findings: list[str] = Field(
        description="3–5 bullet-point findings the LLM derived."
    )
    tensions: list[str] = Field(
        default_factory=list,
        description=(
            "Any conflicts between models or data-quality issues "
            "the LLM flagged."
        ),
    )
    reasoning_trace: str = Field(
        description=(
            "Full chain-of-thought from the thinking step, "
            "attached to the PDF report."
        )
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="LLM self-assessed confidence in the overall assessment.",
    )


# ---------------------------------------------------------------------------
# Final Agent 04 Output (written to pipeline state)
# ---------------------------------------------------------------------------


class Agent04Output(BaseModel):
    """
    Complete output written by Agent 04 to the LangGraph pipeline state.
    Consumed by Agent 05 (Critic & Verifier).
    """

    input: Agent04Input

    # Layer results
    data: DataFetchResult
    chronos: Optional[ChronosResult] = None
    garch: Optional[GARCHResult] = None
    monte_carlo: Optional[MonteCarloResult] = None

    # LLM synthesis
    interpretation: Optional[LLMInterpretation] = None

    # Top-level status
    success: bool
    pipeline_error: Optional[str] = Field(
        None,
        description=(
            "If set, Agent 05 should treat this agent's output as unreliable "
            "and flag accordingly."
        ),
    )
