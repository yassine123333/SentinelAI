"""
RAG Document Store — Qdrant-backed with automatic TTL expiration.

Uses Qdrant as a proper vector database for high-performance semantic
search. Runs in local/embedded mode (no server required) with on-disk
persistence. Data expires after a configurable TTL (default 2 days).
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

# Default: 2 days in seconds
DEFAULT_TTL_SECONDS = 2 * 24 * 60 * 60

QDRANT_PATH = str(Path(__file__).parent.parent / "qdrant_data")

# Collection names
DOCS_COLLECTION = "documents"
SIGNALS_COLLECTION = "signals"

# Default vector dimension (Gemini embedding-001 = 3072, local fallback = 256)
DEFAULT_VECTOR_SIZE = 3072


class DocumentStore:
    """Qdrant-backed vector store with TTL-based expiration."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        vector_size: int = DEFAULT_VECTOR_SIZE,
    ):
        self.ttl_seconds = ttl_seconds
        self.vector_size = vector_size
        storage_path = db_path or QDRANT_PATH

        # Qdrant in local embedded mode — no server needed
        self.client = QdrantClient(path=storage_path)
        self._ensure_collections()

    # ─── Collection Setup ───────────────────────────────────────

    def _ensure_collections(self):
        """Create Qdrant collections if they don't exist."""
        existing = {c.name for c in self.client.get_collections().collections}

        if DOCS_COLLECTION not in existing:
            self.client.create_collection(
                collection_name=DOCS_COLLECTION,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE,
                ),
            )

        if SIGNALS_COLLECTION not in existing:
            self.client.create_collection(
                collection_name=SIGNALS_COLLECTION,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE,
                ),
            )

    # ─── Cleanup ────────────────────────────────────────────────

    def cleanup_expired(self):
        """Remove all documents and signals past their TTL."""
        now = time.time()
        for collection in [DOCS_COLLECTION, SIGNALS_COLLECTION]:
            try:
                self.client.delete(
                    collection_name=collection,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="expires_at",
                                range=Range(lt=now),
                            )
                        ]
                    ),
                )
            except Exception:
                pass

    # ─── Document Operations ────────────────────────────────────

    def store_document(
        self,
        doc_id: str,
        doc_type: str,
        content: str,
        asset: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """
        Store a document with TTL.

        Args:
            doc_id:     Unique identifier.
            doc_type:   'gdelt_article' | 'reddit_post' | 'news' | 'raw_data'
            content:    Text content of the document.
            asset:      Related asset/topic.
            metadata:   Extra metadata dict.
            embedding:  Vector embedding as list of floats.
        """
        self.cleanup_expired()
        now = time.time()
        expires = now + self.ttl_seconds

        vector = embedding if embedding else [0.0] * self.vector_size
        # Adapt vector size if needed
        vector = self._adapt_vector(vector)

        payload = {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "asset": asset,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
            "expires_at": expires,
            "has_embedding": embedding is not None,
        }

        point_id = self._stable_uuid(doc_id)
        self.client.upsert(
            collection_name=DOCS_COLLECTION,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def store_documents_batch(
        self,
        docs: List[Dict[str, Any]],
    ) -> int:
        """
        Batch-store multiple documents.

        Each dict must have: id, doc_type, content.
        Optional: asset, metadata, embedding.

        Returns count of docs stored.
        """
        self.cleanup_expired()
        now = time.time()
        expires = now + self.ttl_seconds

        points = []
        for doc in docs:
            vector = doc.get("embedding") or [0.0] * self.vector_size
            vector = self._adapt_vector(vector)

            payload = {
                "doc_id": doc["id"],
                "doc_type": doc["doc_type"],
                "asset": doc.get("asset", ""),
                "content": doc["content"],
                "metadata": doc.get("metadata") or {},
                "created_at": now,
                "expires_at": expires,
                "has_embedding": doc.get("embedding") is not None,
            }

            point_id = self._stable_uuid(doc["id"])
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        if points:
            self.client.upsert(
                collection_name=DOCS_COLLECTION,
                points=points,
            )

        return len(points)

    def get_documents(
        self,
        doc_type: Optional[str] = None,
        asset: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve non-expired documents, optionally filtered."""
        self.cleanup_expired()
        now = time.time()

        conditions = [
            FieldCondition(key="expires_at", range=Range(gt=now)),
        ]
        if doc_type:
            conditions.append(
                FieldCondition(key="doc_type", match=MatchValue(value=doc_type))
            )
        if asset:
            conditions.append(
                FieldCondition(key="asset", match=MatchValue(value=asset))
            )

        results = self.client.scroll(
            collection_name=DOCS_COLLECTION,
            scroll_filter=Filter(must=conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )[0]

        docs = []
        for point in results:
            p = point.payload
            doc = {
                "id": p.get("doc_id", ""),
                "doc_type": p.get("doc_type", ""),
                "asset": p.get("asset", ""),
                "content": p.get("content", ""),
                "created_at": p.get("created_at", 0),
            }
            if p.get("metadata"):
                doc["metadata"] = p["metadata"]
            docs.append(doc)

        # Sort by created_at descending
        docs.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        return docs

    def search_similar(
        self,
        query_vector: List[float],
        doc_type: Optional[str] = None,
        asset: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search via Qdrant's native vector similarity.

        Returns list of {doc_id, content, similarity} sorted by score.
        """
        self.cleanup_expired()
        now = time.time()

        conditions = [
            FieldCondition(key="expires_at", range=Range(gt=now)),
            FieldCondition(key="has_embedding", match=MatchValue(value=True)),
        ]
        if doc_type:
            conditions.append(
                FieldCondition(key="doc_type", match=MatchValue(value=doc_type))
            )
        if asset:
            conditions.append(
                FieldCondition(key="asset", match=MatchValue(value=asset))
            )

        query_vector = self._adapt_vector(query_vector)

        results = self.client.query_points(
            collection_name=DOCS_COLLECTION,
            query=query_vector,
            query_filter=Filter(must=conditions),
            limit=top_k,
            score_threshold=min_score,
            with_payload=True,
        )

        return [
            {
                "doc_id": hit.payload.get("doc_id", ""),
                "content": hit.payload.get("content", ""),
                "similarity": round(hit.score, 4),
            }
            for hit in results.points
        ]

    # ─── Signal Operations ──────────────────────────────────────

    def store_signal(
        self,
        signal_id: str,
        asset: str,
        signal: Dict[str, Any],
        embedding: Optional[List[float]] = None,
    ) -> None:
        """Store a computed sentiment signal with TTL."""
        self.cleanup_expired()
        now = time.time()
        expires = now + self.ttl_seconds

        vector = embedding if embedding else [0.0] * self.vector_size
        vector = self._adapt_vector(vector)

        payload = {
            "signal_id": signal_id,
            "asset": asset,
            "signal": signal,
            "created_at": now,
            "expires_at": expires,
        }

        point_id = self._stable_uuid(signal_id)
        self.client.upsert(
            collection_name=SIGNALS_COLLECTION,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def get_signals(
        self, asset: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Retrieve recent non-expired signals."""
        self.cleanup_expired()
        now = time.time()

        conditions = [
            FieldCondition(key="expires_at", range=Range(gt=now)),
        ]
        if asset:
            conditions.append(
                FieldCondition(key="asset", match=MatchValue(value=asset))
            )

        results = self.client.scroll(
            collection_name=SIGNALS_COLLECTION,
            scroll_filter=Filter(must=conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )[0]

        signals = []
        for point in results:
            p = point.payload
            signals.append({
                "id": p.get("signal_id", ""),
                "asset": p.get("asset", ""),
                "signal": p.get("signal", {}),
                "created_at": p.get("created_at", 0),
            })

        # Sort by created_at descending
        signals.sort(key=lambda s: s.get("created_at", 0), reverse=True)
        return signals[:limit]

    # ─── Stats ──────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """Return counts of stored documents and signals."""
        self.cleanup_expired()
        try:
            doc_info = self.client.get_collection(DOCS_COLLECTION)
            doc_count = doc_info.points_count
        except Exception:
            doc_count = 0

        try:
            sig_info = self.client.get_collection(SIGNALS_COLLECTION)
            sig_count = sig_info.points_count
        except Exception:
            sig_count = 0

        return {"documents": doc_count, "signals": sig_count}

    # ─── Helpers ────────────────────────────────────────────────

    def _adapt_vector(self, vector: List[float]) -> List[float]:
        """Ensure vector matches collection dimension."""
        if len(vector) < self.vector_size:
            vector = vector + [0.0] * (self.vector_size - len(vector))
        elif len(vector) > self.vector_size:
            vector = vector[: self.vector_size]
        return vector

    @staticmethod
    def _stable_uuid(key: str) -> str:
        """Generate a deterministic UUID from a string key."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

    def close(self):
        """Close the Qdrant client."""
        try:
            self.client.close()
        except Exception:
            pass
