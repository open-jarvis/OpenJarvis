// 48-notifications.js — Notification & Alert Manager
// Sends scheduled alerts and notifications to the owner via Telegram.
// Supports: instant alerts, scheduled daily digest, appointment reminders.

const logger = require('../helpers/logger');

// In-memory scheduled notification store (persists for server lifetime)
const scheduledNotifications = [];

module.exports = {
  id: '48-notifications',
  name: 'Notification Manager',
  description: 'Send instant alerts and manage scheduled notifications via Telegram.',
  triggers: ['NOTIFY:', 'ALERT:', 'SCHEDULE NOTIFY:', 'NOTIFY LIST'],

  execute: async function (payload, context) {
    try {
      logger.info(`[NOTIFY] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      // ── NOTIFY LIST ────────────────────────────────────────────
      if (context.triggerUsed === 'NOTIFY LIST') {
        if (scheduledNotifications.length === 0) {
          return { response: '🔔 *Scheduled Notifications*\n\nNo notifications scheduled.\n\nUse `SCHEDULE NOTIFY: HH:MM | message` to schedule.' };
        }
        const list = scheduledNotifications
          .map((n, i) => `${i + 1}. ⏰ ${n.time} — ${n.message.substring(0, 50)}`)
          .join('\n');
        return { response: `🔔 *Scheduled Notifications (${scheduledNotifications.length}):*\n\n${list}` };
      }

      // ── INSTANT NOTIFY ─────────────────────────────────────────
      if (context.triggerUsed === 'NOTIFY:' || context.triggerUsed === 'ALERT:') {
        if (!payload || payload.trim().length < 2) {
          return {
            response:
              '🔔 *Notification Manager*\n\n' +
              'Usage:\n' +
              '• `NOTIFY: Your message here` — send instant notification to all owners\n' +
              '• `ALERT: urgent message` — same as NOTIFY with 🚨 prefix\n' +
              '• `SCHEDULE NOTIFY: 08:00 | Good morning! You have 3 appointments today`\n' +
              '• `NOTIFY LIST` — view scheduled notifications'
          };
        }

        const isAlert = context.triggerUsed === 'ALERT:';
        const prefix  = isAlert ? '🚨 *ALERT*\n\n' : '🔔 *Notification*\n\n';
        const message = payload.trim();

        if (!context.bot) return { response: '⚠️ Telegram bot not available.' };

        // Send to all configured owner IDs
        const ownerIds = (process.env.OWNER_TELEGRAM_ID || '')
          .split(',').map(s => s.trim()).filter(Boolean);

        if (ownerIds.length === 0) {
          return { response: '⚠️ No OWNER_TELEGRAM_ID set in .env. Cannot send notification.' };
        }

        let sent = 0;
        for (const ownerId of ownerIds) {
          try {
            if (String(ownerId) !== String(context.chatId)) {
              await context.bot.sendMessage(ownerId, prefix + message, { parse_mode: 'Markdown' });
              sent++;
            }
          } catch (sendErr) {
            logger.warn(`[NOTIFY] Failed to send to ${ownerId}: ${sendErr.message}`);
          }
        }

        logger.info(`[NOTIFY] Alert sent to ${sent} owner(s)`);
        return {
          response:
            `✅ *${isAlert ? 'Alert' : 'Notification'} sent*\n\n` +
            `📨 Delivered to ${sent} recipient(s)\n` +
            `💬 _"${message.substring(0, 100)}"_`
        };
      }

      // ── SCHEDULE NOTIFY ────────────────────────────────────────
      if (context.triggerUsed === 'SCHEDULE NOTIFY:') {
        if (!payload || !payload.includes('|')) {
          return {
            response:
              '⏰ *Schedule Notification*\n\n' +
              'Usage: `SCHEDULE NOTIFY: HH:MM | Your message`\n\n' +
              'Example: `SCHEDULE NOTIFY: 08:00 | Good morning! Check your schedule for today.`'
          };
        }

        const [timeStr, ...msgParts] = payload.split('|').map(p => p.trim());
        const message = msgParts.join('|').trim();

        if (!timeStr.match(/^\d{2}:\d{2}$/)) {
          return { response: '⚠️ Time must be in HH:MM format (e.g. 08:30)' };
        }

        const ownerIds = (process.env.OWNER_TELEGRAM_ID || '')
          .split(',').map(s => s.trim()).filter(Boolean);

        // Schedule using simple interval check
        const notification = { time: timeStr, message, ownerIds, id: Date.now() };
        scheduledNotifications.push(notification);

        // Set up a daily check interval if not already running
        if (!global._notifyIntervalRunning) {
          global._notifyIntervalRunning = true;
          setInterval(async () => {
            const now = new Date();
            const currentTime = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
            for (const notif of scheduledNotifications) {
              if (notif.time === currentTime && !notif.sentToday) {
                notif.sentToday = true;
                setTimeout(() => { notif.sentToday = false; }, 60000); // Reset after 1 min
                for (const ownerId of notif.ownerIds) {
                  try {
                    if (context.bot) {
                      await context.bot.sendMessage(ownerId, `⏰ *Scheduled Alert*\n\n${notif.message}`, { parse_mode: 'Markdown' });
                    }
                  } catch (_) {}
                }
                logger.info(`[NOTIFY] Scheduled notification fired at ${currentTime}`);
              }
            }
          }, 60000); // Check every minute
        }

        logger.info(`[NOTIFY] Scheduled: ${timeStr} — "${message.substring(0, 50)}"`);
        return {
          response:
            `✅ *Notification Scheduled*\n\n` +
            `⏰ *Time:* ${timeStr} (daily)\n` +
            `💬 *Message:* ${message.substring(0, 100)}\n\n` +
            `_Fires every day at ${timeStr}. View with_ \`NOTIFY LIST\``
        };
      }

      return { response: '⚠️ Usage: `NOTIFY:`, `ALERT:`, `SCHEDULE NOTIFY:`, `NOTIFY LIST`' };

    } catch (err) {
      logger.error('[NOTIFY] Error:', err.message);
      return { response: `❌ Notification error: ${err.message}` };
    }
  }
};
