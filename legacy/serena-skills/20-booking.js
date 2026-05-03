// 20-booking.js — Patient Booking System
// Bridges between the Telegram bot and Google Calendar (04-calendar.js pattern).
// Adds booking confirmation messaging, conflict detection, and patient DB logging.

const { google } = require('googleapis');
const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

function getCalendarClient() {
  const auth = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET
  );
  auth.setCredentials({ refresh_token: process.env.GOOGLE_REFRESH_TOKEN });
  return google.calendar({ version: 'v3', auth });
}

module.exports = {
  id: '20-booking',
  name: 'Patient Booking System',
  description: 'Schedule, view, and cancel patient appointments via Google Calendar.',
  triggers: ['BOOK APPOINTMENT:', 'NEW BOOKING:', 'MY BOOKINGS', 'CANCEL BOOKING:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_20_booking',
      description: 'Create, list, and cancel patient bookings.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['BOOK APPOINTMENT:', 'NEW BOOKING:', 'MY BOOKINGS', 'CANCEL BOOKING:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      logger.info(`[BOOKING] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      const calendarConfigured = !!(
        process.env.GOOGLE_CLIENT_ID &&
        process.env.GOOGLE_CLIENT_SECRET &&
        process.env.GOOGLE_REFRESH_TOKEN
      );

      // ── MY BOOKINGS ─────────────────────────────────────────────
      if (context.triggerUsed === 'MY BOOKINGS') {
        if (!calendarConfigured) {
          return { response: '⚠️ Google Calendar not configured. Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN to .env' };
        }

        const calendar = getCalendarClient();
        const now      = new Date();
        const in30Days = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);

        const res = await calendar.events.list({
          calendarId:   'primary',
          timeMin:      now.toISOString(),
          timeMax:      in30Days.toISOString(),
          singleEvents: true,
          orderBy:      'startTime',
          maxResults:   20
        });

        const events = res.data.items || [];
        if (events.length === 0) {
          return { response: '📅 No upcoming appointments in the next 30 days.\n\nUse `BOOK APPOINTMENT: Name | Date | Time` to schedule one.' };
        }

        const list = events.map(e => {
          const start = e.start.dateTime
            ? new Date(e.start.dateTime).toLocaleString('en-ZA', { timeZone: 'Africa/Johannesburg', weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
            : e.start.date;
          return `• ${start} — ${e.summary}`;
        }).join('\n');

        return {
          response:
            `📅 *Upcoming Appointments (next 30 days)*\n\n${list}\n\n` +
            `_Use_ \`CANCEL BOOKING: Event ID\` _to cancel._`
        };
      }

      // ── BOOK APPOINTMENT ────────────────────────────────────────
      if (context.triggerUsed === 'BOOK APPOINTMENT:' || context.triggerUsed === 'NEW BOOKING:') {
        if (!payload || payload.trim().length < 5) {
          return {
            response:
              '📅 *Book Appointment*\n\n' +
              'Usage: `BOOK APPOINTMENT: Patient Name | YYYY-MM-DD | HH:MM | duration (min) | type`\n\n' +
              'Examples:\n' +
              '• `BOOK APPOINTMENT: John Smith | 2026-05-15 | 09:00 | 30 | Consultation`\n' +
              '• `BOOK APPOINTMENT: Sarah Jones | 2026-05-16 | 14:30`\n\n' +
              'Duration defaults to 30 minutes. Type defaults to Consultation.'
          };
        }

        if (!calendarConfigured) {
          // Fallback — log to DB only
          const parsed = await generateStructuredOutput(context, {
            logLabel: 'booking-fallback-log',
            reasoningEffort: 'medium',
            systemPrompt: 'Extract a patient booking request from the user instruction.',
            userPrompt:
              `User request: ${payload}\n\n` +
              'Return JSON with name, date, time, duration, type.',
            schema: {
              type: 'object',
              required: ['name', 'date', 'time'],
              properties: {
                name: { type: 'string' },
                date: { type: 'string' },
                time: { type: 'string' },
                duration: { type: 'string' },
                type: { type: 'string' }
              }
            }
          });
          const name = parsed.name;
          const date = parsed.date;
          const time = parsed.time;
          const duration = parsed.duration || '30';
          const type = parsed.type || 'Consultation';

          if (context.db) {
            await context.db.run(
              `INSERT INTO tasks (task_id, name, description, status, skill_name, createdAt, updatedAt)
               VALUES (?, ?, ?, ?, ?, ?, ?)`,
              [
                `BOOK-${Date.now()}`,
                `Appointment: ${name}`,
                `Date: ${date} ${time} | Duration: ${duration}min | Type: ${type}`,
                'pending',
                '20-booking',
                new Date().toISOString(),
                new Date().toISOString()
              ]
            );
          }

          return {
            response:
              `📅 *Appointment Logged*\n\n` +
              `👤 *Patient:* ${name}\n` +
              `📅 *Date:* ${date} at ${time}\n` +
              `⏱️ *Duration:* ${duration} minutes\n` +
              `🩺 *Type:* ${type}\n\n` +
              `⚠️ Google Calendar not configured — logged to internal system only.\n` +
              `Add Google credentials to .env for full calendar sync.`
          };
        }

        const parsed = await generateStructuredOutput(context, {
          logLabel: 'booking-create',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a patient booking request from the user instruction.',
          userPrompt:
            `User request: ${payload}\n\n` +
            'Return JSON with name, date, time, duration, type.',
          schema: {
            type: 'object',
            required: ['name', 'date', 'time'],
            properties: {
              name: { type: 'string' },
              date: { type: 'string' },
              time: { type: 'string' },
              duration: { type: 'string' },
              type: { type: 'string' }
            }
          }
        });
        const name = parsed.name;
        const date = parsed.date;
        const time = parsed.time;
        const duration = parseInt(parsed.duration || '30', 10) || 30;
        const type = parsed.type || 'Consultation';

        const startDT = new Date(`${date}T${time.length === 5 ? time + ':00' : time}`);
        if (isNaN(startDT.getTime())) {
          return { response: `⚠️ Invalid date/time: "${date} ${time}". Use YYYY-MM-DD and HH:MM.` };
        }

        const endDT = new Date(startDT.getTime() + duration * 60000);
        const calendar = getCalendarClient();

        // Check for conflicts
        const busyRes = await calendar.freebusy.query({
          requestBody: {
            timeMin:  startDT.toISOString(),
            timeMax:  endDT.toISOString(),
            items:    [{ id: 'primary' }]
          }
        });

        const busy = busyRes.data.calendars.primary.busy || [];
        if (busy.length > 0) {
          return {
            response:
              `⚠️ *Time slot not available*\n\n` +
              `${date} at ${time} is already booked.\n\n` +
              `Use \`BOOK SLOT: ${date}\` (from 04-calendar) to see free slots.`
          };
        }

        const event = await calendar.events.insert({
          calendarId:  'primary',
          requestBody: {
            summary:     `${type} — ${name}`,
            description: `Patient: ${name}\nType: ${type}\nBooked via Serena`,
            start:       { dateTime: startDT.toISOString(), timeZone: 'Africa/Johannesburg' },
            end:         { dateTime: endDT.toISOString(),   timeZone: 'Africa/Johannesburg' }
          }
        });

        // Save to local DB too
        if (context.db) {
          await context.db.run(
            `INSERT INTO tasks (task_id, name, description, status, skill_name, createdAt, updatedAt)
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
            [
              event.data.id,
              `Appointment: ${name}`,
              `${type} on ${date} at ${time} for ${duration}min`,
              'confirmed',
              '20-booking',
              new Date().toISOString(),
              new Date().toISOString()
            ]
          );
        }

        logger.info(`[BOOKING] Booked: ${name} on ${date} at ${time}`);
        return {
          response:
            `✅ *Appointment Confirmed*\n\n` +
            `👤 *Patient:* ${name}\n` +
            `📅 *Date:* ${date}\n` +
            `🕐 *Time:* ${time} (${duration} min)\n` +
            `🩺 *Type:* ${type}\n` +
            `🔑 *Calendar ID:* \`${event.data.id}\`\n\n` +
            `_Use_ \`TEST REMINDER: ${name} | ${date} at ${time}\` _to send a reminder._`
        };
      }

      // ── CANCEL BOOKING ───────────────────────────────────────────
      if (context.triggerUsed === 'CANCEL BOOKING:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `CANCEL BOOKING: event-id-from-calendar`\n\nGet the ID from `MY BOOKINGS`' };
        }

        if (!calendarConfigured) {
          return { response: '⚠️ Google Calendar not configured. Cannot cancel via calendar.' };
        }

        const eventId  = payload.trim();
        const calendar = getCalendarClient();

        await calendar.events.delete({ calendarId: 'primary', eventId });

        if (context.db) {
          await context.db.run(
            `UPDATE tasks SET status = 'cancelled', updatedAt = ? WHERE task_id = ?`,
            [new Date().toISOString(), eventId]
          );
        }

        logger.info(`[BOOKING] Cancelled event: ${eventId}`);
        return { response: `✅ *Appointment cancelled*\n\nEvent ID: \`${eventId}\`` };
      }

      return { response: '⚠️ Usage: `BOOK APPOINTMENT:`, `MY BOOKINGS`, `CANCEL BOOKING:`' };

    } catch (err) {
      logger.error('[BOOKING] Error:', err.message);
      return { response: `❌ Booking error: ${err.message}` };
    }
  }
};
