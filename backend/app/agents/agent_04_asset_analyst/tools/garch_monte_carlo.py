"""
Layer 3 — GARCH(1,1) Volatility Model + Monte Carlo Simulation.

Two complementary analyses:

GARCH(1,1)
  Fits a Generalised Autoregressive Conditional Heteroskedasticity model to
  the log-return series.  Key insight: volatility is not constant — it
  clusters.  GARCH captures the current regime (calm vs. volatile) and
  projects how it will evolve over the forecast horizon.

Monte Carlo
  Runs 5 000 forward price simulations using the GARCH-projected volatility
  schedule rather than a fixed number.  This means the simulations reflect
  the current market regime rather than a long-run average, which produces
  more realistic tail probabilities.

Output to Agent 05:
  - Current annualised volatility + qualitative regime label
  - GARCH-projected daily vol for each forecast day
  - Scenario distribution: P5/P95 return, drawdown probabilities, upside probs
"""

from __future__ import annotations

import logging

import numpy as np

from ..resources.schemas import (
    GARCHParams,
    GARCHResult,
    MonteCarloResult,
    VolatilityRegime,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_SIMULATIONS = 5_000
TRADING_DAYS_PER_YEAR = 252

# Annualised vol thresholds for VolatilityRegime classification
_REGIME_THRESHOLDS = {
    VolatilityRegime.LOW:      (0.0,  15.0),
    VolatilityRegime.NORMAL:   (15.0, 30.0),
    VolatilityRegime.ELEVATED: (30.0, 50.0),
    VolatilityRegime.EXTREME:  (50.0, float("inf")),
}


# ---------------------------------------------------------------------------
# GARCH public entry point
# ---------------------------------------------------------------------------


def run_garch(
    ticker: str,
    close_prices: list[float],
    forecast_horizon: int = 30,
) -> GARCHResult:
    """
    Fit GARCH(1,1) to the log-return series of *close_prices*.

    Returns a GARCHResult; on failure, result.error is set and safe
    defaults are used so the Monte Carlo step can still run with a
    fallback volatility estimate.
    """
    if len(close_prices) < 20:
        return _garch_error(ticker, "Too few prices for GARCH (need ≥ 20).")

    try:
        from arch import arch_model  # noqa: PLC0415
    except ImportError as exc:
        return _garch_error(
            ticker,
            f"'arch' package not installed: {exc}. Run: pip install arch",
        )

    try:
        returns = _log_returns_pct(close_prices)

        model = arch_model(
            returns,
            vol="Garch",
            p=1,
            q=1,
            mean="Constant",
            dist="normal",
        )
        fit = model.fit(disp="off", show_warning=False)

        # Extract parameters — arch labels vary by version:
        # older: "alpha[1]" / "beta[1]",  newer: "alpha1" / "beta1"
        params = fit.params
        omega = float(params["omega"])
        alpha = float(
            params["alpha[1]"] if "alpha[1]" in params.index
            else params.get("alpha1", 0.0)
        )
        beta = float(
            params["beta[1]"] if "beta[1]" in params.index
            else params.get("beta1", 0.0)
        )
        persistence = alpha + beta

        # Current conditional variance (last in-sample value)
        # conditional_volatility may be a numpy array or pandas Series
        # depending on arch version — use flat indexing to handle both
        cond_vol = fit.conditional_volatility
        current_daily_vol_pct = float(np.sqrt(np.asarray(cond_vol).flat[-1]))
        current_annual_vol = _annualise(current_daily_vol_pct)

        # Forward variance forecast via ARCH package
        fc = fit.forecast(horizon=forecast_horizon, reindex=False)
        daily_vol_forecast = [
            float(np.sqrt(v)) for v in np.asarray(fc.variance).flat[-forecast_horizon:]
        ]

        regime = _classify_regime(current_annual_vol)

        logger.info(
            "GARCH(%s) | alpha=%.4f beta=%.4f persistence=%.4f | "
            "current_ann_vol=%.1f%% | regime=%s",
            ticker, alpha, beta, persistence, current_annual_vol, regime.value,
        )

        return GARCHResult(
            ticker=ticker,
            params=GARCHParams(
                omega=round(omega, 8),
                alpha=round(alpha, 6),
                beta=round(beta, 6),
                persistence=round(persistence, 6),
            ),
            model_converged=True,
            aic=round(float(fit.aic), 4),
            bic=round(float(fit.bic), 4),
            current_annualised_vol=round(current_annual_vol, 4),
            vol_regime=regime,
            vol_forecast_daily=[round(v, 6) for v in daily_vol_forecast],
            error=None,
        )

    except Exception as exc:
        logger.error("GARCH fitting failed for %s: %s", ticker, exc)
        return _garch_error(ticker, str(exc))


# ---------------------------------------------------------------------------
# Monte Carlo public entry point
# ---------------------------------------------------------------------------


def run_monte_carlo(
    ticker: str,
    close_prices: list[float],
    garch_result: GARCHResult,
    forecast_horizon: int = 30,
) -> MonteCarloResult:
    """
    Run N_SIMULATIONS forward price paths using the GARCH volatility schedule.

    If GARCH failed, falls back to a rolling historical volatility estimate
    so the simulation still runs with degraded but usable inputs.

    Parameters
    ----------
    ticker          : Metadata / logging only.
    close_prices    : Historical close prices (oldest first).
    garch_result    : Output of run_garch(); may contain an error.
    forecast_horizon: Number of days to simulate forward.
    """
    current_price = close_prices[-1]
    returns = _log_returns_pct(close_prices)
    mu = float(np.mean(returns))  # historical mean daily return (%)

    # Build the per-day vol schedule
    if garch_result.error is None and garch_result.vol_forecast_daily:
        daily_vols = np.array(garch_result.vol_forecast_daily[:forecast_horizon])
    else:
        # Fallback: constant historical vol
        hist_vol = float(np.std(returns))
        daily_vols = np.full(forecast_horizon, hist_vol)
        logger.warning(
            "Monte Carlo for %s using fallback constant vol=%.4f%%",
            ticker, hist_vol,
        )

    try:
        paths = _simulate_paths(current_price, mu, daily_vols, forecast_horizon)
        return _build_mc_result(ticker, current_price, paths, forecast_horizon)

    except Exception as exc:
        logger.error("Monte Carlo failed for %s: %s", ticker, exc)
        return MonteCarloResult(
            ticker=ticker,
            num_simulations=0,
            forecast_horizon=forecast_horizon,
            mean_return_pct=0.0,
            median_return_pct=0.0,
            p5_return_pct=0.0,
            p95_return_pct=0.0,
            prob_drawdown_5pct=0.0,
            prob_drawdown_10pct=0.0,
            prob_drawdown_20pct=0.0,
            prob_gain_5pct=0.0,
            prob_gain_10pct=0.0,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log_returns_pct(prices: list[float]) -> np.ndarray:
    """Compute log-returns in percentage from a list of closing prices."""
    arr = np.array(prices, dtype=float)
    return np.diff(np.log(arr)) * 100.0


def _annualise(daily_vol_pct: float) -> float:
    """Convert daily percentage volatility to annualised percentage."""
    return daily_vol_pct * np.sqrt(TRADING_DAYS_PER_YEAR)


def _classify_regime(annual_vol_pct: float) -> VolatilityRegime:
    for regime, (lo, hi) in _REGIME_THRESHOLDS.items():
        if lo <= annual_vol_pct < hi:
            return regime
    return VolatilityRegime.EXTREME


def _simulate_paths(
    start_price: float,
    mu_pct: float,
    daily_vols_pct: np.ndarray,
    horizon: int,
) -> np.ndarray:
    """
    Vectorised Monte Carlo simulation.

    Returns an array of shape (N_SIMULATIONS, horizon + 1) where
    column 0 is start_price for every path.

    Daily log-returns are drawn from N(mu/100, vol/100) and
    exponentiated — i.e. geometric Brownian motion with time-varying vol.
    """
    rng = np.random.default_rng()

    # (N_SIMULATIONS, horizon) matrix of shocks
    # vols are in %, convert to decimals
    mu_dec = mu_pct / 100.0
    vols_dec = daily_vols_pct[:horizon] / 100.0

    shocks = rng.normal(
        loc=mu_dec,
        scale=vols_dec,          # broadcasts over rows
        size=(N_SIMULATIONS, horizon),
    )

    # Cumulative sum of log-returns → relative price factor
    cum_log_returns = np.cumsum(shocks, axis=1)         # (N, horizon)
    price_factors   = np.exp(cum_log_returns)            # (N, horizon)

    # Prepend start_price column
    start_col = np.ones((N_SIMULATIONS, 1)) * start_price
    paths = np.hstack([start_col, start_price * price_factors])  # (N, H+1)

    return paths


def _build_mc_result(
    ticker: str,
    start_price: float,
    paths: np.ndarray,
    horizon: int,
) -> MonteCarloResult:
    """
    Compute scenario statistics from the simulated paths array.
    paths shape: (N_SIMULATIONS, horizon + 1)
    """
    terminal_prices = paths[:, -1]                         # (N,)
    terminal_returns = (terminal_prices / start_price - 1) * 100  # %

    # Drawdown: worst intra-path drop from start_price
    max_prices = np.maximum.accumulate(paths, axis=1)
    drawdowns = (paths - max_prices) / max_prices * 100     # negative values
    worst_drawdowns = drawdowns.min(axis=1)                  # (N,) most negative

    prob_dd_5  = float(np.mean(worst_drawdowns <= -5.0))
    prob_dd_10 = float(np.mean(worst_drawdowns <= -10.0))
    prob_dd_20 = float(np.mean(worst_drawdowns <= -20.0))

    prob_gain_5  = float(np.mean(terminal_returns >= 5.0))
    prob_gain_10 = float(np.mean(terminal_returns >= 10.0))

    logger.info(
        "Monte Carlo (%s) | P(dd≥5%%)=%.1f%% P(dd≥10%%)=%.1f%% "
        "P(gain≥5%%)=%.1f%% | P5_ret=%.1f%% P95_ret=%.1f%%",
        ticker,
        prob_dd_5 * 100, prob_dd_10 * 100,
        prob_gain_5 * 100,
        float(np.percentile(terminal_returns, 5)),
        float(np.percentile(terminal_returns, 95)),
    )

    return MonteCarloResult(
        ticker=ticker,
        num_simulations=N_SIMULATIONS,
        forecast_horizon=horizon,
        mean_return_pct=round(float(np.mean(terminal_returns)),  4),
        median_return_pct=round(float(np.median(terminal_returns)), 4),
        p5_return_pct=round(float(np.percentile(terminal_returns,  5)), 4),
        p95_return_pct=round(float(np.percentile(terminal_returns, 95)), 4),
        prob_drawdown_5pct=round(prob_dd_5,   4),
        prob_drawdown_10pct=round(prob_dd_10, 4),
        prob_drawdown_20pct=round(prob_dd_20, 4),
        prob_gain_5pct=round(prob_gain_5,     4),
        prob_gain_10pct=round(prob_gain_10,   4),
        error=None,
    )


def _garch_error(ticker: str, error: str) -> GARCHResult:
    return GARCHResult(
        ticker=ticker,
        params=GARCHParams(omega=0.0, alpha=0.0, beta=0.0, persistence=0.0),
        model_converged=False,
        aic=0.0,
        bic=0.0,
        current_annualised_vol=0.0,
        vol_regime=VolatilityRegime.NORMAL,
        vol_forecast_daily=[],
        error=error,
    )
