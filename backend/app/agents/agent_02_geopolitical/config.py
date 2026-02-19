"""
GeoKG-RAG Configuration
Central config loaded from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Neo4j ────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "yourpassword")

# ── Weaviate ─────────────────────────────────────────────────
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
WEAVIATE_KEY = os.getenv("WEAVIATE_KEY", "")

# ── LLM ──────────────────────────────────────────────────────
GEMINI_API_KEY1     = os.getenv("GEMINI_API_KEY1", "")
GEMINI_API_KEY2     = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_KEY3     = os.getenv("GEMINI_API_KEY3", "")
GEMINI_API_KEY4     = os.getenv("GEMINI_API_KEY4", "")
GEMINI_API_KEY =[GEMINI_API_KEY1, GEMINI_API_KEY2, GEMINI_API_KEY3, GEMINI_API_KEY4]
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")  # optional fallback

# Primary reasoning model — Gemini 2.5 Flash (fast + capable)
REASONING_MODEL    = os.getenv("REASONING_MODEL", "")
# Fast routing model — same model, lower token budget
ROUTING_MODEL      = os.getenv("ROUTING_MODEL", "")
# Embedding model — Gemini native embeddings
EMBEDDING_MODEL    = os.getenv("EMBEDDING_MODEL", "text-embedding-004")  # new SDK: no "models/" prefix
EMBEDDING_DIM      = int(os.getenv("EMBEDDING_DIM", "3072"))  # gemini-embedding-001 = 3072 dims

# ── Data Sources ─────────────────────────────────────────────
GDELT_API_URL  = os.getenv("GDELT_API_URL", "https://api.gdeltproject.org/api/v2")
ACLED_API_KEY  = os.getenv("ACLED_API_KEY", "")

# ── Kafka ────────────────────────────────────────────────────
KAFKA_SERVERS  = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPICS   = {
    "raw":        "geo.news.raw",
    "entities":   "geo.entities.extracted",
    "relations":  "geo.relations.extracted",
    "delta":      "geo.graph.delta",
    "alerts":     "geo.alerts.patterns",
}

# ── App ───────────────────────────────────────────────────────
LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO")
API_PORT           = int(os.getenv("API_PORT", "8000"))
PATTERN_SCAN_HOURS = int(os.getenv("PATTERN_SCAN_INTERVAL_HOURS", "1"))
INGEST_MINUTES     = int(os.getenv("INGESTION_INTERVAL_MINUTES", "15"))

# ── NER ───────────────────────────────────────────────────────
GEO_ENTITY_TYPES = [
    "state actor",
    "non-state armed group",
    "political faction",
    "disputed territory",
    "strategic chokepoint",
    "military base",
    "conflict event",
    "diplomatic event",
    "covert operation",
    "strategic resource",
    "ideology",
    "historical grievance",
    "sanctions measure",
    "arms transfer",
    "proxy relationship",
    "national leader",
    "international organization",
]

# ── Graph Schema ─────────────────────────────────────────────
RELATION_TYPES = [
    "ALLIED_WITH",
    "HOSTILE_TO",
    "PROXY_OF",
    "FUNDS",
    "SUPPLIES_ARMS_TO",
    "CONTROLS",
    "DISPUTES",
    "TRADE_PARTNER",
    "SANCTIONS",
    "RHETORIC_ESCALATION",
    "TROOP_MOVEMENT",
    "DISINFORMATION_TARGET",
    "HISTORICAL_GRIEVANCE",
    "CAUSED",
    "TRIGGERED_BY",
    "IN_CONFLICT_WITH",
]

# ── GDELT Query Terms ─────────────────────────────────────────
GEO_QUERIES = [
    "conflict war military",
    "sanctions diplomatic",
    "proxy militia armed group",
    "territorial dispute sovereignty",
    "coup election political crisis",
    "ceasefire peace negotiation",
    "nuclear missile threat",
]

ALL_REGIONS = [
    "Middle East",
    "Eastern Europe",
    "Sub-Saharan Africa",
    "South Asia",
    "East Asia",
    "Central Asia",
    "Latin America",
    "North Africa",
    "Balkans",
    "Caucasus",
]
