// 64-github.js — GitHub Automation (MCP GitHub Server)
// Gives Serena the ability to manage the codebase on GitHub:
// create issues, read files, push updates, check PRs.
// This is the primary mechanism for Serena to request code changes
// from Kyle without needing filesystem access.
//
// REQUIRES: GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO in .env

const logger = require('../helpers/logger');

module.exports = {
  id: '64-github',
  name: 'GitHub Automation',
  description: 'Create GitHub issues, read code, log feature requests, and manage the Serena repo.',
  triggers: ['GITHUB ISSUE:', 'GITHUB READ:', 'GITHUB STATUS', 'CODE REQUEST:', 'BUG REPORT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[GITHUB] Triggered: ${context.triggerUsed} | ${(payload || '').substring(0, 60)}`);

      const mcpClient = context.mcpClient;
      const owner     = process.env.GITHUB_OWNER;
      const repo      = process.env.GITHUB_REPO;

      if (!mcpClient) return { response: '⚠️ MCP layer not initialised.' };

      const tools = mcpClient.getToolsForServer('github');
      if (!tools || tools.length === 0) {
        return {
          response:
            '⚠️ *GitHub MCP not connected*\n\n' +
            'Add to .env:\n' +
            '• `GITHUB_TOKEN=ghp_...`\n' +
            '• `GITHUB_OWNER=your-username`\n' +
            '• `GITHUB_REPO=serena-agent`'
        };
      }

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🐙 *GitHub Automation*\n\n' +
            'Commands:\n' +
            '• `GITHUB ISSUE: title | description` — create an issue\n' +
            '• `CODE REQUEST: feature description` — auto-create feature request issue\n' +
            '• `BUG REPORT: what broke | steps to reproduce` — auto-create bug report\n' +
            '• `GITHUB READ: src/skills/01-crm.js` — read a file from the repo\n' +
            '• `GITHUB STATUS` — list open issues\n\n' +
            `📦 Repo: ${owner}/${repo}`
        };
      }

      // ── GITHUB STATUS ─────────────────────────────────────────
      if (context.triggerUsed === 'GITHUB STATUS') {
        const result = await mcpClient.callTool('list_issues', {
          owner,
          repo,
          state: 'open'
        });
        const text = result.map(c => c.text || '').join('\n');
        return {
          response:
            `🐙 *Open Issues — ${owner}/${repo}*\n\n` +
            (text || '✅ No open issues') +
            `\n\n💡 Create issue: \`GITHUB ISSUE: title | description\``
        };
      }

      // ── CREATE ISSUE ──────────────────────────────────────────
      if (context.triggerUsed === 'GITHUB ISSUE:' ||
          context.triggerUsed === 'CODE REQUEST:' ||
          context.triggerUsed === 'BUG REPORT:') {
        const parts   = payload.split('|').map(p => p.trim());
        const title   = parts[0];
        const body    = parts[1] || '';

        const isBug     = context.triggerUsed === 'BUG REPORT:';
        const isFeature = context.triggerUsed === 'CODE REQUEST:';

        const labels = isBug ? ['bug'] : isFeature ? ['enhancement', 'serena-auto'] : [];

        const fullBody = isFeature
          ? `**Feature Request from Serena**\n\n${body || title}\n\n_Auto-created by Serena agent_`
          : isBug
            ? `**Bug Report from Serena**\n\n**What broke:** ${title}\n\n**Steps to reproduce:**\n${body}\n\n_Auto-created by Serena_`
            : body || title;

        const result = await mcpClient.callTool('create_issue', {
          owner,
          repo,
          title: isBug ? `[BUG] ${title}` : isFeature ? `[FEATURE] ${title}` : title,
          body:  fullBody,
          labels
        });

        const text       = result.map(c => c.text || '').join('\n');
        const issueMatch = text.match(/number[": ]+(\d+)/i);
        const issueNum   = issueMatch ? issueMatch[1] : '?';

        logger.info(`[GITHUB] Issue created: #${issueNum} — ${title}`);
        return {
          response:
            `🐙 *GitHub Issue Created*\n\n` +
            `📌 *#${issueNum}:* ${title}\n` +
            `🔗 github.com/${owner}/${repo}/issues/${issueNum}\n\n` +
            `_Kyle will be notified via GitHub notification._`
        };
      }

      // ── READ FILE ─────────────────────────────────────────────
      if (context.triggerUsed === 'GITHUB READ:') {
        const filePath = payload.trim();
        const result   = await mcpClient.callTool('get_file_contents', {
          owner,
          repo,
          path: filePath
        });
        const text = result.map(c => c.text || '').join('');
        return {
          response:
            `📄 *${filePath}*\n\n\`\`\`\n${text.substring(0, 3000)}\n\`\`\`` +
            (text.length > 3000 ? '\n_(truncated)_' : '')
        };
      }

      return { response: '⚠️ Unknown GitHub command.' };

    } catch (err) {
      logger.error('[GITHUB] Error:', err.message);
      return { response: `❌ GitHub error: ${err.message}` };
    }
  }
};
