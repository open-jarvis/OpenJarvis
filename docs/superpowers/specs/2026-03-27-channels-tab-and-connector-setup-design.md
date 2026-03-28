# Channels Tab + Seamless Connector Setup

## Goal

Add a Channels tab to every agent for bidirectional messaging (iMessage, Slack, WhatsApp, SMS), and build per-connector step-by-step setup guides in the wizard with one-click OAuth where available.

## Sub-project 1: Channels Tab on Every Agent

### What it does

A new "Channels" tab on the agent detail page showing messaging interfaces to reach the agent. Users can connect/disconnect channels from the UI. Appears on ALL agents.

### Frontend

Add a 7th tab "Channels" to the agent detail view in `AgentsPage.tsx`. Content:

- Header: "Talk to this agent from" + "+ Add Channel" button
- Channel list: iMessage, Slack, WhatsApp, SMS (Twilio)
- Each channel shows: icon, name, description, status badge (Active/Not connected)
- Connected channels expand to show: monitored contact/workspace, instructions, Stop/Settings buttons
- Disconnected channels show a "Connect" button

**"+ Add Channel" / "Connect" flow:**
- Opens a modal/inline form specific to the channel type:
  - **iMessage:** prompt for phone number or contact to monitor → starts daemon
  - **Slack:** prompt for bot token → registers webhook
  - **WhatsApp:** prompt for access token + phone number ID → registers webhook
  - **SMS:** prompt for Twilio account SID + auth token + phone number → registers webhook

### Backend

- `POST /v1/managed-agents/{id}/channels` — bind a channel (creates binding + starts daemon/webhook)
- `DELETE /v1/managed-agents/{id}/channels/{binding_id}` — unbind (stops daemon/webhook)
- `AgentManager.add_channel_binding()` already exists — wire it to the new endpoint
- For iMessage: the endpoint starts/stops the `imessage_daemon` via the existing `run_daemon`/`stop_daemon` functions
- For Slack/WhatsApp/SMS: the endpoint updates `ChannelBridge` channel config

### No new daemon code

`imessage_daemon.py`, `ChannelBridge`, `webhook_routes.py`, and `channels_cmd.py` already exist. This sub-project wires them to the frontend UI.

---

## Sub-project 2: Seamless Connector Setup

### What it does

Replace the current generic "paste token" connect flow with per-connector step-by-step guides. Two patterns:

**Pattern A — Step-by-step guide (for token/password auth):**
Numbered steps with direct links to settings pages, then paste credentials.

**Pattern B — One-click OAuth + manual fallback:**
Primary "Authorize" button opens the service in browser. Manual token paste as secondary option.

### Per-connector flows

| Connector | Pattern | UX |
|-----------|---------|-----|
| Gmail IMAP | A | Steps: enable 2FA → generate app password → paste email:password |
| Outlook | A | Steps: enable 2FA → generate app password → paste email:password |
| Slack | B | "Open Slack App Settings" button → paste bot token (xoxb-...) |
| Notion | B | "Open Notion Integrations" button → paste token (ntn_...) → remind to share pages |
| Granola | A | Steps: open Granola app → Settings → API → paste key (grn_...) |
| Google Drive | B | "Authorize" opens OAuth consent URL → localhost callback captures code → exchanges for tokens |
| Google Calendar | B | Same as Drive (shared OAuth client, different scope) |
| Google Contacts | B | Same as Drive (shared OAuth client, different scope) |
| Obsidian | Filesystem | Path input field |
| Apple Notes | Auto | Check Full Disk Access, auto-connect |
| iMessage | Auto | Check Full Disk Access, auto-connect |

### Google OAuth proper flow (new)

The current Gmail OAuth connector saves the raw auth code without exchanging it. Fix:

1. Add `OAuthCallbackServer` — a tiny localhost HTTP server at `http://localhost:8789/callback` that:
   - Waits for Google to redirect with `?code=...`
   - Exchanges the code for access_token + refresh_token via `POST https://oauth2.googleapis.com/token`
   - Stores tokens in `~/.openjarvis/connectors/{connector}.json`
   - Returns a "Success! You can close this tab" page to the browser

2. Update `oauth.py` with `exchange_google_token(code, client_id, client_secret, redirect_uri)` function

3. Update `handle_callback()` in Gmail, Drive, Calendar, Contacts connectors to use the exchange flow

4. Google OAuth client ID/secret stored in `~/.openjarvis/config.toml` under `[connectors.google]` — user provides their own from Google Cloud Console

### Frontend changes

In `SourceConnectFlow.tsx`, replace the generic OAuth panel with connector-specific panels:

- Each connector gets its own instructions component
- Step-by-step connectors show numbered cards with links
- OAuth connectors show the "Authorize" button + manual fallback input
- All connectors show a "Read-only access · No data leaves your device" badge

### What does NOT change

- SourcePicker (already lists all connectors)
- IngestDashboard (already shows progress)
- ReadyScreen (already shows suggestions)
- Backend connector sync logic (already works)
- KnowledgeStore / ingestion pipeline

## Test Plan

### Channels Tab
- Channels tab appears on all agents (not just DeepResearch)
- Binding iMessage channel starts daemon and shows "Active" status
- Unbinding stops daemon
- Channel status updates in real-time
- Multiple agents can bind different channels

### Connector Setup
- Gmail IMAP: step-by-step flow → paste credentials → connected
- Notion: one-click opens integration page → paste token → connected
- Slack: paste bot token → connected
- Google Drive: OAuth consent URL opens → localhost callback exchanges token → connected
- Setup wizard completes with all connected sources ingested
- Read-only guarantee maintained across all connectors
