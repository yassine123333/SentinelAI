"""
Pipeline shared state schema — LangGraph TypedDict.

All fields are Optional (total=False) so each node only declares what it writes.
The state is serialised to MongoDB after each agent completes for crash-recovery.
"""
from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    # ── Identity ───────────────────────────────────────────────────────────────
    run_id: str
    user_id: str

    # ── Agent 01: Routing ─────────────────────────────────────────────────────
    raw_query: str
    asset_hint: str | None        # raw hint from user request (read by node_intake)
    timeframe_hint: str | None    # raw hint from user request (read by node_intake)
    risk_focus_hint: str | None   # raw hint from user request (read by node_intake)
    asset: str
    timeframe: str
    risk_focus: str
    keywords: list[str]
    routing_confidence: float

    # ── Agent 02: Geopolitical ─────────────────────────────────────────────────
    geopolitical: dict[str, Any]   # GeopoliticalOutput-compatible

    # ── Agent 03: Sentiment ───────────────────────────────────────────────────
    sentiment: dict[str, Any]      # SentimentOutput-compatible

    # ── Agent 04: Asset Analyst ───────────────────────────────────────────────
    asset_analyst: dict[str, Any]  # AssetAnalystOutput-compatible

    # ── Agent 06: Critic ─────────────────────────────────────────────────────
    critic: dict[str, Any]         # CriticOutput-compatible
    critic_attempt: int            # 1–3

    # ── Agent 07: Synthesis ──────────────────────────────────────────────────
    synthesis: dict[str, Any]      # SynthesisOutput (minus pdf_bytes)
    pdf_bytes: bytes | None

    # ── Pipeline metadata ─────────────────────────────────────────────────────
    status: str                    # routing|geo|sentiment|asset|critic|synthesis|done|failed
    started_at: str
    error_message: str | None
    reasoning_trace: list[str]
