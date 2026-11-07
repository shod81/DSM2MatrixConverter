"""Tests for AI configuration and keyring credential lookup (Task T-060)."""

from __future__ import annotations

import os
from unittest.mock import patch

from dsm2emp.ai.config import AiConfig, get_api_key


def test_ai_config_defaults() -> None:
    """AiConfig has secure, offline-by-default parameters."""
    cfg = AiConfig()
    assert cfg.enabled is False
    assert cfg.provider == "openrouter"
    assert cfg.max_retries == 2
    assert cfg.budget_eur_per_run == 1.00
    assert cfg.timeout_s == 60.0


def test_get_api_key_from_keyring() -> None:
    """Keyring retrieval takes precedence without warnings."""
    with patch("dsm2emp.ai.config.keyring.get_password", return_value="secret-key-123"):
        key, warning = get_api_key("openrouter")
        assert key == "secret-key-123"
        assert warning is None


def test_get_api_key_fallback_env_has_warning() -> None:
    """Environment fallback provides key but produces a W5001 warning."""
    with patch("dsm2emp.ai.config.keyring.get_password", return_value=None):
        with patch.dict(os.environ, {"DSM2EMP_OPENROUTER_API_KEY": "env-key-999"}):
            key, warning = get_api_key("openrouter")
            assert key == "env-key-999"
            assert warning is not None
            assert "W5001" in warning


def test_get_api_key_missing_returns_none() -> None:
    """Missing key in both keyring and env returns (None, None)."""
    with patch("dsm2emp.ai.config.keyring.get_password", return_value=None):
        with patch.dict(os.environ, {}, clear=True):
            key, warning = get_api_key("openrouter")
            assert key is None
            assert warning is None
