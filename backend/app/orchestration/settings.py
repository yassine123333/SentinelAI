from __future__ import annotations

import os
from dataclasses import dataclass

from app.security import VaultConfig, VaultSecretManager


_VAULT_MANAGER: VaultSecretManager | None = None


@dataclass
class OrchestratorSettings:
    google_api_key: str | None      # holds Groq key; name kept for compat
    secret_source: str = "missing"
    gemini_model: str = "llama-3.1-8b-instant"
    gemini_timeout_seconds: int = 20
    gemini_max_retries: int = 2
    gemini_retry_backoff_seconds: float = 1.0

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.google_api_key)


def _get_vault_manager_from_env() -> VaultSecretManager:
    global _VAULT_MANAGER
    config = VaultConfig.from_env()
    if _VAULT_MANAGER is None or _VAULT_MANAGER.config != config:
        _VAULT_MANAGER = VaultSecretManager(config=config)
    return _VAULT_MANAGER


def _resolve_groq_key() -> tuple[str | None, str]:
    """Resolve Groq API key from vault → env (multiple var names)."""
    try:
        vault_manager = _get_vault_manager_from_env()
        key_from_vault = vault_manager.get_gemini_api_key()
        if key_from_vault:
            return key_from_vault, "vault"
    except Exception:
        pass

    key = (
        os.getenv("GROQ_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )
    if key:
        return key, "env"

    return None, "missing"


def load_settings() -> OrchestratorSettings:
    timeout_raw = os.getenv("GROQ_TIMEOUT_SECONDS", os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))
    try:
        timeout = max(5, int(timeout_raw))
    except ValueError:
        timeout = 20

    retries_raw = os.getenv("GROQ_MAX_RETRIES", os.getenv("GEMINI_MAX_RETRIES", "2"))
    try:
        retries = max(0, min(5, int(retries_raw)))
    except ValueError:
        retries = 2

    backoff_raw = os.getenv("GROQ_RETRY_BACKOFF_SECONDS", os.getenv("GEMINI_RETRY_BACKOFF_SECONDS", "1.0"))
    try:
        backoff = max(0.1, min(10.0, float(backoff_raw)))
    except ValueError:
        backoff = 1.0

    groq_key, secret_source = _resolve_groq_key()

    return OrchestratorSettings(
        google_api_key=groq_key,
        secret_source=secret_source,
        gemini_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        gemini_timeout_seconds=timeout,
        gemini_max_retries=retries,
        gemini_retry_backoff_seconds=backoff,
    )
