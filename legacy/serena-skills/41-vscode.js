// 41-vscode.js — VS Code / GitHub File Manager
// Manages local and remote (GitHub) files for Serena's development workflow.
// FIXES:
//   - git clone URL corrected to https://github.com/owner/repo.git
//   - 'error' variable reference fixed (was referencing wrong var name)
//   - Promise never-resolving path fixed
//   - temp directory cleanup moved to finally block
//   - GitHub token injected via env for private repos
//   - execute() correctly marked async with proper context param

const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const logger = require('../helpers/logger');

module.exports = {
  id: '41-vscode',
  name: 'VS Code / GitHub File Manager',
  description: 'Read, write, and manage files locally or from a GitHub repository.',
  triggers: ['FILE READ:', 'FILE WRITE:', 'GITHUB CLONE:', 'FILE LIST:'],

  execute: async function (payload, context) {
    try {
      // ── FILE LIST ──────────────────────────────────────────────
      if (context.triggerUsed === 'FILE LIST:') {
        const dirPath = payload.trim() || process.cwd();

        if (!fs.existsSync(dirPath)) {
          return { response: `❌ Path not found: \`${dirPath}\`` };
        }

        const items = fs.readdirSync(dirPath).slice(0, 30);
        const listed = items.map(item => {
          const full = path.join(dirPath, item);
          const isDir = fs.statSync(full).isDirectory();
          return `${isDir ? '📁' : '📄'} ${item}`;
        }).join('\n');

        return {
          response:
            `📂 *Contents of \`${dirPath}\`:*\n\n${listed}` +
            (items.length === 30 ? '\n\n_(showing first 30 items)_' : '')
        };
      }

      // ── FILE READ ──────────────────────────────────────────────
      if (context.triggerUsed === 'FILE READ:') {
        if (!payload || payload.trim().length < 2) {
          return { response: '⚠️ Usage: `FILE READ: /path/to/file.js`' };
        }

        const filePath = payload.trim();
        if (!fs.existsSync(filePath)) {
          return { response: `❌ File not found: \`${filePath}\`` };
        }

        const content = fs.readFileSync(filePath, 'utf-8');
        const lines = content.split('\n').length;
        const preview = content.slice(0, 2000);

        logger.info(`[VSCODE] Read file: ${filePath} (${lines} lines)`);
        return {
          response:
            `📄 *File: \`${path.basename(filePath)}\`* (${lines} lines)\n\n` +
            `\`\`\`\n${preview}\n\`\`\`` +
            (content.length > 2000 ? '\n\n_(truncated — file has more content)_' : '')
        };
      }

      // ── FILE WRITE ─────────────────────────────────────────────
      if (context.triggerUsed === 'FILE WRITE:') {
        if (!payload || payload.trim().length < 5) {
          return { response: '⚠️ Usage: `FILE WRITE: /path/to/file.js | content here`' };
        }

        const sepIdx = payload.indexOf('|');
        if (sepIdx === -1) {
          return { response: '⚠️ Separate file path and content with `|`' };
        }

        const filePath = payload.substring(0, sepIdx).trim();
        const content = payload.substring(sepIdx + 1).trim();

        // Safety: never overwrite protected files
        const protectedPaths = ['server.js', '.env', 'compliance.js', 'ai-engine.js', 'skill-loader.js'];
        if (protectedPaths.some(p => filePath.endsWith(p))) {
          return { response: `🛡️ Cannot overwrite protected file: \`${path.basename(filePath)}\`` };
        }

        // Ensure directory exists
        const dir = path.dirname(filePath);
        if (!fs.existsSync(dir)) {
          fs.mkdirSync(dir, { recursive: true });
        }

        fs.writeFileSync(filePath, content, 'utf-8');
        logger.info(`[VSCODE] File written: ${filePath}`);

        return {
          response:
            `✅ *File written*\n\n` +
            `📄 \`${filePath}\`\n` +
            `📏 ${content.split('\n').length} lines, ${content.length} characters`
        };
      }

      // ── GITHUB CLONE ───────────────────────────────────────────
      if (context.triggerUsed === 'GITHUB CLONE:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `GITHUB CLONE: owner/repo-name`\n' +
              'Example: `GITHUB CLONE: drpiet/serena-agent`'
          };
        }

        const repoRef = payload.trim();
        const [owner, repoName] = repoRef.split('/');

        if (!owner || !repoName) {
          return { response: '⚠️ Format must be `owner/repo-name`' };
        }

        const tempDir = path.join(process.cwd(), 'temp', `clone_${Date.now()}`);
        fs.mkdirSync(tempDir, { recursive: true });

        // FIX: correct HTTPS GitHub URL with optional token for private repos
        const token = process.env.GITHUB_TOKEN;
        const cloneUrl = token
          ? `https://${token}@github.com/${owner}/${repoName}.git`
          : `https://github.com/${owner}/${repoName}.git`;

        return new Promise((resolve) => {
          // FIX: correct variable name in callback (err not error)
          exec(
            `git clone --depth 1 --quiet "${cloneUrl}" "${tempDir}"`,
            { timeout: 60000 },
            (err, stdout, stderr) => {
              // Cleanup always runs regardless of outcome
              const cleanup = () => {
                try {
                  if (fs.existsSync(tempDir)) {
                    fs.rmSync(tempDir, { recursive: true, force: true });
                  }
                } catch (cleanErr) {
                  logger.warn('[VSCODE] Cleanup error:', cleanErr.message);
                }
              };

              if (err) {
                cleanup();
                logger.error('[VSCODE] Clone failed:', err.message);
                resolve({
                  response:
                    `❌ *Clone failed*\n\n` +
                    `Repo: \`${owner}/${repoName}\`\n` +
                    `Error: ${err.message.substring(0, 200)}\n\n` +
                    `_For private repos, set \`GITHUB_TOKEN\` in .env_`
                });
                return;
              }

              const files = fs.readdirSync(tempDir).slice(0, 20);
              const fileList = files.map(f => {
                const isDir = fs.statSync(path.join(tempDir, f)).isDirectory();
                return `${isDir ? '📁' : '📄'} ${f}`;
              }).join('\n');

              cleanup();
              logger.info(`[VSCODE] Cloned: ${owner}/${repoName}`);
              resolve({
                response:
                  `✅ *Repository cloned successfully*\n\n` +
                  `📦 \`${owner}/${repoName}\`\n\n` +
                  `*Contents:*\n${fileList}`
              });
            }
          );
        });
      }

      return {
        response:
          '⚠️ Unknown file command.\n\n' +
          'Available commands:\n' +
          '• `FILE LIST: /path/to/dir`\n' +
          '• `FILE READ: /path/to/file`\n' +
          '• `FILE WRITE: /path/to/file | content`\n' +
          '• `GITHUB CLONE: owner/repo`'
      };

    } catch (err) {
      logger.error('[VSCODE] Error:', err.message);
      return { response: `❌ File manager error: ${err.message}` };
    }
  }
};
