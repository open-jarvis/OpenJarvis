// 66-mcp-status.js — MCP Layer Status & Tool Browser

const logger = require('../helpers/logger');

function getAllTools(mcpClient) {
  if (typeof mcpClient.getToolList === 'function') return mcpClient.getToolList();
  if (typeof mcpClient.listAllTools === 'function') return mcpClient.listAllTools();
  return [];
}

module.exports = {
  id: '66-mcp-status',
  name: 'MCP Status & Tool Browser',
  description: 'View all connected MCP servers, browse available tools, and call tools directly.',
  triggers: ['MCP STATUS', 'MCP TOOLS:', 'MCP CALL:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[MCP-STATUS] Triggered: ${context.triggerUsed}`);

      const mcpClient = context.mcpClient;

      if (!mcpClient) {
        return {
          response:
            '⚠️ *MCP layer not active*\n\n' +
            'MCP integration is not running. Check server.js startup logs.\n\n' +
            '_The MCP layer connects Serena to external capabilities like browser automation, web search, and file management._'
        };
      }

      if (context.triggerUsed === 'MCP STATUS') {
        const status = mcpClient.getStatus();

        if (status.totalServers === 0) {
          return {
            response:
              '🔌 *MCP Status — No Servers Connected*\n\n' +
              'All MCP servers are either disabled or failed to start.\n' +
              'Check your .env for required API keys and restart Serena.'
          };
        }

        const serverLines = (status.serverDetails || []).map(s => {
          return `✅ *${s.name}*\n   ${(s.tools || []).length} tools`;
        }).join('\n\n');

        const allTools = getAllTools(mcpClient);
        const toolsByServer = {};
        for (const tool of allTools) {
          if (!toolsByServer[tool.server]) toolsByServer[tool.server] = [];
          toolsByServer[tool.server].push(tool.name);
        }

        const toolSummary = Object.entries(toolsByServer)
          .map(([server, tools]) => `*${server}:* ${tools.slice(0, 5).join(', ')}${tools.length > 5 ? ` +${tools.length - 5} more` : ''}`)
          .join('\n');

        return {
          response:
            `🔌 *MCP Layer Status*\n\n` +
            `📊 ${status.totalServers} servers | ${status.totalTools} tools total\n\n` +
            `━━━━━━━━━━━━━━━━━━\n\n` +
            serverLines +
            `\n\n━━━━━━━━━━━━━━━━━━\n\n` +
            `*Available Tools:*\n${toolSummary}\n\n` +
            `💡 Browse: \`MCP TOOLS: server-name\`\n` +
            `💡 Call: \`MCP CALL: tool_name | {"arg": "value"}\``
        };
      }

      if (context.triggerUsed === 'MCP TOOLS:') {
        const serverName = payload.trim();
        const allTools = getAllTools(mcpClient);
        const filtered = serverName ? allTools.filter(t => t.server === serverName) : allTools;

        if (filtered.length === 0) {
          return { response: `❌ No tools found for server: "${serverName}"` };
        }

        const toolLines = filtered.slice(0, 20).map(t => {
          return `• *${t.name}*\n  _${(t.description || 'No description').substring(0, 80)}_`;
        }).join('\n\n');

        return {
          response:
            `🔧 *MCP Tools${serverName ? `: ${serverName}` : ' (all)'}*\n\n` +
            toolLines +
            (filtered.length > 20 ? `\n\n_...and ${filtered.length - 20} more_` : '')
        };
      }

      if (context.triggerUsed === 'MCP CALL:') {
        const sepIdx = payload.indexOf('|');
        const toolName = sepIdx !== -1 ? payload.substring(0, sepIdx).trim() : payload.trim();
        const argsStr = sepIdx !== -1 ? payload.substring(sepIdx + 1).trim() : '{}';

        let args;
        try {
          args = JSON.parse(argsStr);
        } catch (e) {
          return { response: `⚠️ Invalid JSON args: ${argsStr}\n\nUsage: \`MCP CALL: tool_name | {"arg": "value"}\`` };
        }

        const result = typeof mcpClient.callToolRaw === 'function'
          ? await mcpClient.callToolRaw(toolName, args, { timeoutMs: 30000 })
          : await mcpClient.callTool(toolName, args, { timeoutMs: 30000 });

        const text = typeof result === 'string'
          ? result
          : Array.isArray(result)
            ? result.map(c => c.text || c.data || '').join('\n')
            : Array.isArray(result?.content)
              ? result.content.map(c => c.text || c.data || '').join('\n')
              : JSON.stringify(result, null, 2);

        logger.info(`[MCP-STATUS] Direct call: ${toolName}`);
        return {
          response:
            `🔧 *Tool Result: ${toolName}*\n\n` +
            ((text || '').substring(0, 3000) || '_(empty result)_')
        };
      }

      return { response: '⚠️ Usage: `MCP STATUS`, `MCP TOOLS: server`, `MCP CALL: tool | args`' };
    } catch (err) {
      logger.error('[MCP-STATUS] Error:', err.message);
      return { response: `❌ MCP error: ${err.message}` };
    }
  }
};
