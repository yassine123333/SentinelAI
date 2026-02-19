"""
Hybrid Retrieval Engine
Runs graph traversal + vector search + pattern detection in parallel,
then fuses and reranks all context for LLM consumption.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from graph.neo4j_client import get_neo4j_client
from retrieval.weaviate_client import hybrid_search, semantic_search
from intelligence.pattern_scanner import PatternScanner

logger = logging.getLogger(__name__)

_pattern_scanner: PatternScanner | None = None


def get_pattern_scanner() -> PatternScanner:
    global _pattern_scanner
    if _pattern_scanner is None:
        _pattern_scanner = PatternScanner()
    return _pattern_scanner


# ── Serialization ─────────────────────────────────────────────────────────────

def serialize_subgraph(subgraph: dict) -> str:
    """
    Convert a Neo4j subgraph dict to human-readable triples for LLM context.
    Format: (Actor A) --[RELATION {confidence: 0.87}]--> (Actor B) since 2023-01
    """
    lines = []

    # Node summary
    nodes = subgraph.get("nodes", [])
    if nodes:
        lines.append(f"ENTITIES ({len(nodes)} nodes):")
        for n in nodes[:30]:  # Cap for context length
            name = n.get("name", n.get("id", "?"))
            ntype = n.get("type", "")
            actor_type = n.get("actor_type", "")
            conf = n.get("confidence", 1.0)
            conf_str = f" [confidence: {conf:.2f}]" if conf < 1.0 else ""
            lines.append(f"  • {name} ({ntype}/{actor_type}){conf_str}")

    # Edge triples
    edges = subgraph.get("edges", [])
    if edges:
        lines.append(f"\nRELATIONSHIPS ({len(edges)} edges):")
        for e in edges[:50]:  # Cap for context length
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            rel = e.get("type", "?")
            conf = e.get("confidence", 1.0)
            inferred = " [INFERRED]" if e.get("inferred") else ""
            since = f" since {e['valid_from'][:10]}" if e.get("valid_from") else ""
            conf_str = f" [confidence: {conf:.2f}]" if conf and conf < 1.0 else ""
            lines.append(f"  ({src}) --[{rel}]--> ({tgt}){conf_str}{inferred}{since}")

    return "\n".join(lines) if lines else "No graph context available."


def rerank_passages(
    passages: list[dict],
    query: str,
    top_k: int = 15,
) -> list[dict]:
    """
    Rerank passages by relevance to query.
    Uses keyword overlap as a fast proxy for relevance
    (production: use cross-encoder reranker like bge-reranker-v2).
    """
    query_words = set(query.lower().split())

    def relevance_score(p: dict) -> float:
        text = (p.get("title", "") + " " + p.get("content", "")).lower()
        overlap = sum(1 for w in query_words if w in text)
        vector_score = 1.0 - (p.get("distance") or 0.5)  # Convert distance to similarity
        return (overlap * 0.3) + (vector_score * 0.7)

    ranked = sorted(passages, key=relevance_score, reverse=True)
    return ranked[:top_k]


def format_passages(passages: list[dict]) -> str:
    """Format retrieved passages for LLM context block."""
    if not passages:
        return "No source passages retrieved."

    lines = ["SOURCE PASSAGES:"]
    for i, p in enumerate(passages, 1):
        bias = p.get("source_bias", "UNKNOWN")
        source = p.get("source", "Unknown")
        date = p.get("published_at", "")[:10] if p.get("published_at") else ""
        title = p.get("title", "Untitled")
        content = p.get("content", "")[:500]
        lines.append(
            f"\n[{i}] {source} [{bias}] {date}\n"
            f"  Title: {title}\n"
            f"  {content}..."
        )
    return "\n".join(lines)


# ── Async Retrieval ───────────────────────────────────────────────────────────

async def graph_retrieve(query: str, seed_entities: list[str], depth: int = 2) -> dict:
    """Retrieve graph subgraph centered on seed entities."""
    neo4j = get_neo4j_client()
    loop = asyncio.get_event_loop()

    # Get actor IDs from names (fulltext search)
    actor_results = await loop.run_in_executor(
        None, lambda: neo4j.search_actors_fulltext(query, limit=5)
    )
    seed_ids = [r["id"] for r in actor_results]

    # Add any directly matched seed_entities
    for entity in seed_entities:
        results = await loop.run_in_executor(
            None, lambda e=entity: neo4j.search_actors_fulltext(e, limit=2)
        )
        seed_ids.extend(r["id"] for r in results)

    seed_ids = list(dict.fromkeys(seed_ids))  # Deduplicate, preserve order

    if not seed_ids:
        logger.info("No graph entities found for query. Returning empty subgraph.")
        return {"nodes": [], "edges": []}

    subgraph = await loop.run_in_executor(
        None, lambda: neo4j.get_actor_subgraph(seed_ids[:5], depth=depth)
    )
    return subgraph


async def vector_retrieve(query: str, region: str | None = None) -> list[dict]:
    """Retrieve semantically similar article passages."""
    loop = asyncio.get_event_loop()
    passages = await loop.run_in_executor(
        None,
        lambda: hybrid_search(query, limit=20),
    )
    return passages


async def check_patterns(region: str | None = None) -> list[dict]:
    """Check for active pattern alerts relevant to the query."""
    scanner = get_pattern_scanner()
    alerts = scanner.get_active_alerts(region)
    return [a.model_dump() for a in alerts]


async def find_historical_analogs_async(
    seed_entities: list[str],
    top_k: int = 3,
) -> list[dict]:
    """Find historically similar situations."""
    neo4j = get_neo4j_client()
    loop = asyncio.get_event_loop()
    analogs = await loop.run_in_executor(
        None,
        lambda: neo4j.find_historical_analogs(seed_entities, top_k=top_k),
    )
    return analogs


# ── Main Hybrid Retrieval ─────────────────────────────────────────────────────

async def hybrid_retrieve(
    query: str,
    query_type: str = "",
    seed_entities: list[str] | None = None,
    region: str | None = None,
    depth: int = 2,
) -> dict[str, Any]:
    """
    Main retrieval function: runs all sources in parallel and fuses results.
    
    Returns dict with:
    - graph_facts: serialized subgraph text
    - source_passages: formatted passages text
    - pattern_alerts: active alerts list
    - historical_analogs: similar past events
    - raw_subgraph: raw graph data for further processing
    - raw_passages: raw passage list
    """
    seed_entities = seed_entities or []

    # Run all retrievals in parallel
    graph_task     = asyncio.create_task(graph_retrieve(query, seed_entities, depth))
    vector_task    = asyncio.create_task(vector_retrieve(query, region))
    pattern_task   = asyncio.create_task(check_patterns(region))
    history_task   = asyncio.create_task(find_historical_analogs_async(seed_entities))

    subgraph, passages, pattern_alerts, historical_analogs = await asyncio.gather(
        graph_task, vector_task, pattern_task, history_task,
        return_exceptions=True,
    )

    # Handle exceptions gracefully
    if isinstance(subgraph, Exception):
        logger.error(f"Graph retrieval failed: {subgraph}")
        subgraph = {"nodes": [], "edges": []}
    if isinstance(passages, Exception):
        logger.error(f"Vector retrieval failed: {passages}")
        passages = []
    if isinstance(pattern_alerts, Exception):
        pattern_alerts = []
    if isinstance(historical_analogs, Exception):
        historical_analogs = []

    # Serialize graph to text
    graph_text = serialize_subgraph(subgraph)

    # Rerank passages
    top_passages = rerank_passages(passages, query, top_k=15)
    passages_text = format_passages(top_passages)

    logger.info(
        f"Retrieval complete: {len(subgraph.get('nodes', []))} nodes, "
        f"{len(top_passages)} passages, "
        f"{len(pattern_alerts)} alerts"
    )

    return {
        "graph_facts":       graph_text,
        "source_passages":   passages_text,
        "pattern_alerts":    pattern_alerts,
        "historical_analogs": historical_analogs,
        "raw_subgraph":      subgraph,
        "raw_passages":      top_passages,
    }
