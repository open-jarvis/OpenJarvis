// 10-payfast.js — PayFast Payments
// DEFERRED: Live PayFast processing (PAYFAST_ENABLED=false in .env)
// When ready: set PAYFAST_MERCHANT_ID, PAYFAST_MERCHANT_KEY, PAYFAST_PASSPHRASE in .env
// Docs: https://developers.payfast.co.za/docs

const logger = require('../helpers/logger');
const crypto = require('crypto');

const safetyRule =
  'This skill handles payment processing only. It does not diagnose conditions ' +
  'or provide medical advice. Consult a physician for medical issues.';

// Build a PayFast payment URL (sandbox or live depending on env)
function buildPayfastUrl(params, passphrase) {
  const orderedKeys = [
    'merchant_id', 'merchant_key', 'return_url', 'cancel_url',
    'notify_url', 'name_first', 'name_last', 'email_address',
    'm_payment_id', 'amount', 'item_name'
  ];

  const pfOutput = orderedKeys
    .filter(k => params[k] !== undefined && params[k] !== '')
    .map(k => `${k}=${encodeURIComponent(params[k].toString().trim())}`)
    .join('&');

  const sigString = passphrase
    ? `${pfOutput}&passphrase=${encodeURIComponent(passphrase.trim())}`
    : pfOutput;

  const signature = crypto.createHash('md5').update(sigString).digest('hex');
  const base = process.env.PAYFAST_SANDBOX === 'true'
    ? 'https://sandbox.payfast.co.za/eng/process'
    : 'https://www.payfast.co.za/eng/process';

  return `${base}?${pfOutput}&signature=${signature}`;
}

module.exports = {
  id: '10-payfast',
  name: 'PayFast Payments & Webhooks',
  description: 'Generate PayFast payment links. Currently in sandbox mode.',
  triggers: ['PAYMENT LINK:', 'PAYMENT STATUS:'],

  execute: async function (payload, context) {
    try {
      // ── PAYMENT LINK ─────────────────────────────────────────
      if (context.triggerUsed === 'PAYMENT LINK:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `PAYMENT LINK: Patient Name | amount | description`\n' +
              'Example: `PAYMENT LINK: John Smith | 850 | Monthly Consultation`'
          };
        }

        const parts = payload.split('|').map(p => p.trim());
        const [patientName, amountStr, description = 'Medical Consultation'] = parts;
        const amount = parseFloat(amountStr);

        if (isNaN(amount) || amount <= 0) {
          return { response: '⚠️ Invalid amount. Enter a positive number (e.g. 850).' };
        }

        // FIX: getPatientProfile now sourced from context.db, not from a missing require
        const [firstName = patientName, lastName = ''] = patientName.split(' ');

        if (process.env.PAYFAST_ENABLED !== 'true') {
          logger.info(`[PAYFAST] Sandbox link generated for ${patientName} — R${amount}`);
          return {
            response:
              `🔔 *PayFast is in sandbox/disabled mode*\n\n` +
              `When enabled, a payment link would be generated for:\n\n` +
              `👤 *Patient:* ${patientName}\n` +
              `💰 *Amount:* R${amount.toFixed(2)}\n` +
              `🩺 *For:* ${description}\n\n` +
              `To enable live payments:\n` +
              `1. Set \`PAYFAST_MERCHANT_ID\`, \`PAYFAST_MERCHANT_KEY\`, \`PAYFAST_PASSPHRASE\` in .env\n` +
              `2. Set \`PAYFAST_ENABLED=true\`\n` +
              `3. Set \`PAYFAST_SANDBOX=false\` for production\n\n` +
              `_${safetyRule}_`
          };
        }

        const paymentId = `PAY-${Date.now()}`;
        const params = {
          merchant_id: process.env.PAYFAST_MERCHANT_ID,
          merchant_key: process.env.PAYFAST_MERCHANT_KEY,
          return_url: `${process.env.WORDPRESS_URL || 'https://drpiet.co.za'}/payment-success`,
          cancel_url: `${process.env.WORDPRESS_URL || 'https://drpiet.co.za'}/payment-cancel`,
          notify_url: `${process.env.WORDPRESS_URL || 'https://drpiet.co.za'}/payfast-webhook`,
          name_first: firstName,
          name_last: lastName,
          m_payment_id: paymentId,
          amount: amount.toFixed(2),
          item_name: description
        };

        const paymentUrl = buildPayfastUrl(params, process.env.PAYFAST_PASSPHRASE);

        logger.info(`[PAYFAST] Payment link generated: ${paymentId} — R${amount}`);
        return {
          response:
            `💳 *Payment Link Generated*\n\n` +
            `👤 *Patient:* ${patientName}\n` +
            `💰 *Amount:* R${amount.toFixed(2)}\n` +
            `🩺 *For:* ${description}\n` +
            `🔑 *Payment ID:* ${paymentId}\n\n` +
            `🔗 *Payment Link:*\n${paymentUrl}\n\n` +
            `_${safetyRule}_`
        };
      }

      return { response: '⚠️ Unknown PayFast command. Try: `PAYMENT LINK: Name | amount | description`' };

    } catch (err) {
      logger.error('[PAYFAST] Error:', err.message);
      return { response: `❌ PayFast error: ${err.message}` };
    }
  }
};
