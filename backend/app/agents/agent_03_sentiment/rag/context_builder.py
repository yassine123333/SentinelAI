"""
RAG Context Builder — Assembles enriched context for the agent.

Combines:
  - Retrieved historical signals for trend comparison
  - Semantically relevant past documents
  - Recent real-time data summaries

Produces a structured context block that the agent injects into
its Gemini prompt for more informed analysis.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from rag.retriever import Retriever


class ContextBuilder:
    """Builds enriched RAG context from stored data."""

    def __init__(self, retriever: Retriever):
        self.retriever = retriever

    def build_context(
        self,
        asset: str,
        keywords: List[str],
        time_window_days: int,
    ) -> Dict[str, Any]:
        """
        Build a comprehensive context block for the agent.

        Returns:
            Dict with:
              - historical_signals: Past signals for this asset
              - relevant_docs: Semantically related stored documents
              - context_summary: Human-readable summary string
              - has_history: Whether any prior data exists
              - data_freshness: Age of most recent data point
        """
        # ── Retrieve historical signals ─────────────────────────
        past_signals = self.retriever.search_signals(asset=asset, limit=5)

        # ── Semantic search for relevant docs ───────────────────
        query = f"{asset} {' '.join(keywords)} sentiment market"
        relevant_docs = self.retriever.search(
            query=query, asset=asset, top_k=10
        )

        # ── Get recent raw data ─────────────────────────────────
        recent_news = self.retriever.get_recent_context(
            asset=asset,
            doc_types=["gdelt_article", "news"],
            limit=20,
        )
        recent_posts = self.retriever.get_recent_context(
            asset=asset,
            doc_types=["reddit_post"],
            limit=20,
        )

        # ── Compute freshness ──────────────────────────────────
        has_history = bool(past_signals or relevant_docs)
        data_freshness = self._compute_freshness(
            past_signals, recent_news, recent_posts
        )

        # ── Build summary ──────────────────────────────────────
        context_summary = self._build_summary(
            asset, past_signals, relevant_docs,
            recent_news, recent_posts, data_freshness,
        )

        # ── Build trend comparison ─────────────────────────────
        trend_comparison = self._build_trend_comparison(past_signals)

        return {
            "historical_signals": past_signals,
            "relevant_docs": relevant_docs,
            "recent_news_count": len(recent_news),
            "recent_posts_count": len(recent_posts),
            "trend_comparison": trend_comparison,
            "context_summary": context_summary,
            "has_history": has_history,
            "data_freshness": data_freshness,
        }

    def build_prompt_context(
        self,
        asset: str,
        keywords: List[str],
        time_window_days: int,
    ) -> str:
        """
        Build a formatted string suitable for injection into the
        Gemini prompt as additional context.
        """
        ctx = self.build_context(asset, keywords, time_window_days)

        if not ctx["has_history"]:
            return ""

        parts = [
            "\n--- RAG HISTORICAL CONTEXT ---",
            f"Asset: {asset}",
            f"Data freshness: {ctx['data_freshness']}",
            f"Stored news articles: {ctx['recent_news_count']}",
            f"Stored social posts: {ctx['recent_posts_count']}",
        ]

        # Add trend comparison
        if ctx["trend_comparison"]:
            parts.append("\nPrevious Signals:")
            for tc in ctx["trend_comparison"]:
                parts.append(
                    f"  [{tc['timestamp']}] score={tc['sentiment_score']}, "
                    f"panic={tc['panic_index']}, conf={tc['confidence']}"
                )

        # Add top relevant retrieved docs
        if ctx["relevant_docs"]:
            parts.append(f"\nTop Relevant Stored Documents ({len(ctx['relevant_docs'])}):")
            for i, doc in enumerate(ctx["relevant_docs"][:5], 1):
                content_preview = doc["content"][:200].replace("\n", " ")
                parts.append(
                    f"  {i}. [sim={doc['similarity']}] {content_preview}"
                )

        parts.append(f"\nSummary: {ctx['context_summary']}")
        parts.append("--- END RAG CONTEXT ---\n")

        return "\n".join(parts)

    def _compute_freshness(
        self,
        signals: List[Dict],
        news: List[Dict],
        posts: List[Dict],
    ) -> str:
        """Compute a human-readable freshness label."""
        timestamps = []

        for s in signals:
            timestamps.append(s.get("created_at", 0))
        for d in news + posts:
            timestamps.append(d.get("created_at", 0))

        if not timestamps:
            return "no_prior_data"

        most_recent = max(timestamps)
        age_hours = (time.time() - most_recent) / 3600

        if age_hours < 1:
            return "very_fresh (<1h)"
        elif age_hours < 6:
            return f"fresh ({age_hours:.0f}h ago)"
        elif age_hours < 24:
            return f"recent ({age_hours:.0f}h ago)"
        elif age_hours < 48:
            return f"aging ({age_hours / 24:.1f}d ago)"
        else:
            return f"stale ({age_hours / 24:.1f}d ago)"

    def _build_summary(
        self,
        asset: str,
        signals: List[Dict],
        docs: List[Dict],
        news: List[Dict],
        posts: List[Dict],
        freshness: str,
    ) -> str:
        """Build a concise human-readable context summary."""
        parts = []

        if signals:
            latest = signals[0].get("signal", {})
            parts.append(
                f"Last known signal for {asset}: "
                f"score={latest.get('sentiment_score', 'N/A')}, "
                f"trend={latest.get('trend_direction', 'N/A')}."
            )

        total_docs = len(news) + len(posts)
        if total_docs > 0:
            parts.append(
                f"{len(news)} news articles and {len(posts)} social posts "
                f"stored in RAG (freshness: {freshness})."
            )

        if not parts:
            parts.append(f"No prior data for {asset} in RAG store.")

        return " ".join(parts)

    @staticmethod
    def _build_trend_comparison(
        signals: List[Dict],
    ) -> List[Dict[str, Any]]:
        """Extract key metrics from past signals for trend tracking."""
        trend = []
        for s in signals:
            sig = s.get("signal", {})
            trend.append({
                "timestamp": datetime.fromtimestamp(
                    s.get("created_at", 0)
                ).strftime("%Y-%m-%d %H:%M"),
                "sentiment_score": sig.get("sentiment_score", 0.0),
                "panic_index": sig.get("panic_index", 0.0),
                "confidence": sig.get("confidence", 0.0),
                "trend_direction": sig.get("trend_direction", "unknown"),
            })
        return trend
