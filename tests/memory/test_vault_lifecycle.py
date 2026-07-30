from __future__ import annotations

import time
from pathlib import Path

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.memory import (
    PollingVaultWatcher,
    build_vault_memory_service,
)
from openjarvis.tasks.store import TaskStore


def _configured(
    tmp_path: Path,
    *,
    mode: str = "read-only",
) -> tuple[JarvisConfig, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    state = tmp_path / "state"
    config = JarvisConfig()
    config.memory.vault_path = str(vault)
    config.memory.vault_index_path = str(state / "index.sqlite3")
    config.memory.vault_restore_path = str(state / "restore")
    config.memory.vault_mode = mode
    return config, vault, state


def test_unconfigured_builder_never_creates_a_vault(tmp_path: Path) -> None:
    config = JarvisConfig()
    missing = tmp_path / "must-not-exist"
    config.memory.vault_path = ""

    assert build_vault_memory_service(config, task_store=None) is None
    assert not missing.exists()


def test_configured_builder_requires_canonical_task_store(tmp_path: Path) -> None:
    config, _vault, _state = _configured(tmp_path)

    with pytest.raises(RuntimeError, match="task runtime"):
        build_vault_memory_service(config, task_store=None)


def test_builder_rebuilds_and_closes_external_index(tmp_path: Path) -> None:
    config, vault, state = _configured(tmp_path)
    (vault / "one.md").write_text("# One\n\nSynthetic.", encoding="utf-8")
    task_store = TaskStore(state / "tasks.sqlite3")

    service = build_vault_memory_service(config, task_store=task_store)

    assert service is not None
    assert service.health().note_count == 1
    assert not service.index.db_path.is_relative_to(vault)
    service.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = service.index.connection
    task_store.close()


def test_polling_watcher_create_modify_move_delete_and_deduplicate(
    tmp_path: Path,
) -> None:
    config, vault, state = _configured(tmp_path)
    task_store = TaskStore(state / "tasks.sqlite3")
    service = build_vault_memory_service(config, task_store=task_store)
    assert service is not None
    watcher = PollingVaultWatcher(
        service,
        interval_seconds=0.25,
        debounce_seconds=0,
    )
    watcher._last_applied = watcher._snapshot()

    note = vault / "one.md"
    note.write_text(
        "---\n"
        "id: 11111111-1111-4111-8111-111111111111\n"
        "schema_version: 1\n"
        "---\n"
        "# One\n\nVersion one.",
        encoding="utf-8",
    )
    created = watcher.poll_once(force=True)
    note_id = service.index.list_notes()[0].note_id
    note.write_text(
        "---\n"
        "id: 11111111-1111-4111-8111-111111111111\n"
        "schema_version: 1\n"
        "---\n"
        "# One\n\nVersion two.",
        encoding="utf-8",
    )
    modified = watcher.poll_once(force=True)
    moved_path = vault / "folder" / "renamed.md"
    moved_path.parent.mkdir()
    note.replace(moved_path)
    moved = watcher.poll_once(force=True)
    moved_path.unlink()
    deleted = watcher.poll_once(force=True)
    unchanged = watcher.poll_once(force=True)

    assert created is not None and created.created == 1
    assert modified is not None and modified.modified == 1
    assert moved is not None and moved.moved == 1
    assert service.index.get_note(note_id) is None
    assert deleted is not None and deleted.deleted == 1
    assert unchanged is None
    assert watcher.sync_count == 4
    service.close()
    task_store.close()


def test_background_watcher_uses_interruptible_wait_and_stops(
    tmp_path: Path,
) -> None:
    config, vault, state = _configured(tmp_path)
    task_store = TaskStore(state / "tasks.sqlite3")
    service = build_vault_memory_service(config, task_store=task_store)
    assert service is not None
    watcher = PollingVaultWatcher(
        service,
        interval_seconds=0.25,
        debounce_seconds=0,
    )
    watcher.start()
    (vault / "background.md").write_text("Synthetic.", encoding="utf-8")
    deadline = time.monotonic() + 3
    while watcher.sync_count == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    watcher.stop()

    assert watcher.sync_count == 1
    assert not watcher.running
    service.close()
    task_store.close()
