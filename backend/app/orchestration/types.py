from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentReport:
    agent_name: str
    status: str
    confidence: float
    payload: dict[str, Any]
    reasoning: str
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class OrchestrationRequest:
    query: str
    session_id: str
    asset_hint: str | None = None
    timeframe_hint: str | None = None
    risk_focus: str | None = None
    use_gemini: bool = False


@dataclass
class OrchestrationResult:
    session_id: str
    final_verdict: str
    scenario_probabilities: dict[str, float]
    normalized_input: dict[str, Any]
    reports: list[AgentReport]
    reasoning_trace: list[str]
    started_at: str
    finished_at: str
