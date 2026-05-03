// 11-whatsapp.js — WhatsApp Business Integration
// DEFERRED: WhatsApp disabled until META_ACCESS_TOKEN configured.
// When ready: set WHATSAPP_ENABLED=true, META_ACCESS_TOKEN, META_PHONE_NUMBER_ID in .env
// API Docs: https://developers.facebook.com/docs/whatsapp/cloud-api

const logger = require('../helpers/logger');

const safetyRule =
  'This skill handles WhatsApp messages only. It does not diagnose conditions ' +
  'or provide medical advice. Consult a physician for medical issues.';

// FIX: renamed internal function to avoid same-scope shadow of any future import
async function sendViaMetaAPI(recipient, message) {
  const response = await fetch(
    `https://graph.facebook.com/${process.env.META_API_VERSION || 'v21.0'}/${process.env.META_PHONE_NUMBER_ID}/messages`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.META_ACCESS_TOKEN}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        messaging_product: 'whatsapp',
        to: recipient,
        type: 'text',
        text: { body: message }
      })
    }
  );

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Meta API error: ${err}`);
  }

  return await response.json();
}

module.exports = {
  id: '11-whatsapp',
  name: 'WhatsApp Business Integration',
  description: 'Send WhatsApp messages via Meta Cloud API. Currently deferred.',
  triggers: ['WHATSAPP:'],

  execute: async function (payload, context) {
    try {
      if (process.env.WHATSAPP_ENABLED !== 'true') {
        return {
          response:
            `📵 *WhatsApp is currently disabled*\n\n` +
            `Serena is communicating with Dr Piet via Telegram only.\n\n` +
            `To enable WhatsApp messaging:\n` +
            `1. Set up Meta WhatsApp Business Cloud API\n` +
            `2. Add \`META_ACCESS_TOKEN\` and \`META_PHONE_NUMBER_ID\` to .env\n` +
            `3. Set \`WHATSAPP_ENABLED=true\`\n\n` +
            `_${safetyRule}_`
        };
      }

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '⚠️ Usage: `WHATSAPP: +27821234567 | Your message here`\n' +
            'Recipient must include country code.'
        };
      }

      const sepIdx = payload.indexOf('|');
      if (sepIdx === -1) {
        return { response: '⚠️ Separate recipient and message with `|`' };
      }

      const recipient = payload.substring(0, sepIdx).trim().replace(/\s+/g, '');
      const message = payload.substring(sepIdx + 1).trim();

      if (!recipient.startsWith('+')) {
        return { response: '⚠️ Recipient must start with country code, e.g. +27821234567' };
      }

      const result = await sendViaMetaAPI(recipient, message);

      logger.info(`[WHATSAPP] Message sent to ${recipient}`);
      return {
        response:
          `✅ *WhatsApp message sent*\n\n` +
          `📱 *To:* ${recipient}\n` +
          `💬 *Message:* ${message.substring(0, 80)}${message.length > 80 ? '...' : ''}\n` +
          `🔑 *Message ID:* ${result.messages?.[0]?.id || 'N/A'}`
      };

    } catch (err) {
      logger.error('[WHATSAPP] Error:', err.message);
      return { response: `❌ WhatsApp error: ${err.message}` };
    }
  }
};
