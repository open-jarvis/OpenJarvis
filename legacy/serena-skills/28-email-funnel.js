// 28-email-funnel.js — Email Nurturing Funnels
// Builds complete automated email sequences.
// SMTP send via nodemailer. Full Mailchimp/Klaviyo API deferred.

const logger = require('../helpers/logger');

module.exports = {
  id: '28-email-funnel',
  name: 'Email Nurturing Funnels',
  description: 'Build complete automated email sequences for patient acquisition and retention.',
  triggers: ['NURTURE:', 'EMAIL FUNNEL:', 'BUILD FUNNEL:', 'DRIP SEQUENCE:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[EMAIL-FUNNEL] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '📧 *Email Nurturing Funnels*\n\n' +
            'Build complete email sequences for:\n\n' +
            'Usage: `NURTURE: [goal] | [audience] | [emails]`\n\n' +
            '*Examples:*\n' +
            '• `NURTURE: convert consultation leads | new enquiries | 5`\n' +
            '• `EMAIL FUNNEL: retain members | existing patients | 4`\n' +
            '• `BUILD FUNNEL: sell membership | cold leads | 7`\n' +
            '• `DRIP SEQUENCE: educate about hypertension | diagnosed patients | 6`\n\n' +
            'Number of emails defaults to 5 if not specified.'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts      = payload.split('|').map(p => p.trim());
      const goal       = parts[0];
      const audience   = parts[1] || 'potential patients';
      const emailCount = parseInt(parts[2]) || 5;

      // Upgraded prompt for high-quality, complete 5-email sequence
      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Create a complete, professional ${emailCount}-email nurturing sequence for Dr Piet Muller's medical practice.\n\n` +
            `Goal: "${goal}"\n` +
            `Target audience: ${audience}\n` +
            `Number of emails: ${emailCount}\n\n` +
            `For EACH email, provide clearly labeled sections:\n` +
            `📧 EMAIL [N] — Day X (e.g. Day 1, Day 3, Day 7, Day 10, Day 14)\n` +
            `SUBJECT LINE: Compelling subject (max 50 chars, no spam words)\n` +
            `PREVIEW TEXT: Short preview (max 90 chars)\n` +
            `FULL BODY: Warm, professional email body (150-300 words)\n` +
            `CTA: Clear call-to-action (ideally booking a consultation)\n` +
            `P.S.: Optional trust-building postscript\n\n` +
            `Sequence flow:\n` +
            `- Email 1: Welcome + deliver immediate value + soft introduction\n` +
            `- Email 2-3: Build trust with education and tips (South African context)\n` +
            `- Email 4: Address objections and show social proof\n` +
            `- Email 5: Strong CTA with urgency to book consultation\n\n` +
            `Tone: Warm, empathetic, professional, South African. Fully HPCSA-compliant. Value-first, never pushy.\n` +
            `Include a simple unsubscribe notice and POPIA compliance note in every email footer.\n` +
            `Make every email ready to copy-paste and send.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.65 }
      );

      const content = result.content || '';

      logger.info(`[EMAIL-FUNNEL] ${emailCount}-email sequence built for: ${goal.substring(0,50)}`);
      return {
        response:
          `📧 *${emailCount}-Email Nurture Sequence*\n` +
          `🎯 Goal: ${goal}\n` +
          `👥 Audience: ${audience}\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          `💡 Save sequence: \`DRIVE SAVE: nurture-sequence-${goal.replace(/\s+/g,'-').substring(0,30)}.txt | [paste full sequence]\``
      };

    } catch (err) {
      logger.error('[EMAIL-FUNNEL] Error:', err.message);
      return { response: `❌ Email funnel error: ${err.message}` };
    }
  }
};