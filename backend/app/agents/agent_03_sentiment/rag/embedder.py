"""
RAG Embedder — Generates vector embeddings for semantic indexing.

Primary:  sentence-transformers all-MiniLM-L6-v2 (384-dim, local, no API key).
Fallback: Lightweight TF-IDF / character n-gram based local embeddings.
"""

import hashlib
import math
import re
from collections import Counter
from typing import Dict, List, Optional


# ─── Embedding Model ───────────────────────────────────────────────────────────
ST_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384   # all-MiniLM-L6-v2 output dimension

_st_model = None   # lazy-loaded SentenceTransformer


def _get_st_model():
    global _st_model
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer(ST_EMBEDDING_MODEL)
        except ImportError:
            pass   # will use local fallback
    return _st_model


class Embedder:
    """Generates embeddings for text documents."""

    def __init__(self, groq_api_key: str = "", **_kwargs):
        # groq_api_key accepted for backward-compat but not used (embeddings are local)
        self._cache: Dict[str, List[float]] = {}
        self._use_st = True   # prefer sentence-transformers

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding vector for the given text.

        Tries sentence-transformers first; falls back to TF-IDF n-gram hashing.
        Results are cached by content hash.
        """
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self._cache:
            return self._cache[text_hash]

        if self._use_st:
            try:
                embedding = self._st_embed(text)
                self._cache[text_hash] = embedding
                return embedding
            except Exception as e:
                print(f"[Embedder] sentence-transformers failed: {e}. Falling back to local.")
                self._use_st = False

        embedding = self._local_embed(text)
        self._cache[text_hash] = embedding
        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts efficiently."""
        if self._use_st:
            try:
                model = _get_st_model()
                if model is not None:
                    vecs = model.encode(
                        [t[:8192] for t in texts],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return [v.tolist() for v in vecs]
            except Exception:
                self._use_st = False
        return [self.embed(t) for t in texts]

    def _st_embed(self, text: str) -> List[float]:
        """Generate embedding via sentence-transformers."""
        model = _get_st_model()
        if model is None:
            raise RuntimeError("sentence-transformers model not available")
        vec = model.encode(text[:8192], normalize_embeddings=True)
        return vec.tolist()

    def _local_embed(self, text: str, dim: int = 256) -> List[float]:
        """
        Lightweight local embedding using character n-gram hashing.
        Not as accurate as sentence-transformers but works fully offline.
        """
        text = text.lower().strip()
        tokens = re.findall(r"[a-z]+", text)

        trigrams: List[str] = []
        for token in tokens:
            for i in range(max(1, len(token) - 2)):
                trigrams.append(token[i:i + 3])

        vec = [0.0] * dim
        counter = Counter(trigrams)
        for gram, count in counter.items():
            bucket = int(hashlib.md5(gram.encode()).hexdigest(), 16) % dim
            vec[bucket] += count

        magnitude = math.sqrt(sum(x * x for x in vec))
        if magnitude > 0:
            vec = [x / magnitude for x in vec]
        return vec

    def clear_cache(self):
        """Clear the embedding cache."""
        self._cache.clear()
