"""
Tool: Source Verifier
Deterministic pre-check — runs before any LLM call.

Rules:
  - Every agent output MUST have at least one source.
  - Each source must be either:
      • A valid HTTP/HTTPS URL, OR
      • A FRED series ID (uppercase letters + digits, 4–20 chars)
  - Attribution rate must be ≥ 90 % to pass.
"""
from __future__ import annotations

import re

from ..schemas import CriticInput

# FRED series IDs: start with a letter, uppercase alphanumeric, 4–20 chars
_FRED_RE = re.compile(r"^[A-Z][A-Z0-9]{3,19}$")
# HTTP/HTTPS URL
_URL_RE = re.compile(r"^https?://\S+")


def _is_valid_source(src: str) -> bool:
    src = src.strip()
    return bool(_URL_RE.match(src)) or bool(_FRED_RE.match(src))


def verify_sources(payload: CriticInput) -> dict:
    """
    Returns a dict compatible with the user-prompt template.

    Keys:
        passed              – bool, overall check result
        sources_verified    – int, valid source count across all agents
        sources_total       – int, total sources declared
        attribution_rate    – float, verified / total
        missing_sources_agents – list[str], agents with zero sources
        per_agent           – per-agent breakdown
    """
    agents: dict[str, list[str]] = {
        "agent_02": payload.geopolitical.sources,
        "agent_03": payload.sentiment.sources,
        "agent_04": payload.asset_analyst.sources,
        "agent_05": payload.quant_risk.sources,
    }

    per_agent: dict = {}
    total = 0
    verified = 0
    missing_agents: list[str] = []

    for agent_id, sources in agents.items():
        total += len(sources)

        if not sources:
            missing_agents.append(agent_id)
            per_agent[agent_id] = {
                "has_sources": False,
                "valid": 0,
                "total": 0,
                "invalid": [],
            }
            continue

        valid = [s for s in sources if _is_valid_source(s)]
        invalid = [s for s in sources if not _is_valid_source(s)]
        verified += len(valid)

        per_agent[agent_id] = {
            "has_sources": True,
            "valid": len(valid),
            "total": len(sources),
            "invalid": invalid,
        }

    attribution_rate = round(verified / total, 4) if total > 0 else 0.0
    passed = (not missing_agents) and (attribution_rate >= 0.90)

    return {
        "passed": passed,
        "sources_verified": verified,
        "sources_total": total,
        "attribution_rate": attribution_rate,
        "missing_sources_agents": missing_agents,
        "per_agent": per_agent,
    }
