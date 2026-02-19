"""
Conflict Pattern Scanner
Runs hourly against the knowledge graph to detect pre-defined conflict signatures.
Emits PatternAlert objects when threshold indicators are firing.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Callable

from models import PatternAlert
from graph.neo4j_client import get_neo4j_client

logger = logging.getLogger(__name__)


# ── Conflict Signature Definitions ────────────────────────────────────────────

CONFLICT_SIGNATURES: dict[str, dict] = {

    "PRE_INVASION_PATTERN": {
        "description": "Multi-indicator signature for imminent military invasion",
        "queries": {
            "troop_buildup": """
                MATCH (a:Actor)-[r:TROOP_MOVEMENT]->(t:Territory)
                WHERE t.name CONTAINS $region
                  AND r.last_seen >= datetime() - duration({days: 7})
                RETURN a.id AS actor, t.name AS territory
            """,
            "rhetoric_spike": """
                MATCH (a:Actor)-[r:RHETORIC_ESCALATION]->(b:Actor)
                WHERE (a.country CONTAINS $region OR b.country CONTAINS $region)
                  AND r.intensity > 7
                  AND r.last_seen >= datetime() - duration({days: 14})
                RETURN a.name AS actor_a, b.name AS actor_b, r.intensity AS intensity
            """,
            "economic_decouple": """
                MATCH (a:Actor)-[r:TRADE_PARTNER]->(b:Actor)
                WHERE (a.country CONTAINS $region OR b.country CONTAINS $region)
                  AND r.trend = 'DECLINING'
                RETURN a.name AS actor_a, b.name AS actor_b
            """,
            "proxy_activated": """
                MATCH (a:Actor)-[:PROXY_OF]->(p:Actor)-[:IN_CONFLICT_WITH]->(b:Actor)
                WHERE a.country CONTAINS $region OR b.country CONTAINS $region
                RETURN a.name AS proxy, p.name AS patron, b.name AS target
            """,
            "disinfo_campaign": """
                MATCH (a:Actor)-[r:DISINFORMATION_TARGET]->(b:Actor)
                WHERE (a.country CONTAINS $region OR b.country CONTAINS $region)
                  AND r.last_seen >= datetime() - duration({days: 30})
                RETURN a.name AS source, b.name AS target
            """,
            "historical_grievance": """
                MATCH (a:Actor)-[r:HISTORICAL_GRIEVANCE]->(b:Actor)
                WHERE (a.country CONTAINS $region OR b.country CONTAINS $region)
                  AND r.intensity > 6
                RETURN a.name AS actor_a, b.name AS actor_b, r.intensity AS intensity
            """,
        },
        "threshold": 3,
        "historical_match": "Russia-Ukraine (Nov 2021 - Feb 2022)",
        "estimated_escalation_weeks": (3, 8),
        "trigger_event": "Border incident or diplomatic breakdown",
        "de_escalation_path": "Third-party mediation + economic incentives",
    },

    "PROXY_WAR_FORMATION": {
        "description": "External actors establishing proxy relationships in a conflict zone",
        "queries": {
            "arms_flow": """
                MATCH (a:Actor)-[r:SUPPLIES_ARMS_TO]->(b:Actor)
                WHERE b.country CONTAINS $region
                  AND r.last_seen >= datetime() - duration({days: 90})
                RETURN a.name AS supplier, b.name AS recipient
            """,
            "funding_detected": """
                MATCH (a:Actor)-[r:FUNDS]->(b:Actor)
                WHERE b.country CONTAINS $region
                  AND r.confidence > 0.5
                RETURN a.name AS funder, b.name AS recipient, r.confidence AS conf
            """,
            "rhetoric_alignment": """
                MATCH (patron:Actor)-[:PROXY_OF]-(proxy:Actor)
                WHERE proxy.country CONTAINS $region
                  AND patron.country <> $region
                RETURN patron.name AS patron, proxy.name AS proxy
            """,
            "external_bases": """
                MATCH (a:Actor)-[:CONTROLS]->(b:Territory)
                WHERE b.name CONTAINS $region
                  AND a.country <> $region
                RETURN a.name AS actor, b.name AS territory
            """,
        },
        "threshold": 2,
        "historical_match": "Syria 2012-2015, Angola 1975",
        "estimated_escalation_weeks": (4, 16),
        "trigger_event": "First direct confrontation between proxy forces",
        "de_escalation_path": "Patron-state negotiations + proxy disarmament agreement",
    },

    "COUP_PRECURSOR": {
        "description": "Internal political destabilization indicating possible coup attempt",
        "queries": {
            "military_faction": """
                MATCH (a:Actor {actor_type: 'military faction'})-[:IN_CONFLICT_WITH]->(gov:Actor)
                WHERE gov.country CONTAINS $region
                RETURN a.name AS faction, gov.name AS government
            """,
            "economic_collapse": """
                MATCH (c:GeoEvent {event_type: 'ECONOMIC'})
                WHERE c.description CONTAINS $region
                  AND c.intensity > 7
                  AND c.date_start >= datetime() - duration({days: 180})
                RETURN c.description AS event, c.intensity AS intensity
            """,
            "protest_spike": """
                MATCH (e:GeoEvent {event_type: 'POLITICAL_CRISIS'})
                WHERE e.description CONTAINS $region
                  AND e.date_start >= datetime() - duration({days: 30})
                RETURN count(e) AS protest_count
            """,
        },
        "threshold": 2,
        "historical_match": "Mali 2021, Myanmar 2021, Sudan 2019",
        "estimated_escalation_weeks": (1, 4),
        "trigger_event": "Leadership weakness signal or external trigger",
        "de_escalation_path": "International mediation + power-sharing agreement",
    },
}

# Alert levels based on number of indicators firing
def _alert_level(n_fired: int) -> str:
    levels = ["WATCH", "WARNING", "ALERT", "CRITICAL"]
    return levels[min(n_fired - 1, 3)]


# ── Pattern Scanner ───────────────────────────────────────────────────────────

class PatternScanner:
    """
    Runs all CONFLICT_SIGNATURES against all regions every scan cycle.
    Emits PatternAlert when indicator threshold is met.
    """

    def __init__(self, alert_callback: Callable[[PatternAlert], None] | None = None):
        self.neo4j = get_neo4j_client()
        self.alert_callback = alert_callback or self._default_alert_handler
        self._active_alerts: list[PatternAlert] = []

    def scan_all(self, regions: list[str] | None = None) -> list[PatternAlert]:
        """
        Run full scan across all regions and signatures.
        Returns list of newly fired alerts.
        """
        from config import ALL_REGIONS
        regions = regions or ALL_REGIONS
        new_alerts: list[PatternAlert] = []

        for region in regions:
            for sig_name, sig in CONFLICT_SIGNATURES.items():
                alert = self._check_signature(region, sig_name, sig)
                if alert:
                    new_alerts.append(alert)
                    self.alert_callback(alert)

        self._active_alerts = new_alerts
        logger.info(f"Pattern scan complete: {len(new_alerts)} alerts fired across {len(regions)} regions")
        return new_alerts

    def get_active_alerts(self, region: str | None = None) -> list[PatternAlert]:
        """Return current active alerts, optionally filtered by region."""
        if region:
            return [a for a in self._active_alerts if region.lower() in a.region.lower()]
        return self._active_alerts

    def _check_signature(
        self, region: str, sig_name: str, sig: dict
    ) -> PatternAlert | None:
        """Check if a signature's indicators are firing for a region."""
        indicators_fired = []
        indicators_missing = []

        for indicator_name, cypher in sig["queries"].items():
            try:
                results = self.neo4j.run_pattern_query(cypher, region)
                if results:
                    indicators_fired.append(indicator_name)
                else:
                    indicators_missing.append(indicator_name)
            except Exception as e:
                logger.warning(f"Pattern query error [{sig_name}/{indicator_name}]: {e}")
                indicators_missing.append(indicator_name)

        n_fired = len(indicators_fired)
        threshold = sig.get("threshold", 3)

        if n_fired >= threshold:
            alert = PatternAlert(
                region=region,
                signature_name=sig_name,
                alert_level=_alert_level(n_fired),
                indicators_fired=indicators_fired,
                indicators_missing=indicators_missing,
                historical_match=sig.get("historical_match"),
                similarity_score=round(n_fired / len(sig["queries"]), 2),
                estimated_escalation_weeks=sig.get("estimated_escalation_weeks"),
                trigger_event=sig.get("trigger_event"),
                de_escalation_path=sig.get("de_escalation_path"),
                timestamp=datetime.utcnow(),
            )
            logger.warning(
                f"🚨 {alert.alert_level} | {sig_name} | {region} | "
                f"{n_fired}/{len(sig['queries'])} indicators firing"
            )
            return alert

        return None

    @staticmethod
    def _default_alert_handler(alert: PatternAlert):
        logger.warning(
            f"PATTERN ALERT [{alert.alert_level}] {alert.signature_name} @ {alert.region} | "
            f"Indicators: {', '.join(alert.indicators_fired)}"
        )
