# Appwrite Trace Sync

Back up OpenJarvis eval traces to [Appwrite](https://appwrite.io) so you can
inspect runs from a different device without re-running them. Appwrite can be
self-hosted, which keeps the local-first ethos — your data, your infra.

## What it does

Each trace file (`*.jsonl`) under a directory is uploaded to an Appwrite
**Storage** bucket, and a row is written to a **TablesDB** index table with:

| Field        | Purpose                                               |
| ------------ | ----------------------------------------------------- |
| `run_id`     | Logical group (e.g. `eval-2026-05`, `morning-digest`) |
| `file_id`    | Appwrite file ID for download                         |
| `filename`   | Original on-disk name                                 |
| `size_bytes` | File size                                             |
| `sha256`     | Content hash — used as a dedup key on push            |
| `created_at` | ISO-8601 UTC timestamp                                |
| `agent`      | Optional: which agent produced the trace              |

The `sha256` column means re-running `push` on the same directory is a no-op,
and `pull` skips files whose local copy already matches the stored hash.

## Requirements

- An Appwrite project (cloud or self-hosted) and a server-scoped API key with
  `databases.read/write`, `tables.read/write`, `files.read/write` scopes
- The user ID that should own the synced traces
- Python deps: `pip install appwrite`

## Setup

```bash
cp examples/appwrite_sync/.env.example .env
# fill in APPWRITE_PROJECT_ID, APPWRITE_API_KEY, APPWRITE_USER_ID
set -a && source .env && set +a

python examples/appwrite_sync/trace_sync.py bootstrap
```

`bootstrap` is idempotent — it creates the `openjarvis` database, the
`trace_index` table, and the `openjarvis_traces` bucket if they don't yet exist,
and grants read/write only to your user role.

## Usage

```bash
# Push every *.jsonl under ./traces into a named run
python examples/appwrite_sync/trace_sync.py push ./traces \
    --run-id eval-2026-05-04 --agent orchestrator

# See what's stored
python examples/appwrite_sync/trace_sync.py list
python examples/appwrite_sync/trace_sync.py list --run-id eval-2026-05-04
python examples/appwrite_sync/trace_sync.py list --since 2026-05-01T00:00:00

# Pull on another machine
python examples/appwrite_sync/trace_sync.py pull ./synced --run-id eval-2026-05-04
```

## How it integrates with OpenJarvis

OpenJarvis eval runs write per-sample traces under a `_traces_dir` (see
`src/openjarvis/evals/core/types.py`). Point `push` at that directory after a
run, then `pull` from another machine to inspect, replay, or feed them back into
the learning loop (`jarvis optimize skills`, `jarvis bench skills`).

## Notes

- Permissions are scoped to `Role.user(<APPWRITE_USER_ID>)`, so the bucket and
  rows are private to that user even though they were created by the API key.
- The script uses `TablesDB` (not the deprecated `Databases` class) and keyword
  arguments throughout, matching current Appwrite Python SDK conventions.
- Storage ≤ 50 MiB per file is fine for typical trace files; larger files
  should be split or compressed before push.
