// 02-reporting.js - Reporting & Daily Briefs
// Pulls live data from ClickUp + Calendar context.
// Falls back to placeholder summary if integrations not yet configured.

const logger = require('../helpers/logger');

module.exports = {
  id: '02-reporting',
  name: 'Reporting & Daily Briefs',
  description: 'Morning briefings, weekly summaries, and KPI snapshots for Dr Piet.',
  triggers: ['MORNING BRIEF', 'WEEKLY REPORT', 'KPI REPORT'],

  execute: async function (payload, context) {
    try {
      const now = new Date();
      const dateStr = now.toLocaleDateString('en-ZA', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        timeZone: 'Africa/Johannesburg'
      });
      const timeStr = now.toLocaleTimeString('en-ZA', {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Africa/Johannesburg'
      });

      if (context.triggerUsed === 'MORNING BRIEF') {
        let todayEvents = '_(Calendar not connected yet)_';
        let taskSummary = '_(ClickUp not connected yet)_';

        if (context.clickup) {
          try {
            const tasks = await context.clickup.getTodayTasks();
            taskSummary = tasks.length > 0
              ? tasks.slice(0, 5).map((task) => `- ${task.name} [${task.status}]`).join('\n')
              : 'No tasks due today';
          } catch (error) {
            logger.warn('[REPORTING] ClickUp unavailable: ' + error.message);
          }
        }

        if (context.calendar) {
          try {
            const events = await context.calendar.getTodayEvents();
            todayEvents = events.length > 0
              ? events.slice(0, 5).map((event) => `- ${event.summary} @ ${event.start}`).join('\n')
              : 'No appointments today';
          } catch (error) {
            logger.warn('[REPORTING] Calendar unavailable: ' + error.message);
          }
        }

        logger.info('[REPORTING] Morning brief generated');
        return {
          response:
            `Good morning, Dr Piet!\n` +
            `${dateStr} at ${timeStr}\n\n` +
            `Today's appointments:\n${todayEvents}\n\n` +
            `Tasks due today:\n${taskSummary}\n\n` +
            `_This is an operational summary only. Consult clinical records for patient-specific decisions._`
        };
      }

      if (context.triggerUsed === 'WEEKLY REPORT') {
        const weekStart = new Date(now);
        weekStart.setDate(now.getDate() - now.getDay());

        logger.info('[REPORTING] Weekly report generated');
        return {
          response:
            `Weekly Report\n` +
            `Week of ${weekStart.toLocaleDateString('en-ZA')}\n\n` +
            `Connect ClickUp and Google Calendar to populate live weekly metrics.\n\n` +
            `_This is an operational summary only. Not for clinical decision-making._`
        };
      }

      if (context.triggerUsed === 'KPI REPORT') {
        logger.info('[REPORTING] KPI report generated');
        return {
          response:
            `KPI Dashboard\n` +
            `Generated: ${dateStr}\n\n` +
            `Status: Connect ClickUp, WooCommerce, and Google Calendar to populate live KPIs.\n\n` +
            `Planned metrics:\n` +
            `- Active patients\n` +
            `- New bookings this week\n` +
            `- Revenue (WooCommerce)\n` +
            `- Membership plan uptake\n` +
            `- Content published\n\n` +
            `_Run \`TEACH ME: [metric = value]\` to manually log any metric._`
        };
      }

      return {
        response: 'Unknown reporting command. Try: `MORNING BRIEF`, `WEEKLY REPORT`, or `KPI REPORT`'
      };
    } catch (err) {
      logger.error('[REPORTING] Error: ' + err.message);
      return { response: `Reporting error: ${err.message}` };
    }
  }
};
