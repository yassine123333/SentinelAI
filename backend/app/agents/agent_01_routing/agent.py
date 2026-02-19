"""
Agent 01 — Intake & Routing

Deterministic (no LLM) query parser that extracts:
  - asset ticker (from hint, explicit mention, or keyword heuristics)
  - time horizon (days/weeks/months parsing)
  - risk focus (volatility, geopolitical, macro, sentiment, …)
  - search keywords for downstream agents

Security:
  - Prompt injection scan on all text inputs (RoutingInput validator)
  - Ticker regex whitelist [A-Z0-9^=.-]{1,12}
  - Max query length 500 chars (RoutingInput validator)
  - No external calls — deterministic parsing only
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .schemas import RoutingInput, RoutingOutput

logger = logging.getLogger(__name__)

# ── Asset aliases / keyword → ticker map ──────────────────────────────────────
_ASSET_ALIASES: dict[str, str] = {
    # Energy
    "brent": "CL=F", "crude": "CL=F", "oil": "CL=F", "wti": "CL=F",
    "natural gas": "NG=F", "natgas": "NG=F",
    # Crypto
    "bitcoin": "BTC-USD", "btc": "BTC-USD",
    "ethereum": "ETH-USD", "eth": "ETH-USD",
    "crypto": "BTC-USD",
    # Metals
    "gold": "GC=F", "xau": "GC=F",
    "silver": "SI=F", "xag": "SI=F",
    # Indices
    "s&p": "^GSPC", "s&p500": "^GSPC", "sp500": "^GSPC", "spy": "SPY",
    "nasdaq": "^IXIC", "qqq": "QQQ", "dow": "^DJI", "djia": "^DJI",
    "vix": "^VIX", "volatility index": "^VIX",
    "russell": "^RUT", "iwm": "IWM",
    # Forex
    "euro": "EURUSD=X", "eur": "EURUSD=X",
    "yen": "JPY=X", "jpy": "JPY=X",
    "gbp": "GBPUSD=X", "pound": "GBPUSD=X",
    # Bonds
    "10y": "^TNX", "10-year": "^TNX", "treasury": "^TNX",
    # Tech
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA",
    "tesla": "TSLA", "amazon": "AMZN", "meta": "META",
    "google": "GOOGL", "alphabet": "GOOGL",
}

# ── Timeframe patterns ─────────────────────────────────────────────────────────
_TIMEFRAME_RE = re.compile(
    r"(?:next\s+|over\s+(?:the\s+)?(?:next\s+)?|in\s+(?:the\s+)?(?:next\s+)?)?"
    r"(\d+)\s*(day|week|month|year)s?",
    re.IGNORECASE,
)
_TIMEFRAME_KEYWORDS: dict[str, str] = {
    "intraday": "1 day", "daily": "1 day",
    "weekly": "7 days", "short-term": "14 days", "short term": "14 days",
    "monthly": "30 days", "medium-term": "30 days", "medium term": "30 days",
    "quarterly": "90 days",
    "long-term": "180 days", "long term": "180 days",
}

# ── Risk focus patterns ───────────────────────────────────────────────────────
_FOCUS_KEYWORDS: dict[str, str] = {
    "volatil": "volatility",
    "geopolit": "geopolitical",
    "macro": "macro",
    "infla": "inflation",
    "recessio": "recession",
    "sentiment": "sentiment",
    "technical": "technical",
    "fundament": "fundamental",
    "credit": "credit",
    "liquidity": "liquidity",
    "systemic": "systemic",
    "tail risk": "tail_risk",
    "default": "default",
    "currency": "currency",
    "commodit": "commodity",
    "interest rate": "interest_rate",
    "rate risk": "interest_rate",
}

# ── Explicit ticker regex ─────────────────────────────────────────────────────
# Matches strings like $AAPL, AAPL, BTC-USD, ^GSPC
_TICKER_MENTION_RE = re.compile(
    r"\b(\^?[A-Z]{1,5}(?:[-=][A-Z0-9]{1,6})?)\b|\$([A-Z]{1,5})\b"
)


class IntakeAgent:
    """
    Agent 01 — Intake & Routing.

    Deterministic parser — no external calls, no LLM.
    Security controls enforced via Pydantic validators on RoutingInput.
    """

    agent_id = "agent_01"

    def run(self, inp: RoutingInput) -> RoutingOutput:
        """
        Parse and normalize the routing input.
        Returns RoutingOutput with asset, timeframe, risk_focus, keywords.
        """
        query_lower = inp.raw_query.lower()

        # ── Asset resolution ─────────────────────────────────────────────────
        asset, asset_source = self._resolve_asset(
            raw_query=inp.raw_query,
            query_lower=query_lower,
            hint=inp.asset_hint,
        )

        # ── Timeframe resolution ─────────────────────────────────────────────
        timeframe, tf_source = self._resolve_timeframe(
            query_lower=query_lower,
            hint=inp.timeframe_hint,
        )

        # ── Risk focus resolution ─────────────────────────────────────────────
        risk_focus = self._resolve_risk_focus(
            query_lower=query_lower,
            hint=inp.risk_focus_hint,
        )

        # ── Keywords ──────────────────────────────────────────────────────────
        keywords = self._extract_keywords(inp.raw_query, asset)

        # ── Confidence ────────────────────────────────────────────────────────
        confidence = self._score_confidence(asset_source, tf_source, inp)

        routing_source: str
        if inp.asset_hint and inp.timeframe_hint:
            routing_source = "hint_override"
        elif asset_source == "default" and tf_source == "default":
            routing_source = "default"
        else:
            routing_source = "extracted"

        logger.info(
            "agent_01 routing: asset=%s timeframe=%s focus=%s confidence=%.2f source=%s",
            asset, timeframe, risk_focus, confidence, routing_source,
        )

        return RoutingOutput(
            asset=asset,
            timeframe=timeframe,
            risk_focus=risk_focus,
            keywords=keywords,
            confidence=confidence,
            routing_source=routing_source,
        )

    # ── Asset resolution ──────────────────────────────────────────────────────

    def _resolve_asset(
        self,
        raw_query: str,
        query_lower: str,
        hint: str | None,
    ) -> tuple[str, str]:
        """Return (ticker, source) where source is 'hint'/'alias'/'mention'/'default'."""
        if hint:
            return hint.upper(), "hint"

        # Check alias map (longest match first to avoid "bitcoin" matching "bit")
        for keyword, ticker in sorted(_ASSET_ALIASES.items(), key=lambda x: -len(x[0])):
            if keyword in query_lower:
                return ticker, "alias"

        # Check explicit ticker mentions: $AAPL or AAPL
        for match in _TICKER_MENTION_RE.finditer(raw_query):
            ticker_candidate = (match.group(1) or match.group(2) or "").upper()
            # Filter out common English words falsely matched
            if ticker_candidate and len(ticker_candidate) >= 2 and ticker_candidate not in {
                "AS", "AN", "AT", "BE", "BY", "DO", "GO", "IF", "IN",
                "IS", "IT", "NO", "OF", "ON", "OR", "TO", "UP", "US",
                "WE", "VS", "VIA", "FOR", "AND", "THE", "A",
            }:
                return ticker_candidate, "mention"

        return "SPY", "default"

    # ── Timeframe resolution ──────────────────────────────────────────────────

    def _resolve_timeframe(
        self,
        query_lower: str,
        hint: str | None,
    ) -> tuple[str, str]:
        if hint:
            return hint, "hint"

        # Keyword shortcuts
        for kw, tf in _TIMEFRAME_KEYWORDS.items():
            if kw in query_lower:
                return tf, "keyword"

        # Numeric pattern: "30 days", "2 weeks", "3 months"
        m = _TIMEFRAME_RE.search(query_lower)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            multipliers = {"day": 1, "week": 7, "month": 30, "year": 365}
            days = n * multipliers.get(unit, 1)
            # Cap to reasonable bounds
            days = max(1, min(days, 365))
            return f"{days} days", "extracted"

        return "30 days", "default"

    # ── Risk focus resolution ─────────────────────────────────────────────────

    def _resolve_risk_focus(self, query_lower: str, hint: str | None) -> str:
        if hint:
            return hint.lower().strip()

        for kw, focus in _FOCUS_KEYWORDS.items():
            if kw in query_lower:
                return focus

        # Detect "risk" without a specific focus
        if "risk" in query_lower:
            return "general_risk"

        return "macro"

    # ── Keywords ─────────────────────────────────────────────────────────────

    def _extract_keywords(self, raw_query: str, asset: str) -> list[str]:
        """
        Extract a clean list of search keywords for downstream agents.
        Includes asset name + meaningful query terms.
        """
        stop_words = {
            "the", "a", "an", "and", "or", "in", "of", "to", "for",
            "with", "what", "is", "are", "how", "give", "me", "please",
            "on", "over", "next", "days", "weeks", "months", "risk", "profile",
        }
        words = re.findall(r"[a-zA-Z]{3,}", raw_query.lower())
        keywords = [w for w in words if w not in stop_words]

        # Add the ticker as a keyword if not already
        if asset.lower() not in {k.lower() for k in keywords}:
            keywords.insert(0, asset)

        # Deduplicate, preserve order, limit to 10
        seen: set[str] = set()
        result: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
            if len(result) >= 10:
                break

        return result

    # ── Confidence scoring ────────────────────────────────────────────────────

    def _score_confidence(
        self,
        asset_source: str,
        tf_source: str,
        inp: RoutingInput,
    ) -> float:
        score = 0.50
        asset_scores = {"hint": 0.40, "alias": 0.35, "mention": 0.25, "default": 0.0}
        tf_scores = {"hint": 0.10, "keyword": 0.08, "extracted": 0.07, "default": 0.0}
        score += asset_scores.get(asset_source, 0.0)
        score += tf_scores.get(tf_source, 0.0)
        return round(min(score, 1.0), 4)
