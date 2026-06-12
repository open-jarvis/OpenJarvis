#!/usr/bin/env python3
"""Appwrite Trace Sync — back up OpenJarvis eval traces across devices.

OpenJarvis is local-first: agents, models, and traces all live on your machine.
But once you run evals on a workstation and want to inspect them on a laptop,
you need a sync layer. This example uses Appwrite Storage + TablesDB as that
layer. Appwrite can be self-hosted, so the data stays on infrastructure you own.

What it does:
    * bootstrap   create database, index table, and storage bucket (idempotent)
    * push        upload every *.jsonl trace under a directory + index row
    * pull        download traces by run_id or since a UTC date
    * list        show indexed runs grouped by run_id

Each upload writes a row to a `trace_index` table containing run_id, sha256,
size, created_at, and the Appwrite file_id. The sha256 acts as a dedup key:
re-pushing the same trace is a no-op.

Setup:
    pip install appwrite
    cp examples/appwrite_sync/.env.example .env  # then fill in
    python examples/appwrite_sync/trace_sync.py bootstrap

Usage:
    python examples/appwrite_sync/trace_sync.py push  ./traces --run-id eval-2026-05
    python examples/appwrite_sync/trace_sync.py list  --run-id eval-2026-05
    python examples/appwrite_sync/trace_sync.py pull  ./synced --run-id eval-2026-05
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

try:
    from appwrite.client import Client
    from appwrite.exception import AppwriteException
    from appwrite.id import ID
    from appwrite.input_file import InputFile
    from appwrite.permission import Permission
    from appwrite.query import Query
    from appwrite.role import Role
    from appwrite.services.storage import Storage
    from appwrite.services.tables_db import TablesDB
except ImportError as exc:
    sys.exit(
        "The 'appwrite' package is required.\n"
        "Install it with:  pip install appwrite\n"
        f"(import error: {exc})"
    )


DATABASE_ID = "openjarvis"
TABLE_ID = "trace_index"
BUCKET_ID = "openjarvis_traces"


@dataclass(slots=True)
class Remote:
    """Bundle of Appwrite service handles plus the configured user role."""

    client: Client
    storage: Storage
    tables: TablesDB
    user_id: str

    @property
    def role(self) -> str:
        return Role.user(self.user_id)


def connect() -> Remote:
    endpoint = os.environ.get("APPWRITE_ENDPOINT", "https://cloud.appwrite.io/v1")
    project = os.environ.get("APPWRITE_PROJECT_ID")
    api_key = os.environ.get("APPWRITE_API_KEY")
    user_id = os.environ.get("APPWRITE_USER_ID")
    missing = [
        name
        for name, val in (
            ("APPWRITE_PROJECT_ID", project),
            ("APPWRITE_API_KEY", api_key),
            ("APPWRITE_USER_ID", user_id),
        )
        if not val
    ]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    client = (
        Client()
        .set_endpoint(endpoint)
        .set_project(project)
        .set_key(api_key)
    )
    return Remote(client=client, storage=Storage(client), tables=TablesDB(client), user_id=user_id)


def bootstrap(remote: Remote) -> None:
    """Create database, table, columns, and bucket if they don't exist."""

    try:
        remote.tables.get(database_id=DATABASE_ID)
    except AppwriteException:
        remote.tables.create(database_id=DATABASE_ID, name="OpenJarvis")
        print(f"  created database  {DATABASE_ID}")

    try:
        remote.tables.get_table(database_id=DATABASE_ID, table_id=TABLE_ID)
    except AppwriteException:
        remote.tables.create_table(
            database_id=DATABASE_ID,
            table_id=TABLE_ID,
            name="Trace index",
            permissions=[
                Permission.read(remote.role),
                Permission.create(remote.role),
                Permission.update(remote.role),
                Permission.delete(remote.role),
            ],
        )
        # Each column is created with its dedicated method (SDK 18+ pattern).
        # Wrapped in try/except so re-running bootstrap is safe.
        varchar_cols = [
            ("run_id", 255, True),
            ("file_id", 64, True),
            ("filename", 512, True),
            ("sha256", 64, True),
            ("created_at", 32, True),
            ("agent", 128, False),
        ]
        for key, size, required in varchar_cols:
            try:
                remote.tables.create_varchar_column(
                    database_id=DATABASE_ID,
                    table_id=TABLE_ID,
                    key=key,
                    size=size,
                    required=required,
                )
            except AppwriteException:
                pass
        try:
            remote.tables.create_integer_column(
                database_id=DATABASE_ID,
                table_id=TABLE_ID,
                key="size_bytes",
                required=True,
            )
        except AppwriteException:
            pass
        print(f"  created table     {TABLE_ID}")

    try:
        remote.storage.get_bucket(bucket_id=BUCKET_ID)
    except AppwriteException:
        remote.storage.create_bucket(
            bucket_id=BUCKET_ID,
            name="OpenJarvis traces",
            permissions=[
                Permission.read(remote.role),
                Permission.create(remote.role),
                Permission.delete(remote.role),
            ],
            file_security=False,
            enabled=True,
        )
        print(f"  created bucket    {BUCKET_ID}")

    print("bootstrap complete")


def _iter_traces(local_dir: Path) -> Iterable[Path]:
    if not local_dir.is_dir():
        sys.exit(f"Not a directory: {local_dir}")
    for path in sorted(local_dir.rglob("*.jsonl")):
        if path.is_file():
            yield path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def push(remote: Remote, local_dir: Path, run_id: str, agent: Optional[str]) -> None:
    """Upload every *.jsonl under local_dir; skip files already indexed by sha256."""

    uploaded = skipped = 0
    for path in _iter_traces(local_dir):
        digest = _sha256(path)
        existing = remote.tables.list_rows(
            database_id=DATABASE_ID,
            table_id=TABLE_ID,
            queries=[Query.equal("sha256", digest), Query.limit(1)],
        )
        if existing.get("total", 0) > 0:
            skipped += 1
            continue

        size = path.stat().st_size
        file = remote.storage.create_file(
            bucket_id=BUCKET_ID,
            file_id=ID.unique(),
            file=InputFile.from_path(str(path)),
            permissions=[
                Permission.read(remote.role),
                Permission.delete(remote.role),
            ],
        )
        remote.tables.create_row(
            database_id=DATABASE_ID,
            table_id=TABLE_ID,
            row_id=ID.unique(),
            data={
                "run_id": run_id,
                "file_id": file["$id"],
                "filename": path.name,
                "size_bytes": size,
                "sha256": digest,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "agent": agent,
            },
            permissions=[Permission.read(remote.role), Permission.delete(remote.role)],
        )
        uploaded += 1
        print(f"  + {path.name}  ({size:,} bytes)")
    print(f"push complete: {uploaded} uploaded, {skipped} already present")


def _query_rows(remote: Remote, run_id: Optional[str], since: Optional[str]) -> list[dict]:
    queries = [Query.order_desc("created_at"), Query.limit(100)]
    if run_id:
        queries.append(Query.equal("run_id", run_id))
    if since:
        queries.append(Query.greater_than_equal("created_at", since))
    return remote.tables.list_rows(
        database_id=DATABASE_ID, table_id=TABLE_ID, queries=queries
    ).get("rows", [])


def list_runs(remote: Remote, run_id: Optional[str], since: Optional[str]) -> None:
    rows = _query_rows(remote, run_id, since)
    if not rows:
        print("(no traces match)")
        return
    by_run: dict[str, list[dict]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row)
    for rid, items in by_run.items():
        total = sum(r["size_bytes"] for r in items)
        first = min(r["created_at"] for r in items)
        print(f"{rid:30s}  {len(items):>4d} files  {total/1024:>9.1f} KiB  first: {first}")


def pull(remote: Remote, dest: Path, run_id: Optional[str], since: Optional[str]) -> None:
    """Download every trace matching the filter into dest/<run_id>/<filename>."""

    rows = _query_rows(remote, run_id, since)
    if not rows:
        print("(no traces match)")
        return
    dest.mkdir(parents=True, exist_ok=True)
    for row in rows:
        target_dir = dest / row["run_id"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / row["filename"]
        if target.exists() and _sha256(target) == row["sha256"]:
            continue
        data = remote.storage.get_file_download(bucket_id=BUCKET_ID, file_id=row["file_id"])
        target.write_bytes(data)
        print(f"  ↓ {row['run_id']}/{row['filename']}")
    print(f"pull complete: {len(rows)} traces under {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bootstrap", help="Create database, table, and bucket (idempotent).")

    p_push = sub.add_parser("push", help="Upload *.jsonl traces under a directory.")
    p_push.add_argument("local_dir", type=Path)
    p_push.add_argument("--run-id", required=True)
    p_push.add_argument("--agent", default=None)

    p_list = sub.add_parser("list", help="List indexed runs.")
    p_list.add_argument("--run-id", default=None)
    p_list.add_argument("--since", default=None, help="ISO timestamp, e.g. 2026-05-01T00:00:00")

    p_pull = sub.add_parser("pull", help="Download matching traces into a directory.")
    p_pull.add_argument("dest", type=Path)
    p_pull.add_argument("--run-id", default=None)
    p_pull.add_argument("--since", default=None)

    args = parser.parse_args()
    remote = connect()

    if args.cmd == "bootstrap":
        bootstrap(remote)
    elif args.cmd == "push":
        push(remote, args.local_dir, args.run_id, args.agent)
    elif args.cmd == "list":
        list_runs(remote, args.run_id, args.since)
    elif args.cmd == "pull":
        pull(remote, args.dest, args.run_id, args.since)


if __name__ == "__main__":
    main()
