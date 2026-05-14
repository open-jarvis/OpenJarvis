const logger = require('../helpers/logger');
const { createWordDocument, uploadGeneratedDocument } = require('../helpers/document-service');
const { createGoogleDoc, isGoogleWorkspaceConfigured } = require('../helpers/google-docs-service');

function parsePayload(payload) {
  const parts = String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return {
    title: parts[0] || '',
    brief: parts[1] || '',
    audience: parts[2] || '',
    format: (parts[3] || '').toLowerCase()
  };
}

async function generateDeckOutline(context, title, brief, audience) {
  const result = await context.aiEngine.chat(
    [{ role: 'user', content: `${title}\n\n${brief}\n\nAudience: ${audience || 'general'}` }],
    {
      systemPrompt:
        `${context.soulFile}\n\n` +
        'You are Serena\'s presentation strategist. ' +
        'Create a presentation deck outline with slide titles, key bullets, and speaker notes. ' +
        'Use plain text headings like "Slide 1", "Slide 2".',
      temperature: 0.45,
      maxTokens: 2200,
      task: 'deck-outline'
    }
  );

  return String(result.content || '').trim();
}

module.exports = {
  id: '07-assets',
  name: 'Asset Generator',
  description: 'Generate slide deck outlines and presentation assets that can be saved as Word docs or Google Docs.',
  triggers: ['GENERATE SLIDES:', 'CREATE DECK:'],

  execute: async function (payload, context) {
    try {
      const { title, brief, audience, format } = parsePayload(payload);
      if (!title) {
        return {
          response:
            '⚠️ Usage: `GENERATE SLIDES: Title | brief | audience | google-doc`'
        };
      }

      const outline = await generateDeckOutline(context, title, brief || title, audience);

      if (format === 'google-doc' && isGoogleWorkspaceConfigured()) {
        const doc = await createGoogleDoc(title, outline);
        return {
          response:
            `✅ *Slide deck outline created*\n\n` +
            `📝 *Title:* ${title}\n` +
            `🔗 *Google Doc:* ${doc.url}`
        };
      }

      const documentPath = await createWordDocument({ title, body: outline });
      const upload = await uploadGeneratedDocument(documentPath, 'docx');

      return {
        response:
          `✅ *Deck outline created*\n\n` +
          `📝 *Title:* ${title}\n` +
          `📄 Sent as a Word document` +
          (upload?.id ? `\n☁️ Drive: \`${upload.id}\`` : ''),
        documentFile: documentPath
      };
    } catch (error) {
      logger.error('[ASSETS] Error: ' + error.message);
      return { response: `❌ Asset generator error: ${error.message}` };
    }
  }
};
