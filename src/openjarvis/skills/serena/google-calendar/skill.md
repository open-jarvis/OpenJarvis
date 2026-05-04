# Serena Google Calendar Full Operator v1

Status: complete_v1_pending_live_token

Legacy source:
- legacy/serena-skills/04-calendar.js

Legacy triggers:
- BOOK SLOT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE
- CANCEL APPOINTMENT:

Purpose:
Serena Google Calendar is the scheduling, availability, appointment, reminder, Google Meet, update, cancellation safety, brief, and audit operator.

Important live-token note:
The Google Calendar operator is code-complete and safety-tested. Live Calendar API read/write tests are pending because Dr Piet must approve a new Google refresh token with Calendar scopes.

Required scopes for shared Google token:
- https://www.googleapis.com/auth/drive
- https://www.googleapis.com/auth/documents
- https://www.googleapis.com/auth/calendar
- https://www.googleapis.com/auth/calendar.events

Core commands:
- status
- env-check
- connect-check
- plan
- today
- upcoming
- search
- event-info
- availability
- create
- appointment
- reminder
- meet
- recurring
- reschedule
- update
- add-attendee
- cancel
- blocked-bulk-delete
- daily-brief
- weekly-brief
- audit

Capabilities:
- Check configuration without exposing secrets.
- Connect-check Calendar API.
- Read today's schedule.
- Read upcoming events.
- Search calendar events.
- Read event details.
- Check busy blocks and availability.
- Create events.
- Create structured appointments.
- Create reminders/follow-ups.
- Create Google Meet events.
- Create recurring events.
- Reschedule specific events.
- Update specific event fields.
- Add attendees with reporting.
- Cancel one specific event only with explicit approval.
- Block silent deletion, bulk deletion, and destructive cleanup.
- Produce daily and weekly briefs.
- Audit Calendar readiness, token state, and safety posture.

Safety:
- Silent deletion is blocked.
- Bulk deletion is blocked.
- Destructive calendar cleanup is blocked.
- Cancelling a specific event requires --approved.
- Event changes must report title, time, calendar, attendees, links, and changed fields.
- Secrets must never be exposed.
- Credentials must never be committed.

Operator standard:
Serena should not merely book slots. Serena should operate Calendar like a professional scheduling assistant: read context, check conflicts, find availability, create clean events, attach Meet links when useful, update safely, cancel safely, and report exactly what changed.

Dr Piet token approval:
When Dr Piet can approve Google verification, regenerate GOOGLE_REFRESH_TOKEN with Drive + Docs + Calendar scopes, then test:
uv run serena gdrive connect-check
uv run serena google-docs connect-check
uv run serena calendar connect-check
uv run serena calendar today
uv run serena calendar create --title "Serena Calendar Live Proof" --start "YYYY-MM-DDTHH:MM" --end "YYYY-MM-DDTHH:MM"
