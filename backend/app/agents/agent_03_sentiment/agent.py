"""
Gemini-Powered Sentiment Agent with Modular RAG.

Orchestrates the full pipeline:
  1. Parse & understand input via RAG parser
  2. Retrieve historical context from RAG store
  3. Fetch GDELT institutional sentiment
  4. Fetch Reddit retail sentiment
  5. Engineer composite signal
  6. (Optional) Refine via Gemini LLM with RAG context
  7. Store results in RAG for future retrieval (TTL 2 days)
  8. Return strict JSON output
"""

import json
from typing import Dict, Any, List, Optional

from google import genai

import config
import gdelt_client
import reddit_client
import sentiment_engine
from rag import RAGPipeline


# ─── System prompt for Gemini refinement ────────────────────────────

SYSTEM_PROMPT = """You are a Market Sentiment Intelligence Agent.

Your role is to analyze public opinion and macro news tone for a given asset or topic and produce a structured sentiment signal that will be consumed by a separate Decision-Making Agent.

You operate independently and are NOT the orchestrator.

INPUT

You will receive structured input in this format:

{
"asset": "<string>",
"keywords": ["<keyword1>", "<keyword2>", ...],
"time_window_days": <integer>
}

YOUR TASK

Retrieve macro news sentiment using the GDELT Tone API (mode=timelinetone) for each keyword.

Retrieve public opinion data using Reddit based on the keywords.

Restrict all analysis to the provided time_window_days.

Extract sentiment from:

News tone (institutional sentiment)

Reddit posts (retail/public sentiment)

PROCESSING REQUIREMENTS
A. GDELT Processing

Compute average tone over time window.

Compute tone trend (linear slope).

Compute tone volatility (std deviation).

Normalize score to range [-1, 1].

B. Reddit Processing

Remove spam-like or duplicate posts.

Perform sentiment scoring per post.

Compute:

Average sentiment

Sentiment acceleration (change over time)

Polarization index (variance of sentiment)

Normalize final score to [-1, 1].

SIGNAL ENGINEERING

You must compute:

sentiment_score
Weighted combination:
50% Reddit sentiment
50% GDELT sentiment

panic_index
High when:

Sentiment strongly negative

Polarization high

Negative acceleration present

divergence_score
Absolute difference between Reddit and GDELT scores.

confidence
Based on:

Data volume

Cross-source agreement

Stability of trend

OUTPUT FORMAT (STRICT JSON)

Return ONLY valid JSON in this format:

{
"asset": "",
"sentiment_score": 0.0,
"confidence": 0.0,
"panic_index": 0.0,
"trend_direction": "accelerating_positive | accelerating_negative | stable",
"source_breakdown": {
"gdelt_score": 0.0,
"reddit_score": 0.0
},
"divergence_score": 0.0,
"data_points_used": {
"gdelt_articles": 0,
"reddit_posts": 0
},
"explanation_summary": ""
}

Do not include markdown.
Do not include extra text.
Return JSON only.

If VIX or volatility proxy available:
Increase weight of retail sentiment during crisis.
Increase weight of news during calm regimes."""


class SentimentAgent:
    """Market Sentiment Intelligence Agent with RAG capabilities."""

    def __init__(self, gemini_api_key: Optional[str] = None):
        self.api_key = gemini_api_key or config.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)
        self.rag = RAGPipeline(
            gemini_api_key=self.api_key,
            ttl_seconds=config.RAG_TTL_SECONDS,
        )

    def analyze_raw(
        self,
        raw_input: Any,
        vix_level: Optional[float] = None,
        use_gemini_refinement: bool = True,
    ) -> Dict[str, Any]:
        """
        Analyze from any input format (structured dict, JSON string,
        or free-text query). The RAG parser extracts essential info.
        Supports multi-asset comparison queries.
        """
        print("\n  Analyzing your query...")

        parsed = self.rag.parse_input(raw_input)

        # ── Comparison mode: analyze each asset separately ──────
        if parsed.get("is_comparison") and parsed.get("assets_list"):
            return self._compare_assets(
                assets_list=parsed["assets_list"],
                time_window_days=parsed["time_window_days"],
                vix_level=vix_level,
                use_gemini_refinement=use_gemini_refinement,
            )

        return self.analyze(
            asset=parsed["asset"],
            keywords=parsed["keywords"],
            time_window_days=parsed["time_window_days"],
            vix_level=vix_level,
            use_gemini_refinement=use_gemini_refinement,
        )

    def analyze(
        self,
        asset: str,
        keywords: list[str],
        time_window_days: int = 7,
        vix_level: Optional[float] = None,
        use_gemini_refinement: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the full sentiment analysis pipeline.

        Args:
            asset:              The asset or topic to analyze.
            keywords:           Search keywords for data retrieval.
            time_window_days:   Lookback window in days.
            vix_level:          Optional VIX level for regime awareness.
            use_gemini_refinement: Whether to pass through Gemini for
                                   explanation refinement.

        Returns:
            Strict JSON dict matching the output schema.
        """
        # ── Gather data silently ──────────────────────────────
        parsed_for_ctx = {
            "asset": asset,
            "keywords": keywords,
            "time_window_days": time_window_days,
        }
        rag_context = self.rag.retrieve_context(parsed_for_ctx)
        rag_prompt_ctx = self.rag.retrieve_prompt_context(parsed_for_ctx)

        gdelt_data = gdelt_client.fetch_all_keywords(keywords, time_window_days)
        reddit_data = reddit_client.fetch_and_score(
            keywords, time_window_days, asset=asset
        )

        signal = sentiment_engine.compute_signal(
            gdelt_data, reddit_data, asset, vix_level
        )

        # ── Gemini Refinement with actual content ───────────────
        if use_gemini_refinement:
            signal = self._refine_with_gemini(
                signal, gdelt_data, reddit_data, rag_prompt_ctx
            )

        # ── Inject RAG historical context ───────────────────────
        if rag_context["has_history"] and rag_prompt_ctx:
            historical_note = self._build_rag_explanation(rag_context)
            signal["explanation_summary"] += "\n\n" + historical_note

        # ── Store results in RAG silently ────────────────────────
        self.rag.ingest_results(
            asset=asset,
            signal=signal,
            gdelt_data=gdelt_data,
            reddit_data=reddit_data,
        )

        return signal

    def _compare_assets(
        self,
        assets_list: List[Dict[str, Any]],
        time_window_days: int,
        vix_level: Optional[float] = None,
        use_gemini_refinement: bool = True,
    ) -> Dict[str, Any]:
        """
        Run analysis for each asset individually, then produce a
        side-by-side comparison with a winner determination.
        """
        asset_names = [a["ticker"] for a in assets_list]
        print(f"  Comparing: {' vs '.join(asset_names)} "
              f"(last {time_window_days} days)...")

        signals = {}
        for asset_info in assets_list:
            ticker = asset_info["ticker"]
            kws = asset_info["keywords"]
            sig = self.analyze(
                asset=ticker,
                keywords=kws,
                time_window_days=time_window_days,
                vix_level=vix_level,
                use_gemini_refinement=use_gemini_refinement,
            )
            signals[ticker] = sig

        # ── Build comparison summary ─────────────────────────
        comparison = self._build_comparison_summary(signals, time_window_days)
        return {
            "is_comparison": True,
            "assets_compared": asset_names,
            "time_window_days": time_window_days,
            "signals": signals,
            "comparison": comparison,
        }

    @staticmethod
    def _build_comparison_summary(
        signals: Dict[str, Dict[str, Any]],
        time_window_days: int,
    ) -> Dict[str, Any]:
        """
        Build a structured comparison of multiple asset signals.
        Determines which has more panic, more negativity, etc.
        """
        tickers = list(signals.keys())
        rows = []
        for t in tickers:
            s = signals[t]
            rows.append({
                "asset": t,
                "sentiment_score": s.get("sentiment_score", 0),
                "panic_index": s.get("panic_index", 0),
                "confidence": s.get("confidence", 0),
                "trend_direction": s.get("trend_direction", "unknown"),
                "divergence_score": s.get("divergence_score", 0),
                "gdelt_score": s.get("source_breakdown", {}).get("gdelt_score", 0),
                "reddit_score": s.get("source_breakdown", {}).get("reddit_score", 0),
            })

        # Determine extremes
        most_panic = max(rows, key=lambda r: r["panic_index"])
        most_negative = min(rows, key=lambda r: r["sentiment_score"])
        most_positive = max(rows, key=lambda r: r["sentiment_score"])
        highest_conf = max(rows, key=lambda r: r["confidence"])

        # Build explanation
        lines = []
        lines.append(f"COMPARISON SUMMARY ({' vs '.join(tickers)}, last {time_window_days} days):")
        lines.append("")

        # Table
        lines.append(f"{'Metric':<22} " + " ".join(f"{t:>12}" for t in tickers))
        lines.append("─" * (22 + 13 * len(tickers)))
        for metric in ["sentiment_score", "panic_index", "confidence",
                       "divergence_score", "gdelt_score", "reddit_score"]:
            vals = [f"{r[metric]:>12.4f}" for r in rows]
            lines.append(f"{metric:<22} " + " ".join(vals))
        trend_vals = [f"{r['trend_direction']:>12}" for r in rows]
        lines.append(f"{'trend_direction':<22} " + " ".join(trend_vals))

        lines.append("")
        lines.append(f"Most PANIC:      {most_panic['asset']} (panic_index={most_panic['panic_index']:.4f})")
        lines.append(f"Most NEGATIVE:   {most_negative['asset']} (sentiment={most_negative['sentiment_score']:.4f})")
        lines.append(f"Most POSITIVE:   {most_positive['asset']} (sentiment={most_positive['sentiment_score']:.4f})")
        lines.append(f"Highest CONF:    {highest_conf['asset']} (confidence={highest_conf['confidence']:.4f})")

        # Negative trend check
        neg_trend = [r for r in rows if "negative" in r["trend_direction"]]
        if neg_trend:
            names = ", ".join(r["asset"] for r in neg_trend)
            lines.append(f"Negative TREND:  {names}")
        else:
            lines.append("Negative TREND:  None")

        summary_text = "\n".join(lines)

        return {
            "per_asset": rows,
            "most_panic_asset": most_panic["asset"],
            "most_negative_asset": most_negative["asset"],
            "most_positive_asset": most_positive["asset"],
            "summary": summary_text,
        }

    @staticmethod
    def _build_rag_explanation(rag_ctx: Dict[str, Any]) -> str:
        """Build a human-readable RAG historical comparison paragraph."""
        parts = ["RAG HISTORICAL CONTEXT:"]
        parts.append(
            f"Data freshness: {rag_ctx['data_freshness']}. "
            f"The RAG store contains {rag_ctx['recent_news_count']} recent "
            f"news documents and {rag_ctx['recent_posts_count']} social posts."
        )
        if rag_ctx.get("trend_comparison"):
            parts.append("Previous signals for this asset:")
            for tc in rag_ctx["trend_comparison"]:
                prev_score = tc.get("sentiment_score", "N/A")
                prev_panic = tc.get("panic_index", "N/A")
                prev_trend = tc.get("trend_direction", "unknown")
                ts = tc.get("timestamp", "unknown")
                parts.append(
                    f"  • [{ts}] score={prev_score}, panic={prev_panic}, "
                    f"trend={prev_trend}"
                )
            # Compare latest vs current
            latest = rag_ctx["trend_comparison"][0]
            prev_s = latest.get("sentiment_score", 0)
            if isinstance(prev_s, (int, float)):
                parts.append(
                    f"Compared to the most recent stored signal "
                    f"(score={prev_s}), the current reading shows "
                    + (
                        "improvement." if prev_s < 0 else
                        "continuation of positive sentiment." if prev_s > 0 else
                        "no significant shift."
                    )
                )
        if rag_ctx.get("context_summary"):
            parts.append(f"Summary: {rag_ctx['context_summary']}")
        return "\n".join(parts)

    def _refine_with_gemini(
        self,
        signal: Dict[str, Any],
        gdelt_data: Dict[str, Any],
        reddit_data: Dict[str, Any],
        rag_context: str = "",
    ) -> Dict[str, Any]:
        """
        Send computed signal + raw data + RAG historical context to
        Gemini for explanation refinement and validation.
        """
        # ── Build content snippets from actual posts/articles ──
        reddit_snippets = ""
        top_posts = reddit_data.get("top_posts", [])
        if top_posts:
            reddit_snippets = "\nTOP REDDIT POSTS (actual content from community):\n"
            for i, p in enumerate(top_posts[:8], 1):
                text = p.get("text", "")[:200]
                sub = p.get("subreddit", "?")
                score = p.get("score", 0)
                reddit_snippets += f"  {i}. [r/{sub}, ↑{score}] {text}\n"

        gdelt_snippets = ""
        keyword_breakdown = gdelt_data.get("keyword_breakdown", [])
        if keyword_breakdown:
            gdelt_snippets = "\nGDELT NEWS TONE BREAKDOWN (institutional media):\n"
            for kw_result in keyword_breakdown:
                kw = kw_result.get("keyword", "?")
                avg = kw_result.get("average_tone", 0)
                trend = kw_result.get("tone_trend", 0)
                vol = kw_result.get("tone_volatility", 0)
                count = kw_result.get("article_count", 0)
                gdelt_snippets += (f"  • '{kw}': {count} articles, "
                                   f"avg_tone={avg:.2f}, trend={trend:.4f}, "
                                   f"volatility={vol:.2f}\n")

        user_message = (
            "Here is the computed sentiment signal along with ACTUAL content "
            "from news articles and Reddit posts. Write the explanation_summary "
            "as a market intelligence briefing that references what you see "
            "in the actual posts and news data. Be specific — mention themes, "
            "topics, and sentiments you observe in the content. "
            "Cover: 1) What the news and community are saying, "
            "2) Overall sentiment interpretation with evidence from the content, "
            "3) Source agreement/disagreement, "
            "4) Trend and momentum, 5) Risk assessment. "
            "Return the final signal as strict JSON only.\n\n"
            f"COMPUTED SIGNAL:\n{json.dumps(signal, indent=2)}\n\n"
            f"GDELT SCORES: score={gdelt_data.get('gdelt_score')}, "
            f"trend={gdelt_data.get('gdelt_trend')}, "
            f"volatility={gdelt_data.get('gdelt_volatility')}, "
            f"articles={gdelt_data.get('gdelt_article_count')}\n"
            f"REDDIT SCORES: score={reddit_data.get('reddit_score')}, "
            f"acceleration={reddit_data.get('sentiment_acceleration')}, "
            f"polarization={reddit_data.get('polarization_index')}, "
            f"posts={reddit_data.get('post_count')}\n"
            f"{gdelt_snippets}"
            f"{reddit_snippets}"
        )

        # Inject RAG historical context if available
        if rag_context:
            user_message += f"\n{rag_context}\n"
            user_message += (
                "\nUse the historical context above to compare current "
                "sentiment with recent trends. Note any significant changes "
                "in your explanation_summary.\n"
            )

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                    {"role": "model", "parts": [{"text": "Understood. I will analyze sentiment data and return strict JSON only."}]},
                    {"role": "user", "parts": [{"text": user_message}]},
                ],
            )
            raw_text = response.text.strip()

            # Strip markdown fences if Gemini wraps them
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[-1]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

            refined = json.loads(raw_text)

            # Validate required keys exist
            required_keys = {
                "asset", "sentiment_score", "confidence", "panic_index",
                "trend_direction", "source_breakdown", "divergence_score",
                "data_points_used", "explanation_summary",
            }
            if required_keys.issubset(refined.keys()):
                return refined
            else:
                print("      [!] Gemini output missing keys — using local signal.")
                return signal

        except json.JSONDecodeError:
            print("      [!] Gemini returned invalid JSON — using local signal.")
            return signal
        except Exception as e:
            print(f"      [!] Gemini refinement error: {e}")
            return signal
