"""
Modular RAG (Retrieval-Augmented Generation) subsystem.

Components:
    store       – TTL-backed SQLite document store (2-day max retention)
    parser      – Input understanding & entity extraction via Gemini
    embedder    – Embedding generation (Gemini API + TF-IDF fallback)
    retriever   – Semantic search over stored documents
    context_builder – Assembles RAG context for the agent

Usage:
    from rag import RAGPipeline
    pipeline = RAGPipeline(gemini_api_key="...")
    parsed = pipeline.parse_input(raw_input)
    context = pipeline.retrieve_context(parsed)
    pipeline.store_results(signal, raw_data)
"""

from rag.pipeline import RAGPipeline

__all__ = ["RAGPipeline"]
