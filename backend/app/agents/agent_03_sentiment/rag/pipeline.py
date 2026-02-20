"""
RAG Pipeline — Unified interface for the modular RAG system.

Orchestrates: parser → embedder → store → retriever → context_builder.

This is the single entry point consumed by the SentimentAgent.
"""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from rag.store import DocumentStore
from rag.parser import InputParser
from rag.embedder import Embedder
from rag.retriever import Retriever
from rag.context_builder import ContextBuilder


class RAGPipeline:
    """
    Unified RAG pipeline for the Sentiment Agent.

    Usage:
        rag = RAGPipeline(gemini_api_key="...")
        parsed = rag.parse_input("How is BTC doing last 3 days?")
        context = rag.retrieve_context(parsed)
        # ... agent does analysis ...
        rag.ingest_results(asset, signal, gdelt_data, reddit_data)
    """

    def __init__(
        self,
        groq_api_key: str = "",
        gemini_api_key: str = "",   # kept for backward compat, ignored
        ttl_seconds: int = 2 * 24 * 60 * 60,  # 2 days
        db_path: Optional[str] = None,
    ):
        api_key = groq_api_key or gemini_api_key
        self.store = DocumentStore(db_path=db_path, ttl_seconds=ttl_seconds)
        self.parser = InputParser(groq_api_key=api_key)
        self.embedder = Embedder(groq_api_key=api_key)
        self.retriever = Retriever(store=self.store, embedder=self.embedder)
        self.context_builder = ContextBuilder(retriever=self.retriever)

    # ─── Input Understanding ────────────────────────────────────

    def parse_input(self, raw_input: Any) -> Dict[str, Any]:
        """
        Parse any input format → structured agent request.

        Accepts: dict, JSON string, or free-text query.
        Returns: { asset, keywords, time_window_days, ... }
        """
        return self.parser.parse(raw_input)

    # ─── Context Retrieval ──────────────────────────────────────

    def retrieve_context(
        self,
        parsed_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Retrieve relevant historical context from the RAG store.

        Returns: structured context dict with signals, docs, summary.
        """
        return self.context_builder.build_context(
            asset=parsed_input["asset"],
            keywords=parsed_input["keywords"],
            time_window_days=parsed_input["time_window_days"],
        )

    def retrieve_prompt_context(
        self,
        parsed_input: Dict[str, Any],
    ) -> str:
        """
        Retrieve context formatted as a string for prompt injection.
        Returns empty string if no history exists.
        """
        return self.context_builder.build_prompt_context(
            asset=parsed_input["asset"],
            keywords=parsed_input["keywords"],
            time_window_days=parsed_input["time_window_days"],
        )

    # ─── Data Ingestion ─────────────────────────────────────────

    def ingest_results(
        self,
        asset: str,
        signal: Dict[str, Any],
        gdelt_data: Optional[Dict[str, Any]] = None,
        reddit_data: Optional[Dict[str, Any]] = None,
        reddit_posts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, int]:
        """
        Store analysis results into the RAG store for future retrieval.

        Ingests:
          - The computed signal
          - GDELT keyword breakdown docs
          - Reddit posts as individual docs
          - Summary documents

        Returns: { signals_stored, docs_stored }
        """
        stats = {"signals_stored": 0, "docs_stored": 0}

        # ── Store signal ────────────────────────────────────────
        signal_id = f"sig_{asset}_{int(time.time())}"
        signal_text = json.dumps(signal)
        try:
            signal_embedding = self.embedder.embed(
                f"{asset} sentiment score={signal.get('sentiment_score')} "
                f"trend={signal.get('trend_direction')} "
                f"panic={signal.get('panic_index')}"
            )
        except Exception:
            signal_embedding = None

        self.store.store_signal(
            signal_id=signal_id,
            asset=asset,
            signal=signal,
            embedding=signal_embedding,
        )
        stats["signals_stored"] = 1

        docs_to_store = []

        # ── Store GDELT breakdown ───────────────────────────────
        if gdelt_data and "keyword_breakdown" in gdelt_data:
            for kw_result in gdelt_data["keyword_breakdown"]:
                kw = kw_result.get("keyword", "unknown")
                doc_id = f"gdelt_{asset}_{hashlib.md5(kw.encode()).hexdigest()[:8]}_{int(time.time())}"
                content = (
                    f"GDELT news tone for '{kw}' related to {asset}: "
                    f"avg_tone={kw_result.get('average_tone', 0)}, "
                    f"trend={kw_result.get('tone_trend', 0)}, "
                    f"volatility={kw_result.get('tone_volatility', 0)}, "
                    f"articles={kw_result.get('article_count', 0)}, "
                    f"normalized_score={kw_result.get('normalized_score', 0)}"
                )
                try:
                    embedding = self.embedder.embed(content)
                except Exception:
                    embedding = None

                docs_to_store.append({
                    "id": doc_id,
                    "doc_type": "gdelt_article",
                    "asset": asset,
                    "content": content,
                    "metadata": kw_result,
                    "embedding": embedding,
                })

        # ── Store Reddit posts ───────────────────────────────────
        if reddit_posts:
            for i, post in enumerate(reddit_posts[:50]):  # Cap at 50
                text = post.get("text", post.get("title", ""))
                doc_id = f"reddit_{asset}_{hashlib.md5(text.encode()).hexdigest()[:8]}_{int(time.time())}"
                try:
                    embedding = self.embedder.embed(text)
                except Exception:
                    embedding = None

                docs_to_store.append({
                    "id": doc_id,
                    "doc_type": "reddit_post",
                    "asset": asset,
                    "content": text,
                    "metadata": {
                        "created_at": post.get("created_at"),
                        "score": post.get("score"),
                        "subreddit": post.get("subreddit"),
                    },
                    "embedding": embedding,
                })

        # ── Store aggregate summary ─────────────────────────────
        summary_content = (
            f"Sentiment analysis for {asset}: "
            f"overall_score={signal.get('sentiment_score', 0)}, "
            f"gdelt_score={signal.get('source_breakdown', {}).get('gdelt_score', 0)}, "
            f"reddit_score={signal.get('source_breakdown', {}).get('reddit_score', 0)}, "
            f"trend={signal.get('trend_direction', 'unknown')}, "
            f"panic={signal.get('panic_index', 0)}, "
            f"confidence={signal.get('confidence', 0)}"
        )
        try:
            summary_emb = self.embedder.embed(summary_content)
        except Exception:
            summary_emb = None

        docs_to_store.append({
            "id": f"summary_{asset}_{int(time.time())}",
            "doc_type": "analysis_summary",
            "asset": asset,
            "content": summary_content,
            "metadata": signal,
            "embedding": summary_emb,
        })

        if docs_to_store:
            stats["docs_stored"] = self.store.store_documents_batch(docs_to_store)

        return stats

    # ─── Semantic Search (direct access) ────────────────────────

    def search(
        self,
        query: str,
        asset: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Direct semantic search over all stored documents."""
        return self.retriever.search(query=query, asset=asset, top_k=top_k)

    # ─── Store Stats ────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return current store statistics."""
        return self.store.stats()

    # ─── Cleanup ────────────────────────────────────────────────

    def cleanup(self):
        """Force cleanup of expired data."""
        self.store.cleanup_expired()

    def close(self):
        """Close all resources."""
        self.store.close()
