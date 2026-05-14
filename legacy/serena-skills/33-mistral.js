// 33-mistral.js — Mistral AI Analyser
// Uses Mistral API for vision analysis and advanced reasoning.
// Requires: MISTRAL_API_KEY in .env
// Falls back to primary AI engine if Mistral unavailable.

const logger = require('../helpers/logger');

const MISTRAL_URL = 'https://api.mistral.ai/v1/chat/completions';

async function callMistral(messages, model = 'mistral-small-latest') {
  const apiKey = process.env.MISTRAL_API_KEY;
  if (!apiKey) throw new Error('MISTRAL_API_KEY not set in .env');

  const res = await fetch(MISTRAL_URL, {
    method:  'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type':  'application/json'
    },
    body: JSON.stringify({
      model,
      messages,
      max_tokens:  4096,
      temperature: 0.3
    })
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Mistral API error ${res.status}: ${err.substring(0, 200)}`);
  }

  const data = await res.json();
  return data.choices?.[0]?.message?.content || '';
}

module.exports = {
  id: '33-mistral',
  name: 'Mistral AI Analyser',
  description: 'Use Mistral AI for image analysis, document reading, and advanced reasoning tasks.',
  triggers: ['MISTRAL ANALYSE:', 'ANALYSE IMAGE:', 'MISTRAL:', 'READ DOCUMENT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[MISTRAL] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🔍 *Mistral AI Analyser*\n\n' +
            'Uses Mistral AI for:\n' +
            '• Image analysis (with photo upload)\n' +
            '• Document text analysis\n' +
            '• Complex multi-step reasoning\n' +
            '• Medical literature review\n\n' +
            'Usage:\n' +
            '• `MISTRAL ANALYSE: [text or question]`\n' +
            '• Upload photo + caption `ANALYSE IMAGE: what is in this image?`\n' +
            '• `READ DOCUMENT: [paste document text]`\n\n' +
            (process.env.MISTRAL_API_KEY
              ? '✅ Mistral API configured'
              : '⚠️ Add MISTRAL_API_KEY to .env — get key at console.mistral.ai')
        };
      }

      const prompt   = payload.trim().slice(0, 8000);
      const messages = [];

      // If there's a photo file ID in context, build a vision message
      if (context.photoFileId && process.env.TELEGRAM_TOKEN) {
        try {
          // Get file URL from Telegram
          const fileInfoRes = await fetch(
            `https://api.telegram.org/bot${process.env.TELEGRAM_TOKEN}/getFile?file_id=${context.photoFileId}`
          );
          const fileInfo = await fileInfoRes.json();
          const imageUrl = `https://api.telegram.org/file/bot${process.env.TELEGRAM_TOKEN}/${fileInfo.result.file_path}`;

          messages.push({
            role:    'user',
            content: [
              { type: 'image_url', image_url: imageUrl },
              { type: 'text',      text: prompt }
            ]
          });
        } catch (imgErr) {
          logger.warn('[MISTRAL] Image fetch failed: ' + imgErr.message);
          messages.push({ role: 'user', content: prompt });
        }
      } else {
        messages.push({ role: 'user', content: prompt });
      }

      let answer;
      try {
        // Use vision model if image present, otherwise small model
        const model = context.photoFileId ? 'pixtral-12b-2409' : 'mistral-small-latest';
        answer = await callMistral(messages, model);
      } catch (mistralErr) {
        logger.warn('[MISTRAL] Falling back to primary AI: ' + mistralErr.message);

        if (!context.aiEngine) throw mistralErr;
        const fallback = await context.aiEngine.chat(
          [{ role: 'user', content: prompt }],
          { systemPrompt: context.soulFile, temperature: 0.3 }
        );
        return {
          response:
            '⚠️ _Mistral unavailable — using primary AI:_\n\n' +
            fallback.content
        };
      }

      logger.info(`[MISTRAL] Analysis complete (${answer.length} chars)`);
      return {
        response:
          `🔍 *Mistral Analysis*\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          answer.substring(0, 3800) +
          (answer.length > 3800 ? '\n\n_[Analysis truncated]_' : '') +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '_Powered by Mistral AI_'
      };

    } catch (err) {
      logger.error('[MISTRAL] Error:', err.message);
      return { response: `❌ Mistral error: ${err.message}` };
    }
  }
};
