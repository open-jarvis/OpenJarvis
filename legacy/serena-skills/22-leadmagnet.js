// 22-leadmagnet.js — Lead Magnet Generator
// Generates complete lead magnet packages: content, landing page copy, thank-you page,
// and optionally saves the lead magnet content to Google Drive.

const logger = require('../helpers/logger');

module.exports = {
  id: '22-leadmagnet',
  name: 'Lead Magnet Generator',
  description: 'Generate complete lead magnet packages — content, landing page copy, and email capture.',
  triggers: ['LEAD PAGE:', 'CAPTURE PAGE:', 'LEAD MAGNET FULL:', 'FREEBIE:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[LEADMAGNET] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🎁 *Lead Magnet Generator*\n\n' +
            'Creates complete lead magnet packages for drpiet.co.za\n\n' +
            'Usage: `LEAD PAGE: topic | target audience | format`\n\n' +
            '*Formats:* guide, checklist, quiz, video-series, ebook, toolkit\n\n' +
            'Examples:\n' +
            '• `LEAD PAGE: controlling blood pressure | hypertension patients | checklist`\n' +
            '• `FREEBIE: 7-day sugar detox plan | weight loss patients | guide`\n' +
            '• `CAPTURE PAGE: corporate wellness ROI | HR managers | toolkit`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts    = payload.split('|').map(p => p.trim());
      const topic    = parts[0];
      const audience = parts[1] || 'patients interested in health';
      const format   = parts[2] || 'guide';

      const formatGuide = {
        guide:       'A 5-10 page PDF guide with actionable steps',
        checklist:   'A one-page printable checklist with 10-15 action items',
        quiz:        'A 5-question health assessment quiz with personalised results',
        'video-series': 'A 3-part video series outline (each 5-10 minutes)',
        ebook:       'A short eBook (20-30 pages) with chapters and exercises',
        toolkit:     'A resource toolkit with templates, trackers, and guides'
      };

      // Upgraded prompt for complete, high-quality output
      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Create a COMPLETE professional lead magnet package for Dr Piet Muller's medical practice.\n\n` +
            `Topic: "${topic}"\n` +
            `Target Audience: ${audience}\n` +
            `Format: ${format} (${formatGuide[format] || format})\n\n` +
            `You MUST deliver ALL sections clearly separated:\n\n` +
            `━━━ 1. LEAD MAGNET CONTENT ━━━\n` +
            `• 3 compelling title options\n` +
            `• Subtitle (benefit-driven)\n` +
            `• Full content (600-1000 words) — well-structured, actionable, South African context\n\n` +
            `━━━ 2. LANDING PAGE COPY ━━━\n` +
            `• Main Headline\n` +
            `• Subheadline\n` +
            `• 5 key benefits (bullet points)\n` +
            `• Social proof / stats placeholder\n` +
            `• 3 CTA button text options\n` +
            `• Form fields (Name + Email)\n` +
            `• POPIA/privacy footer disclaimer\n\n` +
            `━━━ 3. THANK YOU PAGE ━━━\n` +
            `• Thank you headline\n` +
            `• What happens next (3 steps)\n` +
            `• One immediate actionable tip\n` +
            `• Soft CTA to book consultation at drpiet.co.za\n\n` +
            `Tone: Warm, professional, empathetic, South African. Fully HPCSA-compliant. No cure claims or guarantees.\n` +
            `Make the content valuable and ready to use. Use clear markdown headings for each section.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.65 }
      );

      const content = result.content || '';

      logger.info(`[LEADMAGNET] Package generated: ${topic.substring(0,50)}`);
      return {
        response:
          `🎁 *Lead Magnet Package*\n📌 _${topic}_ | _${audience}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          `💡 Save content: \`DRIVE SAVE: ${topic.replace(/\s+/g,'-')}-leadmagnet.txt | [paste full content]\`\n` +
          `💡 Create welcome sequence: \`WELCOME SEQUENCE: ${topic}\``
      };

    } catch (err) {
      logger.error('[LEADMAGNET] Error:', err.message);
      return { response: `❌ Lead magnet error: ${err.message}` };
    }
  }
};