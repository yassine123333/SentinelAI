"""
Groq LLM Client — orchestration layer wrapper.

Replaces the previous raw HTTP Gemini REST client.
Keeps the GeminiClient / GeminiClientError class names so orchestrator.py
needs no changes.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any


class GeminiClientError(RuntimeError):
    pass


class GeminiClient:
    """Groq-backed LLM client with the same public interface as the old Gemini one."""

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout_seconds: int = 20,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._client = None   # lazy Groq client

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
            except ImportError:
                raise GeminiClientError(
                    "groq package not installed. Run: pip install groq"
                )
        return self._client

    def generate_text(self, prompt: str) -> str:
        """Generate text using Groq. Raises GeminiClientError on failure."""
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            try:
                client = self._get_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=1024,
                )
                text = resp.choices[0].message.content
                if not text or not text.strip():
                    raise GeminiClientError("Groq returned empty text")
                return text.strip()

            except GeminiClientError:
                raise
            except Exception as exc:
                last_error = str(exc)
                err_str = last_error.lower()
                is_rate_limit = "429" in last_error or "rate" in err_str
                is_retryable  = is_rate_limit or any(
                    str(code) in last_error for code in self.RETRYABLE_STATUS
                )
                if is_retryable and attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise GeminiClientError(f"Groq error: {exc}") from exc

        raise GeminiClientError(last_error or "Groq request failed without response")

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.retry_backoff_seconds * (2 ** attempt)
        time.sleep(delay)

    def generate_json(self, prompt: str) -> dict[str, Any]:
        text = self.generate_text(prompt)
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        else:
            generic = re.search(r"(\{.*\})", text, re.DOTALL)
            candidate = generic.group(1) if generic else text

        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        raise GeminiClientError("Groq output did not contain valid JSON object")
