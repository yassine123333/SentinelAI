"""Configuration for the Market Sentiment Intelligence Agent."""

import os

# ─── API Keys ───────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── Defaults ───────────────────────────────────────────────
DEFAULT_TIME_WINDOW_DAYS = 2

# ─── Sentiment Weights ──────────────────────────────────────
WEIGHT_REDDIT = 0.50
WEIGHT_GDELT = 0.50

# ─── GDELT ──────────────────────────────────────────────────
GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# ─── Reddit ─────────────────────────────────────────────────
REDDIT_MAX_RESULTS = 25                    # Max posts per subreddit search

# ─── Regime Awareness (Expert Level) ────────────────────────
ENABLE_REGIME_AWARENESS = True
VIX_CRISIS_THRESHOLD = 25.0  # VIX above this → crisis regime

# ─── RAG Configuration ─────────────────────────────────────
RAG_TTL_SECONDS = 2 * 24 * 60 * 60       # 2 days max data retention
RAG_MIN_SIMILARITY = 0.3                  # Min cosine sim for retrieval
RAG_TOP_K = 10                            # Max documents per search
RAG_MAX_POSTS_STORED = 50                 # Max Reddit posts stored per run
RAG_EMBEDDING_MODEL = "gemini-embedding-001"
