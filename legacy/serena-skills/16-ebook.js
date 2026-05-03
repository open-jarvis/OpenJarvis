// 16-ebook.js — eBook Creator
// Generates structured eBook outlines and full chapters via AI.
// Optionally saves to Google Drive as a text file.
// PDF export deferred — content generation is fully live.

const logger = require('../helpers/logger');

module.exports = {
  id: '16-ebook',
  name: 'eBook Creator',
  description: 'Create structured health eBook outlines and chapters for lead magnets and patient education.',
  triggers: ['EBOOK OUTLINE:', 'EBOOK CHAPTER:', 'EBOOK:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[EBOOK] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '📚 *eBook Creator*\n\n' +
            'Commands:\n' +
            '• `EBOOK OUTLINE: topic` — generate full book outline\n' +
            '• `EBOOK CHAPTER: topic | chapter title` — write a full chapter\n' +
            '• `EBOOK: topic | full` — generate complete short eBook (3000 words)\n\n' +
            'Examples:\n' +
            '• `EBOOK OUTLINE: The South African Guide to Managing High Blood Pressure`\n' +
            '• `EBOOK CHAPTER: diabetes management | Chapter 3: What to Eat`\n' +
            '• `EBOOK: 7 Habits for a Healthy Heart | full`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts   = payload.split('|').map(p => p.trim());
      const topic   = parts[0];
      const param2  = parts[1] || '';
      const isFull  = param2.toLowerCase() === 'full';

      // ── EBOOK OUTLINE ────────────────────────────────────────────
      if (context.triggerUsed === 'EBOOK OUTLINE:' || context.triggerUsed.startsWith('EBOOK OUTLINE')) {
        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a complete eBook outline for a South African medical doctor's lead magnet/patient education resource.\n\n` +
              `Title: "${topic}"\n\n` +
              `Provide:\n` +
              `📖 BOOK TITLE: (compelling, SEO-friendly)\n` +
              `📝 SUBTITLE: (benefit-driven, 1 sentence)\n` +
              `🎯 TARGET READER: Who this is for\n` +
              `💡 CORE PROMISE: What transformation this delivers\n\n` +
              `INTRODUCTION\n` +
              `CHAPTER 1: Title — 3-5 bullet points of content\n` +
              `CHAPTER 2: Title — 3-5 bullet points\n` +
              `CHAPTER 3: Title — 3-5 bullet points\n` +
              `CHAPTER 4: Title — 3-5 bullet points\n` +
              `CHAPTER 5: Title — 3-5 bullet points\n` +
              `CHAPTER 6: Title — 3-5 bullet points\n` +
              `CHAPTER 7: Title — 3-5 bullet points (if needed)\n` +
              `CONCLUSION + CALL TO ACTION\n` +
              `DISCLAIMER\n` +
              `ABOUT DR PIET\n\n` +
              `Make it practical, South African, HPCSA-compliant, and genuinely useful to patients. Use 6-8 chapters total.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[EBOOK] Outline created: ${topic.substring(0,50)}`);
        return {
          response:
            `📚 *eBook Outline*\n📌 _${topic}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Next: \`EBOOK CHAPTER: ${topic} | Chapter 1: [title from outline]\``
        };
      }

      // ── EBOOK CHAPTER ────────────────────────────────────────────
      if (context.triggerUsed === 'EBOOK CHAPTER:' || (param2 && !isFull)) {
        const chapterTitle = param2 || 'Chapter 1';

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Write a complete eBook chapter for Dr Piet Muller's health guide.\n\n` +
              `Book topic: "${topic}"\n` +
              `Chapter: "${chapterTitle}"\n\n` +
              `Requirements:\n` +
              `- 600-900 words\n` +
              `- Opening story or patient scenario\n` +
              `- 3-4 H2 subheadings\n` +
              `- Practical tips patients can act on today\n` +
              `- South African context (food, lifestyle, environment)\n` +
              `- "Dr Piet's Tip" callout box\n` +
              `- Chapter summary (3 bullet points)\n` +
              `- Transition to next chapter\n` +
              `- Health disclaimer\n\n` +
              `Tone: Warm, educational, like a knowledgeable friend who is also a doctor.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.65 }
        );

        logger.info(`[EBOOK] Chapter written: ${chapterTitle}`);
        return {
          response:
            `📖 *Chapter: ${chapterTitle}*\n📌 _${topic}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Save to Drive: \`DRIVE SAVE: ${chapterTitle}.txt | [paste chapter]\``
        };
      }

      // ── FULL SHORT EBOOK ─────────────────────────────────────────
      if (isFull) {
        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Write a complete short eBook (3 chapters, ~2500 words total) for Dr Piet Muller.\n\n` +
              `Topic: "${topic}"\n\n` +
              `Include: Title, intro, 3 chapters with subheadings, conclusion, disclaimer, CTA to drpiet.co.za\n` +
              `South African context throughout. HPCSA-compliant. Warm and practical.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[EBOOK] Full eBook generated: ${topic.substring(0,50)}`);
        return {
          response:
            `📚 *Complete eBook*\n📌 _${topic}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content.substring(0, 3800) +
            (result.content.length > 3800 ? '\n\n_[eBook truncated — request remaining sections]_' : '') +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Save to Drive: \`DRIVE SAVE: ${topic.replace(/\s+/g,'-')}.txt | [paste content]\``
        };
      }

      return { response: '⚠️ Usage: `EBOOK OUTLINE: topic`, `EBOOK CHAPTER: topic | chapter`, `EBOOK: topic | full`' };

    } catch (err) {
      logger.error('[EBOOK] Error:', err.message);
      return { response: `❌ eBook error: ${err.message}` };
    }
  }
};