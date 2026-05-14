const fs = require('fs');
const path = require('path');
const logger = require('../helpers/logger');
const canva = require('../helpers/canva');
const canvaMcp = require('../helpers/canva-mcp');
const { createWordDocument, uploadGeneratedDocument } = require('../helpers/document-service');

function parseLooseFields(text) {
  const source = String(text || '').trim();
  const out = {};
  if (!source) return out;
  for (const segment of source.split('|')) {
    const part = segment.trim();
    const m = part.match(/^([A-Za-z][A-Za-z0-9 _-]+)\s*=\s*(.+)$/);
    if (!m) continue;
    const key = m[1].trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    out[key] = m[2].trim();
  }
  return out;
}

function sanitizeLine(value) { return String(value || '').replace(/[*_`]/g, '').trim(); }

function parseLegacyBrief(payload) {
  const parts = String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return { format: parts[0] || 'social design', brief: parts[1] || parts[0] || '', brand: parts[2] || process.env.COMPANY_NAME || 'Dr Piet Muller' };
}

async function generateDesignBrief(context, format, brief, brand) {
  const result = await context.aiEngine.chat([{ role: 'user', content: `Format: ${format}\nBrand: ${brand}\nBrief: ${brief}` }], {
    systemPrompt: `${context.soulFile}\n\nYou are Serena's Canva design strategist. Create a Canva-ready design brief including headline options, layout direction, copy blocks, visual references, CTA, and asset checklist.`,
    temperature: 0.45,
    maxTokens: 1600,
    task: 'canva-brief'
  });
  return String(result.content || '').trim();
}

const TRIGGERS = [
  'CANVA CONNECT', 'CANVA STATUS', 'CANVA LIST DESIGNS', 'CANVA LIST DESIGNS:', 'CANVA FIND:', 'CANVA GET DESIGN:',
  'CANVA EXPORT:', 'CANVA COMMENT:', 'CANVA UPLOAD ASSET:', 'CANVA MCP SEARCH:', 'CANVA ASK:', 'CANVA DESIGN:', 'CREATE DESIGN:'
];

function buildConnectRoute(userId) {
  const base = String(process.env.PUBLIC_BASE_URL || `http://localhost:${process.env.PORT || 3000}`).replace(/\/$/, '');
  return `${base}/integrations/canva/connect?userId=${encodeURIComponent(String(userId))}`;
}

async function buildRestFallback(context, query) {
  const userId = context.userId;
  const list = await canva.listDesigns({ db: context.db, userId, query, sortBy: 'modified_desc' }).catch(() => ({ items: [] }));
  const items = Array.isArray(list.items) ? list.items.slice(0, 8) : [];
  if (!items.length) return 'No Canva designs were found through the Connect API fallback.';
  return [
    '🖼️ *Canva designs visible via Connect API*',
    '',
    ...items.map((item) => `• ${sanitizeLine(item.title || item.name || 'Untitled design')} — \`${item.id}\`${item.urls?.edit_url ? `\n  ↳ edit: ${item.urls.edit_url}` : ''}`)
  ].join('\n');
}

function inferIntent(trigger) {
  const t = String(trigger || '').toUpperCase();
  if (t.startsWith('CANVA MCP SEARCH')) return 'search';
  if (t.startsWith('CANVA ASK')) return 'answer';
  return 'search';
}

async function maybeCallCanvaMcp(context, trigger, payload) {
  const intent = inferIntent(trigger);
  const explicitMcpCommand = String(trigger || '').toUpperCase().startsWith('CANVA MCP');
  const decision = canvaMcp.getRoutingDecision(context.mcpClient, intent, { explicitMcpCommand });
  if (!decision.useMcp) {
    return { usedMcp: false, decision, fallback: await buildRestFallback(context, payload) };
  }
  try {
    const result = await canvaMcp.callIntent(context.mcpClient, intent, payload, { query: payload, question: payload, instruction: payload }, { explicitMcpCommand });
    return { usedMcp: true, response: `🎨 *Canva MCP result*\n\n${String(result).trim()}`, decision };
  } catch (error) {
    return { usedMcp: false, decision: { ...canvaMcp.getRoutingDecision(context.mcpClient, intent, { explicitMcpCommand }), reason: String(error.message || error) }, fallback: await buildRestFallback(context, payload) };
  }
}

module.exports = {
  id: '26-canva',
  name: 'Canva Command Center',
  description: 'Connect Serena to Canva via Connect API and Canva MCP. Use for Canva auth, token lifecycle, design discovery, metadata reads, asset upload, export jobs, comments, natural-language search, and conversational design interaction.',
  triggers: TRIGGERS,

  execute: async function (payload, context) {
    try {
      const trigger = String(context?.triggerUsed || '').trim().toUpperCase();
      const userId = String(context.userId);

      const apiConfigured = canva.isConfigured();

      if (trigger === 'CANVA CONNECT') {
        if (!apiConfigured) {
          return { response: '⚠️ Canva Connect API is not configured yet. Add `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, and `CANVA_REDIRECT_URI` first. Canva MCP can still start separately.' };
        }
        const url = buildConnectRoute(userId);
        return { response: `🔗 *Connect Canva to Serena*\n\nOpen this link to authorize Canva:\n${url}\n\nAfter approval, return and run \`CANVA STATUS\`.` };
      }

      if (trigger === 'CANVA STATUS') {
        const apiStatus = apiConfigured
          ? await canva.getConnectionStatus({ db: context.db, userId })
          : { configured: false, connected: false, expiresAt: null, hasRefreshToken: false };
        const mcpStatus = canvaMcp.buildStatus(context.mcpClient);
        return {
          response: [
            '🧩 *Canva connection status*',
            '',
            `• Connect API configured: ${apiStatus.configured ? 'yes' : 'no'}`,
            `• Connect API connected: ${apiStatus.connected ? 'yes' : 'no'}`,
            `• Token expires: ${apiStatus.expiresAt || 'unknown'}`,
            `• Refresh token present: ${apiStatus.hasRefreshToken ? 'yes' : 'no'}`,
            `• Canva MCP enabled: ${mcpStatus.enabled ? 'yes' : 'no'}`,
            `• Canva MCP connected: ${mcpStatus.connected ? 'yes' : 'no'}`,
            `• Canva MCP URL: ${canvaMcp.getRemoteUrl()}`,
            `• Canva MCP tools: ${mcpStatus.toolCount}`,
            `• MCP healthy: ${mcpStatus.routing.healthy ? 'yes' : 'no'}`,
            `• MCP cooling down: ${mcpStatus.routing.coolingDown ? `yes (${Math.ceil(mcpStatus.routing.cooldownMsRemaining / 1000)}s)` : 'no'}`,
            `• Last MCP error: ${sanitizeLine(mcpStatus.routing.serverLastError || mcpStatus.routing.lastError || 'none')}`,
            '',
            apiConfigured ? `• Connect URL: ${buildConnectRoute(userId)}` : '• Connect API env still missing: CANVA_CLIENT_ID, CANVA_CLIENT_SECRET, CANVA_REDIRECT_URI'
          ].join('\n')
        };
      }

      if (!apiConfigured && !trigger.startsWith('CANVA MCP SEARCH:') && !trigger.startsWith('CANVA ASK:')) {
        return { response: '⚠️ Canva Connect API is not configured yet. Add `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, and `CANVA_REDIRECT_URI` for API-backed Canva actions. MCP search/ask can still run if Canva MCP is connected.' };
      }

      if (trigger.startsWith('CANVA LIST DESIGNS')) {
        const fields = parseLooseFields(payload);
        const result = await canva.listDesigns({ db: context.db, userId, query: fields.query || String(payload || '').trim() || undefined, sortBy: fields.sortby || 'modified_desc' });
        const items = Array.isArray(result.items) ? result.items.slice(0, 15) : [];
        if (!items.length) return { response: 'No Canva designs found.' };
        return { response: ['🖼️ *Canva designs*', '', ...items.map((item) => `• ${sanitizeLine(item.title || item.name || 'Untitled')} — \`${item.id}\`${item.urls?.edit_url ? `\n  ↳ edit: ${item.urls.edit_url}` : ''}`)].join('\n') };
      }

      if (trigger.startsWith('CANVA FIND:')) {
        const result = await canva.listDesigns({ db: context.db, userId, query: String(payload || '').trim(), sortBy: 'modified_desc' });
        const items = Array.isArray(result.items) ? result.items.slice(0, 10) : [];
        if (!items.length) return { response: 'No matching Canva designs found.' };
        return { response: ['🔎 *Matching Canva designs*', '', ...items.map((item) => `• ${sanitizeLine(item.title || item.name || 'Untitled')} — \`${item.id}\``)].join('\n') };
      }

      if (trigger.startsWith('CANVA GET DESIGN:')) {
        const designId = String(payload || '').trim();
        if (!designId) return { response: '⚠️ Usage: `CANVA GET DESIGN: design-id`' };
        const design = await canva.getDesign({ db: context.db, userId, designId });
        const formats = await canva.getDesignExportFormats({ db: context.db, userId, designId }).catch(() => null);
        return { response: [
          '🖼️ *Canva design details*', '',
          `• Title: ${sanitizeLine(design.title || design.name || 'Untitled')}`,
          `• ID: \`${design.id}\``,
          design.urls?.edit_url ? `• Edit URL: ${design.urls.edit_url}` : null,
          design.urls?.view_url ? `• View URL: ${design.urls.view_url}` : null,
          formats?.formats ? `• Export formats: ${formats.formats.map((f) => f.type || f).join(', ')}` : null
        ].filter(Boolean).join('\n') };
      }

      if (trigger.startsWith('CANVA EXPORT:')) {
        const fields = parseLooseFields(payload);
        const designId = fields.designid || fields.id || '';
        const fmt = fields.format || fields.type || 'png';
        if (!designId) return { response: '⚠️ Usage: `CANVA EXPORT: DesignId=<id> | Format=png`' };
        const job = await canva.createDesignExportJob({ db: context.db, userId, designId, format: fmt });
        const jobId = job.job?.id || job.id || 'unknown';
        return { response: `📦 *Canva export job created*\n\n• Design: \`${designId}\`\n• Format: ${fmt}\n• Job: \`${jobId}\`\n\nUse Canva or the API poller to fetch the finished export.` };
      }

      if (trigger.startsWith('CANVA COMMENT:')) {
        const fields = parseLooseFields(payload);
        const designId = fields.designid || fields.id || '';
        const message = fields.message || fields.comment || String(payload || '').trim();
        if (!designId || !message) return { response: '⚠️ Usage: `CANVA COMMENT: DesignId=<id> | Message=Your feedback`' };
        const result = await canva.createCommentThread({ db: context.db, userId, designId, message });
        return { response: `💬 *Canva comment created*\n\n• Design: \`${designId}\`\n• Thread: \`${result.thread?.id || result.id || 'created'}\`` };
      }

      if (trigger.startsWith('CANVA UPLOAD ASSET:')) {
        const fields = parseLooseFields(payload);
        if (fields.url) {
          const result = await canva.createAssetUploadJobFromUrl({ db: context.db, userId, url: fields.url, name: fields.name || undefined });
          return { response: `🖼️ *Canva asset upload job created*\n\n• URL: ${fields.url}\n• Job: \`${result.job?.id || result.id || 'created'}\`` };
        }
        const filePath = fields.path || String(payload || '').trim();
        if (!filePath || !fs.existsSync(filePath)) return { response: '⚠️ Usage: `CANVA UPLOAD ASSET: Path=C:\\path\\image.png | Name=Hero Image` or `CANVA UPLOAD ASSET: Url=https://...`' };
        const result = await canva.uploadAssetFromFile({ db: context.db, userId, filePath, name: fields.name || path.basename(filePath) });
        return { response: `🖼️ *Canva asset uploaded*\n\n• Asset: \`${result.asset?.id || result.id || 'uploaded'}\`` };
      }

      if (trigger.startsWith('CANVA MCP SEARCH:') || trigger.startsWith('CANVA ASK:')) {
        const outcome = await maybeCallCanvaMcp(context, trigger, String(payload || '').trim());
        if (outcome.usedMcp) return { response: outcome.response };
        return { response: `⚠️ *Canva MCP fallback activated*\n\nReason: ${outcome.decision?.reason || 'Canva MCP unavailable'}\n\n${outcome.fallback}` };
      }

      if (trigger.startsWith('CANVA DESIGN:') || trigger.startsWith('CREATE DESIGN:')) {
        const { format, brief, brand } = parseLegacyBrief(payload);
        if (!brief) return { response: '⚠️ Usage: `CANVA DESIGN: format | brief | brand`' };
        const designBrief = await generateDesignBrief(context, format, brief, brand);
        const title = `${brand} ${format} Design Brief`;
        const documentPath = await createWordDocument({ title, body: designBrief });
        const upload = await uploadGeneratedDocument(documentPath, 'docx');
        return {
          response: `✅ *Canva design brief created*\n\n🎨 *Format:* ${format}\n🏷️ *Brand:* ${brand}${upload?.id ? `\n☁️ Drive: \`${upload.id}\`` : ''}`,
          documentFile: documentPath
        };
      }

      return { response: '⚠️ Unknown Canva command. Try: `CANVA CONNECT`, `CANVA STATUS`, `CANVA LIST DESIGNS`, `CANVA FIND:`, `CANVA EXPORT:` or `CANVA ASK:`' };
    } catch (error) {
      logger.error('[CANVA] Error: ' + error.message);
      return { response: `❌ Canva error: ${error.message}` };
    }
  }
};
