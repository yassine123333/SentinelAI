"""
Weaviate Vector Store Client
Manages article embeddings and semantic search.
Uses Gemini embeddings (no built-in vectorizer).
"""
from __future__ import annotations
import logging
from typing import Any, Optional

import config
from models import Article

logger = logging.getLogger(__name__)

_client = None
_schema_initialized = False


def get_weaviate_client():
    """Get or create singleton Weaviate client, auto-initializing schema."""
    global _client
    if _client is None:
        try:
            import weaviate

            if config.WEAVIATE_KEY:
                import weaviate.classes as wvc
                _client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=config.WEAVIATE_URL,
                    auth_credentials=wvc.init.Auth.api_key(config.WEAVIATE_KEY),
                )
            else:
                host = config.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0]
                _client = weaviate.connect_to_local(host=host, port=8080)

            logger.info(f"Connected to Weaviate at {config.WEAVIATE_URL}")
            # Always ensure schema exists after connecting
            _ensure_schema(_client)

        except Exception as e:
            logger.error(f"Weaviate connection failed: {e}")
            _client = None
    return _client


def _ensure_schema(client):
    """Create GeopoliticalArticle collection if it doesn't exist."""
    global _schema_initialized
    if _schema_initialized:
        return
    try:
        import weaviate.classes as wvc

        if client.collections.exists("GeopoliticalArticle"):
            logger.info("Weaviate: GeopoliticalArticle collection already exists.")
            _schema_initialized = True
            return

        client.collections.create(
            name="GeopoliticalArticle",
            vectorizer_config=wvc.config.Configure.Vectorizer.none(),
            properties=[
                wvc.config.Property(name="title",        data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="content",      data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="source",       data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="source_bias",  data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="published_at", data_type=wvc.config.DataType.DATE),
                wvc.config.Property(name="region",       data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="actor_ids",    data_type=wvc.config.DataType.TEXT_ARRAY),
                wvc.config.Property(name="confidence",   data_type=wvc.config.DataType.NUMBER),
                wvc.config.Property(name="article_id",   data_type=wvc.config.DataType.TEXT),
            ],
        )
        logger.info("Weaviate: created GeopoliticalArticle collection.")
        _schema_initialized = True

    except Exception as e:
        logger.error(f"Weaviate schema init failed: {e}")


def initialize_schema():
    """Public entry point — called from main.py seed command."""
    client = get_weaviate_client()
    if client:
        _ensure_schema(client)


def ingest_article(article: Article) -> bool:
    """Store article in Weaviate with Gemini embedding vector."""
    try:
        from gemini_client import embed_text

        client = get_weaviate_client()
        if client is None:
            return False

        text_to_embed = f"{article.title}\n\n{article.content[:2000]}"
        vector = embed_text(text_to_embed)

        collection = client.collections.get("GeopoliticalArticle")
        props = {
            "title":        article.title,
            "content":      article.content[:8000],
            "source":       article.source,
            "source_bias":  article.source_bias,
            "published_at": article.published_at.isoformat() + "Z",
            "region":       article.region or "",
            "actor_ids":    article.actor_ids,
            "confidence":   article.confidence,
            "article_id":   article.id,
        }
        if vector:
            collection.data.insert(props, vector=vector)
        else:
            collection.data.insert(props)
        return True

    except Exception as e:
        logger.error(f"Weaviate ingest failed: {e}")
        return False


def semantic_search(
    query: str,
    limit: int = 10,
    region_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Vector similarity search using Gemini query embedding.
    Since we use Vectorizer.none(), we must embed the query ourselves
    and use near_vector (not near_text).
    """
    try:
        import weaviate.classes as wvc
        from gemini_client import embed_query

        client = get_weaviate_client()
        if client is None:
            return []

        query_vector = embed_query(query)
        if not query_vector:
            logger.warning("Could not generate query embedding — falling back to keyword search")
            return hybrid_search(query, limit=limit)

        collection = client.collections.get("GeopoliticalArticle")

        filters = None
        if region_filter:
            filters = wvc.query.Filter.by_property("region").like(f"*{region_filter}*")

        results = collection.query.near_vector(
            near_vector=query_vector,
            limit=limit,
            filters=filters,
            return_metadata=wvc.query.MetadataQuery(distance=True),
        )

        passages = []
        for obj in results.objects:
            p = obj.properties
            passages.append({
                "title":        p.get("title", ""),
                "content":      p.get("content", "")[:1000],
                "source":       p.get("source", ""),
                "source_bias":  p.get("source_bias", "UNKNOWN"),
                "published_at": p.get("published_at", ""),
                "region":       p.get("region", ""),
                "article_id":   p.get("article_id", ""),
                "distance":     obj.metadata.distance if obj.metadata else None,
            })
        return passages

    except Exception as e:
        logger.error(f"Weaviate semantic search failed: {e}")
        return []


def hybrid_search(
    query: str,
    limit: int = 10,
    alpha: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Hybrid BM25 + vector search.
    Falls back to keyword-only if collection is empty or vector unavailable.
    """
    try:
        import weaviate.classes as wvc
        from gemini_client import embed_query

        client = get_weaviate_client()
        if client is None:
            return []

        collection = client.collections.get("GeopoliticalArticle")

        # Check if collection has any objects before searching
        count = collection.aggregate.over_all(total_count=True).total_count
        if count == 0:
            logger.info("Weaviate collection is empty — no articles ingested yet. Run: python main.py ingest")
            return []

        # For hybrid search with Vectorizer.none(), we need to supply the vector
        query_vector = embed_query(query)

        if query_vector:
            results = collection.query.hybrid(
                query=query,
                vector=query_vector,
                limit=limit,
                alpha=alpha,
                return_metadata=wvc.query.MetadataQuery(score=True),
            )
        else:
            # BM25-only fallback
            results = collection.query.bm25(
                query=query,
                limit=limit,
                return_metadata=wvc.query.MetadataQuery(score=True),
            )

        passages = []
        for obj in results.objects:
            p = obj.properties
            passages.append({
                "title":        p.get("title", ""),
                "content":      p.get("content", "")[:1000],
                "source":       p.get("source", ""),
                "source_bias":  p.get("source_bias", "UNKNOWN"),
                "published_at": p.get("published_at", ""),
                "score":        obj.metadata.score if obj.metadata else None,
            })
        return passages

    except Exception as e:
        logger.error(f"Weaviate hybrid search failed: {e}")
        return []
