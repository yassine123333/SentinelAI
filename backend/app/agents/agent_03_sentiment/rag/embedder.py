"""
RAG Embedder — Generates vector embeddings for semantic indexing.

Primary: Gemini embedding API (text-embedding-004).
Fallback: Lightweight TF-IDF based local embeddings.
"""

import hashlib
import math
import re
from collections import Counter
from typing import Dict, List, Optional

from google import genai


# ─── Gemini Embedding Model ────────────────────────────────────────
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 3072  # gemini-embedding-001 output dimension


class Embedder:
    """Generates embeddings for text documents."""

    def __init__(self, gemini_api_key: str):
        self.client = genai.Client(api_key=gemini_api_key)
        self._cache: Dict[str, List[float]] = {}
        self._use_gemini = True

    def embed(self, text: str) -> List[float]:
        """
        Generate an embedding vector for the given text.

        Uses Gemini API with automatic fallback to TF-IDF.
        Results are cached by content hash.
        """
        # Check cache
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self._cache:
            return self._cache[text_hash]

        # Try Gemini embeddings
        if self._use_gemini:
            try:
                embedding = self._gemini_embed(text)
                self._cache[text_hash] = embedding
                return embedding
            except Exception as e:
                print(f"[Embedder] Gemini embedding failed: {e}. Falling back to local.")
                self._use_gemini = False

        # Fallback: local TF-IDF-like embedding
        embedding = self._local_embed(text)
        self._cache[text_hash] = embedding
        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        results = []
        for text in texts:
            results.append(self.embed(text))
        return results

    def _gemini_embed(self, text: str) -> List[float]:
        """Generate embedding via Gemini API."""
        # Truncate to API limits (max ~2048 tokens)
        truncated = text[:8000]

        result = self.client.models.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            contents=truncated,
        )
        # The API returns an EmbedContentResponse
        return list(result.embeddings[0].values)

    def _local_embed(self, text: str, dim: int = 256) -> List[float]:
        """
        Generate a lightweight local embedding using character n-gram
        hashing. Not as good as Gemini but works offline as a fallback.
        """
        text = text.lower().strip()
        tokens = re.findall(r"[a-z]+", text)

        # Character trigram counting
        trigrams: List[str] = []
        for token in tokens:
            for i in range(max(1, len(token) - 2)):
                trigrams.append(token[i:i + 3])

        # Hash each trigram to a bucket
        vec = [0.0] * dim
        counter = Counter(trigrams)
        for gram, count in counter.items():
            bucket = int(hashlib.md5(gram.encode()).hexdigest(), 16) % dim
            vec[bucket] += count

        # L2 normalize
        magnitude = math.sqrt(sum(x * x for x in vec))
        if magnitude > 0:
            vec = [x / magnitude for x in vec]
        return vec

    def clear_cache(self):
        """Clear the embedding cache."""
        self._cache.clear()
