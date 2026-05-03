const { google } = require('googleapis');
const logger = require('../helpers/logger');

function getCalendarClient() {
  if (!process.env.GOOGLE_CLIENT_ID || !process.env.GOOGLE_CLIENT_SECRET || !process.env.GOOGLE_REFRESH_TOKEN) {
    return null;
  }

  const auth = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET
  );
  auth.setCredentials({ refresh_token: process.env.GOOGLE_REFRESH_TOKEN });
  return google.calendar({ version: 'v3', auth });
}

async function listUpcomingAppointments(hoursAhead = 24) {
  const calendar = getCalendarClient();
  if (!calendar) {
    throw new Error('Google Calendar is not configured');
  }

  const now = new Date();
  const until = new Date(now.getTime() + (hoursAhead * 60 * 60 * 1000));
  const response = await calendar.events.list({
    calendarId: 'primary',
    timeMin: now.toISOString(),
    timeMax: until.toISOString(),
    singleEvents: true,
    orderBy: 'startTime',
    maxResults: 20
  });

  return response.data.items || [];
}

function buildReminderMessage(patientName, appointmentTime) {
  return (
    `Appointment Reminder\n\n` +
    `Hello ${patientName},\n\n` +
    `This is a friendly reminder that you have an appointment with Dr Piet Muller ${appointmentTime}.\n\n` +
    `Location: drpiet.co.za/consult (online) or as arranged\n` +
    `Please have your ID, medical aid card, and any recent test results ready.\n\n` +
    `If you need to reschedule, please reply as early as possible.\n\n` +
    `Dr Piet Muller Practice`
  );
}

module.exports = {
  id: '58-ApptReminders',
  name: 'Appointment Reminders',
  description: 'Preview, queue, and monitor appointment reminders for upcoming consultations.',
  triggers: ['SEND REMINDERS', 'REMINDER STATUS', 'TEST REMINDER:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_58_appt_reminders',
      description: 'Preview and manage appointment reminders for upcoming calendar appointments.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['SEND REMINDERS', 'REMINDER STATUS', 'TEST REMINDER:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      if (context.triggerUsed === 'TEST REMINDER:') {
        if (!payload || payload.trim().length < 3) {
          return { response: 'Usage: TEST REMINDER: Patient Name | appointment time' };
        }

        const parts = payload.split('|').map((part) => part.trim());
        const patientName = parts[0] || 'Patient';
        const appointmentTime = parts[1] || 'tomorrow at 09:00';
        const reminderMsg = buildReminderMessage(patientName, appointmentTime);

        if (context.bot && context.chatId) {
          await context.bot.sendMessage(context.chatId, reminderMsg).catch(() => {});
        }

        logger.info(`[REMINDERS] Test reminder generated for: ${patientName}`);
        return {
          response:
            `Test reminder generated and sent to this chat.\n\n` +
            `${reminderMsg}`
        };
      }

      if (context.triggerUsed === 'REMINDER STATUS') {
        const pendingQueue = context.db
          ? await context.db.get('SELECT COUNT(*) AS count FROM approval_queue WHERE action_type = ? AND status = ?', ['appointment_reminder_draft', 'pending'])
          : { count: 0 };
        const upcoming = (() => listUpcomingAppointments(24))();
        let appointmentCount = 0;
        try {
          appointmentCount = (await upcoming).length;
        } catch (_) {}

        return {
          response:
            `Reminder System Status\n\n` +
            `Upcoming appointments (24h): ${appointmentCount}\n` +
            `Pending reminder approvals: ${pendingQueue?.count || 0}\n` +
            `Autonomous queue: ${context.autonomousEngine ? 'available' : 'unavailable'}\n` +
            `WhatsApp path: ${process.env.WHATSAPP_ENABLED === 'true' ? 'configured' : 'disabled'}`
        };
      }

      if (context.triggerUsed === 'SEND REMINDERS') {
        const appointments = await listUpcomingAppointments(24);
        if (!appointments.length) {
          return { response: 'No appointments found in the next 24 hours.' };
        }

        let queued = 0;
        for (const event of appointments.slice(0, 8)) {
          const patientName = event.summary || 'Patient';
          const appointmentTime = event.start?.dateTime || event.start?.date || 'soon';
          const reminderMsg = buildReminderMessage(patientName, appointmentTime);

          if (context.autonomousEngine) {
            const existing = context.db
              ? await context.db.get(
                  `SELECT id FROM approval_queue WHERE action_type = ? AND payload LIKE ? AND status IN ('pending','approved')`,
                  ['appointment_reminder_draft', `%${event.id}%`]
                )
              : null;

            if (!existing) {
              await context.autonomousEngine.queueApproval('appointment_reminder_draft', {
                eventId: event.id,
                patientName,
                start: appointmentTime,
                summary: `Prepare and send a reminder draft for ${patientName}.`,
                message: `${reminderMsg}\n\nRequires professional review before sending externally.`
              }, {
                reason: 'Upcoming appointment detected during reminder sweep.',
                summary: `Review reminder for ${patientName} scheduled at ${appointmentTime}.`
              });
              queued += 1;
            }
          }
        }

        return {
          response:
            `Reminder sweep complete.\n\n` +
            `Appointments reviewed: ${appointments.length}\n` +
            `Approval items queued: ${queued}\n` +
            `${queued > 0 ? 'Owners will receive approval requests before any reminder is actioned.' : 'No new reminder approvals were needed.'}`
        };
      }

      return { response: 'Usage: REMINDER STATUS, SEND REMINDERS, TEST REMINDER: Name | time' };
    } catch (err) {
      logger.error('[REMINDERS] Error: ' + err.message);
      return { response: `Reminder error: ${err.message}` };
    }
  }
};
