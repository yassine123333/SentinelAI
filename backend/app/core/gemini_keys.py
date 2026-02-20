"""
Groq API client — async wrapper with smart key rotation.

Reads a pool of API keys from the environment:
  GROQ_API_KEY     – primary key (required)
  GROQ_API_KEY_2   – second key  (optional)
  GROQ_API_KEY_3   – third key   (optional)
  GROQ_MODEL       – model to use (default: llama-3.1-8b-instant)

Rotation strategy
-----------------
Keys are tried in round-robin order.  When a key returns a 429 (rate-limit)
error the rotation logic:
  1. Marks the key as cooling down for `cooldown_seconds` (default 60 s,
     extended to the Retry-After header value when present).
  2. Immediately retries the request with the next available key.
  3. If ALL keys are currently cooling down, waits for the soonest
     cooldown to expire before retrying (never gives up within a single
     request).

OllamaConfig is kept as-is so existing agent call sites need no changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Build the key pool from individual env vars (preserves .env clarity).
def _load_key_pool() -> list[str]:
    pool: list[str] = []
    for var in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        key = os.getenv(var, "").strip()
        if key and key not in pool:
            pool.append(key)
    return pool

_KEY_POOL: list[str] = _load_key_pool()

# Kept for backwards-compat (first key, or empty string)
GROQ_API_KEY: str = _KEY_POOL[0] if _KEY_POOL else ""

# Default cooldown when no Retry-After header is returned (seconds)
_DEFAULT_COOLDOWN = 65.0


# ── Response wrapper ───────────────────────────────────────────────────────────

class _LLMResponse:
    """Thin wrapper so callers can use `response.text` unchanged."""

    def __init__(self, text: str) -> None:
        self.text = text


# ── Config shim (replaces google.genai.types.GenerateContentConfig) ────────────

class OllamaConfig:
    """
    Drop-in config object.  Agents pass this to generate_with_key_rotation()
    exactly as before; the Groq client extracts fields via getattr.
    """

    def __init__(
        self,
        system_instruction: str = "",
        response_mime_type: str = "",
        temperature: float = 0.1,
        top_p: float = 0.95,
        max_output_tokens: int = 2048,
        **_kwargs: Any,
    ) -> None:
        self.system_instruction = system_instruction
        self.response_mime_type = response_mime_type
        self.temperature = temperature
        self.top_p = top_p
        self.max_output_tokens = max_output_tokens


# ── Key-pool rotation state ────────────────────────────────────────────────────

class _KeyPool:
    """
    Thread-safe round-robin key pool with per-key cooldown tracking.

    Each key carries a `cooldown_until` timestamp (monotonic).  When a key
    is rate-limited the caller records the cooldown via `mark_rate_limited()`.
    `next_available()` skips cooling keys and returns the best one to use.
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys: list[str] = list(keys)
        # cooldown_until[i] = monotonic time after which key i is usable again
        self._cooldown_until: list[float] = [0.0] * len(keys)
        self._index: int = 0                 # round-robin cursor
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._keys)

    async def next_available(self) -> tuple[int, str]:
        """
        Return (index, api_key) for the next key that is not cooling down.
        If all keys are cooling, waits for the soonest expiry.
        Never raises.
        """
        async with self._lock:
            now = time.monotonic()

            # Fast path: current round-robin key is available
            idx = self._index % self.size
            if self._cooldown_until[idx] <= now:
                self._index = (idx + 1) % self.size
                return idx, self._keys[idx]

            # Look for any available key
            for offset in range(self.size):
                candidate = (idx + offset) % self.size
                if self._cooldown_until[candidate] <= now:
                    self._index = (candidate + 1) % self.size
                    return candidate, self._keys[candidate]

            # All keys cooling — wait for soonest expiry
            soonest = min(self._cooldown_until)
            wait_for = max(0.0, soonest - now)
            logger.warning(
                "groq_key_pool: all %d keys rate-limited — waiting %.1f s",
                self.size, wait_for,
            )

        # Release lock while sleeping so other coroutines can proceed
        await asyncio.sleep(wait_for + 0.5)

        async with self._lock:
            now = time.monotonic()
            # After sleeping, pick whichever key came back first
            best = min(range(self.size), key=lambda i: self._cooldown_until[i])
            self._index = (best + 1) % self.size
            return best, self._keys[best]

    async def mark_rate_limited(self, idx: int, retry_after: float | None) -> None:
        """Record that key `idx` is rate-limited for `retry_after` seconds."""
        cooldown = retry_after if (retry_after and retry_after > 0) else _DEFAULT_COOLDOWN
        async with self._lock:
            self._cooldown_until[idx] = time.monotonic() + cooldown
        logger.warning(
            "groq_key_pool: key[%d] rate-limited — cooling for %.0f s",
            idx, cooldown,
        )


# Module-level singleton — initialised once at import time
_pool: _KeyPool | None = None


def _get_pool() -> _KeyPool:
    global _pool
    if _pool is None:
        _pool = _KeyPool(_KEY_POOL)
    return _pool


# ── Core async generator ───────────────────────────────────────────────────────

async def generate_content(
    prompt: str,
    system: str = "",
    temperature: float = 0.1,
    top_p: float = 0.95,
    max_tokens: int = 2048,
    json_mode: bool = True,
) -> _LLMResponse:
    """
    Call the Groq API with automatic key rotation on 429 errors.

    Rotates through all keys in the pool before giving up.  Logs a warning
    each time a key is rate-limited so quota usage can be monitored.

    Args:
        prompt:      User-turn message.
        system:      System-turn message (empty = no system prompt).
        temperature: Sampling temperature (0.0 = greedy).
        top_p:       Nucleus sampling parameter.
        max_tokens:  Maximum tokens to generate.
        json_mode:   If True, instructs the model to return valid JSON.

    Returns:
        _LLMResponse with .text set to the model output.

    Raises:
        Exception when all keys are exhausted without a successful response.
    """
    from groq import AsyncGroq, RateLimitError  # lazy import

    pool = _get_pool()

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Try every key at least once; if all are cooling we loop after waiting.
    attempts = 0
    max_attempts = pool.size * 2  # allow one full rotation + one retry cycle

    last_exc: Exception | None = None

    while attempts < max_attempts:
        attempts += 1
        key_idx, api_key = await pool.next_available()

        try:
            # max_retries=0: disable the Groq SDK's own retry-with-wait so
            # our pool rotates to the next key immediately on 429.
            client = AsyncGroq(api_key=api_key, max_retries=0)
            response = await client.chat.completions.create(**kwargs)
            # Success — log which key slot was used (index only, never the key)
            logger.debug("groq_key_pool: key[%d] → success (attempt %d)", key_idx, attempts)
            return _LLMResponse(response.choices[0].message.content)

        except RateLimitError as exc:
            last_exc = exc
            # Try to extract Retry-After from the response headers
            retry_after: float | None = None
            try:
                ra = exc.response.headers.get("retry-after") or exc.response.headers.get("Retry-After")
                if ra:
                    retry_after = float(ra)
            except Exception:
                pass
            await pool.mark_rate_limited(key_idx, retry_after)
            # Immediately try the next key (next loop iteration)
            continue

        except Exception as exc:
            # Non-rate-limit error (network, auth, etc.) — propagate immediately
            raise

    # Exhausted all attempts
    raise RuntimeError(
        f"groq_key_pool: all {pool.size} key(s) exhausted after {attempts} attempts. "
        f"Last error: {last_exc}"
    ) from last_exc


# ── Backwards-compat wrapper ───────────────────────────────────────────────────

async def generate_with_key_rotation(
    model: str,
    contents: Any,
    config: Any,
    max_attempts: int | None = None,
) -> _LLMResponse:
    """
    Backwards-compatible shim preserving the original call signature.
    Extracts generation params via getattr from any config object.
    `model` and `max_attempts` are ignored — GROQ_MODEL + pool rotation used.
    """
    system: str = str(getattr(config, "system_instruction", "") or "")
    temperature: float = float(getattr(config, "temperature", 0.1) or 0.1)
    top_p: float = float(getattr(config, "top_p", 0.95) or 0.95)
    max_tokens: int = int(getattr(config, "max_output_tokens", 2048) or 2048)
    mime: str = str(getattr(config, "response_mime_type", "") or "")
    json_mode: bool = "json" in mime.lower()

    prompt = str(contents) if not isinstance(contents, str) else contents
    return await generate_content(
        prompt=prompt,
        system=system,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


# ── Key check (kept for backwards compat) ─────────────────────────────────────

def has_gemini_keys() -> bool:
    """Returns True when at least one GROQ_API_KEY is configured."""
    return bool(_KEY_POOL)
