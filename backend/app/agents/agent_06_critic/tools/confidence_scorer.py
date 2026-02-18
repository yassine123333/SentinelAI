"""
Tool: Confidence Scorer
Deterministic pre-check — aggregates per-agent confidence scores.

Weights (must sum to 1.0):
  agent_02 (Geopolitical) : 0.25
  agent_03 (Sentiment)    : 0.20
  agent_04 (Asset Analyst): 0.25
  agent_05 (Quant & Risk) : 0.30

Pass threshold: aggregate ≥ 0.70 AND no individual agent below 0.70
"""
from __future__ import annotations

from ..schemas import CriticInput

WEIGHTS: dict[str, float] = {
    "agent_02": 0.25,
    "agent_03": 0.20,
    "agent_04": 0.25,
    "agent_05": 0.30,
}

THRESHOLD = 0.70


def get_confidence_breakdown(payload: CriticInput) -> dict:
    """
    Returns a dict compatible with the user-prompt template.

    Keys:
        aggregate               – float, weighted confidence
        passed                  – bool
        per_agent               – per-agent score, weight, pass/fail
        low_confidence_agents   – agents below threshold
        threshold               – float
    """
    scores: dict[str, float] = {
        "agent_02": payload.geopolitical.confidence,
        "agent_03": payload.sentiment.confidence,
        "agent_04": payload.asset_analyst.confidence,
        "agent_05": payload.quant_risk.confidence,
    }

    aggregate = round(
        sum(scores[a] * w for a, w in WEIGHTS.items()), 4
    )

    low_confidence = {a: s for a, s in scores.items() if s < THRESHOLD}

    return {
        "aggregate": aggregate,
        "passed": aggregate >= THRESHOLD and not low_confidence,
        "per_agent": {
            a: {
                "score": round(s, 4),
                "weight": WEIGHTS[a],
                "passed": s >= THRESHOLD,
            }
            for a, s in scores.items()
        },
        "low_confidence_agents": low_confidence,
        "threshold": THRESHOLD,
    }
