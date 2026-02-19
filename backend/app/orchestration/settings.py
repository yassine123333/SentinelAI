from __future__ import annotations

import os
from dataclasses import dataclass

from app.security import VaultConfig, VaultSecretManager


_VAULT_MANAGER: VaultSecretManager | None = None


@dataclass
class OrchestratorSettings:
    google_api_key: str | None
    secret_source: str = "missing"
    gemini_model: str = "gemini-2.5-flash"
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


def _resolve_gemini_key() -> tuple[str | None, str]:
    vault_manager = _get_vault_manager_from_env()
    key_from_vault = vault_manager.get_gemini_api_key()
    if key_from_vault:
        return key_from_vault, "vault"

    key_from_env = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if key_from_env:
        return key_from_env, "env"

    return None, "missing"


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

    google_api_key, secret_source = _resolve_gemini_key()

    return OrchestratorSettings(
        google_api_key=google_api_key,
        secret_source=secret_source,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_timeout_seconds=timeout,
        gemini_max_retries=retries,
        gemini_retry_backoff_seconds=backoff,
    )
