from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class OrchestratorSettings:
    google_api_key: str | None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = 20

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.google_api_key)


def load_settings() -> OrchestratorSettings:
    timeout_raw = os.getenv("GEMINI_TIMEOUT_SECONDS", "20")
    try:
        timeout = max(5, int(timeout_raw))
    except ValueError:
        timeout = 20

    return OrchestratorSettings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_timeout_seconds=timeout,
    )
