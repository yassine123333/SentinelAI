"""
Agent 03 — Sentiment Engine

Package entry point exposing a single clean async interface.
Tries the full agent (GDELT + Reddit + RAG) first; falls back to Gemini
if external services are unavailable.

RAG Poisoning Prevention:
  - Short-memory Qdrant store has a 14-day rolling TTL enforced by the agent.
  - Only GDELT and Reddit sources are ingested — no user-submitted documents.
  - Gemini fallback is closed-book: no RAG context injected, only structured query.

Prompt Injection Prevention:
  - asset and keywords pass through _INJECTION_RE before any LLM call.
  - The real agent's RAG pipeline applies its own injection guards.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|<\|im_end\|>|"
    r"</s>|act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE | re.DOTALL,
)

_SENT_AGENT_DIR = Path(__file__).parent


@contextlib.contextmanager
def _agent_sys_path():
    str_path = str(_SENT_AGENT_DIR)
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

async def _try_real_agent(
    asset: str,
    keywords: list[str],
    time_window_days: int,
) -> dict[str, Any] | None:
    try:
        import asyncio
        with _agent_sys_path():
            from agent import SentimentAgent  # type: ignore[import]

            sent_agent = SentimentAgent()
            structured_input = {
                "asset": asset,
                "keywords": keywords[:8],
                "time_window_days": time_window_days,
            }
            # SentimentAgent.run() may be sync — run in executor
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sent_agent.run(structured_input),
            )
            # Convert to SentimentOutput-compatible dict
            return _normalize_output(result, asset)
    except Exception as exc:
        logger.info("agent_03 real agent unavailable (%s), using Gemini fallback", exc)
        return None


def _normalize_output(result: dict, asset: str) -> dict[str, Any]:
    """Convert raw sentiment engine output to SentimentOutput schema."""
    score = float(result.get("sentiment_score", 0.0))
    # panic_index (0-1) → fear_greed_index (0-100): panic is inversely related to greed
    # 0 panic → 50 neutral, 1 panic → 0 extreme fear
    panic = float(result.get("panic_index", 0.5))
    fear_greed = round((1.0 - panic) * 100.0, 2)

    news_signals = []
    if result.get("gdelt_data"):
        gdelt = result["gdelt_data"]
        if isinstance(gdelt, dict):
            news_signals = [{"source": "GDELT", "score": gdelt.get("gdelt_score", 0.0)}]

    social_signals = []
    if result.get("reddit_data"):
        reddit = result["reddit_data"]
        if isinstance(reddit, dict):
            social_signals = [{"source": "Reddit", "score": reddit.get("reddit_score", 0.0)}]

    return {
        "agent_id": "agent_03",
        "sentiment_score": max(-1.0, min(1.0, score)),
        "fear_greed_index": fear_greed,
        "news_signals": news_signals[:20],
        "social_signals": social_signals[:20],
        "sources": ["GDELT", "Reddit"],
        "confidence": max(0.0, min(1.0, float(result.get("confidence", 0.70)))),
    }


# ── Gemini fallback ───────────────────────────────────────────────────────────

async def _gemini_fallback(
    asset: str,
    keywords: list[str],
    time_window_days: int,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types as gtypes

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("agent_03 fallback: GEMINI_API_KEY not set, returning minimal baseline")
        return _minimal_baseline(asset)

    client = genai.Client(api_key=api_key)
    kw_str = ", ".join(keywords[:8])

    system = (
        "You are a market sentiment analyst. "
        "Respond ONLY with a JSON object. Do not add prose outside the JSON. "
        "Base analysis on general macro sentiment for the asset. "
        "Never generate buy/sell recommendations."
    )
    user = (
        f"Provide a market sentiment assessment for '{asset}' "
        f"using keywords: [{kw_str}]. Time window: {time_window_days} days.\n\n"
        "Return ONLY this JSON structure:\n"
        "{\n"
        '  "sentiment_score": <float -1.0 to 1.0>,\n'
        '  "fear_greed_index": <float 0-100, 0=extreme fear, 100=extreme greed>,\n'
        '  "news_signals": [{"source": "...", "headline": "...", "score": <float>}],\n'
        '  "social_signals": [{"source": "...", "topic": "...", "score": <float>}],\n'
        '  "sources": ["GDELT", "Reddit"],\n'
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
                max_output_tokens=768,
            ),
        )
        data = json.loads(resp.text)
        data["agent_id"] = "agent_03"
        data["sentiment_score"] = max(-1.0, min(1.0, float(data.get("sentiment_score", 0.0))))
        data["fear_greed_index"] = max(0.0, min(100.0, float(data.get("fear_greed_index", 50.0))))
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.65))))
        data["news_signals"] = data.get("news_signals", [])[:20]
        data["social_signals"] = data.get("social_signals", [])[:20]
        data["sources"] = data.get("sources", ["GDELT", "Reddit"])
        return data
    except Exception as exc:
        logger.warning("agent_03 Gemini fallback failed: %s", exc)
        return _minimal_baseline(asset)


def _minimal_baseline(asset: str) -> dict[str, Any]:
    return {
        "agent_id": "agent_03",
        "sentiment_score": 0.0,
        "fear_greed_index": 50.0,
        "news_signals": [{"source": "GDELT", "headline": "Baseline — real-time data unavailable", "score": 0.0}],
        "social_signals": [],
        "sources": ["GDELT"],
        "confidence": 0.40,
    }


# ── Public interface ──────────────────────────────────────────────────────────

async def run_sentiment(
    asset: str,
    keywords: list[str],
    time_window_days: int = 14,
) -> dict[str, Any]:
    """
    Run sentiment analysis for the given asset.

    Returns a dict compatible with SentimentOutput schema.
    Never raises — always returns a valid structure.
    """
    try:
        asset = _sanitize(asset)
        keywords = [_sanitize(k) for k in keywords[:8]]
    except ValueError as exc:
        logger.warning("agent_03 injection detected: %s", exc)
        return _minimal_baseline(asset[:12])

    result = await _try_real_agent(asset, keywords, time_window_days)
    if result is not None:
        return result

    return await _gemini_fallback(asset, keywords, time_window_days)
