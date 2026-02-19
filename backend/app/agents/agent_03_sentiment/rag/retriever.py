"""
RAG Retriever — Semantic search via Qdrant vector database.

Uses Qdrant's native HNSW-based similarity search for high-performance
retrieval over stored documents. Returns ranked results above a minimum
relevance threshold.
"""

from typing import Any, Dict, List, Optional

from rag.store import DocumentStore
from rag.embedder import Embedder


# Minimum similarity score to consider a document relevant
DEFAULT_MIN_SIMILARITY = 0.3
DEFAULT_TOP_K = 10


class Retriever:
    """Semantic search retriever backed by Qdrant."""

    def __init__(
        self,
        store: DocumentStore,
        embedder: Embedder,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        top_k: int = DEFAULT_TOP_K,
    ):
        self.store = store
        self.embedder = embedder
        self.min_similarity = min_similarity
        self.top_k = top_k

    def search(
        self,
        query: str,
        doc_type: Optional[str] = None,
        asset: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for documents semantically similar to the query.

        Uses Qdrant's native vector search (HNSW index).

        Args:
            query:      Search query text.
            doc_type:   Filter by document type.
            asset:      Filter by asset.
            top_k:      Max results (overrides default).

        Returns:
            List of dicts with: doc_id, content, similarity.
            Sorted by descending similarity.
        """
        k = top_k or self.top_k

        # Embed the query
        query_vector = self.embedder.embed(query)

        # Qdrant native similarity search
        return self.store.search_similar(
            query_vector=query_vector,
            doc_type=doc_type,
            asset=asset,
            top_k=k,
            min_score=self.min_similarity,
        )

    def search_signals(
        self,
        asset: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent signals for an asset from the store.
        Direct lookup, not semantic search.
        """
        return self.store.get_signals(asset=asset, limit=limit)

    def get_recent_context(
        self,
        asset: str,
        doc_types: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get recent documents for an asset, optionally filtered by type.
        Useful for building time-ordered context.
        """
        if doc_types:
            all_docs = []
            for dt in doc_types:
                docs = self.store.get_documents(
                    doc_type=dt, asset=asset, limit=limit
                )
                all_docs.extend(docs)
            # Sort by created_at descending
            all_docs.sort(key=lambda d: d.get("created_at", 0), reverse=True)
            return all_docs[:limit]
        else:
            return self.store.get_documents(asset=asset, limit=limit)
