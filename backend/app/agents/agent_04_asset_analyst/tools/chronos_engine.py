"""
Layer 2 — Chronos-2 Forecasting Engine for Agent 04.

What Chronos-2 is:
  Amazon's pre-trained time-series foundation model (chronos-t5-small).
  It was trained on abstract curve behaviour — not financial data specifically.
  It reads pure sequence shape and outputs a distribution of future paths.

What this module does:
  1. Accepts the raw closing-price list from the data fetcher
  2. Runs Chronos-2 to generate 100 independent forward simulations
  3. Extracts median / P10 / P90 paths and terminal statistics
  4. Computes a normalised uncertainty score and directional bias

Why chronos-t5-small (not base/large):
  - Runs on CPU in ~3–8 seconds for 90-day input / 30-day output
  - No GPU required for the production pipeline
  - Accuracy difference vs. base is marginal for risk-range estimation

The model weights are cached to disk after the first download (~250 MB).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from ..resources.schemas import ChronosResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHRONOS_MODEL_ID = "amazon/chronos-t5-small"
NUM_SAMPLES = 100

# ---------------------------------------------------------------------------
# Module-level pipeline singleton
# Loaded once per process; reused across all ticker calls.
# Avoids reloading 250 MB weights on every forecast request.
# ---------------------------------------------------------------------------
_PIPELINE = None


def _get_pipeline(torch):
    global _PIPELINE
    if _PIPELINE is None:
        logger.info("Loading Chronos pipeline (first call — subsequent calls reuse cache)")
        from chronos import ChronosPipeline  # noqa: PLC0415
        _PIPELINE = ChronosPipeline.from_pretrained(
            CHRONOS_MODEL_ID,
            device_map="cpu",
            dtype=torch.float32,
        )
    return _PIPELINE

# Asset-class heuristics for normalising spread_pct → [0, 1]
# spread_pct >= HIGH_SPREAD_PCT → uncertainty_score = 1.0
# spread_pct == 0               → uncertainty_score = 0.0
HIGH_SPREAD_PCT = 40.0   # ~40 % spread covers most extreme assets (crypto)

# Directional bias thresholds (relative to current price)
BULLISH_THRESHOLD = 0.005   # median terminal > +0.5 %
BEARISH_THRESHOLD = -0.005  # median terminal < -0.5 %


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_chronos_forecast(
    ticker: str,
    close_prices: list[float],
    forecast_horizon: int = 30,
) -> ChronosResult:
    """
    Run Chronos-2 on *close_prices* and return a ChronosResult.

    Parameters
    ----------
    ticker          : Used only for metadata / logging.
    close_prices    : Ordered list of closing prices (oldest first).
    forecast_horizon: Number of trading days to project forward.

    Returns
    -------
    ChronosResult — on error, fields are set to safe defaults and
    result.error is populated.
    """
    if len(close_prices) < 10:
        return _error_result(ticker, forecast_horizon, "Too few prices for Chronos-2.")

    try:
        import torch  # noqa: PLC0415
        from chronos import ChronosPipeline  # noqa: PLC0415
    except ImportError as exc:
        return _error_result(
            ticker, forecast_horizon,
            f"Chronos dependencies not installed: {exc}. "
            "Run: pip install chronos-forecasting torch"
        )

    try:
        pipeline = _load_pipeline(torch)
        forecast_tensor = _predict(
            pipeline, torch, close_prices, forecast_horizon
        )
        return _build_result(ticker, close_prices, forecast_horizon, forecast_tensor)

    except Exception as exc:
        logger.error("Chronos-2 forecast failed for %s: %s", ticker, exc)
        return _error_result(ticker, forecast_horizon, str(exc))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_pipeline(torch):
    """Return the singleton Chronos pipeline, initialising it on first call."""
    return _get_pipeline(torch)


def _predict(pipeline, torch, close_prices: list[float], horizon: int):
    """
    Run inference.

    Returns a tensor of shape (1, num_samples, horizon):
      dim 0 → batch size (always 1 here)
      dim 1 → num_samples
      dim 2 → forecast steps
    """
    # context is positional in chronos-forecasting >= 1.x
    context = torch.tensor(close_prices, dtype=torch.float32).unsqueeze(0)
    forecast = pipeline.predict(
        context,
        prediction_length=horizon,
        num_samples=NUM_SAMPLES,
        temperature=1.0,   # maintains calibrated uncertainty
        top_k=50,
        top_p=1.0,
    )
    return forecast   # shape: (1, 100, horizon)


def _build_result(
    ticker: str,
    close_prices: list[float],
    horizon: int,
    forecast_tensor,
) -> ChronosResult:
    """
    Convert the raw Chronos tensor to a ChronosResult.
    """
    import torch  # noqa: PLC0415

    current_price = close_prices[-1]

    # forecast_tensor: (1, 100, horizon) → (100, horizon)
    samples = forecast_tensor.squeeze(0).numpy()  # (100, horizon)

    # Per-step statistics
    median_path = np.quantile(samples, 0.50, axis=0).tolist()
    p10_path    = np.quantile(samples, 0.10, axis=0).tolist()
    p90_path    = np.quantile(samples, 0.90, axis=0).tolist()

    # Terminal-day statistics (last step)
    median_terminal = float(np.quantile(samples[:, -1], 0.50))
    p10_terminal    = float(np.quantile(samples[:, -1], 0.10))
    p90_terminal    = float(np.quantile(samples[:, -1], 0.90))

    # Uncertainty metrics
    spread_pct = (
        (p90_terminal - p10_terminal) / current_price * 100
        if current_price > 0
        else 0.0
    )
    uncertainty_score = float(
        np.clip(spread_pct / HIGH_SPREAD_PCT, 0.0, 1.0)
    )

    # Directional bias from median
    rel_change = (median_terminal - current_price) / current_price
    if rel_change > BULLISH_THRESHOLD:
        directional_bias = "bullish"
    elif rel_change < BEARISH_THRESHOLD:
        directional_bias = "bearish"
    else:
        directional_bias = "neutral"

    logger.info(
        "Chronos forecast for %s | bias=%s | spread=%.1f%% | uncertainty=%.2f",
        ticker, directional_bias, spread_pct, uncertainty_score,
    )

    return ChronosResult(
        ticker=ticker,
        forecast_horizon=horizon,
        num_samples=NUM_SAMPLES,
        median_path=median_path,
        p10_path=p10_path,
        p90_path=p90_path,
        median_terminal=median_terminal,
        p10_terminal=p10_terminal,
        p90_terminal=p90_terminal,
        forecast_spread_pct=round(spread_pct, 4),
        uncertainty_score=round(uncertainty_score, 4),
        directional_bias=directional_bias,
        error=None,
    )


def _error_result(
    ticker: str, horizon: int, error: str
) -> ChronosResult:
    """Return a safe-default ChronosResult with an error message."""
    return ChronosResult(
        ticker=ticker,
        forecast_horizon=horizon,
        num_samples=0,
        median_path=[],
        p10_path=[],
        p90_path=[],
        median_terminal=0.0,
        p10_terminal=0.0,
        p90_terminal=0.0,
        forecast_spread_pct=0.0,
        uncertainty_score=0.5,   # unknown → treat as moderate uncertainty
        directional_bias="neutral",
        error=error,
    )
