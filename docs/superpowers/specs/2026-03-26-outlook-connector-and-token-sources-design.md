# Outlook Connector + Token-Based Source Integration

## Goal

Generalize the Gmail IMAP connector to support Outlook/Microsoft 365, and extend `jarvis deep-research-setup` to detect and connect token-based sources (Slack, Notion, Granola, Gmail IMAP, Outlook) alongside the existing local sources.

## Scope

**In scope:**
- Generalize `gmail_imap.py` to accept an `imap_host` parameter (default `imap.gmail.com`)
- Create `outlook.py` as a thin subclass with `outlook.office365.com` default
- Add `detect_token_sources()` to `deep_research_setup_cmd.py` — scans `~/.openjarvis/connectors/*.json` for already-connected token-based sources
- Add interactive prompts in `deep-research-setup` to connect new token-based sources (Slack, Notion, Granola, Gmail IMAP, Outlook)
- Extend `_instantiate_connector()` to handle all connector types
- Connect and ingest all sources in one unified flow

**Out of scope:**
- Google OAuth token exchange (Drive, Calendar, Contacts still blocked)
- Microsoft Graph API
- Channel plugins (Slack bot, etc.)

## Architecture

### IMAP Generalization

`GmailIMAPConnector` gains one new parameter:

```python
class GmailIMAPConnector(BaseConnector):
    _default_imap_host = "imap.gmail.com"

    def __init__(self, ..., imap_host: str = "") -> None:
        self._imap_host = imap_host or self._default_imap_host
```

The `sync()` method changes from `imaplib.IMAP4_SSL("imap.gmail.com")` to `imaplib.IMAP4_SSL(self._imap_host)`.

### Outlook Connector

A thin subclass in `outlook.py`:

```python
@ConnectorRegistry.register("outlook")
class OutlookConnector(GmailIMAPConnector):
    connector_id = "outlook"
    display_name = "Outlook / Microsoft 365"
    _default_imap_host = "outlook.office365.com"

    def __init__(self, email_address="", app_password="", credentials_path="", *, max_messages=500):
        super().__init__(email_address, app_password,
                         credentials_path or str(DEFAULT_CONFIG_DIR / "connectors" / "outlook.json"),
                         max_messages=max_messages)

    def auth_url(self) -> str:
        return "https://account.microsoft.com/security"

    def sync(self, *, since=None, cursor=None) -> Iterator[Document]:
        # Delegate to parent but override source/doc_id prefix
        for doc in super().sync(since=since, cursor=cursor):
            doc.source = "outlook"
            doc.doc_id = doc.doc_id.replace("gmail:", "outlook:", 1)
            yield doc
```

### Token Source Detection in deep-research-setup

New function `detect_token_sources()`:

```python
_TOKEN_SOURCES = [
    {"connector_id": "gmail_imap", "display_name": "Gmail (IMAP)", "creds_file": "gmail_imap.json"},
    {"connector_id": "outlook", "display_name": "Outlook", "creds_file": "outlook.json"},
    {"connector_id": "slack", "display_name": "Slack", "creds_file": "slack.json"},
    {"connector_id": "notion", "display_name": "Notion", "creds_file": "notion.json"},
    {"connector_id": "granola", "display_name": "Granola", "creds_file": "granola.json"},
]
```

For each: check if `~/.openjarvis/connectors/{creds_file}` exists with valid content. If so, include it as an already-connected source.

### Interactive Connect Flow

For sources not yet connected, `deep-research-setup` offers to connect them:

```
Detected Sources:
  Apple Notes       ready (local)
  iMessage          ready (local)

Available to Connect:
  Gmail (IMAP)      not connected
  Outlook           not connected
  Slack             not connected
  Notion            not connected
  Granola           not connected

Connect additional sources? [y/N]: y
Which source? [gmail_imap/outlook/slack/notion/granola]: slack
Paste your Slack token (xoxb-... or xoxe-...): xoxe-1-...
  Slack: connected!

Connect another? [y/N]: y
...
```

Each connector's `handle_callback()` saves the credential. Then all connected sources are ingested together.

### Connector Credential Formats

| Connector | Credential Format | `handle_callback` Input |
|-----------|------------------|------------------------|
| Gmail IMAP | `{"email": "...", "password": "..."}` | `email:password` |
| Outlook | `{"email": "...", "password": "..."}` | `email:password` |
| Slack | `{"token": "..."}` | Raw token |
| Notion | `{"token": "..."}` | Raw token |
| Granola | `{"token": "..."}` | Raw token |

## Test Plan

- Test `OutlookConnector` inherits IMAP behavior with fake IMAP server (same pattern as gmail_imap tests)
- Test `detect_token_sources()` finds connected sources from credential files
- Test `detect_token_sources()` skips sources with missing/empty credential files
- Test interactive connect saves credentials correctly
