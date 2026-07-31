# Phase 7: evidence-backed learning candidates

## Scope and safety boundary

This phase adds an immutable, metadata-only domain layer between deterministic
trace evaluation and later learning review. Its only runtime input is an
already completed `TraceEvaluation`, explicit typed user feedback, or a
strictly typed metadata proposal. It does not accept raw traces, prompts,
answers, tool output, web content, notes, or optimizer/model judgments.

The implemented flow is:

```text
TraceEvaluation
  -> deterministic extraction
  -> provenance and evidence references
  -> duplicate/conflict signatures
  -> conservative independence groups
  -> quarantine decision
  -> immutable LearningCandidate
```

There is no persistence, promotion, registry, skill execution, production
routing update, model call, network call, or memory/vault write in this layer.

## Candidate schema and states

`LearningCandidate` is a strict frozen Pydantic model (`extra="forbid"`) with
schema version, opaque identity, revision, typed content, scope/project,
origin, evaluation/task/trace/evidence references, provenance, confidence,
independence groups, duplicate and conflict signatures, risk, review and
verification proposals, destination, state, quarantine/rejection details,
UTC timestamps, and a SHA-256 content hash.

The closed candidate types are:

- `fact`
- `user_correction`
- `preference`
- `failure_pattern`
- `successful_solution`
- `routing_rule`
- `skill`
- `test_case`
- `documentation_improvement`
- `code_improvement_proposal`

Each type has a discriminated content model. Successful solutions contain only
typed evidence references, never trace steps or arguments. Skill candidates
contain declarative schemas, tool IDs, pre/postconditions, negative cases,
risk and rollback metadata; they contain no executable body. Routing rules are
always shadow recommendations. Code-improvement candidates contain a problem,
safety boundaries, proposed tests, and expected behavior; `contains_patch` is
fixed to false.

The only states in this phase are `proposed`, `under_review`, `rejected`, and
`quarantined`. Automatic extraction can end only in `proposed` or
`quarantined`. Verified, promoted, testing, pending-promotion, and active
states intentionally do not exist yet.

## Extraction rules

A `successful_solution` is extracted automatically only when the canonical
class is `completed` or `completed_with_warning`, verification passed,
evidence is sufficient, confidence is medium or high, and no tool action is
failed, denied, canceled, pending, unknown, or of unknown effect. Canonical
warnings are retained as bounded limitations.

A `failure_pattern` is extracted only for the specific technical classes
`verification_failed`, `tool_failed`, `browser_failed`, and
`conflicting_evidence`. Cancellation, interruption, policy/approval denial,
partial completion, insufficient evidence, and unknown failure do not become
technical failure rules. Conflicting evidence is immediately quarantined.

Facts and preferences require explicit typed user confirmation. Corrections
require an explicit typed user-correction record. Task success alone can never
create any of them. A skill metadata request must reference verified successful
evaluations and remains only proposed. A routing request remains in shadow mode.
Missing or unsuitable evaluation lineage causes quarantine, not an inferred
claim.

## Provenance and evidence binding

Every normal candidate carries typed provenance. Allowed source kinds are
deterministic trace evaluation, explicit user feedback/correction,
deterministic test result, policy record, and verification record. Provenance
records bind source IDs and digests to a trusted boundary, extraction method,
extractor version, and optional evaluation ID.

Raw model answers, model-judge scores, webpages, documents, tool outputs,
imported skill text, legacy-success claims, and optimizer recommendations are
represented only as untrusted source signals. They force quarantine and are
never stored as candidate payloads. Unknown source enum values are rejected.

## Deduplication and deterministic hashing

The duplicate signature hashes canonical JSON containing candidate type,
scope, case-normalized project, normalized type-specific content, destination,
and risk boundary. It excludes candidate identity, timestamps, revision,
source order, and provenance-only evaluation IDs. Evidence references with the
same semantic evidence types can therefore enrich one candidate instead of
creating copies. Different projects, scopes, content, destinations, or safety
boundaries remain distinct.

Duplicate candidates are merged without deleting provenance. Evaluation,
task, trace, evidence, provenance, test, verification, and independence
references are unioned deterministically. Duplicate links record whether the
overlap was the same evaluation, task lineage, or semantic content.

Candidate content hashes exclude random candidate/provenance identities and
wall-clock timestamps. Extraction run hashes use candidate content hashes and
semantic duplicate/conflict links, not run/candidate IDs or time. Identical
semantic inputs and extractor versions therefore yield identical run hashes
across ordering and process boundaries.

## Independence analysis

Independence is not a source count. Evaluations are conservatively joined by
the same task ID, trace ID, input digest, declared thread, retry/root/parent
task lineage, or replayed trace lineage. Sessions, task IDs, traces, input
digests, and declared lineage are retained in auditable group digests.

Consequently, repeated events, evaluator-version reruns, retries, resumes, and
replays do not inflate the count. Separate synthetic tasks can contribute
separate groups. Repeated use of one explicit feedback record is grouped by its
stable feedback-group ID.

## Conflict detection

Conflict detection compares stable proposition keys and preserves both sides.
It covers differing values for one fact, routes for one condition, incompatible
skill contracts (including pre/postconditions, allowlists, and risk), success
versus verified failure for one task type, explicit corrections targeting
another candidate, and differing safety boundaries. Each link references both
candidates and has a deterministic pair signature.

Explicit user correction receives source priority in the link, but there is no
automatic winner. All conflicted candidates are retained and quarantined for
review.

## Quarantine and privacy

Quarantine rules cover prompt injection, secret-like data, executable code and
shell text, encoded executable instructions, unknown or missing provenance,
manipulated evaluation hashes, legacy-only claims, conflicting evidence,
capability escalation, risk lowering, approval instructions, `full_access`,
external URLs, raw private payload markers, and chain-of-thought requests.
Direct secret or executable-code content is rejected during schema validation;
other unsafe typed proposals are retained only in quarantine for audit.

Candidate schemas contain IDs, digests, enums, bounded redacted summaries,
structured propositions, and evidence references. They contain no complete
prompts, responses, chats, tool outputs, browser DOM, webpages, note contents,
audio, screenshots, cookies, tokens, credentials, chain of thought, or
reasoning tokens.

Quarantine has no promotion, activation, skill execution, memory write, or
routing effect.

## Known limits and later phases

This commit deliberately does not decide whether a candidate is true or useful
beyond deterministic canonical evidence gates. Conflict handling does not
resolve a winner. Independence depends on the lineage metadata supplied by the
caller; missing lineage is handled conservatively. The domain does not store or
query candidates.

Later, separately approved commits may add a persistent learning store, review
and promotion state machine, skill registry, and controlled promotion. Those
layers must consume these immutable records and preserve their provenance,
quarantine, review, and deterministic-hash boundaries; they are not part of
this phase.
