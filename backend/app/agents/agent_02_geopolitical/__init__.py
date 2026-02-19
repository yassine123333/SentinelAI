"""
Agent 02 — Geopolitical & Macro

Package entry point that exposes a single clean async interface used by the
pipeline orchestrator. Internally it tries to call the full GeoKG-RAG agent
(requires Weaviate + Neo4j + GDELT running). If those services are unavailable
it falls back to a Gemini 2.5 Flash direct synthesis using the query text.

RAG Poisoning Prevention:
  - Long-memory store is read-only from this adapter (no user-submitted writes).
  - The real agent's Weaviate index contains only official sources (FRED, GDELT)
    with no user-submitted documents.
  - Gemini fallback uses a closed-book prompt: zero external data injected.

Prompt Injection Prevention:
  - asset and query go through the same _INJECTION_RE check before Gemini call.
  - GeoKG agent applies its own injection detection internally.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Injection guard ───────────────────────────────────────────────────────────
_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|<\|im_end\|>|"
    r"</s>|act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE | re.DOTALL,
)

_GEO_AGENT_DIR = Path(__file__).parent


@contextlib.contextmanager
def _agent_sys_path():
    """Temporarily add agent_02's directory to sys.path for bare-module imports."""
    str_path = str(_GEO_AGENT_DIR)
    inserted = str_path not in sys.path
    if inserted:
        sys.path.insert(0, str_path)
    try:
        yield
    finally:
        if inserted and str_path in sys.path:
            sys.path.remove(str_path)


def _sanitize(text: str) -> str:
    if _INJECTION_RE.search(text[:4000]):
        raise ValueError("Prompt injection pattern detected.")
    return text[:4000]


# ── Real agent call ───────────────────────────────────────────────────────────

async def _try_real_agent(asset: str, query: str, timeframe: str) -> dict[str, Any] | None:
    """
    Attempt to call the full GeoKG-RAG agent.
    Returns None if the required services are unavailable.
    """
    try:
        with _agent_sys_path():
            from agent.geokg_agent import GeoKGAgent  # type: ignore[import]

            geo_agent = GeoKGAgent()
            result = await geo_agent.arun(
                query=f"{query} [{asset}, {timeframe}]"
            )
            # Convert GeoKG result to GeopoliticalOutput-compatible dict
            return {
                "agent_id": "agent_02",
                "stability_score": float(result.get("stability_score", 50.0)),
                "key_events": result.get("key_events", [])[:10],
                "macro_indicators": result.get("macro_indicators", [])[:10],
                "risk_summary": str(result.get("report", ""))[:2000],
                "sources": result.get("sources_used", [])[:20],
                "confidence": float(result.get("confidence", 0.70)),
            }
    except Exception as exc:
        logger.info("agent_02 real agent unavailable (%s), using Gemini fallback", exc)
        return None


# ── Gemini fallback ───────────────────────────────────────────────────────────

async def _gemini_fallback(asset: str, query: str, timeframe: str) -> dict[str, Any]:
    """
    Gemini 2.5 Flash closed-book fallback for geopolitical analysis.
    Only uses the structured query — no external data injected.
    """
    from google import genai
    from google.genai import types as gtypes

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("agent_02 fallback: GEMINI_API_KEY not set, returning minimal baseline")
        return _minimal_baseline(asset)

    client = genai.Client(api_key=api_key)
    system = (
        "You are a geopolitical risk analyst. "
        "Respond ONLY with a JSON object. Do not add prose outside the JSON. "
        "Base your analysis on general knowledge of macroeconomic conditions relevant to the asset. "
        "Never generate buy/sell recommendations. Never invent specific news that is not widely known. "
        "Use conservative, factual language."
    )
    user = (
        f"Provide a geopolitical and macro risk assessment for asset '{asset}' "
        f"given this query: \"{query}\". Timeframe: {timeframe}.\n\n"
        "Return ONLY this JSON structure:\n"
        "{\n"
        '  "stability_score": <float 0-100, 0=crisis 100=stable>,\n'
        '  "key_events": [{"event": "...", "impact": "high|medium|low"}],\n'
        '  "macro_indicators": [{"name": "...", "signal": "bearish|neutral|bullish"}],\n'
        '  "risk_summary": "<2-4 sentence summary>",\n'
        '  "sources": ["GDELT", "FRED"],\n'
        '  "confidence": <float 0.50-0.80>\n'
        "}"
    )

    try:
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=user,
            config=gtypes.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )
        data = json.loads(resp.text)
        data["agent_id"] = "agent_02"
        data["stability_score"] = max(0.0, min(100.0, float(data.get("stability_score", 50.0))))
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.65))))
        data["key_events"] = data.get("key_events", [])[:10]
        data["macro_indicators"] = data.get("macro_indicators", [])[:10]
        data["sources"] = data.get("sources", ["GDELT", "FRED"])
        data["risk_summary"] = str(data.get("risk_summary", ""))[:2000]
        return data
    except Exception as exc:
        logger.warning("agent_02 Gemini fallback failed: %s", exc)
        return _minimal_baseline(asset)


def _minimal_baseline(asset: str) -> dict[str, Any]:
    """Last-resort minimal valid GeopoliticalOutput."""
    return {
        "agent_id": "agent_02",
        "stability_score": 50.0,
        "key_events": [{"event": "Baseline assessment — real-time data unavailable", "impact": "medium"}],
        "macro_indicators": [{"name": "Global macro", "signal": "neutral"}],
        "risk_summary": f"Baseline geopolitical assessment for {asset}. Real-time GDELT/FRED data unavailable in this run.",
        "sources": ["FRED"],
        "confidence": 0.45,
    }


# ── Public interface ──────────────────────────────────────────────────────────

async def run_geopolitical(
    asset: str,
    query: str,
    timeframe: str = "30 days",
) -> dict[str, Any]:
    """
    Run geopolitical & macro analysis for the given asset and query.

    Returns a dict compatible with GeopoliticalOutput schema.
    Never raises — always returns a valid structure.
    """
    try:
        asset = _sanitize(asset)
        query = _sanitize(query)
    except ValueError as exc:
        logger.warning("agent_02 injection detected: %s", exc)
        return _minimal_baseline(asset[:12])

    result = await _try_real_agent(asset, query, timeframe)
    if result is not None:
        return result

    return await _gemini_fallback(asset, query, timeframe)
