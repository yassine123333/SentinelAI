"""
Market Sentiment Intelligence Agent — Entry Point.

Interactive by default. The agent uses RAG + GDELT + Reddit
to answer any market sentiment query.

Usage:
    python main.py                              # Interactive mode (default)
    python main.py --asset "AAPL" --keywords "Apple" "AAPL stock" --days 3
    python main.py --input '{"asset":"ETH","keywords":["Ethereum","ETH"],"time_window_days":5}'
    python main.py --query "How is Bitcoin doing this week?"
    python main.py --rag-stats                  # Show RAG store stats
"""

import json
import argparse
import sys

from agent import SentimentAgent


def main():
    parser = argparse.ArgumentParser(
        description="Market Sentiment Intelligence Agent with RAG"
    )
    parser.add_argument(
        "--input", type=str, default=None,
        help='Structured JSON input: {"asset":"...","keywords":[...],"time_window_days":N}'
    )
    parser.add_argument("--asset", type=str, default=None, help="Asset or topic")
    parser.add_argument("--keywords", nargs="+", default=None, help="Search keywords")
    parser.add_argument("--days", type=int, default=2, help="Time window in days")
    parser.add_argument("--vix", type=float, default=None, help="Current VIX level for regime awareness")
    parser.add_argument("--no-gemini", action="store_true", help="Skip Gemini LLM refinement")
    parser.add_argument(
        "--query", type=str, default=None,
        help="Free-text query (RAG parser extracts asset/keywords automatically)"
    )
    parser.add_argument(
        "--rag-stats", action="store_true",
        help="Show RAG store statistics and exit"
    )

    args = parser.parse_args()

    agent = SentimentAgent()

    # ── RAG stats mode ──────────────────────────────────────────
    if args.rag_stats:
        stats = agent.rag.stats()
        print(json.dumps(stats, indent=2))
        return

    # ── Free-text query mode (RAG parser) ───────────────────────
    if args.query:
        result = agent.analyze_raw(
            raw_input=args.query,
            vix_level=args.vix,
            use_gemini_refinement=not args.no_gemini,
        )
        _print_result(result)
        return

    # ── Structured JSON input ───────────────────────────────────
    if args.input:
        result = agent.analyze_raw(
            raw_input=args.input,
            vix_level=args.vix,
            use_gemini_refinement=not args.no_gemini,
        )
        _print_result(result)
        return

    # ── CLI flags (single analysis) ─────────────────────────────
    if args.asset:
        result = agent.analyze(
            asset=args.asset,
            keywords=args.keywords or [args.asset],
            time_window_days=args.days,
            vix_level=args.vix,
            use_gemini_refinement=not args.no_gemini,
        )
        _print_result(result)
        return

    # ── Default: Interactive mode ───────────────────────────────
    _interactive_mode(agent, args)


def _interactive_mode(agent: SentimentAgent, args):
    """Run the agent in continuous interactive mode."""
    print("\n" + "=" * 60)
    print("  INTERACTIVE SENTIMENT AGENT (RAG-Powered)")
    print("  Type your query or paste JSON. Type 'quit' to exit.")
    print("  Type 'stats' to see RAG store stats.")
    print("  Type 'search <query>' to search stored data.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("\n📊 Query > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Exiting.")
            break
        if user_input.lower() == "stats":
            stats = agent.rag.stats()
            print(json.dumps(stats, indent=2))
            continue
        if user_input.lower().startswith("search "):
            query = user_input[7:].strip()
            results = agent.rag.search(query, top_k=5)
            if results:
                for r in results:
                    print(f"  [{r['similarity']}] {r['content'][:120]}")
            else:
                print("  No results found.")
            continue

        result = agent.analyze_raw(
            raw_input=user_input,
            vix_level=args.vix,
            use_gemini_refinement=not args.no_gemini,
        )
        _print_result(result)


def _print_result(result: dict):
    """Print only scores and explanation — clean output."""
    # ── Comparison output ────────────────────────────────────
    if result.get("is_comparison"):
        _print_comparison(result)
        return

    asset = result.get("asset", "?")
    print(f"\n{'='*60}")
    print(f"  {asset} — SENTIMENT REPORT")
    print(f"{'='*60}")

    # Scores block
    print(f"\n  Sentiment Score:   {result.get('sentiment_score', 0):.4f}")
    print(f"  Confidence:        {result.get('confidence', 0):.4f}")
    print(f"  Panic Index:       {result.get('panic_index', 0):.4f}")
    print(f"  Trend:             {result.get('trend_direction', 'unknown')}")
    sb = result.get("source_breakdown", {})
    print(f"  GDELT Score:       {sb.get('gdelt_score', 0):.4f}")
    print(f"  Reddit Score:      {sb.get('reddit_score', 0):.4f}")
    print(f"  Divergence:        {result.get('divergence_score', 0):.4f}")
    dp = result.get("data_points_used", {})
    print(f"  Data Points:       {dp.get('gdelt_articles', 0)} articles, "
          f"{dp.get('reddit_posts', 0)} posts")

    # Explanation
    explanation = result.get("explanation_summary", "")
    if explanation:
        print(f"\n{'-'*60}")
        print(explanation)
        print(f"{'-'*60}")


def _print_comparison(result: dict):
    """Print a clean comparison of multiple assets."""
    assets = result.get("assets_compared", [])
    comparison = result.get("comparison", {})

    print(f"\n{'='*60}")
    print(f"  {' vs '.join(assets)} — COMPARISON REPORT")
    print(f"{'='*60}")

    # Per-asset scores
    for ticker, sig in result.get("signals", {}).items():
        sb = sig.get("source_breakdown", {})
        dp = sig.get("data_points_used", {})
        print(f"\n  {ticker}:")
        print(f"    Sentiment:  {sig.get('sentiment_score', 0):.4f}")
        print(f"    Confidence: {sig.get('confidence', 0):.4f}")
        print(f"    Panic:      {sig.get('panic_index', 0):.4f}")
        print(f"    Trend:      {sig.get('trend_direction', 'unknown')}")
        print(f"    GDELT:      {sb.get('gdelt_score', 0):.4f}  |  "
              f"Reddit: {sb.get('reddit_score', 0):.4f}")
        print(f"    Data:       {dp.get('gdelt_articles', 0)} articles, "
              f"{dp.get('reddit_posts', 0)} posts")

    # Verdict
    print(f"\n{'─'*60}")
    print(f"  VERDICT:")
    print(f"    Most Panic:    {comparison.get('most_panic_asset', 'N/A')}")
    print(f"    Most Negative: {comparison.get('most_negative_asset', 'N/A')}")
    print(f"    Most Positive: {comparison.get('most_positive_asset', 'N/A')}")

    # Explanations
    for ticker, sig in result.get("signals", {}).items():
        explanation = sig.get("explanation_summary", "")
        if explanation:
            print(f"\n{'-'*60}")
            print(f"  {ticker} — EXPLANATION")
            print(f"{'-'*60}")
            print(explanation)

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
