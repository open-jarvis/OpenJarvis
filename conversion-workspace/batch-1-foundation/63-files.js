// 63-files.js — File Manager (MCP Filesystem Server)
// Gives Serena sandboxed read/write access to allowed directories.
// Works alongside 41-vscode.js but uses the MCP filesystem server
// which provides safer, permission-controlled access.
//
// ALWAYS ENABLED — no extra API key needed

const logger = require('../helpers/logger');

module.exports = {
  id: '63-files',
  name: 'MCP File Manager',
  description: 'Read, write, and list files in allowed directories via MCP filesystem server.',
  triggers: ['MCP FILE READ:', 'MCP FILE WRITE:', 'MCP DIR:', 'MCP FILE SEARCH:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[FILES] Triggered: ${context.triggerUsed} | ${(payload || '').substring(0, 60)}`);

      const mcpClient = context.mcpClient;

      if (!mcpClient) {
        return { response: '⚠️ MCP layer not initialised.' };
      }

      const tools = mcpClient.getToolsForServer('filesystem');
      if (!tools || tools.length === 0) {
        return { response: '⚠️ Filesystem MCP server not connected.' };
      }

      if (!payload || payload.trim().length < 2) {
        return {
          response:
            '📁 *MCP File Manager*\n\n' +
            'Commands:\n' +
            '• `MCP DIR: ./outputs` — list directory\n' +
            '• `MCP FILE READ: ./outputs/report.txt` — read file\n' +
            '• `MCP FILE WRITE: ./outputs/notes.txt | content here` — write file\n' +
            '• `MCP FILE SEARCH: *.pdf` — search for files\n\n' +
            '_Files restricted to allowed directories configured at startup._'
        };
      }

      // ── LIST DIR ────────────────────────────────────────────
      if (context.triggerUsed === 'MCP DIR:') {
        const dirPath = payload.trim();
        const result  = await mcpClient.callTool('list_directory', { path: dirPath });
        const text    = result.map(c => c.text || '').join('\n');
        return { response: `📁 *Directory: ${dirPath}*\n\n${text || 'Empty directory'}` };
      }

      // ── READ FILE ────────────────────────────────────────────
      if (context.triggerUsed === 'MCP FILE READ:') {
        const filePath = payload.trim();
        const result   = await mcpClient.callTool('read_file', { path: filePath });
        const content  = result.map(c => c.text || '').join('');

        if (!content) return { response: `⚠️ File empty or not found: ${filePath}` };

        return {
          response:
            `📄 *File: ${filePath}*\n\n` +
            `\`\`\`\n${content.substring(0, 3000)}\n\`\`\`` +
            (content.length > 3000 ? '\n\n_(truncated)_' : '')
        };
      }

      // ── WRITE FILE ────────────────────────────────────────────
      if (context.triggerUsed === 'MCP FILE WRITE:') {
        const sepIdx = payload.indexOf('|');
        if (sepIdx === -1) return { response: '⚠️ Usage: `MCP FILE WRITE: path | content`' };

        const filePath = payload.substring(0, sepIdx).trim();
        const content  = payload.substring(sepIdx + 1).trim();

        await mcpClient.callTool('write_file', { path: filePath, content });

        logger.info(`[FILES] Written: ${filePath}`);
        return { response: `✅ File written: \`${filePath}\`\n${content.split('\n').length} lines` };
      }

      // ── SEARCH ────────────────────────────────────────────────
      if (context.triggerUsed === 'MCP FILE SEARCH:') {
        const result = await mcpClient.callTool('search_files', {
          path:    '.',
          pattern: payload.trim()
        });
        const text = result.map(c => c.text || '').join('\n');
        return { response: `🔍 *File Search: ${payload.trim()}*\n\n${text || 'No files found'}` };
      }

      return { response: '⚠️ Unknown file command.' };

    } catch (err) {
      logger.error('[FILES] Error:', err.message);
      return { response: `❌ File manager error: ${err.message}` };
    }
  }
};
