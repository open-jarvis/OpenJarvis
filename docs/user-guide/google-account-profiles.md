# Google Account Profiles

OpenJarvis supports named Google profile aliases so multiple Google accounts can
be connected, synced, and searched without overwriting each other's OAuth
tokens. Use aliases such as `personal`, `work`, `subscriptions`,
`kanakia-org-home`, or `banqer` to keep indexed data persona-scoped.

## Connect Profiles

Use `jarvis connect google` when you want one OAuth grant to cover Gmail, Drive,
Calendar, Contacts, and Tasks.

```bash
# Default Google profile
jarvis connect google

# Named profiles
jarvis connect google --account work
jarvis connect google --account personal
jarvis connect google --account subscriptions
```

The connector-specific commands use the same profile store and can also take an
account alias:

```bash
jarvis connect gmail --account work
jarvis connect gdrive --account research
jarvis connect gcalendar --account family
```

`--profile` is accepted as an alias for `--account`.

## Alias Names

Aliases should be short, readable, and stable. They are normalized into safe
directory names, so names such as `aquantive-nirav`, `kanakia.org-home`, and
`banqer` work. Prefer lowercase words separated by `-`, `_`, or `.`.

Avoid putting secrets in alias names. Aliases are used in local file paths,
document IDs, metadata, and source filters.

## Token Storage

Named profiles are stored under:

```text
~/.openjarvis/connectors/google/accounts/<alias>.json
```

Examples:

```text
~/.openjarvis/connectors/google/accounts/work.json
~/.openjarvis/connectors/google/accounts/personal.json
~/.openjarvis/connectors/google/accounts/banqer.json
```

The legacy single-profile token path is still read for compatibility:

```text
~/.openjarvis/connectors/google.json
```

## Migrating A Clean Install With One Existing Profile

If a machine already has one Google connection from before profile aliases,
choose the alias you want that account to become and reconnect:

```bash
jarvis connect google --account work
```

That is the safest path because it creates a fresh profile token in the new
segmented location. Existing indexed data can remain in the knowledge store;
new syncs will write account metadata for the chosen alias.

If you need to preserve the existing token without reauthenticating, copy the
legacy token into the new account directory:

```bash
mkdir -p ~/.openjarvis/connectors/google/accounts
cp ~/.openjarvis/connectors/google.json \
  ~/.openjarvis/connectors/google/accounts/work.json
```

After copying, run a sync for that account so newly indexed chunks receive the
account metadata:

```bash
jarvis connect google --account work
```

## Analysis And Queries

Once profiles have synced, analysis works through the normal research and memory
tools. Each indexed chunk carries account metadata, and source lists expose both
plain connector IDs and scoped connector IDs:

```text
gmail
gmail:work
gdrive:research
gcalendar:family
```

Natural-language examples:

```bash
jarvis ask "Summarize only my work Gmail about subscription renewals"
jarvis ask "Find Drive files from research about the Q3 plan"
jarvis ask "Compare personal calendar and work calendar conflicts this week"
```

The research planner maps these requests to structured filters:

```python
search("subscription renewals", sources=["gmail"], accounts=["work"])
search("Q3 plan", sources=["gdrive"], accounts=["research"])
search("calendar conflicts", sources=["gcalendar"], accounts=["personal", "work"])
```

Direct retrieval can use either scoped source IDs or an account filter:

```python
store.retrieve("subscription renewals", source="gmail:work")
hybrid.search("Q3 plan", sources=["gdrive"], accounts=["research"])
```

## UI And API Sync

The connector sync API accepts an optional `account` query parameter. Use the
real connector routes, not a synthetic `/v1/connectors/google/...` endpoint:

```text
POST /v1/connectors/gmail/sync?account=work
GET  /v1/connectors/gmail/sync?account=work
```

Sync status is tracked per connector/profile pair, so a long sync for
`gmail:work` does not mask the state of `gmail:personal`.

## How To Test

For CLI and connector profile behavior:

```bash
uv run --extra dev pytest \
  tests/connectors/test_oauth_flow.py \
  tests/connectors/test_gmail.py \
  tests/connectors/test_store.py \
  tests/cli/test_connect.py
```

For analysis-layer account filters:

```bash
uv run --extra dev pytest \
  tests/agents/test_research_loop.py \
  tests/connectors/test_hybrid_search.py
```

For linting touched code:

```bash
uv run --extra dev ruff check \
  src/openjarvis/agents/research_loop.py \
  src/openjarvis/connectors/hybrid_search.py \
  src/openjarvis/server/connectors_router.py \
  tests/agents/test_research_loop.py \
  tests/connectors/test_hybrid_search.py
```
