# Serena Google Calendar Legacy Inspection Report

Legacy source:

- `legacy\serena-skills\04-calendar.js`

Initial inspection:

- Lines: 183
- Characters: 6910
- Functions found: 1
- Dependencies found: 2
- Triggers found: 4
- Env variable names mentioned: 4

Triggers:

- BOOK SLOT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE
- CANCEL APPOINTMENT:

Environment / integration mentions:

- `CALENDAR`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`

Target:

Serena Google Calendar Full Operator v1 should let Serena read, search, check availability, create appointments/reminders, create Meet events, reschedule, update, cancel specific events safely, produce schedule briefs, audit calendar state, and block destructive/bulk operations.

Required lifecycle:

1. Check Google Calendar configuration without exposing secrets.
2. Connect-check Google Calendar API.
3. Read today's schedule.
4. Search upcoming events.
5. Read event details.
6. Check availability and find open slots.
7. Create appointments and reminders.
8. Create Google Meet events.
9. Create recurring events.
10. Update and reschedule events safely.
11. Add attendees with reporting.
12. Cancel only specific targeted events.
13. Block silent or bulk deletion.
14. Produce daily and weekly briefs.
15. Audit calendar access and safety posture.

Operator standard:

Serena should not merely book slots.
Serena should operate Calendar like a professional scheduling assistant: read context, check conflicts, find availability, create clean events, attach Meet links when useful, update safely, cancel safely, and report exactly what changed.
