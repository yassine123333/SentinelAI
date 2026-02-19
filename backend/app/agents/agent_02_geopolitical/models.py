"""
GeoKG-RAG Data Models
Pydantic models used throughout the system.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Entity Models ─────────────────────────────────────────────────────────────

class Actor(BaseModel):
    id: str                                # canonical Wikidata QID or slug
    name: str
    actor_type: str                        # state | non-state | faction | org
    aliases: list[str] = Field(default_factory=list)
    country: Optional[str] = None
    ideology: Optional[str] = None
    embedding: Optional[list[float]] = None
    confidence: float = 1.0

class Territory(BaseModel):
    id: str
    name: str
    country: Optional[str] = None
    centroid: Optional[tuple[float, float]] = None   # (lat, lon)
    disputed: bool = False
    controlling_actor: Optional[str] = None

class GeoEvent(BaseModel):
    id: str
    event_type: str                        # ARMED_CONFLICT | DIPLOMATIC | COVERT | ECONOMIC
    description: str
    actors: list[str]                      # actor IDs involved
    territories: list[str] = Field(default_factory=list)
    date_start: datetime
    date_end: Optional[datetime] = None
    intensity: float = Field(ge=1, le=10)  # Goldstein-based 1-10
    military_intensity: float = 0.0
    diplomatic_intensity: float = 0.0
    economic_intensity: float = 0.0
    source_article_id: Optional[str] = None
    confidence: float = 1.0

class Relation(BaseModel):
    subject_id: str
    relation_type: str
    object_id: str
    valid_from: datetime
    valid_to: Optional[datetime] = None
    confidence: float = 1.0
    source: str = "extraction"
    source_count: int = 1
    inferred: bool = False
    properties: dict[str, Any] = Field(default_factory=dict)


# ── Extraction Result ─────────────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    article_id: str
    entities: list[dict[str, Any]]
    triples: list[Relation]
    event: Optional[GeoEvent] = None
    scores: dict[str, float] = Field(default_factory=dict)
    source_bias: str = "UNKNOWN"            # PRO_WESTERN | PRO_RUSSIAN | LOCAL | NEUTRAL
    perspective: str = "NEUTRAL"
    confidence: float = 1.0


# ── Article ───────────────────────────────────────────────────────────────────

class Article(BaseModel):
    id: str
    url: str
    title: str
    content: str
    source: str
    published_at: datetime
    region: Optional[str] = None
    source_bias: str = "UNKNOWN"
    actor_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    embedding: Optional[list[float]] = None


# ── Pattern Alert ─────────────────────────────────────────────────────────────

class PatternAlert(BaseModel):
    region: str
    signature_name: str
    alert_level: str                       # WATCH | WARNING | ALERT | CRITICAL
    indicators_fired: list[str]
    indicators_missing: list[str]
    historical_match: Optional[str] = None
    similarity_score: float = 0.0
    estimated_escalation_weeks: Optional[tuple[int, int]] = None
    trigger_event: Optional[str] = None
    de_escalation_path: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Agent State ───────────────────────────────────────────────────────────────

class GeoIntelState(BaseModel):
    query: str
    query_type: str = ""                   # proxy | genealogy | pattern | leverage | intent
    seed_entities: list[str] = Field(default_factory=list)
    graph_subgraph: dict[str, Any] = Field(default_factory=dict)
    vector_passages: list[dict[str, Any]] = Field(default_factory=list)
    pattern_alerts: list[PatternAlert] = Field(default_factory=list)
    historical_analogs: list[dict[str, Any]] = Field(default_factory=list)
    fused_context: str = ""
    report: str = ""


# ── API Models ────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    region: Optional[str] = None
    depth: int = Field(default=2, ge=1, le=4)
    include_historical: bool = True

class IntelligenceReport(BaseModel):
    query: str
    query_type: str
    report: str
    pattern_alerts: list[PatternAlert] = Field(default_factory=list)
    confidence_overall: float = 0.0
    sources_used: list[str] = Field(default_factory=list)
    processing_time_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
