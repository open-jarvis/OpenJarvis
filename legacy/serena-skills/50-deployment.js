const { execFile } = require('child_process');
const logger = require('../helpers/logger');

function execFileAsync(command, args = []) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { timeout: 30000 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(stderr || error.message));
        return;
      }
      resolve((stdout || '').trim());
    });
  });
}

function isOwner(context) {
  const allowed = new Set([
    ...String(process.env.OWNER_TELEGRAM_ID || '').split(',').map((item) => item.trim()).filter(Boolean),
    ...Object.entries(context.manifest?.allowed_users || {})
      .filter(([, value]) => value.role === 'owner' || value.access === 'full')
      .map(([id]) => id)
  ]);
  return allowed.has(String(context.userId));
}

function parseDeployIntent(payload) {
  const text = String(payload || '').trim();
  if (!text) return { action: 'status', appName: process.env.PM2_APP_NAME || process.env.AGENT_NAME || 'serena' };

  const parts = text.split(/\s+/);
  const action = parts[0].toLowerCase();
  const appName = parts.slice(1).join(' ').trim() || process.env.PM2_APP_NAME || process.env.AGENT_NAME || 'serena';
  return { action, appName };
}

module.exports = {
  id: '50-deployment',
  name: 'Deployment Manager',
  description: 'Inspect PM2 state, restart Serena, view logs, and check process inventory.',
  triggers: ['DEPLOY:', 'RESTART BOT'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_50_deployment',
      description: 'Inspect PM2 deployment state, logs, list processes, or restart the bot.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['DEPLOY:', 'RESTART BOT']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      if (!isOwner(context)) {
        return { response: 'Deployment commands are restricted to Serena owners.' };
      }

      const parsed = parseDeployIntent(payload);
      const action = context.triggerUsed === 'RESTART BOT' ? 'restart' : parsed.action;
      const appName = parsed.appName;

      if (action === 'restart') {
        const output = await execFileAsync('pm2', ['restart', appName]);
        return {
          response:
            `PM2 restart requested\n\n` +
            `App: ${appName}\n\n` +
            `${output.slice(0, 1500)}`
        };
      }

      if (action === 'list' || action === 'ls') {
        const output = await execFileAsync('pm2', ['list']);
        return {
          response:
            `PM2 process inventory\n\n` +
            '```text\n' +
            `${output.slice(0, 2500)}\n` +
            '```'
        };
      }

      if (action === 'logs') {
        const lines = await execFileAsync('pm2', ['logs', appName, '--nostream', '--lines', '40']);
        return {
          response:
            `Recent PM2 logs\n\n` +
            `App: ${appName}\n\n` +
            '```text\n' +
            `${lines.slice(0, 2500)}\n` +
            '```'
        };
      }

      if (action === 'save') {
        const output = await execFileAsync('pm2', ['save']);
        return {
          response:
            `PM2 process list saved\n\n` +
            `${output.slice(0, 1500)}`
        };
      }

      const status = await execFileAsync('pm2', ['describe', appName]);
      return {
        response:
          `Deployment Status\n\n` +
          `App: ${appName}\n\n` +
          '```text\n' +
          `${status.slice(0, 2500)}\n` +
          '```' +
          `\n\nUsage:\n` +
          `DEPLOY: status\n` +
          `DEPLOY: logs\n` +
          `DEPLOY: list\n` +
          `DEPLOY: save\n` +
          `RESTART BOT`
      };
    } catch (error) {
      logger.error('[DEPLOYMENT] Error: ' + error.message);
      return {
        response:
          `Deployment error: ${error.message}\n\n` +
          'Make sure PM2 is installed and PM2_APP_NAME is set correctly in .env.'
      };
    }
  }
};
