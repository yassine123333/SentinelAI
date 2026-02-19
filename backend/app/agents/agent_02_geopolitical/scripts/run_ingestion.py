"""
Continuous Ingestion Runner
Runs the GDELT → Extraction → Graph UPSERT pipeline on a schedule.

Usage:
    python scripts/run_ingestion.py                    # Run once
    python scripts/run_ingestion.py --loop             # Run every 15 minutes
    python scripts/run_ingestion.py --loop --interval 30  # Custom interval
"""
from __future__ import annotations
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingestion")


def run_cycle(hours_back: int = 1):
    """Run a single ingestion cycle: fetch → extract → write."""
    from sources.gdelt_connector import ingest_all_queries
    from extraction.pipeline import GeopoliticalExtractor
    from graph.delta_writer import DeltaGraphWriter
    from retrieval.weaviate_client import ingest_article
    from models import Article

    logger.info(f"Starting ingestion cycle (hours_back={hours_back})")

    # Step 1: Fetch articles
    articles = ingest_all_queries(hours_back=hours_back)
    logger.info(f"Fetched {len(articles)} new articles")

    if not articles:
        logger.info("No new articles. Cycle complete.")
        return {"articles": 0, "extracted": 0, "written": 0}

    # Step 2: Extract + write each article
    extractor = GeopoliticalExtractor()
    writer = DeltaGraphWriter()
    extracted = 0
    written = 0
    errors = 0

    for article in articles:
        try:
            # Extract entities and relations
            result = extractor.extract(article)

            # Write to knowledge graph
            stats = writer.write_extraction(result)
            written += stats.get("relations", 0)

            # Store article in Weaviate for semantic search
            try:
                from datetime import datetime
                art_obj = Article(
                    id=article.get("id", ""),
                    url=article.get("url", ""),
                    title=article.get("title", ""),
                    content=article.get("content") or article.get("title", ""),
                    source=article.get("domain") or article.get("source", ""),
                    published_at=datetime.fromisoformat(article.get("published_at", datetime.utcnow().isoformat())),
                    source_bias=article.get("source_bias", "UNKNOWN"),
                    actor_ids=[e["canonical_id"] for e in result.entities
                               if e.get("canonical_id")][:10],
                    confidence=result.confidence,
                )
                ingest_article(art_obj)
            except Exception as e:
                logger.debug(f"Weaviate ingest skipped: {e}")

            extracted += 1

        except Exception as e:
            errors += 1
            logger.error(f"Article processing failed: {e}")

    summary = {
        "articles": len(articles),
        "extracted": extracted,
        "relations_written": written,
        "errors": errors,
    }
    logger.info(f"Cycle complete: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="GeoKG-RAG Ingestion Runner")
    parser.add_argument("--loop", action="store_true", help="Run continuously on schedule")
    parser.add_argument("--interval", type=int, default=15, help="Interval in minutes (loop mode)")
    parser.add_argument("--hours-back", type=int, default=1, help="Hours to look back for articles")
    args = parser.parse_args()

    if args.loop:
        logger.info(f"Starting ingestion loop (interval={args.interval}min)")
        while True:
            try:
                run_cycle(hours_back=args.hours_back)
            except KeyboardInterrupt:
                logger.info("Ingestion loop stopped by user.")
                break
            except Exception as e:
                logger.error(f"Ingestion cycle error: {e}", exc_info=True)

            logger.info(f"Sleeping {args.interval} minutes until next cycle...")
            time.sleep(args.interval * 60)
    else:
        run_cycle(hours_back=args.hours_back)


if __name__ == "__main__":
    main()
