from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeminiClientError(RuntimeError):
    pass


class GeminiClient:
    RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout_seconds: int = 20,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def generate_text(self, prompt: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        raw: str | None = None
        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    break
            except HTTPError as exc:
                error_details = self._extract_http_error_details(exc)
                last_error = f"Gemini HTTP error: {exc.code}{error_details}"
                if exc.code in self.RETRYABLE_HTTP_CODES and attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise GeminiClientError(last_error) from exc
            except URLError as exc:
                last_error = f"Gemini URL error: {exc.reason}"
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise GeminiClientError(last_error) from exc
            except TimeoutError as exc:
                last_error = "Gemini request timed out"
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise GeminiClientError(last_error) from exc

        if raw is None:
            raise GeminiClientError(last_error or "Gemini request failed without response")

        try:
            parsed = json.loads(raw)
            candidates = parsed.get("candidates", [])
            if not candidates:
                raise GeminiClientError("Gemini response had no candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts).strip()
            if not text:
                raise GeminiClientError("Gemini returned empty text")
            return text
        except json.JSONDecodeError as exc:
            raise GeminiClientError("Could not parse Gemini JSON response") from exc

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.retry_backoff_seconds * (2**attempt)
        time.sleep(delay)

    @staticmethod
    def _extract_http_error_details(exc: HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8")
            parsed = json.loads(body)
            message = parsed.get("error", {}).get("message")
            if message:
                return f" ({message})"
        except Exception:
            pass
        return ""

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

        raise GeminiClientError("Gemini output did not contain valid JSON object")
