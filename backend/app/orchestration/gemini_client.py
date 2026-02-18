from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeminiClientError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout_seconds: int = 20) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

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

        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise GeminiClientError(f"Gemini HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise GeminiClientError(f"Gemini URL error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise GeminiClientError("Gemini request timed out") from exc

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
