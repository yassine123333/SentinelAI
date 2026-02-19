"""
Gemini 2.5 Flash Client  —  google-genai SDK
=============================================
Install:  pip install -U google-genai

Changelog:
  v3 — fix _safe_text returning None on thinking models
       fix embedding model path (gemini-embedding-exp-03-07 fallback chain)
       fix classification returning None crash
  v4 — rotate across multiple API keys after each call
       Reads config.GEMINI_API_KEY (list of strings), e.g.:
         GEMINI_API_KEY = [KEY1, KEY2, KEY3, KEY4]
"""
from __future__ import annotations
import itertools
import json
import logging
import re
import time
from typing import Any
from time import sleep

import config

logger = logging.getLogger(__name__)

# ── Model names ───────────────────────────────────────────────────────────────
_CHAT_MODEL = config.REASONING_MODEL   # "gemini-2.5-flash"

# Embedding model — tried in order until one works
_EMBED_CANDIDATES = [
    "gemini-embedding-exp-03-07",
    "text-embedding-004",
    "embedding-001",
]
_EMBED_MODEL: str | None = None
_EMBED_DIM:   int        = 768


# ── API Key Rotation ──────────────────────────────────────────────────────────

def _load_api_keys() -> list[str]:
    """
    Load API keys from config.GEMINI_API_KEY.
    Supports both a list (preferred) and a plain string (fallback).
    Empty strings are filtered out automatically.
    """
    raw = getattr(config, "GEMINI_API_KEY", None)

    if isinstance(raw, (list, tuple)):
        keys = [k for k in raw if k and k.strip()]
        if keys:
            logger.info(f"API key rotation enabled: {len(keys)} key(s) loaded.")
            return keys

    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]

    raise RuntimeError(
        "No valid Gemini API key found in config.\n"
        "Make sure at least one of GEMINI_API_KEY1..4 is set in your .env file."
    )


_API_KEYS: list[str] = _load_api_keys()
_key_cycle = itertools.cycle(_API_KEYS)
_current_key: str = next(_key_cycle)

# One client instance per key, cached to avoid re-creation overhead
_clients: dict[str, Any] = {}


def _rotate_key() -> str:
    """Advance to the next API key and return it."""
    global _current_key
    _current_key = next(_key_cycle)
    logger.debug(f"Rotated to API key ending in ...{_current_key[-4:]}")
    return _current_key


def _get_client(api_key: str | None = None):
    """
    Return (and cache) a google-genai Client for the given API key.
    If api_key is None, uses the current key.
    """
    key = api_key or _current_key
    if key not in _clients:
        try:
            from google import genai
            _clients[key] = genai.Client(api_key=key)
        except ImportError:
            raise ImportError(
                "google-genai not installed.\n"
                "Run:  pip install -U google-genai"
            )
    return _clients[key]


# ── Embedding model resolution ────────────────────────────────────────────────

def _resolve_embed_model() -> str:
    global _EMBED_MODEL, _EMBED_DIM
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL

    client = _get_client()

    def _try_model(name: str) -> bool:
        global _EMBED_MODEL, _EMBED_DIM
        try:
            result = client.models.embed_content(model=name, contents="test")
            if result.embeddings and result.embeddings[0].values:
                _EMBED_MODEL = name
                _EMBED_DIM   = len(result.embeddings[0].values)
                logger.info(f"Embedding model: {name!r}  dim={_EMBED_DIM}")
                return True
        except Exception:
            logger.debug(f"Embedding model {name!r} not available")
        return False

    for candidate in _EMBED_CANDIDATES:
        if _try_model(candidate):
            return _EMBED_MODEL

    try:
        for m in client.models.list():
            if "embed" in m.name.lower():
                if _try_model(m.name):
                    return _EMBED_MODEL
    except Exception:
        pass

    raise RuntimeError(
        "No working Gemini embedding model found.\n"
        f"Tried: {_EMBED_CANDIDATES}\n"
        "Run:  python scripts/list_gemini_models.py"
    )


# ── Safe text extractor ───────────────────────────────────────────────────────

def _safe_text(response) -> str:
    """
    Extract text from a Gemini response object.
    Always returns a str, never None.
    """
    try:
        text = response.text
        if text is not None:
            return str(text)
    except Exception:
        pass

    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            raise ValueError("Gemini returned no candidates (possible safety block or quota exceeded).")

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        fr_name = getattr(finish_reason, "name", str(finish_reason)).upper()

        if fr_name == "SAFETY":
            raise ValueError(
                "Gemini safety filter blocked this request. "
                "Try rephrasing without specific weapons/violence terms."
            )

        content_obj = getattr(candidate, "content", None)
        parts = getattr(content_obj, "parts", []) if content_obj else []
        if parts:
            text = "".join(getattr(p, "text", "") or "" for p in parts)
            if text.strip():
                return text

        if fr_name == "MAX_TOKENS":
            raise ValueError(
                "Gemini hit MAX_TOKENS with no recoverable text. "
                "Increase max_tokens parameter."
            )

        raise ValueError(
            f"Gemini returned empty response "
            f"(finish_reason={fr_name}, parts={len(parts)})."
        )

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not extract text from Gemini response: {e}") from e


# ── Core LLM call ─────────────────────────────────────────────────────────────

def call_gemini(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    json_mode: bool = False,
    retries: int = 10,
) -> str:
    """
    Call Gemini and return the response text.
    - Rotates to the next API key after every successful call.
    - On rate-limit (429), rotates immediately and retries with the next key.
    - Never returns None — raises on unrecoverable errors.
    """
    from google.genai import types

    model_name = model or _CHAT_MODEL

    cfg_kwargs: dict[str, Any] = {
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        cfg_kwargs["response_mime_type"] = "application/json"

    last_error: Exception | None = None

    for attempt in range(retries):
        current_key = _current_key
        client = _get_client(current_key)

        gen_config = types.GenerateContentConfig(
            **cfg_kwargs,
            system_instruction=system if system else None,
        )

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=gen_config,
            )
            result = _safe_text(response)

            # Rotate key for the next caller
            _rotate_key()
            return result

        except ValueError:
            raise   # safety block / unrecoverable — don't retry

        except Exception as e:
            last_error = e
            err_str = str(e)

            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                # Rotate immediately on rate limit and retry with fresh key
                new_key = _rotate_key()
                sleep(30)
                logger.warning(
                    f"Rate limit on key ...{current_key[-4:]} "
                    f"(attempt {attempt+1}/{retries}). "
                    f"Rotating to key ...{new_key[-4:]}..."
                )
                # If we've cycled through every key once, back off
                if attempt > 0 and attempt % len(_API_KEYS) == 0:
                    wait = 30
                    logger.warning(f"All keys rate-limited. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    time.sleep(1)
            else:
                wait = 2 ** attempt
                logger.warning(
                    f"Gemini call attempt {attempt+1}/{retries} failed: {e}"
                    + (f" — retrying in {wait}s" if attempt < retries - 1 else "")
                )
                _rotate_key()   # rotate on any error
                if attempt < retries - 1:
                    time.sleep(wait)

    raise RuntimeError(f"Gemini call failed after {retries} attempts: {last_error}")


def call_gemini_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 2048,
) -> Any:
    """Call Gemini and return parsed JSON (dict or list)."""
    raw = call_gemini(
        prompt=prompt,
        system=system,
        model=model or _CHAT_MODEL,
        max_tokens=max_tokens,
        temperature=0.1,
        json_mode=True,
    )
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed. Raw response:\n{raw[:500]}")
        raise ValueError(f"Gemini returned invalid JSON: {e}") from e


# ── Classification ────────────────────────────────────────────────────────────

def classify_query(query: str) -> str:
    """
    Classify query → proxy | genealogy | pattern | leverage | intent | general
    Falls back to keyword matching if LLM returns None or fails.
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
        logger.debug(f"classify_query: no valid category in {raw!r}, using keyword fallback")
        return _keyword_classify(query)
    except Exception as e:
        logger.warning(f"Gemini classification failed, using keyword fallback: {e}")
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
        f'  "confidence" : float 0.0–1.0\n'
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
    except Exception as e:
        logger.warning(f"Relation extraction failed: {e}")
        return []


# ── Intelligence Report ───────────────────────────────────────────────────────

def generate_report(system_prompt: str, context: str) -> str:
    return call_gemini(
        prompt=context,
        system=system_prompt,
        model=_CHAT_MODEL,
        max_tokens=4096,
        temperature=0.3,
    )


def extract_relations_from_report(report_text: str) -> list[dict]:
    return extract_relations(report_text, [])


# ── Embeddings ────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Generate a dense embedding using the best available Gemini embedding model."""
    from google.genai import types
    client = _get_client()
    model = _resolve_embed_model()
    try:
        result = client.models.embed_content(
            model=model,
            contents=text[:8192],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        if result.embeddings:
            return list(result.embeddings[0].values)
        return []
    except Exception as e:
        logger.error(f"embed_text failed (model={model}): {e}")
        return []


def embed_query(query: str) -> list[float]:
    """Generate a query embedding (RETRIEVAL_QUERY task for better recall)."""
    from google.genai import types
    client = _get_client()
    model = _resolve_embed_model()
    try:
        result = client.models.embed_content(
            model=model,
            contents=query[:2048],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        if result.embeddings:
            return list(result.embeddings[0].values)
        return []
    except Exception as e:
        logger.error(f"embed_query failed (model={model}): {e}")
        return []


def embed_batch(texts: list[str], batch_size: int = 20) -> list[list[float]]:
    """Embed a list of texts with rate-limit-friendly batching."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        for text in texts[i: i + batch_size]:
            all_embeddings.append(embed_text(text))
            time.sleep(0.05)
        if i + batch_size < len(texts):
            time.sleep(0.5)
    return all_embeddings


# ── Utilities ─────────────────────────────────────────────────────────────────

def test_connection() -> bool:
    try:
        reply = call_gemini("Reply with exactly: OK", max_tokens=20)
        logger.info(f"Gemini OK: {reply!r}")
        return True
    except Exception as e:
        logger.error(f"Gemini test failed: {e}")
        return False


def list_available_models() -> list[str]:
    """List all models available to your API key."""
    try:
        return [m.name for m in _get_client().models.list()]
    except Exception as e:
        logger.error(f"list_available_models failed: {e}")
        return []


def current_key_info() -> str:
    """Return a safe representation of the active key (last 4 chars only)."""
    return f"...{_current_key[-4:]}"