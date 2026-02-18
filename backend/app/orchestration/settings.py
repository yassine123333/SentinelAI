from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class OrchestratorSettings:
    google_api_key: str | None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = 20
    gemini_max_retries: int = 2
    gemini_retry_backoff_seconds: float = 1.0

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.google_api_key)


def load_settings() -> OrchestratorSettings:
    timeout_raw = os.getenv("GEMINI_TIMEOUT_SECONDS", "20")
    try:
        timeout = max(5, int(timeout_raw))
    except ValueError:
        timeout = 20

    retries_raw = os.getenv("GEMINI_MAX_RETRIES", "2")
    try:
        retries = max(0, min(5, int(retries_raw)))
    except ValueError:
        retries = 2

    backoff_raw = os.getenv("GEMINI_RETRY_BACKOFF_SECONDS", "1.0")
    try:
        backoff = max(0.1, min(10.0, float(backoff_raw)))
    except ValueError:
        backoff = 1.0

    return OrchestratorSettings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_timeout_seconds=timeout,
        gemini_max_retries=retries,
        gemini_retry_backoff_seconds=backoff,
    )
