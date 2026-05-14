// 14-podcast.js — Podcast Script Generator
// FIX: Apostrophe in description string caused SyntaxError: Unexpected identifier 's'
//      'Dr Piet's health show.' — the apostrophe terminated the single-quoted string early.
//      Fixed by switching description to double quotes.
// DEFERRED: Podcast hosting API (Buzzsprout/Anchor). Script generation via AI works now.

const logger = require('../helpers/logger');

module.exports = {
  id: '14-podcast',
  name: 'Podcast Script Generator',
  description: "Generate podcast episode scripts for Dr Piet's health show.",
  triggers: ['PODCAST SCRIPT:', 'EPISODE SCRIPT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[PODCAST] Triggered: ${context.triggerUsed} | payload: ${(payload || '').substring(0, 50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🎙️ *Podcast Script Generator*\n\n' +
            'Usage: `PODCAST SCRIPT: your episode topic`\n\n' +
            "Example: `PODCAST SCRIPT: Managing blood pressure naturally for South Africans`\n\n" +
            '⏳ *Hosting API:* Buzzsprout/Anchor integration coming soon.\n' +
            '_Script generation via AI is active now._'
        };
      }

      if (!context.aiEngine) {
        return { response: '⚠️ AI engine not available. Please try again.' };
      }

      const topic = payload.trim().slice(0, 500);

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Write a full podcast episode script for Dr Piet Muller's health show.\n\nTopic: "${topic}"\n\n` +
            'Structure:\n' +
            '1. INTRO (30 seconds) — warm welcome, hook, what listeners will learn today\n' +
            '2. SEGMENT 1 (3-4 min) — background and context on the topic\n' +
            '3. SEGMENT 2 (3-4 min) — practical advice and 3 actionable tips\n' +
            '4. SEGMENT 3 (2-3 min) — South African specific resources and context\n' +
            '5. OUTRO (30 seconds) — recap, health disclaimer, CTA to drpiet.co.za\n\n' +
            'Format each section with a [TIMESTAMP] marker and clear speaker cues.\n' +
            'Tone: Warm, professional, accessible. South African medical doctor voice.\n' +
            'Must include a health disclaimer before the outro.'
        }],
        { systemPrompt: context.soulFile, temperature: 0.65 }
      );

      logger.info(`[PODCAST] Script generated: ${topic.substring(0, 50)}`);
      return {
        response:
          `🎙️ *Podcast Script*\n📌 _${topic.substring(0, 80)}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 *Next:* Use `REPURPOSE: [paste script]` to create show notes and social clips.'
      };

    } catch (err) {
      logger.error('[PODCAST] Error:', err.message);
      return { response: `❌ Podcast script error: ${err.message}` };
    }
  }
};
