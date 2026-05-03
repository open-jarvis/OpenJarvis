// 17-newsletter.js — Health Newsletter Engine
// Generates weekly health newsletters and optionally sends via SMTP.
// Full Mailchimp/Klaviyo integration deferred — SMTP send is live.

const logger = require('../helpers/logger');

module.exports = {
  id: '17-newsletter',
  name: 'Newsletter Engine',
  description: 'Generate and send weekly health newsletters to patients.',
  triggers: ['NEWSLETTER:', 'HEALTH NEWSLETTER:', 'WEEKLY NEWSLETTER'],

  execute: async function (payload, context) {
    try {
      logger.info(`[NEWSLETTER] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (context.triggerUsed === 'WEEKLY NEWSLETTER' && !payload) {
        // Auto-generate this week's newsletter
        payload = 'weekly health roundup — include seasonal tips, a patient FAQ, and a wellness habit';
      }

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '📧 *Newsletter Engine*\n\n' +
            'Usage:\n' +
            '• `NEWSLETTER: topic` — generate newsletter on topic\n' +
            '• `WEEKLY NEWSLETTER` — auto-generate weekly health roundup\n' +
            '• `NEWSLETTER: topic | send | recipient@email.com` — generate and send\n\n' +
            'Example: `NEWSLETTER: managing stress during load-shedding`\n\n' +
            'For bulk send, pair with your email platform.'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts    = payload.split('|').map(p => p.trim());
      const topic    = parts[0];
      const shouldSend = (parts[1] || '').toLowerCase() === 'send';
      const recipient  = parts[2] || '';

      const now      = new Date();
      const monthStr = now.toLocaleString('en-ZA', { month: 'long', year: 'numeric' });

      // Upgraded prompt for richer, longer newsletter
      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Write a professional, high-quality health newsletter for Dr Piet Muller's patients.\n\n` +
            `Month: ${monthStr}\n` +
            `Topic: "${topic}"\n\n` +
            `Requirements — write a FULL, detailed newsletter:\n` +
            `1. SUBJECT LINE: Provide 5 strong, engaging options for A/B testing\n\n` +
            `2. PREVIEW TEXT: One compelling preview text (max 90 characters)\n\n` +
            `3. HEADER: Warm personal greeting from Dr Piet (include both Afrikaans and English if possible)\n\n` +
            `4. MAIN ARTICLE: 350-500 words. Make it warm, educational, practical and South Africa-specific. Deeply cover how the topic affects health (physical + mental). Use real-life SA examples.\n\n` +
            `5. 3 QUICK TIPS: 3 actionable, specific health tips related to the topic\n\n` +
            `6. PATIENT Q&A: 3 common patient questions with thoughtful answers from Dr Piet\n\n` +
            `7. CLINIC NEWS: Short update about the practice or services\n\n` +
            `8. CTA: Strong call-to-action to book a consultation or visit drpiet.co.za\n\n` +
            `9. FOOTER: Unsubscribe notice + full health disclaimer + practice contact\n\n` +
            `Tone: Warm, professional, empathetic, South African, fully HPCSA-compliant. Never make cure claims.\n` +
            `Write the complete newsletter in one response. Do not truncate.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.65 }
      );

      const content = result.content || '';

      // Optionally send via SMTP
      if (shouldSend && recipient && process.env.SMTP_HOST && process.env.SMTP_PASS) {
        try {
          const nodemailer  = require('nodemailer');
          const transporter = nodemailer.createTransporter({
            host:   process.env.SMTP_HOST,
            port:   parseInt(process.env.SMTP_PORT || '587'),
            secure: process.env.SMTP_SECURE === 'true',
            auth:   { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
          });

          const subjectMatch = content.match(/SUBJECT LINE[:\s]+(.+)/i);
          const subject      = subjectMatch ? subjectMatch[1].split('\n')[0].trim() : `Health Update — ${monthStr}`;

          await transporter.sendMail({
            from:    `"${process.env.COMPANY_NAME || 'Dr Piet Muller'}" <${process.env.EMAIL_FROM || process.env.SMTP_USER}>`,
            to:      recipient,
            subject,
            html:    content.replace(/\n/g, '<br>')
          });

          logger.info(`[NEWSLETTER] Sent to ${recipient}`);
          return {
            response:
              `✅ *Newsletter Generated & Sent*\n\n` +
              `📧 *To:* ${recipient}\n` +
              `📌 *Topic:* ${topic}\n\n` +
              `Preview (first 500 chars):\n${content.substring(0, 500)}...`
          };
        } catch (smtpErr) {
          logger.warn('[NEWSLETTER] SMTP send failed: ' + smtpErr.message);
        }
      }

      logger.info(`[NEWSLETTER] Generated for: ${topic.substring(0,50)}`);
      return {
        response:
          `📧 *Newsletter — ${monthStr}*\n📌 _${topic}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          `💡 To send: \`NEWSLETTER: ${topic} | send | recipient@email.com\``
      };

    } catch (err) {
      logger.error('[NEWSLETTER] Error:', err.message);
      return { response: `❌ Newsletter error: ${err.message}` };
    }
  }
};