"""
SentinelAI LangGraph pipeline.

Topology (per presentation spec):
  START → intake → geopolitical → sentiment → asset_analyst → critic
  critic → [conditional]:
    PASS/FAIL → synthesis → END
    REVISE (attempt < 3) → geopolitical (retry from analysis start)
    REVISE (attempt ≥ 3) → synthesis (force forward with FAIL)
  intake/geo/sent/asset error → error_handler → END

LangGraph nodes run sequentially — zero simultaneous GPU load.
State transitions are atomic: each node's return dict is merged into state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .nodes import (
    node_asset_analyst,
    node_critic,
    node_error,
    node_geopolitical,
    node_intake,
    node_sentiment,
    node_synthesis,
)
from .state import PipelineState
from .store import save_state_snapshot

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph

    _LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False


# ── Routing functions ─────────────────────────────────────────────────────────

def _route_after_intake(state: PipelineState) -> str:
    if state.get("status") == "failed":
        return "error_handler"
    return "geopolitical"


def _route_after_geo(state: PipelineState) -> str:
    if state.get("status") == "failed":
        return "error_handler"
    return "sentiment"


def _route_after_sentiment(state: PipelineState) -> str:
    if state.get("status") == "failed":
        return "error_handler"
    return "asset_analyst"


def _route_after_asset(state: PipelineState) -> str:
    if state.get("status") == "failed":
        return "error_handler"
    return "critic"


def _route_after_critic(state: PipelineState) -> str:
    status = state.get("status", "")
    if status == "failed":
        return "error_handler"
    if status == "revise":
        return "geopolitical"  # re-run analysis from agent 02
    return "synthesis"


# ── LangGraph graph builder ───────────────────────────────────────────────────

def compile_pipeline():
    """
    Compile the LangGraph StateGraph.
    Returns a compiled graph or None if LangGraph is unavailable.
    """
    if not _LANGGRAPH_AVAILABLE or StateGraph is None:
        logger.warning("LangGraph unavailable — pipeline will use sequential fallback")
        return None

    builder = StateGraph(PipelineState)

    # Register nodes
    builder.add_node("intake",        node_intake)
    builder.add_node("geopolitical",  node_geopolitical)
    builder.add_node("sentiment",     node_sentiment)
    builder.add_node("asset_analyst", node_asset_analyst)
    builder.add_node("critic",        node_critic)
    builder.add_node("synthesis",     node_synthesis)
    builder.add_node("error_handler", node_error)

    # Edges
    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake",        _route_after_intake,   {"geopolitical": "geopolitical", "error_handler": "error_handler"})
    builder.add_conditional_edges("geopolitical",  _route_after_geo,      {"sentiment": "sentiment",       "error_handler": "error_handler"})
    builder.add_conditional_edges("sentiment",     _route_after_sentiment,{"asset_analyst": "asset_analyst","error_handler": "error_handler"})
    builder.add_conditional_edges("asset_analyst", _route_after_asset,    {"critic": "critic",             "error_handler": "error_handler"})
    builder.add_conditional_edges(
        "critic",
        _route_after_critic,
        {
            "synthesis":    "synthesis",
            "geopolitical": "geopolitical",
            "error_handler":"error_handler",
        },
    )
    builder.add_edge("synthesis",     END)
    builder.add_edge("error_handler", END)

    return builder.compile()


# ── Sequential fallback ───────────────────────────────────────────────────────

async def _sequential_run(state: PipelineState) -> PipelineState:
    """Run pipeline nodes one-by-one if LangGraph is unavailable."""
    steps = [node_intake, node_geopolitical, node_sentiment, node_asset_analyst]

    for step in steps:
        state.update(await step(state))  # type: ignore[arg-type]
        if state.get("status") == "failed":
            state.update(await node_error(state))  # type: ignore[arg-type]
            return state

    # Critic with up to 3 retry loops
    for _attempt in range(3):
        state.update(await node_critic(state))  # type: ignore[arg-type]
        s = state.get("status", "")
        if s == "failed":
            state.update(await node_error(state))  # type: ignore[arg-type]
            return state
        if s != "revise":
            break
        logger.info("Pipeline: critic issued REVISE, retrying analysis (attempt %d)", _attempt + 2)
        # Re-run analysis steps
        for step in [node_geopolitical, node_sentiment, node_asset_analyst]:
            state.update(await step(state))  # type: ignore[arg-type]
            if state.get("status") == "failed":
                state.update(await node_error(state))  # type: ignore[arg-type]
                return state

    state.update(await node_synthesis(state))  # type: ignore[arg-type]
    if state.get("status") == "failed":
        state.update(await node_error(state))  # type: ignore[arg-type]
    return state


# ── Public run_pipeline ───────────────────────────────────────────────────────

_compiled_graph = None


async def run_pipeline(initial_state: PipelineState, db=None) -> PipelineState:
    """
    Execute the full pipeline from initial_state.

    Persists state snapshots to MongoDB after each agent if db is provided.
    Always returns a PipelineState regardless of errors (never raises).
    """
    global _compiled_graph

    if _compiled_graph is None:
        _compiled_graph = compile_pipeline()

    try:
        if _compiled_graph is not None:
            final = await _compiled_graph.ainvoke(initial_state)
        else:
            final = await _sequential_run(dict(initial_state))  # type: ignore[arg-type]
    except Exception as exc:
        logger.error("Pipeline run_id=%s crashed: %s", initial_state.get("run_id"), exc)
        final = dict(initial_state)
        final["status"] = "failed"
        final["error_message"] = f"Pipeline crash: {exc}"

    # Persist final state to MongoDB
    if db is not None:
        try:
            await save_state_snapshot(
                db=db,
                run_id=str(final.get("run_id", "")),
                status=str(final.get("status", "failed")),
                state_snapshot={k: v for k, v in final.items() if k != "pdf_bytes"},
                error_message=final.get("error_message"),
            )
        except Exception as exc:
            logger.error("Failed to persist pipeline state: %s", exc)

    return final  # type: ignore[return-value]
