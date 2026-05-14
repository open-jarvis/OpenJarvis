// 47-health-monitor.js - System Health Monitor
// Real-time bot health: uptime, memory, CPU, skill count, DB status, API status.

const logger = require('../helpers/logger');
const os = require('os');
const { probeGoogleDriveAuth } = require('../helpers/google-drive');

module.exports = {
  id: '47-health-monitor',
  name: 'System Health Monitor',
  description: 'Check bot health, uptime, memory, database, and skill status.',
  triggers: ['HEALTH CHECK', 'SYSTEM STATUS', 'BOT STATUS', 'STATUS'],

  execute: async function (payload, context) {
    try {
      logger.info(`[HEALTH] Triggered: ${context.triggerUsed}`);

      const uptimeSec = process.uptime();
      const uptimeStr = uptimeSec < 60
        ? `${Math.round(uptimeSec)}s`
        : uptimeSec < 3600
          ? `${Math.round(uptimeSec / 60)}m`
          : `${Math.round(uptimeSec / 3600)}h ${Math.round((uptimeSec % 3600) / 60)}m`;

      const mem = process.memoryUsage();
      const heapUsedMB = (mem.heapUsed / 1024 / 1024).toFixed(1);
      const heapTotMB = (mem.heapTotal / 1024 / 1024).toFixed(1);
      const rssMB = (mem.rss / 1024 / 1024).toFixed(1);

      const cpuLoad = os.loadavg()[0].toFixed(2);
      const freeMem = (os.freemem() / 1024 / 1024).toFixed(0);
      const totalMem = (os.totalmem() / 1024 / 1024).toFixed(0);

      const skillCount = context.skills ? Object.keys(context.skills).length : 0;
      const triggerCount = context.triggerMap ? Object.keys(context.triggerMap).length : 0;

      let dbStatus = 'Warning: Not connected';
      if (context.db) {
        try {
          await context.db.get('SELECT 1');
          dbStatus = 'OK: Connected (SQLite)';
        } catch (_) {
          dbStatus = 'Error: Query failed';
        }
      }

      let aiStatus = 'Warning: Unknown';
      if (context.aiEngine) {
        const aiInfo = context.aiEngine.getStatus();
        const healthy = aiInfo.providers.filter((p) => p.status === 'healthy' || p.status === 'assumed-healthy');
        aiStatus = `OK: ${healthy.length}/${aiInfo.providers.length} providers healthy`;
      }

      const apiFlags = {
        Groq: !!process.env.GROQ_API_KEY,
        Gemini: !!process.env.GEMINI_API_KEY,
        HuggingFace: !!process.env.HUGGINGFACE_API_KEY,
        WordPress: !!(process.env.WORDPRESS_URL && process.env.WORDPRESS_APP_PASSWORD),
        ClickUp: !!process.env.CLICKUP_API_KEY,
        PayFast: process.env.PAYFAST_ENABLED === 'true',
        WhatsApp: process.env.WHATSAPP_ENABLED === 'true',
        'SMTP Email': !!(process.env.SMTP_HOST && process.env.SMTP_PASS)
      };

      const apiLines = Object.entries(apiFlags)
        .map(([name, ok]) => `${ok ? 'OK' : 'Warning'} ${name}`)
        .join('\n');

      let googleDriveLine = 'Warning Google Drive: not configured';
      if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET && process.env.GOOGLE_REFRESH_TOKEN) {
        const probe = await probeGoogleDriveAuth().catch((error) => ({
          healthy: false,
          detail: error.message
        }));
        googleDriveLine = probe.healthy
          ? 'OK Google Drive: authenticated'
          : `Warning Google Drive: auth failed (${probe.detail || 'unknown error'})`;
      }

      logger.info(`[HEALTH] Status check: uptime=${uptimeStr}, heap=${heapUsedMB}MB, skills=${skillCount}`);

      return {
        response:
          `${process.env.AGENT_NAME || 'Serena'} - System Status\n\n` +
          `Uptime: ${uptimeStr}\n` +
          `Memory: ${heapUsedMB}MB / ${heapTotMB}MB heap (RSS: ${rssMB}MB)\n` +
          `CPU Load: ${cpuLoad} | Free RAM: ${freeMem}MB / ${totalMem}MB\n` +
          `Database: ${dbStatus}\n` +
          `AI Engine: ${aiStatus}\n\n` +
          `Skills loaded: ${skillCount}\n` +
          `Triggers active: ${triggerCount}\n\n` +
          `${googleDriveLine}\n\n` +
          `API Integrations:\n${apiLines}\n\n` +
          `Node.js ${process.version} | ${os.platform()} | ${os.arch()}`
      };
    } catch (err) {
      logger.error('[HEALTH] Error:', err.message);
      return { response: `Health check error: ${err.message}` };
    }
  }
};
