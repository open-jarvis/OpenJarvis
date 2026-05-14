# Serena Google Calendar Full Operator v1

Legacy source:

- `legacy/serena-skills/04-calendar.js`

Goal:

Turn Serena Google Calendar into a full calendar and scheduling operator.

Primary role:

Serena should manage Google Calendar better than a human assistant by reading, searching, scheduling, checking availability, creating appointments/reminders, updating events, creating Meet links, producing schedule briefs, and reporting exactly what changed.

Legacy triggers:

- BOOK SLOT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE
- CANCEL APPOINTMENT:

Target capability:

inspect -> search -> availability -> create -> update -> reschedule -> remind -> meet -> brief -> audit -> safety report

Required v1 commands:

Foundation:
- calendar status
- calendar env-check
- calendar connect-check
- calendar plan

Read/search:
- calendar today
- calendar upcoming
- calendar search
- calendar event-info
- calendar availability

Create/schedule:
- calendar create
- calendar appointment
- calendar reminder
- calendar meet
- calendar recurring

Update/cancel:
- calendar reschedule
- calendar update
- calendar add-attendee
- calendar cancel
- calendar blocked-bulk-delete

Reports:
- calendar daily-brief
- calendar weekly-brief
- calendar audit

Safety model:

Allowed:
- read calendar events
- search calendar events
- check availability
- create events
- create appointments
- create reminders
- create Google Meet events
- update events
- reschedule events
- add attendees
- cancel specific events with clear report

Blocked or guarded:
- silent deletion
- bulk deletion
- destructive calendar cleanup
- deleting without exact event targeting
- changing attendees without reporting
- exposing credentials
- committing credentials
- creating events without reporting time, calendar, attendees, and link

Operator standard:

Serena should not merely book slots.

Serena should operate Calendar like a professional scheduling assistant:
read context, check conflicts, find availability, create clean events, attach Meet links when useful, update safely, cancel safely, and report exactly what changed.
