const logger = require('../helpers/logger');

function parsePayload(payload) {
  return String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
}

module.exports = {
  id: '45-payflow',
  name: 'PayFlow Manager',
  description: 'Manage recurring payment plans and subscription workflow summaries for the practice.',
  triggers: ['PAYFLOW:', 'SUBSCRIPTION:'],

  execute: async function (payload, context) {
    try {
      const parts = parsePayload(payload);

      if (context.triggerUsed === 'SUBSCRIPTION:') {
        if (parts.length < 2) {
          return { response: '⚠️ Usage: `SUBSCRIPTION: Plan Name | monthly amount | notes`' };
        }

        const [planName, amount, notes = ''] = parts;
        const createdAt = new Date().toISOString();

        if (context.db) {
          await context.db.run(
            `INSERT INTO tasks (task_id, name, description, status, priority, skill_name, payload, result, createdAt, updatedAt)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
            [
              `subscription-${Date.now()}`,
              `Subscription Plan: ${planName}`,
              notes,
              'pending',
              2,
              '45-payflow',
              JSON.stringify({ planName, amount, notes }),
              '',
              createdAt,
              createdAt
            ]
          );
        }

        return {
          response:
            `✅ *Subscription workflow captured*\n\n` +
            `📦 *Plan:* ${planName}\n` +
            `💰 *Amount:* ${amount}\n` +
            `📝 *Notes:* ${notes || 'None'}\n\n` +
            `Use \`PAYFLOW: status\` to review payment workflow guidance.`
        };
      }

      const pending = context.db
        ? await context.db.all(
            `SELECT name, payload, createdAt FROM tasks WHERE skill_name = ? ORDER BY createdAt DESC LIMIT 10`,
            ['45-payflow']
          )
        : [];

      return {
        response:
          `💳 *PayFlow Manager*\n\n` +
          `Serena is managing recurring payment workflows at the planning and tracking layer.\n\n` +
          `*Tracked Subscription Items*\n` +
          `${pending.length ? pending.map((item) => `• ${item.name} (${item.createdAt})`).join('\n') : '• None yet'}\n\n` +
          `*Next Practical Steps*\n` +
          `• Create a subscription plan with \`SUBSCRIPTION:\`\n` +
          `• Pair it with \`PAYMENT LINK:\` if using PayFast manually\n` +
          `• Use membership and renewal automations to operationalize recurring revenue`
      };
    } catch (error) {
      logger.error('[PAYFLOW] Error: ' + error.message);
      return { response: `❌ PayFlow error: ${error.message}` };
    }
  }
};
