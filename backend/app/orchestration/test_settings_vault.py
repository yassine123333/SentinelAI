from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from .settings import load_settings


class _FakeVaultManager:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def get_gemini_api_key(self) -> str | None:
        return self.value


class TestSettingsVaultResolution(unittest.TestCase):
    def test_prefers_vault_over_env(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "env-key"}, clear=False):
            with patch("app.orchestration.settings._get_vault_manager_from_env", return_value=_FakeVaultManager("vault-key")):
                settings = load_settings()

        self.assertEqual(settings.google_api_key, "vault-key")
        self.assertEqual(settings.secret_source, "vault")

    def test_falls_back_to_env_when_vault_empty(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "env-key"}, clear=False):
            with patch("app.orchestration.settings._get_vault_manager_from_env", return_value=_FakeVaultManager(None)):
                settings = load_settings()

        self.assertEqual(settings.google_api_key, "env-key")
        self.assertEqual(settings.secret_source, "env")

    def test_missing_when_vault_and_env_empty(self) -> None:
        env = {
            "GOOGLE_API_KEY": "",
            "GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("app.orchestration.settings._get_vault_manager_from_env", return_value=_FakeVaultManager(None)):
                settings = load_settings()

        self.assertIsNone(settings.google_api_key)
        self.assertEqual(settings.secret_source, "missing")


if __name__ == "__main__":
    unittest.main()
