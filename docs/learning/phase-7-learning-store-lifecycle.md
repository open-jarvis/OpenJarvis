# Phase 7: persistent learning store and review lifecycle

## Scope

This phase adds an isolated, path-bound SQLite domain for immutable trace
evaluations, extraction runs, stable candidate identities, append-only
candidate revisions, review transitions, duplicate/conflict links,
idempotency, recovery, and metadata-only audit events.

The implemented write path is:

```text
TraceEvaluation
  -> CandidateExtractor
  -> LearningRepository.ingest
  -> cross-run duplicate signature lookup
  -> append-only CandidateRevisionRecord
  -> Candidate Head compare-and-swap
  -> optional explicit review transition
  -> new revision + transition + audit event
```

The store does not replace or modify task, trace, or memory stores. Database
construction does not open a file. A caller must provide an absolute path and
explicitly initialize it. Tests use temporary SQLite files only.

There are no skill-registry, promotion, execution, routing, API, UI, or
self-improvement tables or services in this phase.

## SQLite configuration and migrations

Every connection enables:

- write-ahead logging (`journal_mode=WAL`);
- foreign-key enforcement;
- a configured `busy_timeout`;
- explicit `BEGIN IMMEDIATE` write transactions;
- row-based reads and parameterized values.

Migration version 1 creates:

| Table | Purpose |
|---|---|
| `learning_schema_migrations` | Applied versions and immutable checksums |
| `trace_evaluations` | Canonical metadata-only evaluation JSON and indexes |
| `extraction_runs` | Immutable extraction JSON plus stable persisted references |
| `candidate_revisions` | Append-only candidate snapshots and parent hashes |
| `candidate_heads` | Current revision projection keyed by stable identity |
| `candidate_transition_events` | Immutable review transition records |
| `candidate_duplicate_links` | Intra-/cross-run duplicate evidence |
| `candidate_conflict_links` | Open conflicts between stable candidate identities |
| `learning_idempotency_records` | Operation/request digests and result references |
| `learning_audit_events` | Sequenced, metadata-only operational events |

Migrations are idempotent. Reapplying an existing version verifies its
checksum; a changed migration is an integrity error rather than an implicit
repair.

## Evaluation persistence

`TraceEvaluation` is validated before writing and after reading. The canonical
payload hash, row ID, input digest, and indexed hash must agree. An existing
evaluation ID with the same hash is a no-op; the same ID with a different hash
is rejected. Multiple evaluator versions and IDs may reference the same input
digest.

Only the existing metadata-only evaluation JSON is stored. No adapter accepts
raw traces, prompts, answers, tool outputs, or reasoning content.

## Extraction-run persistence

`ExtractionResult`, every candidate content hash, and the run hash are checked
before the transaction starts. The supplied evaluation set must exactly match
the run's input evaluation IDs.

An existing run ID with the same hash is idempotent. Reusing that ID with a
different hash is an integrity failure. Different run IDs may share a semantic
run hash. Stable candidate IDs, duplicate links, and conflict links are stored
as indexed references alongside the immutable original extraction payload.

Reads validate both the extraction JSON and the denormalized run ID/hash
columns so a valid payload cannot be substituted under another index row.

## Stable candidate identity

Persistent identity is based on `duplicate_signature`, not the random
extraction-time candidate ID. The first ingest creates a stable identity from
the signature. Later runs with the same signature select the same head.

Titles do not participate in this lookup. Project, scope, candidate type,
destination, normalized domain content, and safety boundary are already
covered by the duplicate signature.

Cross-run ingest deterministically unions:

- evaluation, task, trace, and evidence IDs;
- provenance records;
- independence groups;
- proposed tests and verification requirements;
- successful-solution evidence references and limitations;
- confidence bases and quarantine reasons.

If this union does not change the semantic candidate content hash, no revision
is added. New evidence, independence, quarantine, or other semantic state
creates exactly one next revision.

## Append-only revisions and heads

`CandidateRevisionRecord` contains the stable candidate ID, exact revision,
parent revision and parent content hash, validated candidate snapshot, state,
content hash, transition or ingest reference, creation time, and record hash.

Revision 1 has no parent and requires an ingest ID. Later revisions require the
immediately preceding revision and content hash, and exactly one transition or
ingest reference. Revisions are never updated or deleted by the repository.

`candidate_heads` is only a projection. A deferred composite foreign key
requires its current `(candidate_id, revision)` to exist. Updates use
compare-and-swap against both expected revision and content hash. Revision
insert, transition/conflict record, audit event, and head CAS share one
transaction.

Historical reads revalidate the candidate hash, revision-record hash,
denormalized columns, immediate parent existence, and parent content hash.

## Review state machine

The closed states remain:

- `proposed`
- `under_review`
- `rejected`
- `quarantined`

Allowed transitions are:

```text
proposed -> under_review | rejected | quarantined
under_review -> rejected | quarantined
quarantined -> under_review | rejected
rejected -> (terminal)
```

Automatic candidate revision 1 remains restricted to `proposed` or
`quarantined`. Later automatic-origin snapshots are accepted only as part of a
validated revision chain. Review state changes cannot mutate a candidate in
place.

`TransitionRequest` requires an expected revision, closed actor type, actor ID,
bounded reason, reason code, correlation ID, and idempotency key. Actor types
are only `user`, `system_policy`, and `deterministic_test`. Model, webpage,
document, imported-skill, and optimizer actors are not representable.

Each successful request produces a self-validating `TransitionRecord`, the
next candidate revision, a CAS head update, and one corresponding audit event.
Rejected is terminal. States for verification, testing, promotion, or
activation do not exist yet.

## Quarantine resolution

Quarantine cannot be cleared by changing only the state. A transition to
`under_review` must provide one typed resolution record for every current
quarantine reason and no extra reason. Resolution summaries retain the same
secret/executable-text validation as candidate summaries.

Manipulated evaluations are not resolvable. A candidate with an open conflict
link cannot leave quarantine. User-correction priority remains review metadata;
it never closes a conflict, chooses a winner, deletes a record, or activates a
candidate.

## Conflict transactions

After candidate upsert, the repository runs deterministic conflict detection
against stable current heads. New conflict links use stable candidate IDs and
signatures. Both non-terminal candidates receive append-only quarantine
revisions before the link is inserted. Those revisions, both head updates, the
link, and audit events commit atomically.

An identical conflict is a no-op. Reusing a conflict ID with different core
content is rejected. Conflict reads validate link/hash/index consistency and
the current candidates' duplicate signatures.

## Idempotency and concurrency

Evaluation ingest, extraction ingest, candidate revisions, lifecycle
transitions, quarantine actions/resolution, and conflict creation execute under
explicit transactions. Mutating public operations require an idempotency key.

Records store only operation name, semantic request digest, completion status,
and result identifiers/hashes. They do not contain full requests or secrets.

The same key and digest returns the recorded result without a new revision,
event, or link. Reusing a key with another operation or digest is a hard
conflict. Candidate-head CAS ensures that two requests against the same
expected revision cannot both succeed. SQLite serialization plus CAS leaves no
partial revision, event, or head.

## Audit events

The store emits sequenced events for evaluation/extraction persistence,
candidate creation/revision/deduplication/conflict, review start, rejection,
quarantine, quarantine resolution, and denied lifecycle transitions.

Events contain only identity, sequence, closed event/actor types, revision,
correlation ID, reason code, redacted reference IDs, timestamp, and SHA-256
hash. Candidate/evaluation payloads, prompts, answers, tool output, documents,
and reasoning are absent.

## Restart recovery and integrity

The database is the recovery boundary. A new repository instance reconstructs
heads from the persisted projection and verified current revision. Revision
history, quarantine, open conflicts, transitions, event sequence, and
idempotency records survive restart. No incomplete mutation is replayed
automatically.

Reads verify:

- evaluation, extraction, candidate, transition, conflict, duplicate, event,
  and revision-record hashes;
- row IDs and denormalized index columns against canonical JSON;
- candidate head against its current revision;
- revision parent existence and content hash;
- conflict/duplicate signatures against referenced stable heads.

Corruption produces a clear integrity exception. The store never repairs,
projects, or silently accepts a manipulated record.

## Privacy boundary

The schema permits bounded domain metadata, enums, IDs, digests, typed
propositions, and evidence references. It does not persist complete prompts,
model answers, chats, tool outputs, browser data, webpages, note contents,
audio, screenshots, cookies, tokens, credentials, chain of thought, or
reasoning tokens.

## Known limits and later integration

This phase does not resolve open conflicts and deliberately provides no
promotion or active state. SQLite write concurrency is serialized; the CAS
contract exposes stale revisions rather than retrying an unknown mutation.
Independence quality still depends on canonical lineage supplied during
extraction.

Future separately approved work may connect these verified heads and histories
to a skill registry, verification/promotion workflow, API, and UI. Skill
execution, routing learning, promotion, and activation must not bypass the
revision, quarantine, idempotency, or integrity boundaries defined here.
