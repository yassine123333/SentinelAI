"""
Groq LLM Client + Sentence-Transformer Embeddings for Agent 02 (GeoKG-RAG)
===========================================================================

Replaces the previous google-genai / Gemini client.
- LLM calls  →  groq.Groq (sync, llama-3.1-8b-instant)
- Embeddings →  sentence-transformers all-MiniLM-L6-v2 (384 dims, local, no API)

All public function signatures are kept identical so geokg_agent.py,
weaviate_client.py, and extraction/pipeline.py need zero changes.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import config

logger = logging.getLogger(__name__)

# ── Groq model ────────────────────────────────────────────────────────────────
_GROQ_MODEL = getattr(config, "GROQ_MODEL", "llama-3.1-8b-instant")
_GROQ_KEY   = getattr(config, "GROQ_API_KEY", "")

# ── Embedding model (lazy-loaded) ─────────────────────────────────────────────
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBED_DIM        = 384
_st_model         = None   # SentenceTransformer instance, loaded on first use


def _get_st_model():
    """Lazy-load sentence-transformers model (downloads once, then cached)."""
    global _st_model
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading sentence-transformer model: {_EMBED_MODEL_NAME}")
            _st_model = SentenceTransformer(_EMBED_MODEL_NAME)
            logger.info("Sentence-transformer model loaded.")
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed.\n"
                "Run: pip install sentence-transformers"
            )
    return _st_model


# ── Groq client (lazy, singleton) ─────────────────────────────────────────────
_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq
            if not _GROQ_KEY:
                raise RuntimeError(
                    "GROQ_API_KEY not set.\n"
                    "Add GROQ_API_KEY=gsk_... to backend/.env"
                )
            _groq_client = Groq(api_key=_GROQ_KEY)
        except ImportError:
            raise ImportError(
                "groq not installed.\n"
                "Run: pip install groq"
            )
    return _groq_client


# ── Core LLM call ─────────────────────────────────────────────────────────────

def call_gemini(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    json_mode: bool = False,
    retries: int = 4,
) -> str:
    """
    Call Groq LLM and return the response text.
    Signature unchanged from the original Gemini version.
    """
    client = _get_groq_client()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model":       model or _GROQ_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            last_error = exc
            err_str = str(exc)
            wait = 2 ** attempt
            if "429" in err_str or "rate" in err_str.lower():
                wait = max(wait, 10)
            logger.warning(
                f"Groq call attempt {attempt + 1}/{retries} failed: {exc}"
                + (f" — retrying in {wait}s" if attempt < retries - 1 else "")
            )
            if attempt < retries - 1:
                time.sleep(wait)

    raise RuntimeError(f"Groq call failed after {retries} attempts: {last_error}")


def call_gemini_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2048,
) -> Any:
    """Call Groq and return parsed JSON (dict or list). Signature unchanged."""
    raw = call_gemini(
        prompt=prompt,
        system=system,
        model=model or _GROQ_MODEL,
        max_tokens=max_tokens,
        temperature=0.1,
        json_mode=True,
    )
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed. Raw response:\n{raw[:500]}")
        raise ValueError(f"Groq returned invalid JSON: {e}") from e


# ── Classification ────────────────────────────────────────────────────────────

def classify_query(query: str) -> str:
    """
    Classify query → proxy | genealogy | pattern | leverage | intent | general
    Falls back to keyword matching on LLM failure.
    """
    valid = {"proxy", "genealogy", "pattern", "leverage", "intent", "general"}
    prompt = (
        "Classify this geopolitical intelligence query into exactly ONE of these six categories:\n"
        "proxy | genealogy | pattern | leverage | intent | general\n\n"
        "proxy     = who funds/controls/sponsors a group\n"
        "genealogy = causal history, origins, root causes\n"
        "pattern   = escalation detection, early warning, thresholds\n"
        "leverage  = dependencies, pressure, sanctions, chokepoints\n"
        "intent    = narrative gaps, what actors are NOT saying\n"
        "general   = anything else\n\n"
        f"Query: {query}\n\n"
        "Respond with ONE word only — the category name."
    )
    try:
        raw = call_gemini(prompt, max_tokens=50, temperature=0.0)
        if raw:
            for word in re.sub(r"[^a-z|]", " ", raw.lower()).split():
                if word in valid:
                    return word
        return _keyword_classify(query)
    except Exception as exc:
        logger.warning(f"Groq classification failed, using keyword fallback: {exc}")
        return _keyword_classify(query)


def _keyword_classify(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ["fund", "proxy", "behind", "patron", "sponsor", "who pays", "financed"]):
        return "proxy"
    if any(w in q for w in ["history", "cause", "origin", "genealogy", "root", "why did", "started"]):
        return "genealogy"
    if any(w in q for w in ["pattern", "escalat", "threshold", "approaching", "warning", "about to", "imminent"]):
        return "pattern"
    if any(w in q for w in ["leverage", "depend", "pressure", "sanction", "energy", "chokepoint"]):
        return "leverage"
    if any(w in q for w in ["narrative", "saying", "signal", "message", "intent", "not say", "silence"]):
        return "intent"
    return "general"


# ── Relation Extraction ───────────────────────────────────────────────────────

def extract_relations(text: str, entity_names: list[str]) -> list[dict]:
    """Extract geopolitical relation triples from text. Returns list of dicts."""
    relation_types = config.RELATION_TYPES[:10]
    entity_str = ", ".join(entity_names[:15]) if entity_names else "auto-detect from text"
    prompt = (
        f"Extract geopolitical relations from the text below.\n"
        f"Known entities: {entity_str}\n\n"
        f"Text:\n{text[:2500]}\n\n"
        f"Return a JSON array. Each element must have these exact keys:\n"
        f'  "subject"    : actor name\n'
        f'  "relation"   : one of {relation_types}\n'
        f'  "object"     : actor name\n'
        f'  "confidence" : float 0.0-1.0\n'
        f'  "evidence"   : brief quote from the text\n\n'
        f"Return ONLY the JSON array — no markdown, no explanation."
    )
    try:
        result = call_gemini_json(prompt, max_tokens=1024)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "relations" in result:
            return result["relations"]
        return []
    except Exception as exc:
        logger.warning(f"Relation extraction failed: {exc}")
        return []


# ── Intelligence Report ───────────────────────────────────────────────────────

def generate_report(system_prompt: str, context: str) -> str:
    return call_gemini(
        prompt=context,
        system=system_prompt,
        model=_GROQ_MODEL,
        max_tokens=4096,
        temperature=0.3,
    )


def extract_relations_from_report(report_text: str) -> list[dict]:
    return extract_relations(report_text, [])


# ── Embeddings (sentence-transformers) ────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Generate a dense embedding using sentence-transformers (384-dim)."""
    try:
        model = _get_st_model()
        vec = model.encode(text[:8192], normalize_embeddings=True)
        return vec.tolist()
    except Exception as exc:
        logger.error(f"embed_text failed: {exc}")
        return []


def embed_query(query: str) -> list[float]:
    """Generate a query embedding (same model — symmetric retrieval)."""
    return embed_text(query[:2048])


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed a list of texts efficiently using batched inference."""
    try:
        model = _get_st_model()
        vecs = model.encode(
            [t[:8192] for t in texts],
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vecs]
    except Exception as exc:
        logger.error(f"embed_batch failed: {exc}")
        # Fallback: embed one by one
        return [embed_text(t) for t in texts]


# ── Utilities ─────────────────────────────────────────────────────────────────

def test_connection() -> bool:
    try:
        reply = call_gemini("Reply with exactly: OK", max_tokens=20)
        logger.info(f"Groq OK: {reply!r}")
        return True
    except Exception as exc:
        logger.error(f"Groq test failed: {exc}")
        return False


def current_key_info() -> str:
    """Return a safe representation of the active key (last 4 chars only)."""
    return f"...{_GROQ_KEY[-4:]}" if _GROQ_KEY else "NOT SET"
