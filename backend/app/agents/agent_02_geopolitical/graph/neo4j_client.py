"""
Neo4j Knowledge Graph Client
Handles connection, schema initialization, and all graph operations.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Optional

from neo4j import GraphDatabase, Driver, Session
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from models import Actor, Territory, GeoEvent, Relation

logger = logging.getLogger(__name__)

# Suppress verbose Neo4j server notification messages (property/index warnings)
# These are informational and don't affect functionality.
class _Neo4jNotificationFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "Received notification from DBMS server" not in msg

for _handler in logging.root.handlers:
    _handler.addFilter(_Neo4jNotificationFilter())
# Also suppress from neo4j driver's own logger
logging.getLogger("neo4j").addFilter(_Neo4jNotificationFilter())
logging.getLogger("neo4j.notifications").setLevel(logging.CRITICAL)


# ── Schema Cypher ─────────────────────────────────────────────────────────────

SCHEMA_CYPHER = """
// Node uniqueness constraints
CREATE CONSTRAINT actor_id IF NOT EXISTS FOR (a:Actor) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT territory_id IF NOT EXISTS FOR (t:Territory) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:GeoEvent) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT resource_id IF NOT EXISTS FOR (r:Resource) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT sig_id IF NOT EXISTS FOR (s:ConflictSignature) REQUIRE s.name IS UNIQUE;

// Indexes for performance
CREATE INDEX event_date IF NOT EXISTS FOR (e:GeoEvent) ON (e.date_start);
CREATE INDEX actor_type IF NOT EXISTS FOR (a:Actor) ON (a.actor_type);
CREATE INDEX territory_country IF NOT EXISTS FOR (t:Territory) ON (t.country);
CREATE INDEX alert_level IF NOT EXISTS FOR (a:PatternAlert) ON (a.alert_level);

// Full-text index for name search
CREATE FULLTEXT INDEX actor_names IF NOT EXISTS
  FOR (a:Actor) ON EACH [a.name, a.aliases];
"""

VECTOR_INDEX_CYPHER = """
CREATE VECTOR INDEX actor_embedding IF NOT EXISTS
  FOR (a:Actor) ON (a.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}};  // gemini-embedding-001 = 3072 dims
"""


# ── Client ────────────────────────────────────────────────────────────────────

class Neo4jClient:
    """Thread-safe Neo4j client with connection pooling."""

    def __init__(
        self,
        uri: str = config.NEO4J_URI,
        user: str = config.NEO4J_USER,
        password: str = config.NEO4J_PASSWORD,
    ):
        uri = self._fix_uri(uri)
        try:
            # Suppress INFO/SCHEMA notifications (index already exists, missing props etc)
            try:
                from neo4j import NotificationMinimumSeverity
                self._driver: Driver = GraphDatabase.driver(
                    uri, auth=(user, password),
                    notifications_min_severity=NotificationMinimumSeverity.WARNING,
                )
            except (TypeError, ImportError, Exception):
                # Fallback for older driver versions
                self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        except Exception as e:
            raise ConnectionError(
                f"\n\n❌  Cannot create Neo4j driver."
                f"\n   URI used : {uri}"
                f"\n   Error    : {e}"
                f"\n\n   Fix 1 → Make sure NEO4J_URI in your .env uses bolt:// not http://"
                f"\n            NEO4J_URI=bolt://localhost:7687"
                f"\n   Fix 2 → Make sure Neo4j is running:"
                f"\n            docker compose up -d neo4j"
            ) from e
        logger.info(f"Connected to Neo4j at {uri}")

    @staticmethod
    def _fix_uri(uri: str) -> str:
        """Auto-correct common Neo4j URI scheme mistakes."""
        if uri.startswith("http://"):
            fixed = uri.replace("http://", "bolt://", 1)
            logger.warning(f"NEO4J_URI auto-corrected: {uri!r} → {fixed!r}  (update your .env)")
            return fixed
        if uri.startswith("https://"):
            fixed = uri.replace("https://", "bolt+s://", 1)
            logger.warning(f"NEO4J_URI auto-corrected: {uri!r} → {fixed!r}  (update your .env)")
            return fixed
        if "://" not in uri:
            fixed = f"bolt://{uri}"
            logger.warning(f"NEO4J_URI had no scheme, auto-corrected to {fixed!r}")
            return fixed
        return uri

    def close(self):
        self._driver.close()

    def verify_connectivity(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            return False

    def run(self, cypher: str, **params) -> list[dict]:
        """Execute a Cypher query and return list of record dicts."""
        with self._driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(r) for r in result]

    def run_write(self, cypher: str, **params) -> list[dict]:
        """Execute a write Cypher query in a write transaction."""
        with self._driver.session() as session:
            def _tx(tx: Session):
                return list(tx.run(cypher, **params))
            return session.execute_write(_tx)

    # ── Schema ────────────────────────────────────────────────────────────────

    def initialize_schema(self):
        """Create all constraints, indexes, and vector index."""
        logger.info("Initializing Neo4j schema...")
        with self._driver.session() as session:
            for stmt in SCHEMA_CYPHER.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        session.run(stmt)
                    except Exception as e:
                        logger.debug(f"Schema stmt skipped (may already exist): {e}")
            # Vector index (requires Neo4j 5.x)
            try:
                session.run(VECTOR_INDEX_CYPHER)
            except Exception as e:
                logger.warning(f"Vector index creation skipped: {e}")
        logger.info("Schema initialization complete.")

    # ── UPSERT Operations ─────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def upsert_actor(self, actor: Actor):
        """MERGE actor — creates if not exists, updates properties."""
        self.run_write("""
            MERGE (a:Actor {id: $id})
            SET a.name = $name,
                a.actor_type = $actor_type,
                a.country = $country,
                a.ideology = $ideology,
                a.confidence = $confidence,
                a.last_seen = datetime(),
                a.aliases = CASE
                    WHEN a.aliases IS NULL THEN $aliases
                    ELSE [x IN $aliases WHERE NOT x IN a.aliases] + a.aliases
                END
        """,
            id=actor.id,
            name=actor.name,
            actor_type=actor.actor_type,
            country=actor.country,
            ideology=actor.ideology,
            confidence=actor.confidence,
            aliases=actor.aliases,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def upsert_territory(self, territory: Territory):
        self.run_write("""
            MERGE (t:Territory {id: $id})
            SET t.name = $name,
                t.country = $country,
                t.disputed = $disputed,
                t.controlling_actor = $controlling_actor,
                t.last_updated = datetime()
        """,
            id=territory.id,
            name=territory.name,
            country=territory.country,
            disputed=territory.disputed,
            controlling_actor=territory.controlling_actor,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def upsert_event(self, event: GeoEvent):
        self.run_write("""
            MERGE (e:GeoEvent {id: $id})
            SET e.event_type = $event_type,
                e.description = $description,
                e.date_start = datetime($date_start),
                e.intensity = $intensity,
                e.military_intensity = $military_intensity,
                e.diplomatic_intensity = $diplomatic_intensity,
                e.economic_intensity = $economic_intensity,
                e.confidence = $confidence
        """,
            id=event.id,
            event_type=event.event_type,
            description=event.description,
            date_start=event.date_start.isoformat(),
            intensity=event.intensity,
            military_intensity=event.military_intensity,
            diplomatic_intensity=event.diplomatic_intensity,
            economic_intensity=event.economic_intensity,
            confidence=event.confidence,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def upsert_relation(self, rel: Relation):
        """
        Temporal edge UPSERT:
        - Close old edge if the relationship has changed
        - MERGE new edge with valid_from + source as identity key
        """
        cypher = f"""
            MATCH (a {{id: $subj}}), (b {{id: $obj}})
            OPTIONAL MATCH (a)-[old:{rel.relation_type}]->(b)
              WHERE old.valid_to IS NULL
            WITH a, b, old
            // Close stale edges only if confidence changes significantly
            FOREACH (_ IN CASE
              WHEN old IS NOT NULL AND abs(old.confidence - $confidence) > 0.2 THEN [1]
              ELSE [] END |
              SET old.valid_to = datetime()
            )
            MERGE (a)-[r:{rel.relation_type} {{source: $source, valid_from: $valid_from}}]->(b)
            SET r.confidence = CASE
                  WHEN r.confidence IS NULL THEN $confidence
                  ELSE (r.confidence * r.source_count + $confidence) / (r.source_count + 1)
                END,
                r.source_count = coalesce(r.source_count, 0) + 1,
                r.inferred = $inferred,
                r.last_seen = datetime()
        """
        self.run_write(
            cypher,
            subj=rel.subject_id,
            obj=rel.object_id,
            source=rel.source,
            valid_from=rel.valid_from.isoformat(),
            confidence=rel.confidence,
            inferred=rel.inferred,
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_actor_subgraph(self, actor_ids: list[str], depth: int = 2) -> dict:
        """
        Retrieve ego-network subgraph up to `depth` hops from seed actors.
        Returns nodes + edges with temporal and confidence properties.
        NOTE: Cypher does not allow $param in variable-length path [*1..$depth].
              We safely inject the literal integer into the query string.
        NOTE: COLLECT(DISTINCT map) fails — maps are not hashable in Cypher.
              We collect node/rel objects (hashable) then extract properties.
        """
        depth_literal = max(1, min(int(depth), 4))  # Clamp 1-4, safe integer only
        try:
            # Collect distinct node and relationship objects (not maps)
            node_rows = self.run(f"""
                MATCH path = (seed:Actor)-[*1..{depth_literal}]-(connected)
                WHERE seed.id IN $actor_ids
                UNWIND nodes(path) AS n
                WITH DISTINCT n
                RETURN n.id AS id,
                       coalesce(n.name, n.id) AS name,
                       labels(n)[0] AS type,
                       n.actor_type AS actor_type,
                       coalesce(n.confidence, 1.0) AS confidence
            """, actor_ids=actor_ids)

            edge_rows = self.run(f"""
                MATCH path = (seed:Actor)-[*1..{depth_literal}]-(connected)
                WHERE seed.id IN $actor_ids
                UNWIND relationships(path) AS r
                WITH DISTINCT r
                RETURN startNode(r).id AS source,
                       endNode(r).id AS target,
                       type(r) AS type,
                       coalesce(r.confidence, 1.0) AS confidence,
                       toString(r.valid_from) AS valid_from,
                       toString(coalesce(r.valid_to, '')) AS valid_to,
                       coalesce(r.inferred, false) AS inferred
            """, actor_ids=actor_ids)

            return {"nodes": node_rows, "edges": edge_rows}
        except Exception as e:
            logger.error(f"get_actor_subgraph failed: {e}")
            return {"nodes": [], "edges": []}
    
    def find_proxy_chains(self, actor_id: str, max_hops: int = 4) -> list[dict]:
        """Traverse PROXY_OF + FUNDS + SUPPLIES_ARMS_TO chains."""
        hops_literal = max(1, min(int(max_hops), 6))
        return self.run(f"""
            MATCH path = (patron:Actor)-[:PROXY_OF|FUNDS|SUPPLIES_ARMS_TO*1..{hops_literal}]->(proxy:Actor)
            WHERE patron.id = $actor_id OR proxy.id = $actor_id
            WITH path, [r IN relationships(path) | {{
                type: type(r), confidence: r.confidence
            }}] AS rels
            RETURN
                [n IN nodes(path) | {{id: n.id, name: n.name}}] AS chain,
                rels,
                length(path) AS hops
            ORDER BY hops
            LIMIT 20
        """, actor_id=actor_id)

    def get_conflict_timeline(self, region: str, days_back: int = 365) -> list[dict]:
        """Return events in a region ordered chronologically."""
        return self.run("""
            MATCH (e:GeoEvent)-[:IN_REGION]->(t:Territory)
            WHERE t.name CONTAINS $region
              AND e.date_start >= datetime() - duration({days: $days_back})
            RETURN e.id AS id, e.event_type AS type, e.description AS desc,
                   toString(e.date_start) AS date, e.intensity AS intensity
            ORDER BY e.date_start
        """, region=region, days_back=days_back)

    def get_escalation_deltas(self, region: str, days: int = 90) -> list[dict]:
        """Compute change in conflict intensity over time windows."""
        return self.run("""
            MATCH (e:GeoEvent)-[:IN_REGION]->(t:Territory)
            WHERE t.name CONTAINS $region
              AND e.date_start >= datetime() - duration({days: $days})
            WITH e.date_start AS dt, e.intensity AS intensity
            ORDER BY dt
            WITH COLLECT(intensity) AS intensities
            RETURN
                intensities[0] AS start_intensity,
                intensities[-1] AS end_intensity,
                intensities[-1] - intensities[0] AS delta,
                size(intensities) AS event_count
        """, region=region, days=days)

    def find_historical_analogs(self, current_actor_ids: list[str], top_k: int = 3) -> list[dict]:
        """Find past situations structurally similar to current actor set."""
        try:
            # Find GeoEvents that involve any of the seed actors via any relationship
            # Uses coalesce() so missing properties don't cause errors
            return self.run("""
                MATCH (e:GeoEvent)
                WHERE e.date_start < datetime() - duration({years: 2})
                OPTIONAL MATCH (e)-[]->(a:Actor)
                WHERE a.id IN $actor_ids
                WITH e, count(a) AS actor_overlap
                RETURN e.id AS id,
                       coalesce(e.description, e.title, e.id) AS description,
                       toString(e.date_start) AS date,
                       coalesce(e.intensity, 0) AS intensity,
                       coalesce(e.event_type, 'UNKNOWN') AS type,
                       actor_overlap
                ORDER BY actor_overlap DESC, intensity DESC
                LIMIT $top_k
            """, actor_ids=current_actor_ids, top_k=top_k)
        except Exception as e:
            logger.warning(f"find_historical_analogs failed (non-critical): {e}")
            return []

    def search_actors_fulltext(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across actor names and aliases."""
        # NOTE: param renamed to `search_term` to avoid conflict with
        # session.run()'s own `query` keyword argument in the neo4j driver.
        return self.run("""
            CALL db.index.fulltext.queryNodes('actor_names', $search_term)
            YIELD node, score
            RETURN node.id AS id, node.name AS name,
                   node.actor_type AS type, score
            ORDER BY score DESC LIMIT $limit
        """, search_term=query, limit=limit)

    def run_pattern_query(self, cypher: str, region: str) -> list[dict]:
        """Execute a pattern detection Cypher query for a given region."""
        try:
            return self.run(cypher, region=region)
        except Exception as e:
            logger.error(f"Pattern query failed for region {region}: {e}")
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[Neo4jClient] = None

def get_neo4j_client() -> Neo4jClient:
    global _client
    if _client is None:
        _client = Neo4jClient()
    return _client
