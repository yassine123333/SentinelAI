from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

try:
    import hvac  # type: ignore
except Exception:  # pragma: no cover
    hvac = None


@dataclass
class VaultConfig:
    enabled: bool
    addr: str | None
    token: str | None
    namespace: str | None
    mount_point: str
    secret_path: str
    gemini_key_field: str
    refresh_interval_seconds: int
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "VaultConfig":
        enabled_raw = os.getenv("VAULT_ENABLED", "false").strip().lower()
        enabled = enabled_raw in {"1", "true", "yes", "on"}

        refresh_raw = os.getenv("VAULT_REFRESH_INTERVAL_SECONDS", "60")
        timeout_raw = os.getenv("VAULT_TIMEOUT_SECONDS", "5")

        try:
            refresh = max(5, int(refresh_raw))
        except ValueError:
            refresh = 60

        try:
            timeout = max(2, int(timeout_raw))
        except ValueError:
            timeout = 5

        return cls(
            enabled=enabled,
            addr=os.getenv("VAULT_ADDR"),
            token=os.getenv("VAULT_TOKEN"),
            namespace=os.getenv("VAULT_NAMESPACE"),
            mount_point=os.getenv("VAULT_MOUNT", "secret"),
            secret_path=os.getenv("VAULT_SECRET_PATH", "sentinelai/llm"),
            gemini_key_field=os.getenv("VAULT_GEMINI_KEY_FIELD", "google_api_key"),
            refresh_interval_seconds=refresh,
            timeout_seconds=timeout,
        )


class VaultSecretManager:
    def __init__(self, config: VaultConfig) -> None:
        self.config = config
        self._cached_secret: dict[str, Any] = {}
        self._expires_at = 0.0

    def get_gemini_api_key(self, force_refresh: bool = False) -> str | None:
        if not self.config.enabled:
            return None

        secret = self._read_secret(force_refresh=force_refresh)
        value = secret.get(self.config.gemini_key_field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _read_secret(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force_refresh and self._cached_secret and now < self._expires_at:
            return self._cached_secret

        self._cached_secret = self._fetch_secret_from_vault()
        self._expires_at = now + self.config.refresh_interval_seconds
        return self._cached_secret

    def _fetch_secret_from_vault(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {}

        if not self.config.addr or not self.config.token:
            return {}

        if hvac is None:
            return {}

        try:
            client = hvac.Client(
                url=self.config.addr,
                token=self.config.token,
                namespace=self.config.namespace,
                timeout=self.config.timeout_seconds,
            )
            if not client.is_authenticated():
                return {}

            response = client.secrets.kv.v2.read_secret_version(
                path=self.config.secret_path,
                mount_point=self.config.mount_point,
                raise_on_deleted_version=True,
            )
            payload = response.get("data", {}).get("data", {})
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}
