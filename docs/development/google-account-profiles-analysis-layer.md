# Google Account Profiles: Analysis Layer Plan

This note extends the Google connector profile work from the connect/auth layer
into analysis, retrieval, citations, and test coverage.

## Goal

Named Google profiles should not stop at token storage. Once users connect
accounts such as `personal`, `work`, `research`, `subscriptions`, or `banqer`,
OpenJarvis should preserve that account boundary through indexing and analysis
so a query can intentionally search one persona, several personas, or all
indexed Google data.

## Data Model

Connector documents now carry profile metadata:

```python
metadata = {
    "account": "work",
    "source_profile": "work",
    "connector": "gmail",
}
```

Google document IDs are also account-aware where applicable, for example:

```text
gmail:work:<message-id>
gdrive:research:<file-id>
gcalendar:family:<event-id>
```

The knowledge store exposes both plain connector IDs and account-scoped IDs in
`distinct_sources()`:

```text
gmail
gmail:work
gdrive:research
gcalendar:family
```

## Retrieval Semantics

Analysis supports two equivalent scoping styles:

```python
store.retrieve("renewals", source="gmail:work")
hybrid.search("renewals", sources=["gmail"], accounts=["work"])
```

The first form is useful for direct retrieval and config-style source lists.
The second form is useful for planners because account aliases can be combined
with multiple connectors:

```python
hybrid.search(
    "calendar conflicts",
    sources=["gcalendar"],
    accounts=["personal", "work"],
)
```

`HybridSearch` applies account filters with
`json_extract(metadata, '$.account')`, so source and account filters intersect
instead of overwriting each other. For example, `sources=["gdrive"]` plus
`accounts=["work"]` returns work Drive chunks, not work Gmail or personal Drive.

## Planner Behavior

The research loop exposes a structured `accounts` search parameter:

```python
search(query, person=None, time_range=None, sources=None, accounts=None, limit=20)
```

Planner rules now tell the model:

- Use `sources=[...]` when the user names a connector such as Gmail, Drive, or
  Calendar.
- Use account-scoped source IDs such as `gmail:work` only when they appear in
  the connected-sources list.
- Use `accounts=[...]` when the user names a persona/profile/account such as
  "work account", "personal Drive", or "research calendar".
- Combine both filters when the user names both a connector and an account, for
  example `sources=["gmail"], accounts=["work"]`.

Example user requests:

```text
Summarize only my work email and calendar.
Search my research Drive, not personal Drive.
What overlaps between my personal calendar and project calendar?
Find docs related to x0bni across my project account and personal notes.
```

## Citation And UI Metadata

Search hits now include:

```python
SearchHit.account
SearchHit.source_profile
```

`build_sources_for_client()` passes both fields through to the citation payload
so the UI can render provenance such as `Gmail / work` and follow-up queries can
preserve the same profile scope.

## Sync API

The connector sync API accepts an optional account query parameter:

```text
POST /api/connectors/{connector_id}/sync?account=work
GET  /api/connectors/{connector_id}/sync-status?account=work
```

Sync state is keyed by connector/profile pair. A long-running `gmail:work` sync
does not hide or overwrite `gmail:personal` status.

## Migration

For a clean install that already has one legacy Google profile:

```bash
jarvis connect google --account work
```

This creates a fresh token at:

```text
~/.openjarvis/connectors/google/accounts/work.json
```

If reauthenticating is not desirable, copy the legacy token:

```bash
mkdir -p ~/.openjarvis/connectors/google/accounts
cp ~/.openjarvis/connectors/google.json \
  ~/.openjarvis/connectors/google/accounts/work.json
```

Then run a profile sync so newly indexed chunks receive account metadata.

## Test Plan

Connector/auth/profile tests:

```bash
uv run --extra dev pytest \
  tests/connectors/test_oauth_flow.py \
  tests/connectors/test_gmail.py \
  tests/connectors/test_store.py \
  tests/cli/test_connect.py
```

Analysis-layer tests:

```bash
uv run --extra dev pytest \
  tests/agents/test_research_loop.py \
  tests/connectors/test_hybrid_search.py
```

Lint:

```bash
uv run --extra dev ruff check \
  src/openjarvis/agents/research_loop.py \
  src/openjarvis/connectors/hybrid_search.py \
  src/openjarvis/server/connectors_router.py \
  tests/agents/test_research_loop.py \
  tests/connectors/test_hybrid_search.py
```
