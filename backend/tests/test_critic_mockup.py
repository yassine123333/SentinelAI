"""
test_critic_mockup.py — End-to-end tests for Agent 06 (Critic & Verifier)
using realistic mock pipeline data.

Run from the backend/ directory:
    python tests/test_critic_mockup.py

Scenarios
---------
  1. PASS  — Gold, clean pipeline. All checks healthy.
  2. FAIL  — Bitcoin, missing sources + agents below confidence threshold.
  3. FAIL  — Oil, internal contradiction (geo stable + extreme fear + VaR mismatch).
  4. RETRY — S&P 500: attempt 1 fails (incomplete data), attempt 2 passes (corrected).

Each scenario shows the full PASS/FAIL verdict, per-check breakdown,
retry instructions (on FAIL), and the LLM reasoning trace.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.agent_06_critic.agent import CriticAgent
from app.agents.agent_06_critic.schemas import CriticInput

# ── ANSI colours ──────────────────────────────────────────────────────────────
BOLD  = "\033[1m"
GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
CYAN  = "\033[96m"
DIM   = "\033[2m"
RESET = "\033[0m"

# ═════════════════════════════════════════════════════════════════════════════
# MOCK DATA
# ═════════════════════════════════════════════════════════════════════════════

# ── Scenario 1: PASS — Gold ───────────────────────────────────────────────────
GOLD_PASS = {
    "query_id": "test-pass-gold-001",
    "asset": "GC=F",
    "attempt": 1,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 62.0,
        "key_events": [
            {"date": "2026-02-10", "description": "Fed held rates; gold rallied 1.2%", "impact": "moderate"},
            {"date": "2026-02-12", "description": "Middle East tensions elevated; safe-haven demand up", "impact": "high"},
            {"date": "2026-02-15", "description": "US CPI came in at 3.1%, below consensus 3.3%", "impact": "moderate"},
        ],
        "macro_indicators": [
            {"series_id": "FEDFUNDS", "name": "Fed Funds Rate",       "value": 5.25, "trend": "stable"},
            {"series_id": "CPIAUCSL", "name": "CPI (YoY)",            "value": 3.1,  "trend": "falling"},
            {"series_id": "DGS10",    "name": "10-Year Treasury",     "value": 4.35, "trend": "stable"},
            {"series_id": "DEXUSEU", "name": "USD/EUR Exchange Rate", "value": 1.082,"trend": "falling"},
        ],
        "risk_summary": (
            "Moderate geopolitical risk. Middle East tensions support safe-haven demand. "
            "Fed on hold while inflation cools; USD weakening slightly supports gold. "
            "No imminent escalation risk in major gold-importing nations."
        ),
        "sources": [
            "https://www.gdeltproject.org/",
            "FEDFUNDS", "CPIAUCSL", "DGS10", "DEXUSEU",
            "https://fred.stlouisfed.org/series/DGS10",
        ],
        "confidence": 0.82,
    },
    "sentiment": {
        "agent_id": "agent_03",
        "sentiment_score": 0.18,
        "fear_greed_index": 47.0,
        "news_signals": [
            {"source": "Reuters",    "headline": "Gold climbs on rate pause expectations", "tone": "positive", "score": 0.4},
            {"source": "Bloomberg",  "headline": "Analysts raise gold price targets",       "tone": "positive", "score": 0.35},
        ],
        "social_signals": [
            {"platform": "Reddit r/gold",          "tone": "bullish", "score": 0.45},
            {"platform": "Twitter #XAUUSD",        "tone": "neutral",  "score": 0.10},
        ],
        "sources": [
            "https://alternative.me/crypto/fear-and-greed-index/",
            "https://reuters.com/markets/commodities/",
            "https://bloomberg.com/markets/commodities",
        ],
        "confidence": 0.76,
    },
    "asset_analyst": {
        "agent_id": "agent_04",
        "asset": "GC=F",
        "current_price": 2680.5,
        "price_trend": "bullish",
        "key_patterns": ["ascending triangle breakout", "golden cross on daily chart", "RSI 62 — not overbought"],
        "short_term_outlook": (
            "Gold has broken above the ascending triangle resistance at $2,655. "
            "A golden cross (50-DMA crossing above 200-DMA) confirmed bullish momentum. "
            "Technical target: $2,750–$2,780 over 30 days. Key support: $2,620."
        ),
        "sources": [
            "https://finance.yahoo.com/quote/GC%3DF/",
            "https://www.tradingview.com/symbols/XAUUSD/",
            "GOLDAMGBD228NLBM",
        ],
        "confidence": 0.79,
    },
    "quant_risk": {
        "agent_id": "agent_05",
        "volatility_30d": 0.18,
        "var_95": 0.032,
        "monte_carlo_scenarios": {
            "bull": {"probability": 0.35, "price_target": 2780, "description": "Fed dovish + geopolitical safe-haven"},
            "base": {"probability": 0.45, "price_target": 2650, "description": "Range-bound, status quo"},
            "bear": {"probability": 0.20, "price_target": 2550, "description": "Risk-on shift, USD strengthening"},
        },
        "garch_forecast": {"forecast_30d_vol": 0.17, "confidence_interval": [0.14, 0.21]},
        "risk_level": "medium",
        "sources": [
            "https://finance.yahoo.com/quote/GC%3DF/history/",
            "GOLDAMGBD228NLBM",
            "VIXCLS",
        ],
        "confidence": 0.81,
    },
}

# ── Scenario 2: FAIL — Bitcoin (missing sources + low confidence) ─────────────
BTC_FAIL_LOW_CONFIDENCE = {
    "query_id": "test-fail-btc-low-confidence",
    "asset": "BTC-USD",
    "attempt": 1,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 55.0,
        "key_events": [],
        "macro_indicators": [],
        "risk_summary": "Some geopolitical factors may affect Bitcoin price.",
        "sources": [],                   # ← MISSING SOURCES (critical failure)
        "confidence": 0.52,             # ← BELOW THRESHOLD
    },
    "sentiment": {
        "agent_id": "agent_03",
        "sentiment_score": -0.35,
        "fear_greed_index": 32.0,
        "news_signals": [
            {"source": "CoinDesk", "headline": "Regulatory headwinds mount", "tone": "negative", "score": -0.4},
        ],
        "social_signals": [],
        "sources": ["https://alternative.me/crypto/fear-and-greed-index/"],
        "confidence": 0.61,             # ← BELOW THRESHOLD
    },
    "asset_analyst": {
        "agent_id": "agent_04",
        "asset": "BTC-USD",
        "current_price": 94500.0,
        "price_trend": "bearish",
        "key_patterns": ["death cross", "bearish engulfing on weekly"],
        "short_term_outlook": "Bitcoin showing weakness below $95K. Support at $88K.",
        "sources": [],                   # ← MISSING SOURCES
        "confidence": 0.58,             # ← BELOW THRESHOLD
    },
    "quant_risk": {
        "agent_id": "agent_05",
        "volatility_30d": 0.72,
        "var_95": 0.09,
        "monte_carlo_scenarios": {
            "bull": {"probability": 0.22, "price_target": 105000},
            "base": {"probability": 0.48, "price_target": 88000},
            "bear": {"probability": 0.30, "price_target": 72000},
        },
        "garch_forecast": {"forecast_30d_vol": 0.68},
        "risk_level": "high",
        "sources": ["https://finance.yahoo.com/quote/BTC-USD/history/"],
        "confidence": 0.73,
    },
}

# ── Scenario 3: FAIL — Oil (internal contradictions) ─────────────────────────
OIL_FAIL_CONTRADICTION = {
    "query_id": "test-fail-oil-contradiction",
    "asset": "CL=F",
    "attempt": 1,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 85.0,          # ← Very HIGH stability
        "key_events": [
            {"date": "2026-02-05", "description": "OPEC+ signed 6-month production agreement", "impact": "low"},
        ],
        "macro_indicators": [
            {"series_id": "DCOILWTICO", "name": "WTI Crude", "value": 75.2, "trend": "stable"},
        ],
        "risk_summary": "Geopolitical environment is stable. OPEC+ agreement provides supply predictability.",
        "sources": ["https://gdelt.org/", "DCOILWTICO"],
        "confidence": 0.84,
    },
    "sentiment": {
        "agent_id": "agent_03",
        "sentiment_score": -0.7,
        "fear_greed_index": 12.0,         # ← EXTREME FEAR — contradicts stability=85
        "news_signals": [
            {"source": "Bloomberg", "headline": "Oil demand collapse fears grow", "tone": "very negative", "score": -0.8},
        ],
        "social_signals": [{"platform": "Twitter #OOTT", "tone": "panic", "score": -0.9}],
        "sources": [
            "https://alternative.me/crypto/fear-and-greed-index/",
            "https://bloomberg.com/energy",
        ],
        "confidence": 0.77,
    },
    "asset_analyst": {
        "agent_id": "agent_04",
        "asset": "CL=F",
        "current_price": 75.2,
        "price_trend": "bearish",
        "key_patterns": ["head and shoulders top", "MACD negative crossover"],
        "short_term_outlook": "Crude oil breaking support at $75. Target $68 on continued weakness.",
        "sources": [
            "https://finance.yahoo.com/quote/CL%3DF/",
            "https://www.eia.gov/petroleum/",
        ],
        "confidence": 0.80,
    },
    "quant_risk": {
        "agent_id": "agent_05",
        "volatility_30d": 0.45,
        "var_95": 0.22,                   # ← Very HIGH VaR
        "monte_carlo_scenarios": {
            "bull": {"probability": 0.15, "price_target": 82},
            "base": {"probability": 0.40, "price_target": 72},
            "bear": {"probability": 0.45, "price_target": 61},
        },
        "garch_forecast": {"forecast_30d_vol": 0.42},
        "risk_level": "low",              # ← CONTRADICTS VaR=22% → critical
        "sources": [
            "https://finance.yahoo.com/quote/CL%3DF/history/",
            "DCOILWTICO",
        ],
        "confidence": 0.75,
    },
}

# ── Scenario 4a: RETRY attempt 1 — SPY (incomplete data) ─────────────────────
SPY_RETRY_ATTEMPT1 = {
    "query_id": "test-retry-spy",
    "asset": "SPY",
    "attempt": 1,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 70.0,
        "key_events": [],                 # ← Empty events (completeness issue)
        "macro_indicators": [],           # ← Empty indicators
        "risk_summary": "US economic conditions appear broadly stable.",
        "sources": [],                    # ← MISSING SOURCES
        "confidence": 0.55,             # ← BELOW THRESHOLD
    },
    "sentiment": {
        "agent_id": "agent_03",
        "sentiment_score": 0.30,
        "fear_greed_index": 62.0,
        "news_signals": [
            {"source": "CNBC", "headline": "Markets near all-time highs", "tone": "positive", "score": 0.5},
        ],
        "social_signals": [],
        "sources": ["https://alternative.me/crypto/fear-and-greed-index/", "https://cnbc.com/markets"],
        "confidence": 0.72,
    },
    "asset_analyst": {
        "agent_id": "agent_04",
        "asset": "SPY",
        "current_price": 592.3,
        "price_trend": "bullish",
        "key_patterns": ["ATH breakout", "strong breadth"],
        "short_term_outlook": "S&P 500 breaking to new highs with broad market participation.",
        "sources": ["https://finance.yahoo.com/quote/SPY/"],
        "confidence": 0.76,
    },
    "quant_risk": {
        "agent_id": "agent_05",
        "volatility_30d": 0.14,
        "var_95": 0.021,
        "monte_carlo_scenarios": {
            "bull": {"probability": 0.50, "price_target": 620},
            "base": {"probability": 0.35, "price_target": 590},
            "bear": {"probability": 0.15, "price_target": 555},
        },
        "garch_forecast": {"forecast_30d_vol": 0.13},
        "risk_level": "low",
        "sources": ["https://finance.yahoo.com/quote/SPY/history/", "SP500", "VIXCLS"],
        "confidence": 0.78,
    },
}

# ── Scenario 4b: RETRY attempt 2 — SPY (corrected by Agent 02) ───────────────
SPY_RETRY_ATTEMPT2 = {
    **SPY_RETRY_ATTEMPT1,
    "attempt": 2,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 71.0,
        "key_events": [
            {"date": "2026-02-10", "description": "Fed minutes signal two rate cuts in 2026", "impact": "high"},
            {"date": "2026-02-14", "description": "US GDP Q4 revised up to 2.8% annualised",    "impact": "moderate"},
            {"date": "2026-02-17", "description": "US–China trade talks resume constructively",   "impact": "moderate"},
        ],
        "macro_indicators": [
            {"series_id": "FEDFUNDS", "name": "Fed Funds Rate",   "value": 5.25, "trend": "stable"},
            {"series_id": "CPIAUCSL", "name": "CPI (YoY)",        "value": 3.0,  "trend": "falling"},
            {"series_id": "UNRATE",   "name": "Unemployment Rate","value": 4.1,  "trend": "stable"},
            {"series_id": "SP500",    "name": "S&P 500 Index",    "value": 5890, "trend": "rising"},
        ],
        "risk_summary": (
            "US macro environment remains supportive for equities. "
            "Fed signalled two cuts in 2026 which boosted risk appetite. "
            "GDP revised upward and employment stable. US–China trade tone improving."
        ),
        "sources": [
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "FEDFUNDS", "CPIAUCSL", "UNRATE", "SP500",
            "https://www.gdeltproject.org/",
        ],
        "confidence": 0.83,             # ← Now above threshold
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _banner(title: str, scenario: int, total: int) -> None:
    print(f"\n{'═'*64}")
    print(f"  Scenario {scenario}/{total}: {BOLD}{title}{RESET}")
    print(f"{'═'*64}")


def _print_result(result: dict, label: str = "") -> None:
    verdict = result["verdict"]
    vc      = GREEN if verdict == "PASS" else RED

    print(f"\n  {BOLD}{vc}▶ {verdict}{RESET}  {DIM}{label}{RESET}")
    print(f"  Confidence : {result['overall_confidence']:.1%}")
    print(f"  Sources    : {result['sources_verified']}/{result['sources_total']} verified")

    print(f"\n  {CYAN}Checks:{RESET}")
    for chk in result.get("checks", []):
        icon = "✓" if chk["passed"] else "✗"
        col  = GREEN if chk["passed"] else RED
        print(f"    {col}{icon}{RESET} [{chk['score']:.2f}] {chk['check_name']}")
        print(f"         {DIM}{chk['details']}{RESET}")

    ri_list = result.get("retry_instructions", [])
    if ri_list:
        print(f"\n  {RED}Retry Instructions:{RESET}")
        for ri in ri_list:
            prio_col = RED if ri["priority"] == "critical" else YELLOW
            print(f"    [{prio_col}{ri['priority'].upper()}{RESET}] {BOLD}{ri['agent_id']}{RESET}: {ri['reason']}")
            for corr in ri["specific_corrections"]:
                print(f"      • {corr}")

    flagged = result.get("flagged_claims", [])
    if flagged:
        print(f"\n  {RED}Flagged Claims:{RESET}")
        for f in flagged:
            print(f"    ⚑ {f}")

    trace = result.get("reasoning_trace", "")
    print(f"\n  {CYAN}Reasoning Trace (first 600 chars):{RESET}")
    print(f"  {DIM}{trace[:600]}{'…' if len(trace) > 600 else ''}{RESET}")


def _separator(msg: str = "") -> None:
    print(f"\n  {DIM}{'─'*56}{RESET}")
    if msg:
        print(f"  {YELLOW}{msg}{RESET}")


# ═════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═════════════════════════════════════════════════════════════════════════════

async def run_all() -> None:
    agent = CriticAgent()

    results_summary: list[tuple[str, str, str]] = []  # (scenario, expected, actual)

    # ── Scenario 1: PASS ─────────────────────────────────────────────────────
    _banner("PASS — Gold (clean pipeline)", 1, 4)
    r1 = await agent.run(CriticInput(**GOLD_PASS))
    _print_result(r1.model_dump(), "Expected: PASS")
    results_summary.append(("Gold (clean)",     "PASS", r1.verdict))

    # Rate-limit courtesy pause between LLM calls
    time.sleep(2)

    # ── Scenario 2: FAIL (low confidence + missing sources) ──────────────────
    _banner("FAIL — Bitcoin (missing sources + low confidence)", 2, 4)
    r2 = await agent.run(CriticInput(**BTC_FAIL_LOW_CONFIDENCE))
    _print_result(r2.model_dump(), "Expected: FAIL")
    results_summary.append(("Bitcoin (low conf.)", "FAIL", r2.verdict))

    time.sleep(2)

    # ── Scenario 3: FAIL (internal contradiction) ────────────────────────────
    _banner("FAIL — Oil (internal contradictions)", 3, 4)
    r3 = await agent.run(CriticInput(**OIL_FAIL_CONTRADICTION))
    _print_result(r3.model_dump(), "Expected: FAIL")
    results_summary.append(("Oil (contradiction)", "FAIL", r3.verdict))

    time.sleep(2)

    # ── Scenario 4: RETRY flow ────────────────────────────────────────────────
    _banner("RETRY — S&P 500 (attempt 1 FAIL → attempt 2 PASS)", 4, 4)

    _separator("Attempt 1 — incomplete Agent 02 data")
    r4a = await agent.run(CriticInput(**SPY_RETRY_ATTEMPT1))
    _print_result(r4a.model_dump(), "Expected: FAIL (attempt 1)")
    results_summary.append(("SPY retry attempt 1", "FAIL", r4a.verdict))

    time.sleep(2)

    _separator("Attempt 2 — Agent 02 corrected per retry instructions")
    r4b = await agent.run(CriticInput(**SPY_RETRY_ATTEMPT2))
    _print_result(r4b.model_dump(), "Expected: PASS (attempt 2)")
    results_summary.append(("SPY retry attempt 2", "PASS", r4b.verdict))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*64}")
    print(f"  {BOLD}TEST SUMMARY{RESET}")
    print(f"{'═'*64}")
    all_pass = True
    for label, expected, actual in results_summary:
        match  = expected == actual
        colour = GREEN if match else RED
        icon   = "✓" if match else "✗"
        if not match:
            all_pass = False
        print(f"  {colour}{icon}{RESET} {label:<28} expected={expected:<5} got={actual}")

    print()
    if all_pass:
        print(f"  {GREEN}{BOLD}All scenarios matched expected verdicts.{RESET}")
    else:
        print(f"  {RED}{BOLD}Some scenarios did not match — review LLM output above.{RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(run_all())
