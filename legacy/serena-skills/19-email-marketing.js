// 19-email-marketing.js — Email Marketing Campaigns
// Uses SMTP via nodemailer for now. Mailchimp/Klaviyo integration deferred.
// DEFERRED: Mailchimp/Klaviyo API (configure when email platform chosen)

const logger = require('../helpers/logger');

module.exports = {
  id: '19-email-marketing',
  name: 'Email Marketing Campaigns',
  description: 'Send email campaigns via SMTP. Mailchimp/Klaviyo integration deferred.',
  triggers: ['EMAIL CAMPAIGN:', 'EMAIL DRAFT:'],

  execute: async function (payload, context) {
    try {
      // ── EMAIL DRAFT (AI-generated) ───────────────────────────
      if (context.triggerUsed === 'EMAIL DRAFT:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `EMAIL DRAFT: subject | audience | topic`\n' +
              'Example: `EMAIL DRAFT: Managing Blood Pressure | hypertension patients | lifestyle tips`'
          };
        }

        // FIX: all variables now pulled from payload, not undeclared identifiers
        const parts = payload.split('|').map(p => p.trim());
        const subject = parts[0] || 'Health Update from Dr Piet';
        const audience = parts[1] || 'patients';
        const topic = parts[2] || subject;

        if (!context.aiEngine) {
          return { response: '⚠️ AI engine not available. Cannot generate email draft.' };
        }

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Write a health email newsletter for ${audience} about: "${topic}".\n\n` +
              `Subject line: ${subject}\n\n` +
              `Requirements:\n` +
              `- Warm, professional South African medical doctor tone\n` +
              `- 250-350 words\n` +
              `- 3 actionable tips\n` +
              `- Health disclaimer at the end\n` +
              `- Clear call to action (book a consultation at drpiet.co.za)\n` +
              `- Opening greeting and personal sign-off from Dr Piet`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[EMAIL] Draft generated: ${subject}`);
        return {
          response:
            `✉️ *Email Campaign Draft*\n\n` +
            `📧 *Subject:* ${subject}\n` +
            `👥 *Audience:* ${audience}\n\n` +
            `━━━━━━━━━━━━━━━━━━\n\n` +
            result.content +
            `\n\n━━━━━━━━━━━━━━━━━━\n` +
            `_Review and send via your email platform. Use \`EMAIL CAMPAIGN:\` to send via SMTP._`
        };
      }

      // ── SEND CAMPAIGN ────────────────────────────────────────
      if (context.triggerUsed === 'EMAIL CAMPAIGN:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `EMAIL CAMPAIGN: recipient@email.com | Subject | Body`\n\n' +
              '💡 Tip: Use `EMAIL DRAFT:` first to generate the content, then send here.'
          };
        }

        // FIX: variables pulled from data correctly
        const parts = payload.split('|').map(p => p.trim());
        const [toAddress, subject, ...bodyParts] = parts;
        const body = bodyParts.join('|').trim();

        if (!toAddress || !subject || !body) {
          return { response: '⚠️ Please provide: recipient | subject | body content' };
        }

        if (!process.env.SMTP_HOST || !process.env.SMTP_USER || !process.env.SMTP_PASS || process.env.SMTP_PASS === 'your-app-password-here') {
          return {
            response:
              `⚠️ *SMTP not configured*\n\n` +
              `Add to .env:\n` +
              `• \`SMTP_HOST=smtp.gmail.com\`\n` +
              `• \`SMTP_USER=dokterpiet@gmail.com\`\n` +
              `• \`SMTP_PASS=your-gmail-app-password\`\n\n` +
              `Gmail App Password: myaccount.google.com → Security → App Passwords\n\n` +
              `_Draft content was generated successfully — save it and send manually for now._`
          };
        }

        const nodemailer = require('nodemailer');
        const transporter = nodemailer.createTransporter({
          host: process.env.SMTP_HOST,
          port: parseInt(process.env.SMTP_PORT || '587', 10),
          secure: process.env.SMTP_SECURE === 'true',
          auth: {
            user: process.env.SMTP_USER,
            pass: process.env.SMTP_PASS
          }
        });

        await transporter.sendMail({
          from: `"${process.env.COMPANY_NAME || 'Dr Piet Muller'}" <${process.env.EMAIL_FROM || process.env.SMTP_USER}>`,
          to: toAddress,
          subject,
          html: body.replace(/\n/g, '<br>')
        });

        logger.info(`[EMAIL] Campaign sent to ${toAddress}: ${subject}`);
        return {
          response:
            `✅ *Email sent successfully*\n\n` +
            `📧 *To:* ${toAddress}\n` +
            `📝 *Subject:* ${subject}`
        };
      }

      return { response: '⚠️ Unknown email command. Try: `EMAIL DRAFT:` or `EMAIL CAMPAIGN:`' };

    } catch (err) {
      logger.error('[EMAIL] Error:', err.message);
      return { response: `❌ Email error: ${err.message}` };
    }
  }
};
