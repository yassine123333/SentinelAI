from __future__ import annotations

import math
import re
from dataclasses import dataclass


ASSET_ALIASES = {
    "brent": "CL=F",
    "brent crude": "CL=F",
    "oil": "CL=F",
    "gold": "GC=F",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "sp500": "^GSPC",
    "s&p": "^GSPC",
}


@dataclass
class RoutingResult:
    asset: str
    timeframe: str
    risk_focus: str


class SimulationEngine:
    @staticmethod
    def route_query(query: str, asset_hint: str | None, timeframe_hint: str | None, risk_focus: str | None) -> RoutingResult:
        text = query.strip()
        lowered = text.lower()
        asset = SimulationEngine._extract_asset(text, lowered, asset_hint)
        timeframe = timeframe_hint or SimulationEngine._extract_timeframe(lowered)
        focus = risk_focus or SimulationEngine._extract_focus(lowered)
        return RoutingResult(asset=asset, timeframe=timeframe, risk_focus=focus)

    @staticmethod
    def geopolitical_score(query: str) -> tuple[float, list[str]]:
        lowered = query.lower()
        score = 0.25
        drivers: list[str] = []
        rules = [
            ("war|conflict|tension|military", 0.25, "Active conflict risk"),
            ("sanction|embargo|trade restriction", 0.18, "Sanctions/trade pressure"),
            ("election|instability|coup|protest", 0.12, "Political instability"),
            ("fed|rate|inflation|cpi|gdp|yield", 0.15, "Macro policy sensitivity"),
            ("middle east|red sea|hormuz", 0.2, "Energy chokepoint exposure"),
        ]
        for pattern, weight, label in rules:
            if re.search(pattern, lowered):
                score += weight
                drivers.append(label)
        return min(score, 0.98), drivers or ["No major geopolitical trigger detected"]

    @staticmethod
    def sentiment_score(query: str) -> tuple[float, str]:
        lowered = query.lower()
        negative = len(re.findall(r"panic|fear|selloff|recession|crash|uncertain", lowered))
        positive = len(re.findall(r"optimism|rally|growth|bullish|upside|recovery", lowered))
        net = positive - negative
        score = 0.5 + (net * 0.12)
        score = max(0.05, min(score, 0.95))
        label = "bullish" if score > 0.58 else "bearish" if score < 0.42 else "neutral"
        return score, label

    @staticmethod
    def asset_risk(asset: str, geo_score: float, sentiment_score: float) -> dict[str, float | str]:
        baseline = 0.4
        if asset.endswith("-USD"):
            baseline = 0.62
        elif asset in {"CL=F", "NG=F"}:
            baseline = 0.58
        elif asset.startswith("^"):
            baseline = 0.38

        implied = baseline + 0.35 * geo_score + 0.15 * (1 - sentiment_score)
        implied = min(max(implied, 0.08), 0.97)
        regime = "high" if implied > 0.7 else "medium" if implied > 0.45 else "low"

        spread = 0.04 + implied * 0.08
        median_move = (implied - 0.5) * 0.06
        return {
            "volatility_regime": regime,
            "implied_risk": round(implied, 4),
            "scenario_low": round(median_move - spread, 4),
            "scenario_mid": round(median_move, 4),
            "scenario_high": round(median_move + spread, 4),
        }

    @staticmethod
    def critic_verdict(geo_score: float, sentiment_score: float, implied_risk: float) -> tuple[str, str]:
        contradiction = abs((1 - geo_score) - sentiment_score)
        if implied_risk > 0.8 and sentiment_score > 0.7:
            return "REVISE", "Risk model is severe while sentiment is strongly bullish; check data freshness."
        if contradiction > 0.65:
            return "REVISE", "Sentiment and geopolitical drivers disagree materially; treat as unstable signal."
        if implied_risk < 0.25 and geo_score > 0.7:
            return "REVISE", "Low implied risk conflicts with elevated geopolitical stress."
        return "PASS", "Cross-agent consistency acceptable."

    @staticmethod
    def scenario_probabilities(implied_risk: float, sentiment_score: float, critic_verdict: str) -> dict[str, float]:
        high = 0.25 + implied_risk * 0.5 + max(0.0, 0.5 - sentiment_score) * 0.2
        low = 0.2 + (1 - implied_risk) * 0.45 + max(0.0, sentiment_score - 0.5) * 0.2
        mid = max(0.05, 1 - high - low)
        total = high + low + mid
        high, mid, low = high / total, mid / total, low / total

        if critic_verdict == "REVISE":
            high = min(0.85, high + 0.05)
            low = max(0.05, low - 0.03)
            mid = 1 - high - low

        probs = {
            "high_risk": round(high, 4),
            "base_case": round(mid, 4),
            "low_risk": round(low, 4),
        }

        residual = 1.0 - sum(probs.values())
        if not math.isclose(residual, 0.0):
            probs["base_case"] = round(probs["base_case"] + residual, 4)
        return probs

    @staticmethod
    def _extract_asset(original: str, lowered: str, asset_hint: str | None) -> str:
        if asset_hint:
            return asset_hint.upper()

        for alias, ticker in ASSET_ALIASES.items():
            if alias in lowered:
                return ticker

        token_match = re.findall(r"\b[A-Z0-9\^=\-\.]{1,12}\b", original)
        for token in token_match:
            if token.isdigit():
                continue
            return token

        return "SPY"

    @staticmethod
    def _extract_timeframe(lowered: str) -> str:
        match = re.search(r"(\d+\s*(?:day|days|week|weeks|month|months|year|years))", lowered)
        if match:
            return match.group(1)
        if "short" in lowered:
            return "14 days"
        if "long" in lowered:
            return "90 days"
        return "30 days"

    @staticmethod
    def _extract_focus(lowered: str) -> str:
        if "volatility" in lowered:
            return "volatility"
        if "macro" in lowered:
            return "macro-risk"
        if "sentiment" in lowered:
            return "sentiment-shift"
        return "overall-risk"
