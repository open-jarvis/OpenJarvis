// 04-calendar.js — Google Calendar & Scheduling
// Uses googleapis SDK. All API calls properly awaited.
// DEFERRED: SMS/WhatsApp reminders (enable when WhatsApp goes live)

const { google } = require('googleapis');
const logger = require('../helpers/logger');

function getCalendarClient() {
  const auth = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET
  );
  auth.setCredentials({ refresh_token: process.env.GOOGLE_REFRESH_TOKEN });
  return google.calendar({ version: 'v3', auth });
}

module.exports = {
  id: '04-calendar',
  name: 'Google Calendar & Scheduling',
  description: 'Book appointments, check availability, list today\'s events.',
  triggers: ['BOOK SLOT:', 'CHECK AVAILABILITY:', 'TODAY SCHEDULE', 'CANCEL APPOINTMENT:'],

  execute: async function (payload, context) {
    try {
      const calendar = getCalendarClient();

      // ── TODAY SCHEDULE ───────────────────────────────────────
      if (context.triggerUsed === 'TODAY SCHEDULE') {
        const now = new Date();
        const startOfDay = new Date(now);
        startOfDay.setHours(0, 0, 0, 0);
        const endOfDay = new Date(now);
        endOfDay.setHours(23, 59, 59, 999);

        // FIX: properly awaited
        const res = await calendar.events.list({
          calendarId: 'primary',
          timeMin: startOfDay.toISOString(),
          timeMax: endOfDay.toISOString(),
          singleEvents: true,
          orderBy: 'startTime'
        });

        const events = res.data.items || [];
        if (events.length === 0) {
          return { response: '📅 *No appointments scheduled for today.*\n\nUse `BOOK SLOT:` to add one.' };
        }

        const list = events.map(e => {
          const start = e.start.dateTime
            ? new Date(e.start.dateTime).toLocaleTimeString('en-ZA', { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Johannesburg' })
            : 'All day';
          return `• ${start} — ${e.summary}`;
        }).join('\n');

        logger.info(`[CALENDAR] Today: ${events.length} events`);
        return { response: `📅 *Today's schedule (${events.length} events):*\n\n${list}` };
      }

      // ── BOOK SLOT ────────────────────────────────────────────
      if (context.triggerUsed === 'BOOK SLOT:') {
        if (!payload || payload.trim().length < 5) {
          return {
            response:
              '⚠️ Usage: `BOOK SLOT: Patient Name | YYYY-MM-DD | HH:MM | duration_minutes`\n' +
              'Example: `BOOK SLOT: John Smith | 2025-08-15 | 09:00 | 30`'
          };
        }

        const parts = payload.split('|').map(p => p.trim());
        if (parts.length < 3) {
          return { response: '⚠️ Please provide: Patient Name | Date | Time (and optionally duration in minutes).' };
        }

        const [patientName, date, time, durationStr = '30'] = parts;
        const duration = parseInt(durationStr, 10) || 30;

        const startDateTime = new Date(`${date}T${time}:00`);
        if (isNaN(startDateTime.getTime())) {
          return { response: `⚠️ Invalid date/time: ${date} ${time}. Use YYYY-MM-DD and HH:MM.` };
        }

        const endDateTime = new Date(startDateTime.getTime() + duration * 60000);

        // Check availability first
        const busyRes = await calendar.freebusy.query({
          requestBody: {
            timeMin: startDateTime.toISOString(),
            timeMax: endDateTime.toISOString(),
            items: [{ id: 'primary' }]
          }
        });

        const busy = busyRes.data.calendars.primary.busy || [];
        if (busy.length > 0) {
          return {
            response:
              `⚠️ *Time slot unavailable*\n\n` +
              `${date} at ${time} is already booked.\n` +
              `Use \`CHECK AVAILABILITY: ${date}\` to see free slots.`
          };
        }

        // FIX: properly awaited
        const event = await calendar.events.insert({
          calendarId: 'primary',
          requestBody: {
            summary: `Patient Consultation — ${patientName}`,
            description: `Booked via Serena for ${patientName}`,
            start: {
              dateTime: startDateTime.toISOString(),
              timeZone: 'Africa/Johannesburg'
            },
            end: {
              dateTime: endDateTime.toISOString(),
              timeZone: 'Africa/Johannesburg'
            }
          }
        });

        logger.info(`[CALENDAR] Booked: ${patientName} on ${date} at ${time}`);
        return {
          response:
            `✅ *Appointment booked*\n\n` +
            `👤 *Patient:* ${patientName}\n` +
            `📅 *Date:* ${date}\n` +
            `🕐 *Time:* ${time} (${duration} min)\n` +
            `🔑 *Event ID:* \`${event.data.id}\``
        };
      }

      // ── CHECK AVAILABILITY ───────────────────────────────────
      if (context.triggerUsed === 'CHECK AVAILABILITY:') {
        const date = payload.trim() || new Date().toISOString().split('T')[0];
        const start = new Date(`${date}T08:00:00`);
        const end = new Date(`${date}T18:00:00`);

        // FIX: properly awaited
        const res = await calendar.events.list({
          calendarId: 'primary',
          timeMin: start.toISOString(),
          timeMax: end.toISOString(),
          singleEvents: true,
          orderBy: 'startTime'
        });

        const events = res.data.items || [];
        const bookedTimes = events.map(e => ({
          start: new Date(e.start.dateTime || e.start.date),
          end: new Date(e.end.dateTime || e.end.date),
          name: e.summary
        }));

        // Generate free 30-min slots between 08:00 and 17:30
        const freeSlots = [];
        for (let h = 8; h < 18; h++) {
          for (let m = 0; m < 60; m += 30) {
            const slotStart = new Date(`${date}T${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:00`);
            const slotEnd = new Date(slotStart.getTime() + 30 * 60000);
            const isBusy = bookedTimes.some(b => slotStart < b.end && slotEnd > b.start);
            if (!isBusy) {
              freeSlots.push(`• ${slotStart.toLocaleTimeString('en-ZA', { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Johannesburg' })}`);
            }
          }
        }

        logger.info(`[CALENDAR] Availability checked for ${date}`);
        return {
          response:
            `📅 *Available slots on ${date}:*\n\n` +
            (freeSlots.length > 0 ? freeSlots.join('\n') : '❌ No free slots — fully booked.') +
            `\n\nUse \`BOOK SLOT: Name | ${date} | HH:MM\` to book.`
        };
      }

      return { response: '⚠️ Unknown calendar command. Try: `TODAY SCHEDULE`, `BOOK SLOT:`, or `CHECK AVAILABILITY:`' };

    } catch (err) {
      logger.error('[CALENDAR] Error:', err.message);
      return { response: `❌ Calendar error: ${err.message}\n\n_Check Google credentials in .env_` };
    }
  }
};
