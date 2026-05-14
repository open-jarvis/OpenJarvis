const logger = require('../helpers/logger');
const {
  createPdfDocument,
  createWordDocument,
  createExcelDocument,
  uploadGeneratedDocument
} = require('../helpers/document-service');

function deriveTitleAndBrief(payload, fallbackTitle) {
  const raw = String(payload || '').trim();
  if (!raw) {
    return { title: fallbackTitle, brief: '' };
  }

  const separatorIndex = raw.indexOf('|');
  if (separatorIndex === -1) {
    const autoTitle = raw.split(/\s+/).slice(0, 8).join(' ');
    return { title: autoTitle || fallbackTitle, brief: raw };
  }

  const title = raw.substring(0, separatorIndex).trim() || fallbackTitle;
  const brief = raw.substring(separatorIndex + 1).trim();
  return { title, brief };
}

function extractJsonBlock(text) {
  const fenced = text.match(/```json\s*([\s\S]*?)```/i);
  if (fenced) return fenced[1].trim();
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start !== -1 && end > start) return text.slice(start, end + 1);
  return text.trim();
}

async function generateNarrative(aiEngine, soulFile, brief, format, title) {
  const response = await aiEngine.chat(
    [{ role: 'user', content: brief }],
    {
      systemPrompt:
        `${soulFile}\n\n` +
        `You are Serena's document writing engine.\n` +
        `Create polished ${format.toUpperCase()}-ready content for a real business document.\n` +
        `Rules:\n` +
        `- Write in clean plain text with headings and short paragraphs.\n` +
        `- Do not use markdown tables.\n` +
        `- Keep it structured and professional.\n` +
        `- Title of the document: ${title}\n` +
        `- If the request is vague, choose the most useful professional structure.\n`,
      maxTokens: 2200,
      temperature: 0.4,
      task: `document-${format}`
    }
  );

  return response.content.trim();
}

async function generateWorkbookData(aiEngine, soulFile, brief, title) {
  const response = await aiEngine.chat(
    [{ role: 'user', content: brief }],
    {
      systemPrompt:
        `${soulFile}\n\n` +
        `You build Excel workbooks for Serena.\n` +
        `Return ONLY valid JSON with this exact shape:\n` +
        `{"title":"string","sheets":[{"name":"string","columns":["Col 1","Col 2"],"rows":[["value1","value2"]]}]}\n` +
        `Rules:\n` +
        `- Return valid JSON only.\n` +
        `- Use arrays for rows.\n` +
        `- Keep each sheet practical and business-ready.\n` +
        `- Document title: ${title}\n`,
      maxTokens: 1800,
      temperature: 0.2,
      task: 'document-xlsx'
    }
  );

  return JSON.parse(extractJsonBlock(response.content));
}

module.exports = {
  id: '67-documents',
  name: 'Document Factory',
  description: 'Create Word, Excel, and PDF files, send them to Telegram, and upload them to Google Drive.',
  triggers: ['CREATE PDF:', 'CREATE WORD:', 'CREATE DOCX:', 'CREATE EXCEL:', 'CREATE XLSX:', 'EXPORT PDF:'],

  execute: async function (payload, context) {
    try {
      const trigger = context.triggerUsed;
      const isPdf = trigger === 'CREATE PDF:' || trigger === 'EXPORT PDF:';
      const isWord = trigger === 'CREATE WORD:' || trigger === 'CREATE DOCX:';
      const isExcel = trigger === 'CREATE EXCEL:' || trigger === 'CREATE XLSX:';

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '⚠️ Usage examples:\n' +
            '`CREATE PDF: Weekly Report | Build a clean weekly practice performance report.`\n' +
            '`CREATE WORD: Patient Guide | Create a patient-friendly prep guide for metabolic screening.`\n' +
            '`CREATE EXCEL: Revenue Tracker | Build a monthly revenue tracker with totals.`'
        };
      }

      const { title, brief } = deriveTitleAndBrief(payload, 'Serena Document');
      const format = isPdf ? 'pdf' : isWord ? 'docx' : 'xlsx';
      let documentPath = null;
      let upload = null;

      if (isPdf) {
        const body = await generateNarrative(context.aiEngine, context.soulFile, brief, format, title);
        documentPath = await createPdfDocument({ title, body });
      } else if (isWord) {
        const body = await generateNarrative(context.aiEngine, context.soulFile, brief, format, title);
        documentPath = await createWordDocument({ title, body });
      } else if (isExcel) {
        const workbookData = await generateWorkbookData(context.aiEngine, context.soulFile, brief, title);
        documentPath = await createExcelDocument({ title: workbookData.title || title, workbookData });
      }

      upload = await uploadGeneratedDocument(documentPath, format);

      logger.info(`[DOCS] Created ${format.toUpperCase()} document: ${documentPath}`);

      const responseLines = [
        `✅ *${format.toUpperCase()} document created*`,
        `📄 *Title:* ${title}`,
        `📤 Sent to Telegram as an attachment`
      ];

      if (upload?.id) {
        responseLines.push(`☁️ Uploaded to Google Drive: \`${upload.id}\``);
      } else {
        responseLines.push('☁️ Google Drive upload skipped or unavailable');
      }

      return {
        response: responseLines.join('\n'),
        documentFile: documentPath
      };
    } catch (error) {
      logger.error('[DOCS] Error: ' + error.message);
      return { response: `❌ Document generation failed: ${error.message}` };
    }
  }
};
