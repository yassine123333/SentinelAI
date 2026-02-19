"""
GeoKG-RAG Intelligence API
FastAPI REST interface for the geopolitical intelligence agent.
"""
from __future__ import annotations
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.requests import Request
from starlette.responses import Response

import config
from models import QueryRequest, IntelligenceReport, PatternAlert

logger = logging.getLogger(__name__)

# ── Prometheus Metrics ────────────────────────────────────────────────────────

QUERY_COUNTER   = Counter("geokg_queries_total", "Total queries processed", ["query_type"])
QUERY_LATENCY   = Histogram("geokg_query_duration_seconds", "Query processing time",
                             buckets=[0.5, 1, 2, 5, 10, 30, 60])
INGEST_COUNTER  = Counter("geokg_articles_ingested_total", "Articles ingested")
ALERT_COUNTER   = Counter("geokg_pattern_alerts_total", "Pattern alerts fired", ["level"])


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    logger.info("GeoKG-RAG API starting up...")

    # Initialize Neo4j schema
    try:
        from graph.neo4j_client import get_neo4j_client
        client = get_neo4j_client()
        if client.verify_connectivity():
            client.initialize_schema()
            logger.info("✅ Neo4j connected and schema initialized")
        else:
            logger.warning("⚠️  Neo4j not available — graph features disabled")
    except Exception as e:
        logger.warning(f"⚠️  Neo4j startup error: {e}")

    # Initialize Weaviate schema
    try:
        from retrieval.weaviate_client import initialize_schema
        initialize_schema()
        logger.info("✅ Weaviate schema initialized")
    except Exception as e:
        logger.warning(f"⚠️  Weaviate startup error: {e}")

    # Pre-load agent (compiles graph)
    try:
        from agent.geokg_agent import get_agent
        get_agent()
        logger.info("✅ LangGraph agent compiled and ready")
    except Exception as e:
        logger.error(f"❌ Agent compilation failed: {e}")

    logger.info("🌍 GeoKG-RAG API ready.")
    yield

    # Shutdown
    logger.info("GeoKG-RAG API shutting down...")
    try:
        from graph.neo4j_client import _client
        if _client:
            _client.close()
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="GeoKG-RAG Intelligence API",
    description="Geopolitical Knowledge Graph RAG Agent — structured intelligence from live news",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ───────────────────────────────────────────────────

class QueryResponse(BaseModel):
    query: str
    query_type: str
    report: str
    pattern_alerts: list[dict] = []
    sources_used: list[str] = []
    processing_time_ms: float
    timestamp: str

class IngestRequest(BaseModel):
    hours_back: int = 1
    queries: Optional[list[str]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse, tags=["Intelligence"])
async def query_agent(req: QueryRequest) -> QueryResponse:
    """
    Submit a geopolitical intelligence query to the agent.
    
    The agent will:
    1. Classify query type (proxy/genealogy/pattern/leverage/intent)
    2. Extract seed entities
    3. Retrieve graph subgraph + vector passages in parallel
    4. Check pattern alerts
    5. Fuse all context
    6. Generate structured intelligence report
    """
    from agent.geokg_agent import run_query

    try:
        with QUERY_LATENCY.time():
            result = run_query(req.query)

        QUERY_COUNTER.labels(query_type=result.get("query_type", "unknown")).inc()

        return QueryResponse(
            query=req.query,
            query_type=result.get("query_type", ""),
            report=result.get("report", ""),
            pattern_alerts=result.get("pattern_alerts", []),
            sources_used=result.get("sources_used", []),
            processing_time_ms=result.get("processing_time_ms", 0),
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/alerts", tags=["Intelligence"])
async def get_active_alerts(
    region: Optional[str] = Query(None, description="Filter by region name"),
    level: Optional[str] = Query(None, description="Filter by alert level: WATCH|WARNING|ALERT|CRITICAL"),
) -> list[dict]:
    """Get currently active conflict pattern alerts."""
    try:
        from intelligence.pattern_scanner import PatternScanner
        scanner = PatternScanner()
        alerts = scanner.get_active_alerts(region)
        result = [a.model_dump() for a in alerts]

        if level:
            result = [a for a in result if a.get("alert_level") == level.upper()]

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/alerts/scan", tags=["Intelligence"])
async def trigger_pattern_scan(background_tasks: BackgroundTasks) -> dict:
    """Trigger an immediate pattern scan across all regions (runs in background)."""
    def _scan():
        try:
            from intelligence.pattern_scanner import PatternScanner
            scanner = PatternScanner()
            alerts = scanner.scan_all()
            for a in alerts:
                ALERT_COUNTER.labels(level=a.alert_level).inc()
            logger.info(f"Background scan complete: {len(alerts)} alerts")
        except Exception as e:
            logger.error(f"Background scan failed: {e}")

    background_tasks.add_task(_scan)
    return {"status": "Pattern scan triggered", "timestamp": datetime.utcnow().isoformat()}


@app.get("/graph/actor/{actor_id}/network", tags=["Graph"])
async def get_actor_network(
    actor_id: str,
    depth: int = Query(2, ge=1, le=4),
) -> dict:
    """Get the network subgraph for a specific actor."""
    try:
        from graph.neo4j_client import get_neo4j_client
        from retrieval.hybrid import serialize_subgraph

        neo4j = get_neo4j_client()
        subgraph = neo4j.get_actor_subgraph([actor_id], depth=depth)
        return {
            "actor_id": actor_id,
            "depth": depth,
            "nodes": subgraph.get("nodes", []),
            "edges": subgraph.get("edges", []),
            "serialized": serialize_subgraph(subgraph),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/actor/{actor_id}/proxy-chains", tags=["Graph"])
async def get_proxy_chains(actor_id: str, max_hops: int = 4) -> list[dict]:
    """Get proxy/funding chains involving a specific actor."""
    try:
        from graph.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        return neo4j.find_proxy_chains(actor_id, max_hops=max_hops)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/conflict/{region}/timeline", tags=["Graph"])
async def get_conflict_timeline(
    region: str,
    days_back: int = Query(365, ge=1, le=3650),
) -> list[dict]:
    """Get chronological conflict event timeline for a region."""
    try:
        from graph.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        return neo4j.get_conflict_timeline(region, days_back=days_back)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/actor/search", tags=["Graph"])
async def search_actors(
    q: str = Query(..., description="Search query for actor name/alias"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    """Full-text search for actors by name or alias."""
    try:
        from graph.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        return neo4j.search_actors_fulltext(q, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/trigger", tags=["Ingestion"])
async def trigger_ingestion(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Trigger manual news ingestion cycle."""
    def _ingest():
        try:
            from sources.gdelt_connector import ingest_all_queries
            from extraction.pipeline import GeopoliticalExtractor
            from graph.delta_writer import DeltaGraphWriter

            articles = ingest_all_queries(hours_back=req.hours_back)
            extractor = GeopoliticalExtractor()
            writer = DeltaGraphWriter()

            success = 0
            for article in articles:
                try:
                    result = extractor.extract(article)
                    writer.write_extraction(result)
                    INGEST_COUNTER.inc()
                    success += 1
                except Exception as e:
                    logger.error(f"Article processing failed: {e}")

            logger.info(f"Ingestion complete: {success}/{len(articles)} articles processed")
        except Exception as e:
            logger.error(f"Ingestion background task failed: {e}")

    background_tasks.add_task(_ingest)
    return {
        "status": "Ingestion triggered",
        "hours_back": req.hours_back,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/graph/stats", tags=["Graph"])
async def get_graph_stats() -> dict:
    """Get current knowledge graph statistics."""
    try:
        from graph.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()

        stats = {}
        for label in ("Actor", "Territory", "GeoEvent", "Article"):
            result = neo4j.run(f"MATCH (n:{label}) RETURN count(n) AS count")
            stats[label.lower() + "_count"] = result[0]["count"] if result else 0

        rel_result = neo4j.run("MATCH ()-[r]->() RETURN count(r) AS count")
        stats["relation_count"] = rel_result[0]["count"] if rel_result else 0

        return stats
    except Exception as e:
        return {"error": str(e), "note": "Neo4j may not be running"}


@app.get("/health", tags=["System"])
async def health_check() -> dict:
    """Health check — verifies connectivity to all services."""
    status = {"api": "ok", "timestamp": datetime.utcnow().isoformat()}

    # Neo4j check
    try:
        from graph.neo4j_client import get_neo4j_client
        status["neo4j"] = "ok" if get_neo4j_client().verify_connectivity() else "error"
    except Exception:
        status["neo4j"] = "error"

    # Weaviate check
    try:
        from retrieval.weaviate_client import get_weaviate_client
        client = get_weaviate_client()
        status["weaviate"] = "ok" if client and client.is_connected() else "error"
    except Exception:
        status["weaviate"] = "error"

    return status


@app.get("/metrics", tags=["System"])
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", tags=["System"])
async def root() -> dict:
    return {
        "name": "GeoKG-RAG Intelligence API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "query_endpoint": "POST /query",
    }
