"""
Manual test suite for Agent 04 — Universal Asset Engine.

Run modes
---------
1. Layer-by-layer (no API key needed):
       python tests/test_agent04.py --layers

2. Full agent including LLM synthesis:
       python tests/test_agent04.py --full

3. Quick smoke test (data fetch only):
       python tests/test_agent04.py --smoke

4. Via pytest (runs all non-LLM tests automatically):
       pytest tests/test_agent04.py -v

All commands should be run from the `backend/` directory.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Make `backend/` importable regardless of where the script is invoked from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.agent_04_asset_analyst.tools.data_fetcher import fetch_asset_data
from app.agents.agent_04_asset_analyst.tools.garch_monte_carlo import (
    run_garch,
    run_monte_carlo,
)
from app.agents.agent_04_asset_analyst.tools.cache import clear_all, cache_stats
from app.agents.agent_04_asset_analyst.resources.schemas import DataQuality

# ---------------------------------------------------------------------------
# Test fixtures — easy to swap out different assets
# ---------------------------------------------------------------------------

FIXTURES = [
    {"ticker": "GC=F",   "asset_name": "Gold Futures",        "lookback": 90, "horizon": 30},
    {"ticker": "CL=F",   "asset_name": "Crude Oil (WTI)",     "lookback": 90, "horizon": 30},
    {"ticker": "BTC-USD","asset_name": "Bitcoin",             "lookback": 90, "horizon": 14},
    {"ticker": "^GSPC",  "asset_name": "S&P 500 Index",       "lookback": 90, "horizon": 30},
    {"ticker": "AAPL",   "asset_name": "Apple Inc.",          "lookback": 90, "horizon": 30},
]

DEFAULT_FIXTURE = FIXTURES[0]   # Gold — stable, always has data


# ===========================================================================
# LAYER 1 — Data Fetcher
# ===========================================================================

def test_data_fetcher_returns_data():
    """Data fetcher returns bars and close prices for a known-good ticker."""
    f = DEFAULT_FIXTURE
    result = fetch_asset_data(f["ticker"], f["asset_name"], f["lookback"])

    assert result.ticker == f["ticker"]
    assert result.quality != DataQuality.FAILED, \
        f"Data fetch failed: {result.error}"
    assert len(result.close_prices) >= 30, \
        f"Expected ≥30 bars, got {len(result.close_prices)}"
    assert result.close_prices[-1] > 0

    _print_ok(
        f"[L1] {f['ticker']} — {result.trading_days} bars | "
        f"last close: {result.close_prices[-1]:.2f} | "
        f"quality: {result.quality.value} | "
        f"VIX: {result.vix_current}"
    )


def test_data_fetcher_handles_bad_ticker():
    """Data fetcher returns FAILED quality (not exception) for invalid ticker."""
    result = fetch_asset_data("XXXXNOTREAL", "Fake Asset", 90)
    assert result.quality == DataQuality.FAILED
    assert result.error is not None
    _print_ok(f"[L1] Bad ticker handled gracefully: {result.error}")


# ===========================================================================
# LAYER 3 — GARCH + Monte Carlo  (no heavy ML deps)
# ===========================================================================

def test_garch_fits():
    """GARCH(1,1) converges on a real return series."""
    f = DEFAULT_FIXTURE
    data = fetch_asset_data(f["ticker"], f["asset_name"], f["lookback"])
    assert data.quality != DataQuality.FAILED

    result = run_garch(f["ticker"], data.close_prices, f["horizon"])

    assert result.error is None, f"GARCH failed: {result.error}"
    assert result.model_converged
    assert 0.0 < result.params.persistence <= 1.05, \
        f"Unusual persistence: {result.params.persistence}"
    assert result.current_annualised_vol > 0

    igarch_flag = " ⚠ IGARCH" if result.igarch_warning else ""
    _print_ok(
        f"[L3-GARCH] {f['ticker']} | "
        f"alpha={result.params.alpha:.4f} beta={result.params.beta:.4f} "
        f"persist={result.params.persistence:.4f} | "
        f"ann_vol={result.current_annualised_vol:.2f}% | "
        f"regime={result.vol_regime.value}{igarch_flag}"
    )


def test_monte_carlo_runs():
    """Monte Carlo produces probability-weighted scenario statistics."""
    f = DEFAULT_FIXTURE
    data  = fetch_asset_data(f["ticker"], f["asset_name"], f["lookback"])
    garch = run_garch(f["ticker"], data.close_prices, f["horizon"])
    mc    = run_monte_carlo(f["ticker"], data.close_prices, garch, f["horizon"])

    assert mc.error is None, f"Monte Carlo failed: {mc.error}"
    assert mc.num_simulations == 5000
    assert mc.p5_return_pct < mc.p95_return_pct
    assert 0.0 <= mc.prob_drawdown_5pct <= 1.0

    _print_ok(
        f"[L3-MC] {f['ticker']} | "
        f"median_ret={mc.median_return_pct:+.2f}% | "
        f"P5={mc.p5_return_pct:+.2f}% P95={mc.p95_return_pct:+.2f}% | "
        f"P(dd≥5%)={mc.prob_drawdown_5pct*100:.1f}% "
        f"P(dd≥10%)={mc.prob_drawdown_10pct*100:.1f}%"
    )


# ===========================================================================
# LAYER 2 — Chronos-2  (needs torch + chronos-forecasting installed)
# ===========================================================================

def test_chronos_forecast():
    """Chronos-2 generates 100 paths and extracts P10/median/P90."""
    try:
        import torch  # noqa: F401
        from chronos import ChronosPipeline  # noqa: F401
    except ImportError:
        _print_skip("[L2] Chronos-2 not installed — skipping (pip install chronos-forecasting torch)")
        return

    from app.agents.agent_04_asset_analyst.tools.chronos_engine import run_chronos_forecast

    f = DEFAULT_FIXTURE
    data = fetch_asset_data(f["ticker"], f["asset_name"], f["lookback"])
    assert data.quality != DataQuality.FAILED

    t0 = time.time()
    result = run_chronos_forecast(f["ticker"], data.close_prices, f["horizon"])
    elapsed = time.time() - t0

    assert result.error is None, f"Chronos failed: {result.error}"
    assert result.num_samples == 100
    assert len(result.median_path) == f["horizon"]
    assert result.p10_terminal < result.p90_terminal

    _print_ok(
        f"[L2] {f['ticker']} in {elapsed:.1f}s | "
        f"bias={result.directional_bias} | "
        f"spread={result.forecast_spread_pct:.2f}% | "
        f"uncertainty={result.uncertainty_score:.3f} | "
        f"P10={result.p10_terminal:.2f} "
        f"med={result.median_terminal:.2f} "
        f"P90={result.p90_terminal:.2f}"
    )


# ===========================================================================
# FULL AGENT  (needs GOOGLE_API_KEY / GEMINI_API_KEY)
# ===========================================================================

def run_full_agent(ticker: str = "GC=F", asset_name: str = "Gold Futures"):
    """
    Run the complete agent_04_node and print the structured output.
    Requires:  GOOGLE_API_KEY or GEMINI_API_KEY in environment.
    """
    from app.agents.agent_04_asset_analyst.agent import agent_04_node

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[SKIP] Full agent test requires GOOGLE_API_KEY or GEMINI_API_KEY.")
        print("       Export it first, then re-run with --full.\n")
        return

    state = {
        "ticker":           ticker,
        "asset_name":       asset_name,
        "lookback_days":    90,
        "forecast_horizon": 30,
    }

    print(f"\n{'='*60}")
    print(f"  FULL AGENT 04 RUN — {asset_name} ({ticker})")
    print(f"{'='*60}\n")

    t0 = time.time()
    result_state = agent_04_node(state)
    elapsed = time.time() - t0

    output = result_state["agent_04_output"]

    print(f"  Completed in {elapsed:.1f}s\n")
    print(f"  Success:         {output.success}")
    if output.pipeline_error:
        print(f"  Pipeline error:  {output.pipeline_error}")

    print(f"\n--- DATA ---")
    print(f"  Trading days:    {output.data.trading_days}")
    print(f"  Quality:         {output.data.quality.value}")
    print(f"  VIX current:     {output.data.vix_current}")
    if output.data.quality_notes:
        for n in output.data.quality_notes:
            print(f"  ⚠  {n}")

    if output.chronos:
        print(f"\n--- CHRONOS-2 ---")
        print(f"  Bias:            {output.chronos.directional_bias}")
        print(f"  Spread:          {output.chronos.forecast_spread_pct:.2f}%")
        print(f"  Uncertainty:     {output.chronos.uncertainty_score:.3f}")
        print(f"  P10 terminal:    {output.chronos.p10_terminal:.4f}")
        print(f"  Median terminal: {output.chronos.median_terminal:.4f}")
        print(f"  P90 terminal:    {output.chronos.p90_terminal:.4f}")
        if output.chronos.error:
            print(f"  Error:           {output.chronos.error}")

    if output.garch:
        print(f"\n--- GARCH ---")
        print(f"  Regime:          {output.garch.vol_regime.value}")
        print(f"  Annual vol:      {output.garch.current_annualised_vol:.2f}%")
        print(f"  Alpha:           {output.garch.params.alpha:.6f}")
        print(f"  Beta:            {output.garch.params.beta:.6f}")
        print(f"  Persistence:     {output.garch.params.persistence:.6f}")
        if output.garch.error:
            print(f"  Error:           {output.garch.error}")

    if output.monte_carlo:
        print(f"\n--- MONTE CARLO ---")
        print(f"  Median return:   {output.monte_carlo.median_return_pct:+.2f}%")
        print(f"  P5  return:      {output.monte_carlo.p5_return_pct:+.2f}%")
        print(f"  P95 return:      {output.monte_carlo.p95_return_pct:+.2f}%")
        print(f"  P(dd ≥  5%):    {output.monte_carlo.prob_drawdown_5pct*100:.1f}%")
        print(f"  P(dd ≥ 10%):    {output.monte_carlo.prob_drawdown_10pct*100:.1f}%")
        print(f"  P(dd ≥ 20%):    {output.monte_carlo.prob_drawdown_20pct*100:.1f}%")

    if output.interpretation:
        print(f"\n--- LLM INTERPRETATION ---")
        print(f"  Agreement:       {output.interpretation.model_agreement.value}")
        print(f"  Risk rating:     {output.interpretation.risk_rating.value}")
        print(f"  Confidence:      {output.interpretation.confidence:.2f}")
        print(f"\n  Key findings:")
        for i, f_ in enumerate(output.interpretation.key_findings, 1):
            print(f"    {i}. {f_}")
        if output.interpretation.tensions:
            print(f"\n  Tensions:")
            for t in output.interpretation.tensions:
                print(f"    ⚠  {t}")
        print(f"\n  Reasoning trace (first 500 chars):")
        print(f"    {output.interpretation.reasoning_trace[:500]}...")

    print(f"\n{'='*60}\n")


# ===========================================================================
# CLI entry point
# ===========================================================================

# ===========================================================================
# CACHE TEST
# ===========================================================================

def test_cache():
    """
    Verify the TTL cache works by calling each tool twice and comparing timing.
    First call = MISS (live work), second call = HIT (near-zero latency).
    """
    f = DEFAULT_FIXTURE
    ticker, lookback, horizon = f["ticker"], f["lookback"], f["horizon"]

    # Start clean
    clear_all()
    print(f"\n  Cache cleared. Running two identical calls for {ticker}...\n")

    # --- DATA CACHE ---
    t0 = time.perf_counter()
    r1 = fetch_asset_data(ticker, f["asset_name"], lookback)
    miss_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    r2 = fetch_asset_data(ticker, f["asset_name"], lookback)
    hit_time = time.perf_counter() - t0

    assert r1.close_prices == r2.close_prices, "Cache returned different data"
    speedup = miss_time / hit_time if hit_time > 0 else float("inf")
    _print_ok(
        f"[cache/data]  MISS={miss_time*1000:.0f}ms  "
        f"HIT={hit_time*1000:.1f}ms  "
        f"speedup={speedup:.0f}x"
    )
    assert hit_time < miss_time * 0.1, \
        f"Cache HIT ({hit_time*1000:.1f}ms) should be <10% of MISS ({miss_time*1000:.0f}ms)"

    # --- GARCH CACHE ---
    t0 = time.perf_counter()
    g1 = run_garch(ticker, r1.close_prices, horizon)
    miss_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    g2 = run_garch(ticker, r1.close_prices, horizon)
    hit_time = time.perf_counter() - t0

    assert g1.params.alpha == g2.params.alpha, "Cache returned different GARCH params"
    speedup = miss_time / hit_time if hit_time > 0 else float("inf")
    _print_ok(
        f"[cache/garch] MISS={miss_time*1000:.0f}ms  "
        f"HIT={hit_time*1000:.1f}ms  "
        f"speedup={speedup:.0f}x"
    )
    assert hit_time < miss_time * 0.1, \
        f"Cache HIT ({hit_time*1000:.1f}ms) should be <10% of MISS ({miss_time*1000:.0f}ms)"

    # --- MONTE CARLO CACHE ---
    t0 = time.perf_counter()
    m1 = run_monte_carlo(ticker, r1.close_prices, g1, horizon)
    miss_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    m2 = run_monte_carlo(ticker, r1.close_prices, g1, horizon)
    hit_time = time.perf_counter() - t0

    assert m1.median_return_pct == m2.median_return_pct, "Cache returned different MC results"
    speedup = miss_time / hit_time if hit_time > 0 else float("inf")
    _print_ok(
        f"[cache/mc]    MISS={miss_time*1000:.0f}ms  "
        f"HIT={hit_time*1000:.1f}ms  "
        f"speedup={speedup:.0f}x"
    )
    assert hit_time < miss_time * 0.1, \
        f"Cache HIT ({hit_time*1000:.1f}ms) should be <10% of MISS ({miss_time*1000:.0f}ms)"

    # Final stats
    stats = cache_stats()
    _print_ok(
        f"[cache/stats] data={stats['data_cache']['size']} entries  "
        f"model={stats['model_cache']['size']} entries"
    )


def _print_ok(msg: str):
    print(f"  ✓  {msg}")

def _print_skip(msg: str):
    print(f"  ⊘  {msg}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--smoke" in args or not args:
        print("\n=== SMOKE TEST (Layer 1 only) ===\n")
        test_data_fetcher_returns_data()
        test_data_fetcher_handles_bad_ticker()

    if "--layers" in args:
        print("\n=== LAYER TESTS (no LLM) ===\n")
        test_data_fetcher_returns_data()
        test_data_fetcher_handles_bad_ticker()
        test_garch_fits()
        test_monte_carlo_runs()
        test_chronos_forecast()
        print("\nAll layer tests passed.\n")

    if "--cache" in args:
        print("\n=== CACHE TEST ===\n")
        test_cache()
        print("\nCache test passed.\n")

    if "--full" in args:
        # Optionally pass a ticker: --full AAPL
        idx = args.index("--full")
        ticker = args[idx + 1] if idx + 1 < len(args) and not args[idx+1].startswith("--") else "GC=F"
        asset  = args[idx + 2] if idx + 2 < len(args) and not args[idx+2].startswith("--") else "Gold Futures"
        run_full_agent(ticker=ticker, asset_name=asset)
