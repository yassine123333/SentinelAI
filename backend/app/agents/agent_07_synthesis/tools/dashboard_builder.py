"""
Dashboard builder for Agent 07 — Report Synthesis.

All logic here is fully deterministic — no LLM calls.
Computes the structured DashboardPayload consumed by the React frontend.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..resources.schemas import (
    AgentConfidenceBar,
    DashboardPayload,
    RiskGauge,
    ScenarioProbabilities,
    SynthesisInput,
)


# ── Risk gauge ────────────────────────────────────────────────────────────────

_LEVEL_BASE_SCORES: dict[str, float] = {
    "low": 0.20,
    "medium": 0.50,
    "high": 0.75,
    "extreme": 0.95,
}


def _compute_risk_gauge(payload: SynthesisInput) -> RiskGauge:
    """
    Blend three risk signals into a single 0–1 composite score:
      - 50 %  quant risk level (from QuantRiskOutput.risk_level)
      - 25 %  geopolitical stress  (1 − stability_score / 100)
      - 25 %  sentiment fear       (1 − fear_greed_index / 100)
    """
    base_score = _LEVEL_BASE_SCORES.get(payload.quant_risk.risk_level, 0.5)
    geo_factor = 1.0 - (payload.geopolitical.stability_score / 100.0)
    sent_factor = 1.0 - (payload.sentiment.fear_greed_index / 100.0)

    composite = round(
        base_score * 0.50 + geo_factor * 0.25 + sent_factor * 0.25, 4
    )
    composite = max(0.0, min(1.0, composite))

    if composite >= 0.80:
        level, label = "extreme", "Extreme Risk"
    elif composite >= 0.55:
        level, label = "high", "High Risk"
    elif composite >= 0.30:
        level, label = "medium", "Moderate Risk"
    else:
        level, label = "low", "Low Risk"

    return RiskGauge(score=composite, level=level, label=label)


# ── Scenario probabilities ─────────────────────────────────────────────────────

def _extract_scenario_probs(payload: SynthesisInput) -> ScenarioProbabilities:
    """
    Extract bull / base / bear probabilities from QuantRiskOutput.monte_carlo_scenarios.
    Tries multiple key variants (bull/high_risk, base/base_case, bear/low_risk).
    Normalizes to sum = 1.0.
    """
    mc: dict = payload.quant_risk.monte_carlo_scenarios

    def _pick(keys: list[str], default: float) -> float:
        for k in keys:
            if k in mc:
                return float(mc[k])
        return default

    bull = _pick(["bull", "high_risk", "upside"], 0.20)
    base = _pick(["base", "base_case", "neutral"], 0.50)
    bear = _pick(["bear", "low_risk", "downside"], 0.30)

    total = bull + base + bear
    if total > 0:
        bull, base, bear = bull / total, base / total, bear / total
    else:
        bull, base, bear = 0.20, 0.50, 0.30

    return ScenarioProbabilities(
        bull=round(bull, 4),
        base=round(base, 4),
        bear=round(bear, 4),
    )


# ── Agent confidence chart ─────────────────────────────────────────────────────

def _build_confidence_chart(payload: SynthesisInput) -> list[AgentConfidenceBar]:
    return [
        AgentConfidenceBar(
            agent_id="agent_02",
            agent_label="Geopolitical",
            confidence=round(payload.geopolitical.confidence, 4),
        ),
        AgentConfidenceBar(
            agent_id="agent_03",
            agent_label="Sentiment",
            confidence=round(payload.sentiment.confidence, 4),
        ),
        AgentConfidenceBar(
            agent_id="agent_04",
            agent_label="Asset Analyst",
            confidence=round(payload.asset_analyst.confidence, 4),
        ),
        AgentConfidenceBar(
            agent_id="agent_05",
            agent_label="Quant Risk",
            confidence=round(payload.quant_risk.confidence, 4),
        ),
        AgentConfidenceBar(
            agent_id="agent_06",
            agent_label="Critic",
            confidence=round(payload.critic.overall_confidence, 4),
        ),
    ]


# ── Sentiment label ────────────────────────────────────────────────────────────

def _sentiment_label(fear_greed_index: float) -> str:
    if fear_greed_index >= 75:
        return "Extreme Greed"
    if fear_greed_index >= 55:
        return "Greed"
    if fear_greed_index >= 45:
        return "Neutral"
    if fear_greed_index >= 25:
        return "Fear"
    return "Extreme Fear"


# ── Critic summary ─────────────────────────────────────────────────────────────

def _build_critic_summary(payload: SynthesisInput) -> dict:
    critic = payload.critic
    checks_passed = sum(1 for c in critic.checks if c.passed)
    return {
        "verdict": critic.verdict,
        "overall_confidence": round(critic.overall_confidence, 4),
        "checks_passed": checks_passed,
        "checks_total": len(critic.checks),
        "sources_verified": critic.sources_verified,
        "sources_total": critic.sources_total,
        "flagged_claims_count": len(critic.flagged_claims),
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def build_dashboard_payload(payload: SynthesisInput) -> DashboardPayload:
    """
    Deterministically assemble the full DashboardPayload from pipeline data.
    No LLM involved — pure data transformation.
    """
    risk_gauge = _compute_risk_gauge(payload)
    scenario_probs = _extract_scenario_probs(payload)
    conf_chart = _build_confidence_chart(payload)

    geo = payload.geopolitical
    sent = payload.sentiment
    asset = payload.asset_analyst
    quant = payload.quant_risk
    critic = payload.critic

    return DashboardPayload(
        meta={
            "query_id": payload.query_id,
            "asset": payload.asset,
            "verdict": critic.verdict,
            "overall_confidence": round(critic.overall_confidence, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        risk_gauge=risk_gauge,
        scenario_probabilities=scenario_probs,
        agent_confidence_chart=conf_chart,
        key_risks=[],       # filled by LLM output after Gemini call
        key_opportunities=[],
        geopolitical={
            "stability_score": round(geo.stability_score, 2),
            "risk_summary": geo.risk_summary[:500],
            "key_events_count": len(geo.key_events),
            "macro_indicators_count": len(geo.macro_indicators),
            "confidence": round(geo.confidence, 4),
        },
        sentiment={
            "score": round(sent.sentiment_score, 4),
            "fear_greed_index": round(sent.fear_greed_index, 2),
            "label": _sentiment_label(sent.fear_greed_index),
            "news_signals_count": len(sent.news_signals),
            "social_signals_count": len(sent.social_signals),
            "confidence": round(sent.confidence, 4),
        },
        asset={
            "ticker": asset.asset,
            "current_price": asset.current_price,
            "price_trend": asset.price_trend,
            "key_patterns": asset.key_patterns[:5],
            "short_term_outlook": asset.short_term_outlook[:300],
            "confidence": round(asset.confidence, 4),
        },
        quant_risk={
            "volatility_30d": round(quant.volatility_30d, 6),
            "volatility_30d_pct": round(quant.volatility_30d * 100, 2),
            "var_95": round(quant.var_95, 6),
            "var_95_pct": round(quant.var_95 * 100, 2),
            "risk_level": quant.risk_level,
            "monte_carlo_scenarios": quant.monte_carlo_scenarios,
            "garch_forecast": quant.garch_forecast,
            "confidence": round(quant.confidence, 4),
        },
        critic=_build_critic_summary(payload),
    )
