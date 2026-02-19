"""
Layer 1 — Data Fetcher for Agent 04.

Responsibilities:
  1. Pull OHLCV for the user-provided ticker via yfinance
  2. Pull ^VIX (always) and OVX (energy assets) as supplementary context
  3. Run validation: minimum bars, gap detection, split/outlier detection
  4. Return a DataFetchResult or set quality=FAILED for unrecoverable errors

Design notes:
  - No hardcoded tickers; the ticker string comes straight from Agent 01
  - Supplementary indices (VIX, OVX) are context only — not forecasted
  - Validation failures return a structured result with quality flags rather
    than raising exceptions, so Agent 04 can emit a clean pipeline_error
    instead of crashing the LangGraph DAG
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import yfinance as yf

from .cache import CacheNamespace, get_cached, make_key, set_cached

# Suppress yfinance's own stderr chatter (404s, "possibly delisted", etc.)
# Our validation layer handles these cases explicitly via DataQuality.FAILED
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", category=UserWarning, module="yfinance")

from ..resources.schemas import DataFetchResult, DataQuality, OHLCVBar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_REQUIRED_BARS = 30          # fewer bars → SPARSE
MAX_GAP_DAYS = 5                # consecutive missing trading days → GAPPED
OUTLIER_ZSCORE_THRESHOLD = 6.0  # |z| > 6 → likely split artefact → SUSPECT

# Tickers whose option-implied vol index is OVX rather than VIX
_ENERGY_PREFIXES = ("CL", "BZ", "HO", "NG", "RB", "WTI", "OVX")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_asset_data(
    ticker: str,
    asset_name: str,
    lookback_days: int = 90,
) -> DataFetchResult:
    """
    Download and validate OHLCV data for *ticker*.

    Results are cached for 60 minutes so repeated calls for the same ticker
    within a pipeline retry or multi-asset run skip the yfinance HTTP round-trip.

    Parameters
    ----------
    ticker       : Exchange-standard ticker resolved by Agent 01.
    asset_name   : Human-readable label (used only for metadata).
    lookback_days: Calendar days of history to request (default 90).

    Returns
    -------
    DataFetchResult — always returned, never raised.
    quality == FAILED when the data is completely unusable.
    """
    cache_key = make_key("data", ticker, lookback_days)
    cached = get_cached(CacheNamespace.DATA, cache_key)
    if cached is not None:
        logger.debug("Cache HIT [data] %s", ticker)
        return cached
    logger.debug("Cache MISS [data] %s — fetching from yfinance", ticker)

    end_dt   = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days + 10)  # buffer for weekends

    # --- Primary asset ---------------------------------------------------
    try:
        raw = _download(ticker, start_dt, end_dt)
    except Exception as exc:
        logger.error("yfinance download failed for %s: %s", ticker, exc)
        return _failed_result(ticker, asset_name, str(exc))

    if raw is None or raw.empty:
        return _failed_result(
            ticker, asset_name,
            f"yfinance returned no data for '{ticker}'.",
        )

    # Normalise to plain Python lists / dicts
    bars, close_prices = _normalise(raw)

    if not bars:
        return _failed_result(
            ticker, asset_name,
            "Price series is empty after normalisation.",
        )

    # --- Supplementary volatility indices --------------------------------
    vix_current = _fetch_last_close("^VIX", start_dt, end_dt)
    ovx_current: Optional[float] = None
    if _is_energy_ticker(ticker):
        ovx_current = _fetch_last_close("OVX", start_dt, end_dt)

    # --- Validation ------------------------------------------------------
    quality, notes = _validate(close_prices, bars)

    result = DataFetchResult(
        ticker=ticker,
        asset_name=asset_name,
        bars=bars,
        close_prices=close_prices,
        trading_days=len(bars),
        quality=quality,
        quality_notes=notes,
        vix_current=vix_current,
        ovx_current=ovx_current,
        error=None,
    )
    # Only cache clean/usable results — don't cache FAILED so a retry
    # can attempt a fresh download
    if result.quality.value != "failed":
        set_cached(CacheNamespace.DATA, cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _download(ticker: str, start: datetime, end: datetime):
    """Thin wrapper around yf.download for testability."""
    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=True,   # adjusts for splits/dividends automatically
        actions=False,
    )
    # yfinance may return a MultiIndex when downloading a single ticker;
    # flatten it so we always have simple column names.
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    return df


def _fetch_last_close(ticker: str, start: datetime, end: datetime) -> Optional[float]:
    """Return the most recent closing price for an auxiliary ticker, or None."""
    try:
        df = _download(ticker, start, end)
        if df is not None and not df.empty and "Close" in df.columns:
            return float(df["Close"].dropna().iloc[-1])
    except Exception as exc:
        logger.debug("Could not fetch supplementary ticker %s: %s", ticker, exc)
    return None


def _normalise(df) -> tuple[list[OHLCVBar], list[float]]:
    """Convert a yfinance DataFrame into OHLCVBar list + plain close list."""
    bars: list[OHLCVBar] = []
    close_prices: list[float] = []

    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(df.columns)):
        logger.warning("Missing columns in price data: %s", df.columns.tolist())
        return bars, close_prices

    df = df.dropna(subset=["Close"])

    for ts, row in df.iterrows():
        close = float(row["Close"])
        if close <= 0:
            continue
        bars.append(
            OHLCVBar(
                date=str(ts.date()),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=close,
                volume=float(row.get("Volume", 0.0) or 0.0),
            )
        )
        close_prices.append(close)

    return bars, close_prices


def _validate(
    close_prices: list[float],
    bars: list[OHLCVBar],
) -> tuple[DataQuality, list[str]]:
    """
    Run three checks on the price series and return a (quality, notes) tuple.

    Checks (in order of severity):
      1. Sparse — not enough bars to fit models reliably
      2. Gapped — multi-day windows of missing trading data
      3. Suspect — extreme single-day moves suggesting split artefacts
    """
    notes: list[str] = []

    # --- Check 1: Sparse -------------------------------------------------
    if len(close_prices) < MIN_REQUIRED_BARS:
        notes.append(
            f"Only {len(close_prices)} bars available; "
            f"minimum required is {MIN_REQUIRED_BARS}."
        )
        return DataQuality.SPARSE, notes

    # --- Check 2: Gap detection ------------------------------------------
    dates = [b.date for b in bars]
    gap_found = False
    for i in range(1, len(dates)):
        d0 = datetime.fromisoformat(dates[i - 1])
        d1 = datetime.fromisoformat(dates[i])
        calendar_gap = (d1 - d0).days
        # More than MAX_GAP_DAYS calendar days between consecutive bars
        # is suspicious even accounting for weekends/holidays
        if calendar_gap > MAX_GAP_DAYS:
            notes.append(
                f"Gap detected between {dates[i-1]} and {dates[i]} "
                f"({calendar_gap} calendar days)."
            )
            gap_found = True
    if gap_found:
        return DataQuality.GAPPED, notes

    # --- Check 3: Outlier / split artefact detection ---------------------
    prices = np.array(close_prices, dtype=float)
    log_returns = np.diff(np.log(prices))
    if len(log_returns) > 0:
        z_scores = (log_returns - log_returns.mean()) / (log_returns.std() + 1e-10)
        extreme_idx = np.where(np.abs(z_scores) > OUTLIER_ZSCORE_THRESHOLD)[0]
        if len(extreme_idx) > 0:
            for idx in extreme_idx:
                notes.append(
                    f"Extreme return on {dates[idx + 1]}: "
                    f"{log_returns[idx] * 100:.1f}% log-return "
                    f"(z = {z_scores[idx]:.1f}). Possible split artefact."
                )
            return DataQuality.SUSPECT, notes

    return DataQuality.OK, notes


def _is_energy_ticker(ticker: str) -> bool:
    """Return True if the ticker looks like an energy futures contract."""
    upper = ticker.upper()
    return any(upper.startswith(prefix) for prefix in _ENERGY_PREFIXES)


def _failed_result(ticker: str, asset_name: str, error: str) -> DataFetchResult:
    return DataFetchResult(
        ticker=ticker,
        asset_name=asset_name,
        bars=[],
        close_prices=[],
        trading_days=0,
        quality=DataQuality.FAILED,
        quality_notes=[error],
        error=error,
    )
