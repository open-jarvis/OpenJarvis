# Channels + Messaging Tabs — Unified Agent Setup

## Goal

Replace the current disconnected setup experience with two new tabs on every agent detail page: **Channels** (data sources the agent can search) and **Messaging** (ways to talk to the agent from your phone). Clicking "+ Add" on an unconnected source opens step-by-step setup inline.

## Tab Structure

```
Overview | Interact | Channels | Messaging | Tasks | Memory | Learning | Logs
```

### Channels Tab

Shows all data source connectors with their connection status and chunk counts.

**Connected sources** — green border, checkmark, chunk count:
- Gmail (1,076 chunks) ✓
- iMessage (52,956 chunks) ✓
- Granola (1,144 chunks) ✓
- etc.

**Not connected** — dashed border, "+ Add" button:
- Google Drive — Not connected [+ Add]
- Calendar — Not connected [+ Add]
- Outlook — Not connected [+ Add]

Clicking "+ Add" expands inline with the StepByStepPanel (per-connector instructions, links to settings pages, input fields for credentials). Same flow currently in the setup wizard but embedded in the tab.

**Data shown per connected source:**
- Icon + name
- Chunk count (from KnowledgeStore)
- Connection status
- Disconnect option (on hover/click)

### Messaging Tab

Shows ways to reach the agent from your phone or other platforms.

**Active channels** — green border, clear instructions:
- iMessage: "Text +1 (408) 981-9553 from your iPhone" [Active]
- Slack: "DM @jarvis in your workspace" [Active]

**Not set up** — dashed border, "Set Up" button:
- WhatsApp — Not set up [Set Up]
- SMS (Twilio) — Not set up [Set Up]

The key UX principle: **tell the user what to do, don't ask them for config.** Active channels show the action ("Text this number"), not the plumbing ("Enter phone number to monitor").

### What Changes vs Current

| Before | After |
|--------|-------|
| Separate "Channels" tab with confusing "phone number to monitor" prompt | **Messaging** tab with clear "Text this number" instructions |
| Setup wizard only during onboarding, hidden after | **Channels** tab shows all sources with inline "+ Add" |
| No way to see connected data sources on agent page | **Channels** tab shows all with chunk counts |
| Connector setup disconnected from agent | Unified on the agent page |

### What Does NOT Change

- Overview tab (stats, config, instruction)
- Interact tab (chat)
- Tasks, Memory, Learning, Logs tabs
- Backend API endpoints (already exist)
- Connector sync logic
- iMessage daemon / ChannelBridge / webhook routes

### Backend Requirements

One new endpoint needed:

`GET /v1/connectors/status` — returns all connectors with connection status AND chunk counts from KnowledgeStore. The Channels tab calls this to populate the grid.

Everything else (bind/unbind channel, connect/disconnect source, sync status) already exists.

## Test Plan

- Channels tab shows connected sources with chunk counts
- Channels tab shows unconnected sources with "+ Add"
- Clicking "+ Add" shows step-by-step instructions inline
- Completing setup adds the source and starts ingestion
- Messaging tab shows active channels with clear action text
- Messaging tab shows "Set Up" for inactive channels
- Setting up iMessage starts the daemon
- Both tabs appear on ALL agents, not just DeepResearch
