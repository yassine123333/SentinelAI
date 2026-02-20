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

# ── LLM (Groq) ───────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Kept for compatibility with orchestration layer references
REASONING_MODEL = os.getenv("REASONING_MODEL", GROQ_MODEL)
ROUTING_MODEL   = os.getenv("ROUTING_MODEL",   GROQ_MODEL)

# ── Embeddings (sentence-transformers, local) ─────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # local, no API key required
EMBEDDING_DIM   = 384                   # all-MiniLM-L6-v2 output dimension

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
