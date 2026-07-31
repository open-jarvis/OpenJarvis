"""Explicit SQLite connection and transaction boundary for learning data."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from openjarvis.learning.store.migrations import MIGRATIONS


class MigrationIntegrityError(RuntimeError):
    """Raised when an applied migration checksum no longer matches."""


class SQLiteLearningDatabase:
    """A path-bound database; construction alone never opens a file."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        if not path.is_absolute():
            raise ValueError("learning database path must be absolute")
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms:d}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> tuple[int, ...]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        applied: list[int] = []
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for migration in MIGRATIONS:
                    first_statement, *remaining = migration.statements
                    connection.execute(first_statement)
                    row = connection.execute(
                        """
                        SELECT checksum
                        FROM learning_schema_migrations
                        WHERE version = ?
                        """,
                        (migration.version,),
                    ).fetchone()
                    if row is not None:
                        if row["checksum"] != migration.checksum:
                            raise MigrationIntegrityError(
                                f"migration {migration.version} checksum mismatch"
                            )
                        continue
                    for statement in remaining:
                        connection.execute(statement)
                    now = datetime.now(timezone.utc).isoformat()
                    connection.execute(
                        """
                        INSERT INTO learning_schema_migrations(
                            version, checksum, applied_at
                        ) VALUES (?, ?, ?)
                        """,
                        (migration.version, migration.checksum, now),
                    )
                    applied.append(migration.version)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        finally:
            connection.close()
        return tuple(applied)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()


__all__ = [
    "MigrationIntegrityError",
    "SQLiteLearningDatabase",
]
