"""
Pattern Scanner Runner
Runs conflict signature detection across all regions.

Usage:
    python scripts/run_pattern_scan.py             # Single scan
    python scripts/run_pattern_scan.py --loop      # Hourly scan
    python scripts/run_pattern_scan.py --region "Middle East"  # Single region
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pattern_scan")


def run_scan(region: str | None = None):
    from intelligence.pattern_scanner import PatternScanner
    from config import ALL_REGIONS

    scanner = PatternScanner()
    regions = [region] if region else ALL_REGIONS

    logger.info(f"Running pattern scan across {len(regions)} regions...")
    alerts = scanner.scan_all(regions)

    if not alerts:
        logger.info("No alerts fired in this scan.")
        return

    logger.info(f"\n{'='*60}")
    logger.info(f"⚠  {len(alerts)} PATTERN ALERTS FIRED")
    logger.info(f"{'='*60}")
    for alert in alerts:
        print(f"\n⚠  [{alert.alert_level}] {alert.signature_name} @ {alert.region}")
        print(f"   Firing:  {', '.join(alert.indicators_fired)}")
        print(f"   Missing: {', '.join(alert.indicators_missing)}")
        if alert.historical_match:
            print(f"   Match:   {alert.historical_match} (similarity: {alert.similarity_score:.0%})")
        if alert.estimated_escalation_weeks:
            lo, hi = alert.estimated_escalation_weeks
            print(f"   Timeline: {lo}-{hi} weeks if pattern completes")
        if alert.trigger_event:
            print(f"   Trigger:  {alert.trigger_event}")
        if alert.de_escalation_path:
            print(f"   De-escalation: {alert.de_escalation_path}")


def main():
    parser = argparse.ArgumentParser(description="GeoKG-RAG Pattern Scanner")
    parser.add_argument("--loop", action="store_true", help="Run hourly")
    parser.add_argument("--region", help="Scan specific region only")
    args = parser.parse_args()

    if args.loop:
        logger.info("Starting hourly pattern scan loop...")
        while True:
            try:
                run_scan(args.region)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)
            logger.info("Next scan in 1 hour...")
            time.sleep(3600)
    else:
        run_scan(args.region)


if __name__ == "__main__":
    main()
