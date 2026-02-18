"""
run_critic.py — Standalone CLI runner for Agent 06.

Usage:
    cd backend
    python run_critic.py <path/to/input.json>

If no file is provided, it runs with a built-in sample PASS scenario.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

from app.agents.agent_06_critic.agent import CriticAgent
from app.agents.agent_06_critic.schemas import CriticInput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── Built-in sample (Gold, all-clean) ─────────────────────────────────────────
_SAMPLE: dict = {
    "query_id": "sample-run-001",
    "asset": "GC=F",
    "attempt": 1,
    "geopolitical": {
        "agent_id": "agent_02",
        "stability_score": 62.0,
        "key_events": [
            {"date": "2026-02-10", "description": "Fed held rates steady", "impact": "moderate"},
            {"date": "2026-02-12", "description": "Middle East tensions elevated", "impact": "high"},
        ],
        "macro_indicators": [
            {"series_id": "FEDFUNDS", "name": "Fed Funds Rate", "value": 5.25, "trend": "stable"},
            {"series_id": "CPIAUCSL", "name": "CPI", "value": 3.1, "trend": "falling"},
            {"series_id": "DGS10", "name": "10-Year Treasury Yield", "value": 4.35, "trend": "stable"},
        ],
        "risk_summary": (
            "Moderate geopolitical risk driven by ongoing Middle East tensions and "
            "Fed policy uncertainty. Safe-haven demand for gold remains elevated. "
            "USD showing mild weakness as rate cut expectations grow."
        ),
        "sources": [
            "https://www.gdeltproject.org/",
            "FEDFUNDS",
            "CPIAUCSL",
            "DGS10",
            "https://fred.stlouisfed.org/series/DGS10",
        ],
        "confidence": 0.82,
    },
    "sentiment": {
        "agent_id": "agent_03",
        "sentiment_score": 0.15,
        "fear_greed_index": 45.0,
        "news_signals": [
            {"source": "Reuters", "tone": "cautiously positive", "score": 0.2},
            {"source": "Bloomberg", "tone": "neutral", "score": 0.05},
        ],
        "social_signals": [
            {"platform": "Reddit r/gold", "tone": "positive", "score": 0.3},
        ],
        "sources": [
            "https://alternative.me/crypto/fear-and-greed-index/",
            "https://reuters.com/markets/commodities/",
        ],
        "confidence": 0.75,
    },
    "asset_analyst": {
        "agent_id": "agent_04",
        "asset": "GC=F",
        "current_price": 2680.5,
        "price_trend": "bullish",
        "key_patterns": ["ascending triangle breakout", "golden cross on daily chart"],
        "short_term_outlook": (
            "Gold shows strong upward momentum. Ascending triangle breakout confirmed "
            "on the daily chart with a golden cross signal. Technical target: $2,750 "
            "over 30 days if macro tailwinds persist."
        ),
        "sources": [
            "https://finance.yahoo.com/quote/GC%3DF/",
            "https://www.tradingview.com/symbols/XAUUSD/",
            "GOLDAMGBD228NLBM",
        ],
        "confidence": 0.78,
    },
    "quant_risk": {
        "agent_id": "agent_05",
        "volatility_30d": 0.18,
        "var_95": 0.032,
        "monte_carlo_scenarios": {
            "bull": {"probability": 0.35, "price_target": 2780,
                     "description": "Fed dovish pivot + safe haven demand surge"},
            "base": {"probability": 0.45, "price_target": 2650,
                     "description": "Status quo — range-bound movement"},
            "bear": {"probability": 0.20, "price_target": 2550,
                     "description": "Risk-on sentiment reduces gold appeal"},
        },
        "garch_forecast": {
            "forecast_30d_vol": 0.17,
            "confidence_interval": [0.14, 0.21],
        },
        "risk_level": "medium",
        "sources": [
            "https://finance.yahoo.com/quote/GC%3DF/history/",
            "GOLDAMGBD228NLBM",
            "VIXCLS",
        ],
        "confidence": 0.80,
    },
}


def _print_result(result: dict) -> None:
    BOLD  = "\033[1m"
    GREEN = "\033[92m"
    RED   = "\033[91m"
    CYAN  = "\033[96m"
    RESET = "\033[0m"

    verdict = result["verdict"]
    colour  = GREEN if verdict == "PASS" else RED

    print("\n" + "═" * 64)
    print(f"  {BOLD}{colour}VERDICT : {verdict}{RESET}")
    print(f"  Confidence : {result['overall_confidence']:.1%}")
    print(f"  Sources    : {result['sources_verified']}/{result['sources_total']} verified")
    print("═" * 64)

    print(f"\n{BOLD}{CYAN}── Checks ──────────────────────────────────────────{RESET}")
    for chk in result.get("checks", []):
        icon = "✓" if chk["passed"] else "✗"
        col  = GREEN if chk["passed"] else RED
        print(f"  {col}{icon}{RESET} [{chk['score']:.2f}] {chk['check_name']}")
        print(f"       {chk['details']}")

    if result.get("retry_instructions"):
        print(f"\n{BOLD}{RED}── Retry Instructions ──────────────────────────────{RESET}")
        for ri in result["retry_instructions"]:
            print(f"  [{ri['priority'].upper()}] {ri['agent_id']}: {ri['reason']}")
            for c in ri["specific_corrections"]:
                print(f"    • {c}")

    if result.get("flagged_claims"):
        print(f"\n{BOLD}{RED}── Flagged Claims ──────────────────────────────────{RESET}")
        for fc in result["flagged_claims"]:
            print(f"  ⚑ {fc}")

    print(f"\n{BOLD}{CYAN}── Reasoning Trace ─────────────────────────────────{RESET}")
    trace = result.get("reasoning_trace", "")
    # Print first 800 chars to keep CLI readable
    print(f"  {trace[:800]}{'...' if len(trace) > 800 else ''}")
    print()


async def main() -> None:
    if len(sys.argv) >= 2:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"Error: file not found: {path}")
            sys.exit(1)
        data = json.loads(path.read_text())
        print(f"Loaded input from: {path}")
    else:
        data = _SAMPLE
        print("No input file provided — running built-in PASS sample (Gold).")

    payload = CriticInput(**data)
    agent   = CriticAgent()

    print(f"Running Agent 06 on query_id='{payload.query_id}' asset='{payload.asset}' …\n")
    result = await agent.run(payload)
    _print_result(result.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
