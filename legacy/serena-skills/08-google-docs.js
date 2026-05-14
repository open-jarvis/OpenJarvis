const logger = require('../helpers/logger');
const { createGoogleDoc, findGoogleDocByTitle, isGoogleWorkspaceConfigured, updateGoogleDoc } = require('../helpers/google-docs-service');

function parsePayload(payload) {
  const parts = String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return {
    primary: parts[0] || '',
    secondary: parts[1] || '',
    tertiary: parts[2] || '',
    parts
  };
}

async function generateDocContent(context, title, brief) {
  const result = await context.aiEngine.chat(
    [{ role: 'user', content: brief || title }],
    {
      systemPrompt:
        `${context.soulFile}\n\n` +
        'You are Serena\'s Google Docs writing engine. ' +
        'Write a polished, professional document in plain text with headings and short paragraphs.',
      temperature: 0.4,
      maxTokens: 1800,
      task: 'google-docs'
    }
  );

  return String(result.content || '').trim();
}

module.exports = {
  id: '08-google-docs',
  name: 'Google Docs Integration',
  description: 'Create and update Google Docs documents using the connected Google Workspace account.',
  triggers: ['CREATE DOC:', 'UPDATE DOC:'],

  execute: async function (payload, context) {
    try {
      if (!isGoogleWorkspaceConfigured()) {
        return {
          response:
            '⚠️ *Google Docs not configured*\n\n' +
            'Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` in `.env`.'
        };
      }

      const { primary, secondary, tertiary, parts } = parsePayload(payload);

      if (context.triggerUsed === 'CREATE DOC:') {
        if (!primary) {
          return {
            response:
              '⚠️ Usage: `CREATE DOC: Document Title | brief or content`'
          };
        }

        const content = secondary
          ? await generateDocContent(context, primary, secondary)
          : await generateDocContent(context, primary, primary);
        const created = await createGoogleDoc(primary, content);

        return {
          response:
            `✅ *Google Doc created*\n\n` +
            `📝 *Title:* ${primary}\n` +
            `🔗 *Open:* ${created.url}`
        };
      }

      if (!primary || !secondary) {
        return {
          response:
            '⚠️ Usage: `UPDATE DOC: doc title or id | new content or brief | replace`'
        };
      }

      const replaceExisting = (tertiary || '').toLowerCase() === 'replace';
      const existing = primary.includes('docs.google.com') || /^[a-zA-Z0-9_-]{20,}$/.test(primary)
        ? { id: primary.replace(/^.*\/d\/([a-zA-Z0-9_-]+).*$/, '$1') }
        : await findGoogleDocByTitle(primary);

      if (!existing?.id) {
        return { response: `❌ Could not find a Google Doc matching "${primary}".` };
      }

      const content = await generateDocContent(context, primary, secondary);
      const updated = await updateGoogleDoc(existing.id, content, replaceExisting);

      return {
        response:
          `✅ *Google Doc updated*\n\n` +
          `📝 *Target:* ${primary}\n` +
          `🔗 *Open:* ${updated.url}`
      };
    } catch (error) {
      logger.error('[GOOGLE-DOCS] Error: ' + error.message);
      return { response: `❌ Google Docs error: ${error.message}` };
    }
  }
};
