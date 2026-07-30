# Phase 4: Obsidian memory, retrieval, evidence, and controlled writes

## Result

Phase 4 adds an isolated Markdown-vault memory subsystem without accessing or
changing the real Obsidian vault, the 46 real notes, or `jarvis-desktop`.
Markdown remains the source of truth. SQLite is a disposable projection that
can be rebuilt from Markdown.

The implementation baseline was Phase-3 commit
`9b70235b538b48ff6841846ffcd193d87d748c22`. The required code audit was
committed first as `e1846e31` and is recorded in
`docs/memory/phase-4-memory-audit.md`.

No default vault is guessed, created, or probed. Phase-4 tests and smokes use
only temporary synthetic vaults and external temporary state directories.

## Configuration and lifecycle

Vault memory is disabled while `memory.vault_path` is empty.

```toml
[memory]
vault_path = ""
vault_index_path = "C:/external-state/vault-memory.sqlite3"
vault_restore_path = "C:/external-state/vault-memory-restore"
vault_mode = "read-only" # read-only | writable-test
vault_embeddings_enabled = false
vault_watch_enabled = false
vault_poll_interval_seconds = 2.0
```

Safety invariants:

- `vault_path` must be an existing directory; it is never created.
- The index and restore roots must be outside the vault.
- The canonical Phase-3 task runtime is mandatory when vault memory is enabled.
- Server startup performs an initial full rebuild.
- Server shutdown stops the optional poller and closes SQLite.
- Markdown writes are rejected outside `writable-test`.
- `full_access`, API-key fallback, Responses API fallback, automatic approval,
  mandatory embeddings, and mandatory local LLMs are not used.

## Canonical note and identity model

`MemoryNote` includes:

```text
note_id, identity_kind, path, title, note_type, status, scope, project,
tags, aliases, source, source_task_id, source_session_id, created_at,
updated_at, content_hash, frontmatter_version, body, body_start_line,
outgoing_links, backlinks, folder_relations, archived, conflict_state,
modified_ns, size_bytes, indexed_at, parser_error, raw_frontmatter
```

`note_id` is identity; `path` is a mutable attribute. A valid existing
frontmatter ID is retained across move and rename. Read-only legacy notes
without an ID receive a visibly provisional identity:

```text
provisional:<40 hex characters>
```

The provisional value is deterministic from relative path and content hash,
is not a UUID, and is never written to Markdown. A UUID is generated only
while preparing a controlled candidate for a later approved write.

Supported note types are `fact`, `preference`, `project`, `decision`, `task`,
`experience`, `error`, `solution`, `skill`, `person`, `capture`, `review`, and
`system`.

Conflict states are `none`, `duplicate`, `possible_conflict`,
`confirmed_conflict`, `externally_modified`, and `invalid_schema`.

## YAML schema

New notes use schema version 1:

```yaml
---
id: "<uuid>"
schema_version: 1
type: fact
status: active
scope: personal
project:
tags: []
aliases: []
source: user
source_task_id:
source_session_id:
created_at: "timezone-aware ISO-8601"
updated_at: "timezone-aware ISO-8601"
---
```

`ruamel.yaml` round-trip parsing is used. Unknown fields, key order, quoted
values, and comments are retained where a controlled update is required.
Invalid YAML is reported and is not silently repaired. Indexing never renders
or rewrites a note.

## Reconstructible SQLite index

Schema version 1 contains:

- `memory_schema_migrations`
- `memory_notes`
- `memory_note_paths`
- `memory_fts`
- `memory_tags`
- `memory_links`
- `memory_backlinks` (view)
- `memory_relations`
- `memory_index_errors`
- `memory_conflicts`
- `memory_candidates`
- `memory_write_operations`
- `memory_sources`
- `memory_index_runs`
- `memory_api_operations`

The index enables `foreign_keys`, WAL for file databases, `busy_timeout`, and
`synchronous=FULL`. Updates use short explicit transactions. A rebuild clears
the generated projection and reconstructs it from Markdown. Incremental sync
detects create, modify, move/rename, and delete by stable ID, path, timestamps,
size, and content hash.

Wikilinks support `[[Title]]`, `[[Title|Alias]]`, and headings. Resolved edges
use stable note IDs. Unresolved and ambiguous same-title links remain visible.
Backlinks are derived from resolved link rows. Folder, project, task/source,
and Wikilink relations feed the graph API but do not replace Markdown or the
retrieval index.

## Retrieval and evidence

The default and complete MVP is `fts5_bm25`. It does not instantiate an
embedding provider and does not contact Ollama.

Pipeline:

1. Unicode NFKC and whitespace normalization, including German `ß`/`ss`
   search expansion.
2. Validated type, status, scope, project, tag, time, and archive filters.
3. FTS5 candidate search.
4. Weighted BM25 columns: title `10`, aliases `7`, body `1`, tags `4`,
   project `5`.
5. Exact-title, title, alias, tag, project, folder, linked-candidate, and
   source-priority boosts.
6. Duplicate-body elimination that retains the stronger and more authoritative
   source.
7. Folder-diverse bounded selection.
8. Bounded relevant span extraction with section and reliable line references.
9. Explicit evidence classification.

Evidence statuses are `sufficient`, `partial`, `insufficient`, `conflicting`,
and `unavailable`. Empty or weak support produces the machine-readable
`insufficient_evidence` marker. Only selected sources are returned and stored;
considered-but-unused candidates do not become Task Sources.

Every selected source contains `source_id`, `retrieval_id`, stable `note_id`,
relative path, title, bounded relevant text, line/section reference, score,
selection reason, content hash, and index timestamp.

## Phase-3 task, source, and trace integration

Every correlated memory operation validates:

```text
task_id, session_id, correlation_id, thread_id, turn_id
```

Retrieval adds `retrieval_id`, `source_id`, and `note_id`. Task Sources contain
only actual selected evidence. Timeline and trace events are:

- `memory.query_started`
- `memory.candidate_found`
- `memory.source_selected`
- `memory.evidence_insufficient`
- `memory.conflict_detected`
- `memory.write_candidate_created`
- `memory.write_approved`
- `memory.write_rejected`
- `memory.write_applied`
- `memory.index_updated`
- `memory.index_failed`

Events store redacted previews, hashes, IDs, bounded spans, and retrieval
metadata rather than complete personal notes.

## Candidate, approval, conflict, and write flow

An explicit “Merke dir …” request creates a persistent candidate, not a note.
The candidate includes proposed type/scope, stable UUID, source task/session,
similar-note search, duplicate/conflict state, path, complete planned Markdown,
bounded diff, before hash, risk, and approval ID.

The candidate queues one Phase-3 `FILE_CHANGE` approval with
`workspace_write`, the isolated vault root, diff, restore information, and
`allow_once_only=true`. Deny and expiry write nothing. Approval cannot be
converted into “always allow.”

Source priority is:

1. current direct user correction;
2. explicitly confirmed information;
3. manual information;
4. verified import;
5. automatically derived memory.

Conflicts are visible and are never silently overwritten. Duplicate IDs,
duplicate bodies, explicit conflict keys, and external modification between
planning and apply are recorded.

Approved writes enforce:

- an existing non-reparse vault root;
- relative Markdown-only targets;
- rejection of absolute, drive, UNC, empty, `.` and `..` paths;
- symlink and Windows junction/reparse-point rejection;
- before-hash compare-and-swap;
- a same-filesystem temporary file;
- flush, `fsync`, and `os.replace`;
- after-hash verification;
- bounded unified diff;
- an external restore artifact;
- write audit before index synchronization.

Restore verifies the post-write hash before replacing or deleting the target.

## Local API

Read routes:

```text
GET /v1/memory/health
GET /v1/memory/search
GET /v1/memory/notes/{note_id}
GET /v1/memory/notes/{note_id}/links
GET /v1/memory/graph
GET /v1/memory/candidates
GET /v1/memory/conflicts
GET /v1/tasks/{task_id}/sources
```

Mutation routes:

```text
POST /v1/memory/reindex
POST /v1/memory/candidates
POST /v1/memory/candidates/{id}/approve
POST /v1/memory/candidates/{id}/reject
POST /v1/memory/conflicts/{id}/resolve
```

Vault-memory mutations require loopback access, `X-Task-ID`,
`X-Session-ID`, `X-Correlation-ID`, and `Idempotency-Key`; optional thread and
turn headers preserve deeper correlation. Inputs are bounded and validated.
Reindex is idempotent and never writes Markdown. Candidate apply is additionally
gated by `writable-test` and the allow-once approval record.

The older OpenJarvis chunk-memory endpoints remain separate for compatibility.
Their consolidation or removal is a Phase-8 migration decision, as recorded in
the audit.

## Existing UI

The main frontend now has a `/memory` route and sidebar entry. It displays:

- privacy-safe health and FTS5/embedding mode;
- indexed-note and parser-error counts;
- canonical-task selection for correlated search;
- evidence status, confidence, warnings, and only actual selected sources;
- note ID, path, bounded span, lines/section, score, and selection reason;
- candidates, planned diff, risk, approval ID/status, and conflict state;
- open conflicts;
- explicitly selected note detail with stable ID, path, links, and backlinks.

Complete note content is fetched only after the user selects a source and is
bounded in the rendered preview.

## Reindex and migration preparation

Manual rebuild is authoritative. The optional Windows polling fallback hashes
Markdown snapshots, deduplicates unchanged states, debounces bursts, uses an
interruptible wait of at least 250 ms, and calls incremental sync only after a
stable change. Startup rebuild provides process-restart recovery.

The only Phase-4 migration command is:

```text
jarvis memory migration --dry-run --vault <explicit-existing-path>
```

It reports schema distribution, missing IDs, invalid YAML, duplicate IDs,
top-level folder schemas, possible duplicate bodies, conflict-key
disagreements, proposed diffs, before hashes, and a rollback plan. Planned UUID
fields use a placeholder; no permanent UUID is generated by the analysis.
Source hashes are compared before and after analysis. `--apply` does not exist.

## Verification

Environment:

```text
Python                    3.11.9
SQLite                    3.45.1 (ENABLE_FTS5)
ruamel.yaml               0.18.17
openai-codex              0.144.4
openai-codex-cli-bin      0.144.4
FastAPI                   0.129.0
Pydantic                  2.12.5
pytest                    9.0.2
polars                    1.40.1
```

Focused backend/API/CLI verification:

```text
260 passed, 16 skipped
```

The skips are existing platform/optional-capability skips. No Phase-4 focused
test failed.

Frontend:

```text
Full Vitest suite: 8 passed (including MemoryVaultPanel: 2 passed)
TypeScript/Vite production build: passed
```

The build retained the existing large-chunk and mixed static/dynamic import
warnings.

Final full hermetic selector:

```text
pytest tests -n auto -q --tb=short \
  -m "not live and not cloud and not hub and not live_external \
      and not live_channel and not docker"
```

Final result:

```text
7,348 passed, 45 skipped, 52 failed, 10 errors, 70 warnings
```

The failures are outside Phase 4 and match the established baseline classes:
POSIX permission/process assumptions on Windows, colon-bearing Linux RAPL
paths, Windows in-memory/path fixtures, optional WhatsApp/Node, unmarked legacy
Ollama dense-memory tests, telemetry timing/energy assumptions, registry/order
dependence, and Windows SQLite temporary-directory teardown. The optional
framework-comparison `polars` dependency was restored and its previously
failing import block passed 7/7 when rerun with the Codex transport checks.
Xdist ordering makes the exact legacy failure count fluctuate; all focused
Phase-4 tests remained green after the full run.

## Smoke tests

`scripts/phase4_memory_smoke.py` passed:

- temporary synthetic vault with three notes;
- full index and FTS5/BM25 sufficient evidence;
- exact Task Sources;
- move detection with stable ID;
- candidate remained non-permanent before approval;
- allow-once, atomic write, graph update, external restore, and verified undo;
- server health `200`;
- server shutdown closed the index;
- temporary vault was removed.

One and only one controlled live Codex smoke was run through
`openai-codex==0.144.4` after:

```text
codex login status
Logged in using ChatGPT
```

It used `read-only`, `deny_all`, an empty temporary workspace, a temporary
synthetic vault, one selected bounded source, no requested tools, and one turn.
Codex returned exactly:

```text
COBALT-47 [source: <the selected synthetic note UUID>]
```

The answer's note ID and the persisted Task Source note ID matched exactly.
Workspace and Markdown remained unchanged. The live run's initial diagnostic
printed the SDK root wrappers as `ThreadItem`; the helper was corrected
afterward to unwrap their concrete discriminator for future runs, but the live
turn was not repeated because Phase 4 permits at most one. The enforced
`deny_all`/`read-only` policy, exact evidence-only response, and unchanged
workspace/vault provide the retained no-write evidence.

## Windows limitations and deferred work

- Polling is the tested watcher fallback; no native Windows filesystem-event
  backend is required in Phase 4.
- Symlink tests may skip when the Windows account lacks symbolic-link
  privilege. Reparse-point and junction checks remain implemented and
  separately exercised where the platform permits.
- Python's SQLite build supplies FTS5 and WAL; external processes can still
  hold SQLite files long enough to trigger known Windows temp teardown errors.
- Embeddings are intentionally disabled by default. The pre-existing dense
  memory test module still attempts legacy Ollama calls and is not activated by
  the new vault subsystem.
- Existing legacy chunk memory, automatic extracted-fact memory, and vault
  memory are not consolidated in Phase 4.
- Real note migration, automatic ID insertion, folder restructuring, cleanup,
  and any access to the real vault remain Phase 8 work requiring separate,
  explicit authorization.

## Phase-5 recommendation

Phase 5 can safely begin on the current feature branch if it treats this
Phase-4 API and source model as the memory contract, keeps the real vault
locked, and does not broaden migration or write authority. Phase 5 should add
conversation-level orchestration that performs retrieval before Codex,
passes only bounded selected sources, renders the evidence status in answers,
and creates candidates rather than direct writes.
