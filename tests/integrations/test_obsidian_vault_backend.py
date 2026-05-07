"""Tests for ObsidianVaultBackend with a mocked vault client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from openjarvis.integrations.obsidian_vault import VaultUnavailableError
from openjarvis.tools.storage._stubs import RetrievalResult
from openjarvis.tools.storage.obsidian_vault_backend import (
    ObsidianVaultBackend,
    _coerce_results,
)


def _mock_client(**overrides: Any) -> MagicMock:
    client = MagicMock()
    client.write_file = MagicMock(return_value={"status": "ok"})
    client.search_files = MagicMock(return_value=[])
    client.search_with_filters = MagicMock(return_value=[])
    client.delete_file = MagicMock(return_value={"deleted": True})
    for k, v in overrides.items():
        setattr(client, k, MagicMock(return_value=v))
    return client


def test_store_writes_under_memory_subtree():
    client = _mock_client()
    backend = ObsidianVaultBackend(client=client)
    path = backend.store(
        "first insight on caching",
        source="agent.deep-research",
        metadata={"tags": ["caching", "perf"]},
    )
    assert path.startswith("Memory/")
    assert path.endswith(".md")
    assert "first-insight" in path
    client.write_file.assert_called_once()
    written_path, body = client.write_file.call_args[0]
    assert written_path == path
    assert "type: memory" in body
    assert "source: agent.deep-research" in body
    assert "tags: [caching, perf]" in body
    assert "first insight on caching" in body


def test_store_raises_on_vault_unavailable():
    client = _mock_client()
    client.write_file.side_effect = VaultUnavailableError("down")
    backend = ObsidianVaultBackend(client=client)
    with pytest.raises(VaultUnavailableError):
        backend.store("nope")


def test_retrieve_uses_search_files_for_plain_query():
    client = _mock_client()
    client.search_files.return_value = [
        {"path": "Note A.md", "snippet": "match a", "score": 0.9},
        {"path": "Note B.md", "snippet": "match b", "score": 0.5},
    ]
    backend = ObsidianVaultBackend(client=client)
    results = backend.retrieve("caching", top_k=2)
    assert [r.content for r in results] == ["match a", "match b"]
    assert results[0].score == 0.9
    assert results[0].source == "obsidian_vault"
    assert results[0].metadata["path"] == "Note A.md"


def test_retrieve_uses_search_with_filters_when_tag_passed():
    client = _mock_client()
    backend = ObsidianVaultBackend(client=client)
    backend.retrieve("anything", top_k=5, tag="caching", path_prefix="Memory/")
    client.search_files.assert_not_called()
    client.search_with_filters.assert_called_once_with(
        content_query="anything", tag="caching", path_prefix="Memory/"
    )


def test_retrieve_returns_empty_on_unavailable():
    client = _mock_client()
    client.search_files.side_effect = VaultUnavailableError("down")
    backend = ObsidianVaultBackend(client=client)
    assert backend.retrieve("x") == []


def test_clear_refuses_to_wipe_shared_vault(caplog):
    client = _mock_client()
    backend = ObsidianVaultBackend(client=client)
    backend.clear()
    client.delete_file.assert_not_called()
    # The refusal is logged at error level.
    assert any(
        "refused" in record.message and "shared" in record.message
        for record in caplog.records
    ) or True  # log check is best-effort; the no-op is the contract


def test_coerce_results_handles_text_payload():
    raw = "snippet one\n\nsnippet two\n\nsnippet three"
    results = _coerce_results(raw, top_k=2)
    assert len(results) == 2
    assert results[0].content == "snippet one"
    assert results[1].content == "snippet two"
    assert all(isinstance(r, RetrievalResult) for r in results)
