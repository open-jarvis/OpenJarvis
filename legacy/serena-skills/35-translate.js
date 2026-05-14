// 35-translate.js — Multi-language Translator
// Translates between English, Afrikaans, Zulu, Xhosa, and Sotho.
// Uses AI engine (no external API key required).
// Falls back to HF Helsinki-NLP model if HUGGINGFACE_API_KEY is set.

const logger = require('../helpers/logger');

const LANGUAGE_MAP = {
  af: 'Afrikaans', afrikaans: 'Afrikaans',
  zu: 'Zulu', zulu: 'Zulu',
  xh: 'Xhosa', xhosa: 'Xhosa',
  st: 'Sesotho', sotho: 'Sesotho', sesotho: 'Sesotho',
  en: 'English', english: 'English',
  fr: 'French', french: 'French',
  pt: 'Portuguese', portuguese: 'Portuguese'
};

module.exports = {
  id: '35-translate',
  name: 'South African Language Translator',
  description: 'Translate text between English, Afrikaans, Zulu, Xhosa, and Sesotho.',
  triggers: ['TRANSLATE:', 'AFRIKAANS:', 'VERTAAL:', 'TRANSLATE TO:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[TRANSLATE] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 2) {
        return {
          response:
            '🌍 *South African Translator*\n\n' +
            'Usage: `TRANSLATE: [text] | [target language]`\n\n' +
            '*Supported languages:*\n' +
            '• Afrikaans (af)\n• Zulu (zu)\n• Xhosa (xh)\n• Sesotho (st)\n• English (en)\n• French (fr)\n\n' +
            '*Examples:*\n' +
            '• `TRANSLATE: Please take your medication daily | Afrikaans`\n' +
            '• `AFRIKAANS: Good morning, how are you feeling today?`\n' +
            '• `TRANSLATE: Consult your doctor | Zulu`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      let targetLang = 'Afrikaans';
      let textToTranslate = payload.trim();

      // Handle AFRIKAANS: shortcut
      if (context.triggerUsed === 'AFRIKAANS:') {
        targetLang = 'Afrikaans';
      } else {
        // Parse "text | language" format
        const sepIdx = payload.lastIndexOf('|');
        if (sepIdx !== -1) {
          const langKey = payload.substring(sepIdx + 1).trim().toLowerCase();
          targetLang    = LANGUAGE_MAP[langKey] || langKey;
          textToTranslate = payload.substring(0, sepIdx).trim();
        }
      }

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Translate the following text to ${targetLang}. ` +
            `Return ONLY the translation — no explanation, no original text, no prefix.\n\n` +
            `Text: "${textToTranslate}"`
        }],
        { systemPrompt: 'You are a professional South African medical translator. Translate accurately and naturally.', temperature: 0.2 }
      );

      logger.info(`[TRANSLATE] Translated to ${targetLang}`);
      return {
        response:
          `🌍 *Translation to ${targetLang}*\n\n` +
          `*Original:* _${textToTranslate.substring(0, 200)}_\n\n` +
          `*${targetLang}:* ${result.content.trim()}`
      };

    } catch (err) {
      logger.error('[TRANSLATE] Error:', err.message);
      return { response: `❌ Translation error: ${err.message}` };
    }
  }
};
