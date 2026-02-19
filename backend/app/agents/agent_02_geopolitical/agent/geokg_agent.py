"""
GeoKG-RAG LangGraph Agent
Stateful multi-step intelligence workflow:
Query → Classify → Extract Entities → Graph Retrieval → Vector Retrieval
→ Pattern Detection → Historical Matching → Context Fusion
→ LLM Reasoning → Report + Graph Feedback
"""
from __future__ import annotations
import asyncio
import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

import config
from models import PatternAlert
from agent.prompts import SYSTEM_PROMPT, get_sub_prompt, build_user_message

logger = logging.getLogger(__name__)


# ── Agent State ───────────────────────────────────────────────────────────────

class GeoIntelState(TypedDict):
    query: str
    query_type: str
    seed_entities: list[str]
    graph_subgraph: dict
    vector_passages: list[dict]
    pattern_alerts: list[dict]
    historical_analogs: list[dict]
    fused_context: str
    graph_facts: str
    source_passages: str
    report: str
    sources_used: list[str]
    processing_start: float


# ── Node Functions ────────────────────────────────────────────────────────────

def classify_query_type(state: GeoIntelState) -> GeoIntelState:
    """Classify the query using Gemini 2.5 Flash."""
    query = state["query"]
    try:
        from gemini_client import classify_query
        query_type = classify_query(query)
    except Exception as e:
        logger.warning(f"Gemini classification failed, using keywords: {e}")
        from gemini_client import _keyword_classify
        query_type = _keyword_classify(query)
    logger.info(f"Query classified as: {query_type}")
    return {**state, "query_type": query_type}


def extract_query_entities(state: GeoIntelState) -> GeoIntelState:
    """Extract entity mentions from the query text for graph seeding."""
    query = state["query"]

    # Try GLiNER NER
    entities = []
    try:
        from gliner import GLiNER
        model = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
        raw = model.predict_entities(query, config.GEO_ENTITY_TYPES[:6], threshold=0.4)
        entities = [e["text"] for e in raw]
    except Exception:
        pass

    # Fallback: spaCy NER
    if not entities:
        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(query)
            entities = [ent.text for ent in doc.ents
                       if ent.label_ in ("GPE", "ORG", "PERSON", "NORP")]
        except Exception:
            pass

    # Last fallback: extract capitalized phrases
    if not entities:
        entities = re.findall(r"\b[A-Z][a-z]+ (?:[A-Z][a-z]+ )*", query)
        entities = [e.strip() for e in entities if len(e) > 3][:5]

    logger.info(f"Extracted seed entities: {entities}")
    return {**state, "seed_entities": entities}


def retrieve_graph_subgraph(state: GeoIntelState) -> GeoIntelState:
    """Retrieve relevant subgraph from Neo4j."""
    try:
        from graph.neo4j_client import get_neo4j_client
        from retrieval.hybrid import serialize_subgraph

        neo4j = get_neo4j_client()
        seed_entities = state["seed_entities"]

        # Search for actor IDs from entity names
        actor_ids = []
        for entity in seed_entities:
            results = neo4j.search_actors_fulltext(entity, limit=2)
            actor_ids.extend(r["id"] for r in results)

        actor_ids = list(dict.fromkeys(actor_ids))[:5]

        if actor_ids:
            subgraph = neo4j.get_actor_subgraph(actor_ids, depth=2)
        else:
            subgraph = {"nodes": [], "edges": []}

        graph_facts = serialize_subgraph(subgraph)
        logger.info(f"Graph retrieval: {len(subgraph.get('nodes', []))} nodes, {len(subgraph.get('edges', []))} edges")

    except Exception as e:
        logger.error(f"Graph retrieval failed: {e}")
        subgraph = {"nodes": [], "edges": []}
        graph_facts = "Graph retrieval unavailable."

    return {**state, "graph_subgraph": subgraph, "graph_facts": graph_facts}


def retrieve_vector_passages(state: GeoIntelState) -> GeoIntelState:
    """Retrieve semantically relevant article passages from Weaviate."""
    try:
        from retrieval.weaviate_client import hybrid_search
        from retrieval.hybrid import rerank_passages, format_passages

        passages = hybrid_search(state["query"], limit=20)
        top_passages = rerank_passages(passages, state["query"], top_k=12)
        passages_text = format_passages(top_passages)
        sources = list({p.get("source", "") for p in top_passages if p.get("source")})

    except Exception as e:
        logger.warning(f"Vector retrieval failed (Weaviate may not be running): {e}")
        top_passages = []
        passages_text = "Vector retrieval unavailable (Weaviate not connected)."
        sources = []

    return {**state, "vector_passages": top_passages, "source_passages": passages_text, "sources_used": sources}


def run_pattern_scanner(state: GeoIntelState) -> GeoIntelState:
    """Check active pattern alerts relevant to the query."""
    try:
        from intelligence.pattern_scanner import PatternScanner

        scanner = PatternScanner()
        # Detect region from query
        region = None
        for r in config.ALL_REGIONS:
            if r.lower() in state["query"].lower():
                region = r
                break

        alerts = scanner.get_active_alerts(region)
        alerts_dicts = [a.model_dump() for a in alerts]

    except Exception as e:
        logger.warning(f"Pattern scanner unavailable: {e}")
        alerts_dicts = []

    return {**state, "pattern_alerts": alerts_dicts}


def find_historical_analogs(state: GeoIntelState) -> GeoIntelState:
    """Find historically similar situations from the graph."""
    try:
        from graph.neo4j_client import get_neo4j_client

        neo4j = get_neo4j_client()
        analogs = neo4j.find_historical_analogs(
            state["seed_entities"], top_k=3
        )
    except Exception as e:
        logger.warning(f"Historical analog search failed: {e}")
        analogs = []

    return {**state, "historical_analogs": analogs}


def fuse_and_rank_context(state: GeoIntelState) -> GeoIntelState:
    """Merge all retrieved context into a single LLM-ready context string."""
    fused = build_user_message(
        query=state["query"],
        graph_facts=state["graph_facts"],
        source_passages=state["source_passages"],
        pattern_alerts=state["pattern_alerts"],
        historical_analogs=state["historical_analogs"],
    )
    return {**state, "fused_context": fused}


def generate_intel_report(state: GeoIntelState) -> GeoIntelState:
    """Call Gemini 2.5 Flash to generate the structured intelligence report."""
    sub_prompt = get_sub_prompt(state["query_type"])
    full_system = f"{SYSTEM_PROMPT}\n\n{sub_prompt}"

    report = ""
    try:
        from gemini_client import generate_report
        report = generate_report(full_system, state["fused_context"])
        logger.info(f"Intelligence report generated ({len(report)} chars)")
    except Exception as e:
        logger.error(f"Gemini report generation failed: {e}")
        report = _fallback_report(state)

    return {**state, "report": report}


def extract_new_triples(state: GeoIntelState) -> GeoIntelState:
    """
    Graph Feedback: extract new facts from the LLM report and write to graph.
    This closes the learning loop — every query potentially enriches the graph.
    """
    if not state.get("report"):
        return state

    try:
        from graph.delta_writer import DeltaGraphWriter
        from extraction.pipeline import _llm_relation_extraction

        # Extract relations from the generated report
        new_triples = _llm_relation_extraction(state["report"], [])
        if new_triples:
            writer = DeltaGraphWriter()
            from models import ExtractionResult
            import hashlib

            dummy_result = ExtractionResult(
                article_id="report_" + hashlib.sha256(state["query"].encode()).hexdigest()[:8],
                entities=[],
                triples=new_triples,
                source_bias="INTERNAL",
                confidence=0.6,
            )
            stats = writer.write_extraction(dummy_result)
            logger.info(f"Graph feedback: {stats['relations']} new relations from report")

    except Exception as e:
        logger.debug(f"Graph feedback skipped: {e}")

    return state


# ── Fallback Report ───────────────────────────────────────────────────────────

def _fallback_report(state: GeoIntelState) -> str:
    """Generate a structured fallback report when LLM is unavailable."""
    alerts = state.get("pattern_alerts", [])
    alert_section = ""
    if alerts:
        alert_section = "\n## Pattern Alerts\n"
        for a in alerts:
            alert_section += (
                f"⚠ **{a.get('alert_level')}** — {a.get('signature_name')} @ {a.get('region')}\n"
                f"  Firing: {', '.join(a.get('indicators_fired', []))}\n"
            )

    return f"""## Executive Summary
Analysis based on retrieved graph data and source passages for: {state['query']}
Note: LLM reasoning unavailable — showing raw retrieval context.

## Retrieved Graph Facts
{state.get('graph_facts', 'No graph data available.')}

{alert_section}

## Source Passages
{state.get('source_passages', 'No source passages available.')}

## Evidence Trail
Query type: {state.get('query_type', 'unknown')}
Seed entities: {', '.join(state.get('seed_entities', []))}
Sources: {', '.join(state.get('sources_used', []))}
"""


# ── Build LangGraph Workflow ──────────────────────────────────────────────────

def build_agent():
    """Construct and compile the LangGraph agent workflow."""
    workflow = StateGraph(GeoIntelState)

    # Add all nodes
    workflow.add_node("classify_query",     classify_query_type)
    workflow.add_node("extract_entities",   extract_query_entities)
    workflow.add_node("graph_retrieval",    retrieve_graph_subgraph)
    workflow.add_node("vector_retrieval",   retrieve_vector_passages)
    workflow.add_node("pattern_detection",  run_pattern_scanner)
    workflow.add_node("historical_matching",find_historical_analogs)
    workflow.add_node("context_fusion",     fuse_and_rank_context)
    workflow.add_node("llm_reasoning",      generate_intel_report)
    workflow.add_node("graph_feedback",     extract_new_triples)

    # Wire the linear pipeline
    workflow.set_entry_point("classify_query")
    workflow.add_edge("classify_query",     "extract_entities")
    workflow.add_edge("extract_entities",   "graph_retrieval")
    workflow.add_edge("graph_retrieval",    "vector_retrieval")
    workflow.add_edge("vector_retrieval",   "pattern_detection")
    workflow.add_edge("pattern_detection",  "historical_matching")
    workflow.add_edge("historical_matching","context_fusion")
    workflow.add_edge("context_fusion",     "llm_reasoning")
    workflow.add_edge("llm_reasoning",      "graph_feedback")
    workflow.add_edge("graph_feedback",     END)

    return workflow.compile()


# ── Singleton Agent ───────────────────────────────────────────────────────────

_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def run_query(query: str) -> dict[str, Any]:
    """
    Synchronous entry point: run a query through the full agent pipeline.
    Returns the final state dict including the intelligence report.
    """
    agent = get_agent()
    start = time.time()

    initial_state: GeoIntelState = {
        "query":            query,
        "query_type":       "",
        "seed_entities":    [],
        "graph_subgraph":   {},
        "vector_passages":  [],
        "pattern_alerts":   [],
        "historical_analogs": [],
        "fused_context":    "",
        "graph_facts":      "",
        "source_passages":  "",
        "report":           "",
        "sources_used":     [],
        "processing_start": start,
    }

    final_state = agent.invoke(initial_state)
    elapsed = round((time.time() - start) * 1000, 1)

    return {
        "query":         query,
        "query_type":    final_state.get("query_type", ""),
        "report":        final_state.get("report", ""),
        "pattern_alerts": final_state.get("pattern_alerts", []),
        "sources_used":  final_state.get("sources_used", []),
        "processing_time_ms": elapsed,
    }
