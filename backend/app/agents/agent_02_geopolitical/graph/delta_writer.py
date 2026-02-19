"""
Delta Graph Writer
Handles all incremental UPSERT operations to Neo4j.
NEVER rebuilds the graph — always merges new information with existing.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from models import Actor, Territory, GeoEvent, Relation, ExtractionResult
from graph.neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)


class DeltaGraphWriter:
    """
    Writes extraction results as incremental graph updates.
    All operations are idempotent MERGE/UPSERT — safe to replay.
    """

    def __init__(self, client: Neo4jClient | None = None):
        self.neo4j = client or get_neo4j_client()

    def write_extraction(self, result: ExtractionResult) -> dict:
        """
        Write a full extraction result to the graph.
        Returns counts of entities and relations written.
        """
        actors_written = 0
        relations_written = 0
        events_written = 0

        # 1. Write all entities
        for entity in result.entities:
            try:
                if entity.get("type") in ("state actor", "non-state armed group",
                                           "political faction", "national leader",
                                           "international organization"):
                    actor = Actor(
                        id=entity.get("wikidata_id") or self._slug(entity["text"]),
                        name=entity["text"],
                        actor_type=entity["type"],
                        aliases=[entity["text"]],
                        confidence=entity.get("score", 0.8),
                    )
                    self.neo4j.upsert_actor(actor)
                    actors_written += 1

                elif entity.get("type") in ("disputed territory", "strategic chokepoint"):
                    territory = Territory(
                        id=self._slug(entity["text"]),
                        name=entity["text"],
                        disputed=entity["type"] == "disputed territory",
                    )
                    self.neo4j.upsert_territory(territory)

            except Exception as e:
                logger.error(f"Failed to write entity {entity}: {e}")

        # 2. Write all relations
        for triple in result.triples:
            try:
                self.neo4j.upsert_relation(triple)
                relations_written += 1
            except Exception as e:
                logger.error(f"Failed to write relation {triple}: {e}")

        # 3. Write event if present
        if result.event:
            try:
                self.neo4j.upsert_event(result.event)
                events_written += 1
            except Exception as e:
                logger.error(f"Failed to write event {result.event}: {e}")

        stats = {
            "actors": actors_written,
            "relations": relations_written,
            "events": events_written,
            "article_id": result.article_id,
        }
        logger.info(f"Delta write complete: {stats}")
        return stats

    def write_inferred_relation(
        self,
        subject_id: str,
        relation_type: str,
        object_id: str,
        confidence: float,
        model: str = "RotatE",
    ):
        """Write a GNN-inferred relation with inferred=True flag."""
        rel = Relation(
            subject_id=subject_id,
            relation_type=relation_type,
            object_id=object_id,
            valid_from=datetime.now(timezone.utc),
            confidence=confidence,
            source=f"inference:{model}",
            inferred=True,
        )
        self.neo4j.upsert_relation(rel)
        logger.debug(f"Inferred relation written: {subject_id} -{relation_type}-> {object_id} [{confidence:.2f}]")

    def update_actor_embedding(self, actor_id: str, embedding: list[float]):
        """Store vector embedding on Actor node for similarity search."""
        self.neo4j.run_write("""
            MATCH (a:Actor {id: $id})
            SET a.embedding = $embedding
        """, id=actor_id, embedding=embedding)

    def record_pattern_alert(self, alert: dict):
        """Persist a pattern alert node to the graph for historical tracking."""
        self.neo4j.run_write("""
            MERGE (p:PatternAlert {
                region: $region,
                signature: $signature,
                fired_at: datetime($fired_at)
            })
            SET p.alert_level = $level,
                p.indicators = $indicators,
                p.similarity = $similarity
        """,
            region=alert["region"],
            signature=alert["signature_name"],
            fired_at=alert.get("timestamp", datetime.now(timezone.utc).isoformat()),
            level=alert["alert_level"],
            indicators=alert["indicators_fired"],
            similarity=alert.get("similarity_score", 0.0),
        )

    @staticmethod
    def _slug(text: str) -> str:
        """Convert entity name to a stable slug ID."""
        return text.lower().strip().replace(" ", "_").replace("'", "")
