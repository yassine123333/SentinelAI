"""
Tool: Consistency Checker
Deterministic pre-check — detects contradictions between upstream agents.

Contradiction rules (severity levels: critical > high > medium):
  1. Geopolitical stability > 75  AND Fear/Greed < 20  → high
  2. Geopolitical stability < 25  AND Fear/Greed > 75  → high
  3. Bullish price trend          AND quant risk = extreme → critical
  4. VaR 95 % > 15 %             AND risk_level = 'low'  → critical
  5. VaR 95 % < 2 %              AND risk_level in high/extreme → critical
  6. Strongly negative sentiment  AND bullish trend (|score| > 0.6) → medium (warning)
  7. Positive sentiment           AND bearish trend (score > 0.5)   → medium (warning)
"""
from __future__ import annotations

from ..schemas import CriticInput


def check_consistency(payload: CriticInput) -> dict:
    """
    Returns a dict compatible with the user-prompt template.

    Keys:
        passed              – bool (False if any contradiction exists)
        has_critical        – bool
        contradictions      – list of contradiction dicts
        warnings            – list of warning dicts (non-blocking)
        contradiction_count – int
        warning_count       – int
    """
    geo = payload.geopolitical
    sent = payload.sentiment
    asset = payload.asset_analyst
    quant = payload.quant_risk

    contradictions: list[dict] = []
    warnings: list[dict] = []

    # ── Rule 1: High geopolitical stability + extreme market fear ─────────────
    if geo.stability_score > 75 and sent.fear_greed_index < 20:
        contradictions.append({
            "type": "geo_stable_vs_extreme_fear",
            "description": (
                f"Geopolitical stability is {geo.stability_score:.0f}/100 (high) but the "
                f"Fear & Greed index is {sent.fear_greed_index:.0f}/100 (extreme fear). "
                "A market-specific driver not captured by Agent 02 may be present."
            ),
            "agents": ["agent_02", "agent_03"],
            "severity": "high",
        })

    # ── Rule 2: Geopolitical crisis + extreme market greed ───────────────────
    if geo.stability_score < 25 and sent.fear_greed_index > 75:
        contradictions.append({
            "type": "geo_crisis_vs_extreme_greed",
            "description": (
                f"Geopolitical stability is {geo.stability_score:.0f}/100 (crisis) but the "
                f"Fear & Greed index is {sent.fear_greed_index:.0f}/100 (extreme greed). "
                "Data staleness or significant divergence between agents."
            ),
            "agents": ["agent_02", "agent_03"],
            "severity": "high",
        })

    # ── Rule 3: Bullish trend + extreme quant risk ───────────────────────────
    if asset.price_trend == "bullish" and quant.risk_level == "extreme":
        contradictions.append({
            "type": "bullish_trend_vs_extreme_risk",
            "description": (
                f"Asset analyst flags a bullish trend for {asset.asset} but the quant model "
                f"assigns EXTREME risk (VaR 95 % = {quant.var_95 * 100:.1f} %). "
                "Review Monte Carlo inputs and trend indicators."
            ),
            "agents": ["agent_04", "agent_05"],
            "severity": "critical",
        })

    # ── Rule 4: VaR too high for a 'low' risk label ──────────────────────────
    if quant.var_95 > 0.15 and quant.risk_level == "low":
        contradictions.append({
            "type": "var_too_high_for_low_risk",
            "description": (
                f"VaR 95 % = {quant.var_95 * 100:.1f} % (very high) but risk_level is "
                f"labelled 'low'. Agent 05 quantitative output is internally inconsistent."
            ),
            "agents": ["agent_05"],
            "severity": "critical",
        })

    # ── Rule 5: VaR too low for high/extreme risk label ──────────────────────
    if quant.var_95 < 0.02 and quant.risk_level in ("high", "extreme"):
        contradictions.append({
            "type": "var_too_low_for_high_risk",
            "description": (
                f"VaR 95 % = {quant.var_95 * 100:.1f} % (very low) but risk_level is "
                f"'{quant.risk_level}'. Agent 05 quantitative output is internally inconsistent."
            ),
            "agents": ["agent_05"],
            "severity": "critical",
        })

    # ── Rule 6: Strongly negative sentiment vs bullish price trend ───────────
    if sent.sentiment_score < -0.6 and asset.price_trend == "bullish":
        warnings.append({
            "type": "negative_sentiment_vs_bullish",
            "description": (
                f"Sentiment score is {sent.sentiment_score:.2f} (strongly negative) "
                "but the asset analyst sees a bullish trend. Possible sentiment lag or "
                "technical rally against market tone."
            ),
            "agents": ["agent_03", "agent_04"],
            "severity": "medium",
        })

    # ── Rule 7: Positive sentiment vs bearish price trend ────────────────────
    if sent.sentiment_score > 0.5 and asset.price_trend == "bearish":
        warnings.append({
            "type": "positive_sentiment_vs_bearish",
            "description": (
                f"Sentiment score is {sent.sentiment_score:.2f} (positive) "
                "but the asset analyst sees a bearish trend. Potential reversal signal "
                "or data misalignment."
            ),
            "agents": ["agent_03", "agent_04"],
            "severity": "medium",
        })

    has_critical = any(c["severity"] == "critical" for c in contradictions)
    passed = len(contradictions) == 0

    return {
        "passed": passed,
        "has_critical": has_critical,
        "contradictions": contradictions,
        "warnings": warnings,
        "contradiction_count": len(contradictions),
        "warning_count": len(warnings),
    }
