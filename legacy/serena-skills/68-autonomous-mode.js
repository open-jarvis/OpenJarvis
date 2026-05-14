const logger = require('../helpers/logger');

module.exports = {
  id: '68-autonomous-mode',
  name: 'Autonomous Mode Engine',
  description: 'Owner-controlled autonomous monitoring and approval queue management.',
  triggers: ['AUTO ON', 'AUTO OFF', 'AUTO STATUS', 'AUTO REPORT', 'PENDING', 'CLEAR PENDING'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_68_autonomous_mode',
      description: 'Manage Serena autonomous monitoring state and approval queue.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['AUTO ON', 'AUTO OFF', 'AUTO STATUS', 'AUTO REPORT', 'PENDING', 'CLEAR PENDING']
          },
          payload: {
            type: 'string'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const ownerIds = new Set([
        ...(String(process.env.OWNER_TELEGRAM_ID || '').split(',').map((value) => value.trim()).filter(Boolean)),
        ...Object.entries(context.manifest?.allowed_users || {})
          .filter(([, value]) => value.role === 'owner' || value.access === 'full')
          .map(([id]) => id)
      ]);

      if (!ownerIds.has(String(context.userId))) {
        return { response: '🔒 Autonomous mode commands are restricted to Serena owners.' };
      }

      if (!context.autonomousEngine) {
        return { response: '⚠️ Autonomous engine is not available right now.' };
      }

      const result = await context.autonomousEngine.handleOwnerCommand(context.triggerUsed, payload, context);
      return result || { response: '⚠️ Unknown autonomous mode command.' };
    } catch (error) {
      logger.error('[AUTO] Skill error: ' + error.message);
      return { response: `❌ Autonomous mode error: ${error.message}` };
    }
  }
};
