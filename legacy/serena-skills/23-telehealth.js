const logger = require('../helpers/logger');
const { createWordDocument, uploadGeneratedDocument } = require('../helpers/document-service');

function parsePayload(payload) {
  const parts = String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return {
    patient: parts[0] || 'Patient',
    topic: parts[1] || 'telehealth consultation',
    date: parts[2] || 'next available session'
  };
}

async function generatePrep(context, patient, topic, date) {
  const result = await context.aiEngine.chat(
    [{ role: 'user', content: `Patient: ${patient}\nTopic: ${topic}\nDate: ${date}` }],
    {
      systemPrompt:
        `${context.soulFile}\n\n` +
        'You are Serena\'s telehealth preparation assistant. ' +
        'Create a patient-ready telehealth prep pack with setup checklist, documents to prepare, questions to think about, and consultation-day instructions. ' +
        'Keep it professional, practical, and safe.',
      temperature: 0.35,
      maxTokens: 1800,
      task: 'telehealth-prep'
    }
  );

  return String(result.content || '').trim();
}

module.exports = {
  id: '23-telehealth',
  name: 'Telehealth Prep',
  description: 'Prepare patients for online consultations with a practical telehealth checklist and consult-prep pack.',
  triggers: ['TELEHEALTH PREP:', 'CONSULT PREP:'],

  execute: async function (payload, context) {
    try {
      const { patient, topic, date } = parsePayload(payload);
      const prep = await generatePrep(context, patient, topic, date);
      const title = `${patient} Telehealth Prep`;
      const documentPath = await createWordDocument({ title, body: prep });
      const upload = await uploadGeneratedDocument(documentPath, 'docx');

      return {
        response:
          `✅ *Telehealth prep pack ready*\n\n` +
          `👤 *Patient:* ${patient}\n` +
          `📌 *Focus:* ${topic}\n` +
          `🗓️ *Session:* ${date}` +
          (upload?.id ? `\n☁️ Drive: \`${upload.id}\`` : ''),
        documentFile: documentPath
      };
    } catch (error) {
      logger.error('[TELEHEALTH] Error: ' + error.message);
      return { response: `❌ Telehealth prep error: ${error.message}` };
    }
  }
};
