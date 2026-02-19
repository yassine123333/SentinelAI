"""
Local LLM client — Ollama async wrapper.

Replaces the Gemini API key manager with a zero-config local model.
Model is set via OLLAMA_MODEL env var (default: llama3.1:8b-instruct-q4_K_M).

All agents that previously called generate_with_key_rotation() continue to
work unchanged — the same interface is preserved.
Agents using types.GenerateContentConfig should import OllamaConfig instead.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ── Response wrapper ───────────────────────────────────────────────────────────

class _LLMResponse:
    """Thin wrapper so callers can use `response.text` unchanged."""

    def __init__(self, text: str) -> None:
        self.text = text


# ── Config shim (replaces google.genai.types.GenerateContentConfig) ────────────

class OllamaConfig:
    """
    Drop-in replacement for types.GenerateContentConfig.
    Agents import this instead of google.genai.types and pass it to
    generate_with_key_rotation() exactly as before.
    """

    def __init__(
        self,
        system_instruction: str = "",
        response_mime_type: str = "",
        temperature: float = 0.1,
        top_p: float = 0.95,
        max_output_tokens: int = 2048,
        **_kwargs: Any,          # absorb unknown Gemini-specific fields silently
    ) -> None:
        self.system_instruction = system_instruction
        self.response_mime_type = response_mime_type
        self.temperature = temperature
        self.top_p = top_p
        self.max_output_tokens = max_output_tokens


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
    Call the local Ollama model and return a response with a .text attribute.

    Args:
        prompt:      User-turn message.
        system:      System-turn message (empty = no system prompt).
        temperature: Sampling temperature (0.0 = greedy).
        top_p:       Nucleus sampling parameter.
        max_tokens:  Maximum tokens to generate.
        json_mode:   If True, Ollama is instructed to return valid JSON.

    Returns:
        _LLMResponse with .text set to the model output.

    Raises:
        Exception on connection or model errors.
    """
    import ollama as _ollama  # lazy import — avoids startup cost if unused

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    client = _ollama.AsyncClient(host=OLLAMA_BASE_URL)
    response = await client.chat(
        model=OLLAMA_MODEL,
        messages=messages,
        format="json" if json_mode else "",
        options={
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": max_tokens,
        },
    )
    return _LLMResponse(response.message.content)


# ── Backwards-compat wrapper ───────────────────────────────────────────────────

async def generate_with_key_rotation(
    model: str,
    contents: Any,
    config: Any,
    max_attempts: int | None = None,
) -> _LLMResponse:
    """
    Backwards-compatible shim preserving the Gemini call signature.
    Extracts system_instruction and generation params via getattr so it works
    with both OllamaConfig and any legacy config object.
    The `model` and `max_attempts` parameters are ignored.
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
    """Always returns True — local Ollama requires no API key."""
    return True
