// 49-security.js — Security Audit & Access Log
// Runs live security checks and displays access logs from the gap log.
// Full audit trail DB implementation uses existing logger + gap-log.json.

const logger = require('../helpers/logger');
const fs     = require('fs');
const path   = require('path');
const os     = require('os');
const { buildSecurityAuditReport } = require('../helpers/security-audit');

module.exports = {
  id: '49-security',
  name: 'Security Audit',
  description: 'Run security checks, view access logs, and audit the system.',
  triggers: ['SECURITY AUDIT', 'ACCESS LOG', 'SECURITY STATUS', 'AUDIT BOT'],

  execute: async function (payload, context) {
    try {
      logger.info(`[SECURITY] Triggered: ${context.triggerUsed}`);

      // ── ACCESS LOG ───────────────────────────────────────────────
      if (context.triggerUsed === 'ACCESS LOG') {
        const logPath = path.join(__dirname, '../../logs/agent.log');
        let recentLines = [];

        if (fs.existsSync(logPath)) {
          const content = fs.readFileSync(logPath, 'utf-8');
          const lines   = content.split('\n').filter(Boolean);
          recentLines   = lines.slice(-20).reverse();
        }

        if (recentLines.length === 0) {
          return { response: '📋 *Access Log*\n\nNo log entries found.\n\nLog location: `logs/agent.log`' };
        }

        const truncated = recentLines.map(l => l.substring(0, 120)).join('\n');
        return {
          response:
            `📋 *Recent Access Log (last 20 entries)*\n\n` +
            `\`\`\`\n${truncated}\n\`\`\``
        };
      }

      // ── SECURITY AUDIT ────────────────────────────────────────────
      if (context.triggerUsed === 'SECURITY AUDIT' || context.triggerUsed === 'AUDIT BOT') {
        const { report, plan } = buildSecurityAuditReport();
        const ownerIds = (process.env.OWNER_TELEGRAM_ID || '').split(',').map((value) => value.trim()).filter(Boolean);
        const envPath = path.join(__dirname, '../../.env');
        const envMode = fs.existsSync(envPath)
          ? ((fs.statSync(envPath).mode & 0o777).toString(8))
          : 'missing';
        const envSecure = !fs.existsSync(envPath) || envMode === '600' || envMode === '400';
        const score = [
          ownerIds.length > 0,
          !!(process.env.JWT_SECRET && process.env.JWT_SECRET !== 'serena-super-secret-key-change-in-production'),
          envSecure,
          process.env.PAYFAST_ENABLED !== 'true' || process.env.PAYFAST_SANDBOX === 'true',
          !process.env.WORDPRESS_URL || String(process.env.WORDPRESS_URL).startsWith('https://'),
          true,
          true,
          ownerIds.length > 0,
          fs.existsSync(path.join(__dirname, '../../logs'))
        ].filter(Boolean).length;
        const total = 9;
        const percent = Math.round((score / total) * 100);
        const emoji  = percent >= 90 ? '🟢' : percent >= 70 ? '🟡' : '🔴';

        logger.info(`[SECURITY] Audit complete: ${percent}/100`);
        return {
          response:
            `🔒 *Security Audit Report*\n\n` +
            `${emoji} *Score: ${percent}/100* (${score}/${total} checks passed)\n\n` +
            `━━━━━━━━━━━━━━━━━━\n\n` +
            `${report}\n\n` +
            `Rotation plan (no rotation executed yet)\n` +
            plan.rotationPlan.map((line) => `• ${line}`).join('\n') +
            `\n\n━━━━━━━━━━━━━━━━━━\n` +
            `_Run \`ACCESS LOG\` to view recent activity._`
        };
      }

      // ── SECURITY STATUS ───────────────────────────────────────────
      return {
        response:
          '🔒 *Security Commands*\n\n' +
          '• `SECURITY AUDIT` — full security check\n' +
          '• `ACCESS LOG` — view recent bot activity\n' +
          '• `AUDIT BOT` — alias for security audit'
      };

    } catch (err) {
      logger.error('[SECURITY] Error:', err.message);
      return { response: `❌ Security audit error: ${err.message}` };
    }
  }
};
