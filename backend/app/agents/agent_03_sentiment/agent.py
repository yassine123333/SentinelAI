"""
Groq-Powered Sentiment Agent with Modular RAG.

Orchestrates the full pipeline:
  1. Parse & understand input via RAG parser
  2. Retrieve historical context from RAG store
  3. Fetch GDELT institutional sentiment
  4. Fetch Reddit retail sentiment
  5. Engineer composite signal
  6. (Optional) Refine via Groq LLM with RAG context
  7. Store results in RAG for future retrieval (TTL 2 days)
  8. Return strict JSON output
"""

import json
import os
from typing import Dict, Any, List, Optional

import config
import gdelt_client
import reddit_client
import sentiment_engine
from rag import RAGPipeline


# ─── System prompt for Groq refinement ────────────────────────────

SYSTEM_PROMPT = """You are a Market Sentiment Intelligence Agent.

Your role is to analyze public opinion and macro news tone for a given asset or topic and produce a structured sentiment signal.

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

Do not include markdown. Return JSON only."""


_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


class SentimentAgent:
    """Market Sentiment Intelligence Agent with RAG capabilities."""

    def __init__(self, groq_api_key: Optional[str] = None, **_kwargs):
        self.api_key = groq_api_key or config.GROQ_API_KEY
        self.rag = RAGPipeline(
            groq_api_key=self.api_key,
            ttl_seconds=config.RAG_TTL_SECONDS,
        )

    def run(self, structured_input: Any) -> Dict[str, Any]:
        """Synchronous entry point called by agent_03/__init__.py."""
        return self.analyze(
            asset=structured_input.get("asset", "UNKNOWN"),
            keywords=structured_input.get("keywords", []),
            time_window_days=structured_input.get("time_window_days", 7),
        )

    def analyze_raw(
        self,
        raw_input: Any,
        vix_level: Optional[float] = None,
        use_groq_refinement: bool = True,
    ) -> Dict[str, Any]:
        """Analyze from any input format (structured dict, JSON string, or free-text)."""
        print("\n  Analyzing your query...")
        parsed = self.rag.parse_input(raw_input)

        if parsed.get("is_comparison") and parsed.get("assets_list"):
            return self._compare_assets(
                assets_list=parsed["assets_list"],
                time_window_days=parsed["time_window_days"],
                vix_level=vix_level,
                use_groq_refinement=use_groq_refinement,
            )

        return self.analyze(
            asset=parsed["asset"],
            keywords=parsed["keywords"],
            time_window_days=parsed["time_window_days"],
            vix_level=vix_level,
            use_groq_refinement=use_groq_refinement,
        )

    def analyze(
        self,
        asset: str,
        keywords: list[str],
        time_window_days: int = 7,
        vix_level: Optional[float] = None,
        use_groq_refinement: bool = True,
    ) -> Dict[str, Any]:
        """Run the full sentiment analysis pipeline."""
        parsed_for_ctx = {"asset": asset, "keywords": keywords, "time_window_days": time_window_days}
        rag_context    = self.rag.retrieve_context(parsed_for_ctx)
        rag_prompt_ctx = self.rag.retrieve_prompt_context(parsed_for_ctx)

        gdelt_data  = gdelt_client.fetch_all_keywords(keywords, time_window_days)
        reddit_data = reddit_client.fetch_and_score(keywords, time_window_days, asset=asset)
        signal      = sentiment_engine.compute_signal(gdelt_data, reddit_data, asset, vix_level)

        if use_groq_refinement:
            signal = self._refine_with_groq(signal, gdelt_data, reddit_data, rag_prompt_ctx)

        if rag_context["has_history"] and rag_prompt_ctx:
            signal["explanation_summary"] += "\n\n" + self._build_rag_explanation(rag_context)

        self.rag.ingest_results(asset=asset, signal=signal, gdelt_data=gdelt_data, reddit_data=reddit_data)
        return signal

    def _compare_assets(
        self,
        assets_list: List[Dict[str, Any]],
        time_window_days: int,
        vix_level: Optional[float] = None,
        use_groq_refinement: bool = True,
    ) -> Dict[str, Any]:
        asset_names = [a["ticker"] for a in assets_list]
        signals = {}
        for asset_info in assets_list:
            signals[asset_info["ticker"]] = self.analyze(
                asset=asset_info["ticker"],
                keywords=asset_info["keywords"],
                time_window_days=time_window_days,
                vix_level=vix_level,
                use_groq_refinement=use_groq_refinement,
            )
        return {
            "is_comparison": True,
            "assets_compared": asset_names,
            "time_window_days": time_window_days,
            "signals": signals,
            "comparison": self._build_comparison_summary(signals, time_window_days),
        }

    @staticmethod
    def _build_comparison_summary(signals: Dict[str, Dict[str, Any]], time_window_days: int) -> Dict[str, Any]:
        tickers = list(signals.keys())
        rows = [
            {
                "asset": t,
                "sentiment_score": signals[t].get("sentiment_score", 0),
                "panic_index":     signals[t].get("panic_index", 0),
                "confidence":      signals[t].get("confidence", 0),
                "trend_direction": signals[t].get("trend_direction", "unknown"),
                "divergence_score":signals[t].get("divergence_score", 0),
                "gdelt_score":     signals[t].get("source_breakdown", {}).get("gdelt_score", 0),
                "reddit_score":    signals[t].get("source_breakdown", {}).get("reddit_score", 0),
            }
            for t in tickers
        ]
        return {
            "per_asset":          rows,
            "most_panic_asset":   max(rows, key=lambda r: r["panic_index"])["asset"],
            "most_negative_asset":min(rows, key=lambda r: r["sentiment_score"])["asset"],
            "most_positive_asset":max(rows, key=lambda r: r["sentiment_score"])["asset"],
            "summary": f"Compared {len(tickers)} assets over {time_window_days} days.",
        }

    @staticmethod
    def _build_rag_explanation(rag_ctx: Dict[str, Any]) -> str:
        parts = [
            "RAG HISTORICAL CONTEXT:",
            f"Data freshness: {rag_ctx['data_freshness']}. "
            f"Store contains {rag_ctx['recent_news_count']} news docs and "
            f"{rag_ctx['recent_posts_count']} social posts.",
        ]
        if rag_ctx.get("context_summary"):
            parts.append(f"Summary: {rag_ctx['context_summary']}")
        return "\n".join(parts)

    def _refine_with_groq(
        self,
        signal: Dict[str, Any],
        gdelt_data: Dict[str, Any],
        reddit_data: Dict[str, Any],
        rag_context: str = "",
    ) -> Dict[str, Any]:
        """Send computed signal + raw data to Groq for explanation refinement."""
        reddit_snippets = ""
        for i, p in enumerate(reddit_data.get("top_posts", [])[:8], 1):
            reddit_snippets += f"  {i}. [r/{p.get('subreddit','?')}, ↑{p.get('score',0)}] {p.get('text','')[:200]}\n"

        gdelt_snippets = ""
        for kw_result in gdelt_data.get("keyword_breakdown", []):
            gdelt_snippets += (
                f"  • '{kw_result.get('keyword','?')}': {kw_result.get('article_count',0)} articles, "
                f"avg_tone={kw_result.get('average_tone',0):.2f}\n"
            )

        user_message = (
            "Analyze the sentiment data below and write a market intelligence briefing "
            "in the explanation_summary field. Return the full signal as strict JSON.\n\n"
            f"COMPUTED SIGNAL:\n{json.dumps(signal, indent=2)}\n\n"
            f"GDELT: score={gdelt_data.get('gdelt_score')}, articles={gdelt_data.get('gdelt_article_count')}\n"
            f"REDDIT: score={reddit_data.get('reddit_score')}, posts={reddit_data.get('post_count')}\n"
        )
        if gdelt_snippets:
            user_message += f"\nGDELT BREAKDOWN:\n{gdelt_snippets}"
        if reddit_snippets:
            user_message += f"\nREDDIT TOP POSTS:\n{reddit_snippets}"
        if rag_context:
            user_message += f"\nHISTORICAL CONTEXT:\n{rag_context}\n"

        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            resp = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1024,
            )
            raw_text = resp.choices[0].message.content.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[-1]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()

            refined = json.loads(raw_text)
            required = {"asset", "sentiment_score", "confidence", "panic_index",
                        "trend_direction", "source_breakdown", "divergence_score",
                        "data_points_used", "explanation_summary"}
            return refined if required.issubset(refined.keys()) else signal

        except json.JSONDecodeError:
            print("      [!] Groq returned invalid JSON — using local signal.")
            return signal
        except Exception as e:
            print(f"      [!] Groq refinement error: {e}")
            return signal
