"""Tests for OpenRouter key loading in the cloud engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from openjarvis.engine.cloud import CloudEngine


def _clear_cloud_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MINIMAX_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_CODEX_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_cloud_engine_loads_openrouter_key_from_cloud_keys_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CloudEngine should discover OpenRouter credentials from cloud-keys.env."""
    keys_file = tmp_path / "cloud-keys.env"
    keys_file.write_text("OPENROUTER_API_KEY=sk-or-test-from-file\n")

    _clear_cloud_env(monkeypatch)

    fake_openai = mock.MagicMock()
    with mock.patch("openjarvis.engine.cloud._CLOUD_ENV_FILE", keys_file), \
        mock.patch.dict("sys.modules", {"openai": fake_openai}):
        engine = CloudEngine()

    assert engine._openrouter_client is not None
    assert engine.health() is True


def _write_vault(config_dir: Path, payload: dict[str, str]) -> mock._patch:
    """Stage a fake encrypted vault under ``config_dir``.

    The on-disk ``Fernet`` cipher (AES-CBC) is unavailable on some hardened
    crypto backends, so we write placeholder files and patch ``Fernet`` to
    return the decrypted JSON. This keeps the test hermetic while still
    exercising the engine's file-discovery, decrypt, parse, and key-filter
    logic.
    """
    (config_dir / ".vault_key").write_bytes(b"fake-key")
    (config_dir / "vault.enc").write_bytes(b"fake-ciphertext")

    fake_fernet_cls = mock.MagicMock()
    fake_fernet_cls.return_value.decrypt.return_value = json.dumps(payload).encode()
    return mock.patch("cryptography.fernet.Fernet", fake_fernet_cls)


def test_cloud_engine_loads_openrouter_key_from_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CloudEngine should discover credentials stored via ``jarvis vault set``.

    This is the source the live CLI uses, so the engine must read the encrypted
    vault when neither cloud-keys.env nor the process env carry the key.
    """
    _clear_cloud_env(monkeypatch)
    vault_patch = _write_vault(
        tmp_path, {"OPENROUTER_API_KEY": "sk-or-test-from-vault"}
    )

    missing_env = tmp_path / "cloud-keys.env"  # intentionally absent
    fake_openai = mock.MagicMock()
    with vault_patch, \
        mock.patch("openjarvis.engine.cloud.get_config_dir", return_value=tmp_path), \
        mock.patch("openjarvis.engine.cloud._CLOUD_ENV_FILE", missing_env), \
        mock.patch.dict("sys.modules", {"openai": fake_openai}):
        from openjarvis.engine.cloud import _load_cloud_keys

        keys = _load_cloud_keys()
        engine = CloudEngine()

    assert keys.get("OPENROUTER_API_KEY") == "sk-or-test-from-vault"
    assert engine._openrouter_client is not None
    assert engine.health() is True


def test_process_env_overrides_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process env should take precedence over the on-disk vault value."""
    _clear_cloud_env(monkeypatch)
    vault_patch = _write_vault(tmp_path, {"OPENROUTER_API_KEY": "sk-or-from-vault"})
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")

    missing_env = tmp_path / "cloud-keys.env"
    with vault_patch, \
        mock.patch("openjarvis.engine.cloud.get_config_dir", return_value=tmp_path), \
        mock.patch("openjarvis.engine.cloud._CLOUD_ENV_FILE", missing_env):
        from openjarvis.engine.cloud import _load_cloud_keys

        keys = _load_cloud_keys()

    assert keys["OPENROUTER_API_KEY"] == "sk-or-from-env"


def test_openrouter_free_alias_resolves_to_listed_free_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``openrouter/free`` must resolve to a concrete, listed ``:free`` slug.

    The bare ``free`` token is not routable and previously produced a 502. The
    resolver should prefer a curated free model that the live models list
    actually exposes, and must never return a paid slug.
    """
    _clear_cloud_env(monkeypatch)
    engine = CloudEngine()

    # Simulate OpenRouter exposing only a subset of the curated free models.
    listed = mock.MagicMock()
    listed.data = [
        mock.MagicMock(id="google/gemma-4-31b-it:free"),
        mock.MagicMock(id="some/paid-model"),
    ]
    engine._openrouter_client = mock.MagicMock()
    engine._openrouter_client.models.list.return_value = listed

    resolved = engine._openrouter_model_id("openrouter/free")
    assert resolved == "google/gemma-4-31b-it:free"
    assert resolved.endswith(":free")

    # Concrete slugs pass through unchanged; ``auto`` keeps its real slug.
    assert (
        engine._openrouter_model_id("openrouter/meta-llama/llama-3.3-70b-instruct")
        == "meta-llama/llama-3.3-70b-instruct"
    )
    assert engine._openrouter_model_id("openrouter/auto") == "openrouter/auto"


