// 09-finance.js — Finance & Invoicing Engine
// Generates invoices and financial summaries for Dr Piet's practice.
// DEFERRED: PayFast live payments (enable when PAYFAST_ENABLED=true)

const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

const safetyRule =
  'This skill handles financial operations only. It does not diagnose conditions ' +
  'or provide medical advice. Consult a physician for medical issues.';

module.exports = {
  id: '09-finance',
  name: 'Finance & Invoicing Engine',
  description: 'Generate invoices, payment summaries, and financial records.',
  triggers: ['GENERATE INVOICE:', 'INVOICE SUMMARY', 'RECORD PAYMENT:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_09_finance',
      description: 'Generate invoices, record payments, and fetch invoice summaries.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['GENERATE INVOICE:', 'INVOICE SUMMARY', 'RECORD PAYMENT:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      // ── GENERATE INVOICE ─────────────────────────────────────
      if (context.triggerUsed === 'GENERATE INVOICE:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `GENERATE INVOICE: Patient Name | Amount | Service`\n' +
              'Example: `GENERATE INVOICE: John Smith | 850 | Consultation`'
          };
        }

        const parsed = await generateStructuredOutput(context, {
          logLabel: 'finance-generate-invoice',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract invoice details from the request.',
          userPrompt: `User request: ${payload}\n\nReturn JSON with patientName, amount, service.`,
          schema: {
            type: 'object',
            required: ['patientName', 'amount'],
            properties: {
              patientName: { type: 'string' },
              amount: { type: 'number' },
              service: { type: 'string' }
            }
          }
        });
        const patientName = parsed.patientName;
        const amount = parsed.amount;
        const service = parsed.service || 'Medical Consultation';

        if (isNaN(amount) || amount <= 0) {
          return { response: '⚠️ Invalid amount. Please enter a positive number (e.g. 850).' };
        }

        const invoiceNumber = `INV-${Date.now()}`;
        const invoiceDate = new Date().toLocaleDateString('en-ZA', { timeZone: 'Africa/Johannesburg' });
        const vatAmount = (amount * 0.15).toFixed(2);
        const totalAmount = (amount + parseFloat(vatAmount)).toFixed(2);

        // FIX: renamed from generateInvoice to avoid collision with imported name
        const invoiceRecord = {
          invoiceNumber,
          patientName,
          service,
          amountExcl: amount.toFixed(2),
          vat: vatAmount,
          totalIncl: totalAmount,
          date: invoiceDate,
          status: 'PENDING',
          createdAt: new Date().toISOString()
        };

        // Save to DB if available
        if (context.db) {
          await context.db.run(
            `INSERT INTO invoices (invoiceNumber, patientName, service, amount, vat, total, status, createdAt)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
            [
              invoiceRecord.invoiceNumber, invoiceRecord.patientName, invoiceRecord.service,
              invoiceRecord.amountExcl, invoiceRecord.vat, invoiceRecord.totalIncl,
              invoiceRecord.status, invoiceRecord.createdAt
            ]
          );
        }

        logger.info(`[FINANCE] Invoice generated: ${invoiceNumber} for ${patientName} — R${totalAmount}`);
        return {
          response:
            `🧾 *Invoice Generated*\n\n` +
            `📋 *Invoice #:* ${invoiceNumber}\n` +
            `👤 *Patient:* ${patientName}\n` +
            `🩺 *Service:* ${service}\n` +
            `━━━━━━━━━━━━━━━━━━\n` +
            `💰 *Amount (excl. VAT):* R${invoiceRecord.amountExcl}\n` +
            `🏛️ *VAT (15%):* R${invoiceRecord.vat}\n` +
            `💵 *Total (incl. VAT):* R${invoiceRecord.totalIncl}\n` +
            `━━━━━━━━━━━━━━━━━━\n` +
            `📅 *Date:* ${invoiceDate}\n` +
            `📌 *Status:* PENDING\n\n` +
            `_${safetyRule}_`
        };
      }

      // ── RECORD PAYMENT ───────────────────────────────────────
      if (context.triggerUsed === 'RECORD PAYMENT:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `RECORD PAYMENT: INV-123456 | paid`' };
        }

        const parsed = await generateStructuredOutput(context, {
          logLabel: 'finance-record-payment',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a payment update from the request.',
          userPrompt: `User request: ${payload}\n\nReturn JSON with invoiceNumber and status.`,
          schema: {
            type: 'object',
            required: ['invoiceNumber', 'status'],
            properties: {
              invoiceNumber: { type: 'string' },
              status: { type: 'string' }
            }
          }
        });
        const invoiceNum = parsed.invoiceNumber;
        const status = parsed.status || 'PAID';

        if (context.db) {
          await context.db.run(
            'UPDATE invoices SET status = ? WHERE invoiceNumber = ?',
            [status.toUpperCase(), invoiceNum]
          );
        }

        logger.info(`[FINANCE] Payment recorded: ${invoiceNum} → ${status.toUpperCase()}`);
        return { response: `✅ *Payment recorded*\n\n📋 Invoice: ${invoiceNum}\n📌 Status: ${status.toUpperCase()}` };
      }

      // ── INVOICE SUMMARY ──────────────────────────────────────
      if (context.triggerUsed === 'INVOICE SUMMARY') {
        if (context.db) {
          const rows = await context.db.all('SELECT status, COUNT(*) as count, SUM(total) as total FROM invoices GROUP BY status');
          const lines = rows.map(r => `• ${r.status}: ${r.count} invoices — R${parseFloat(r.total || 0).toFixed(2)}`);
          return { response: `💰 *Invoice Summary*\n\n${lines.join('\n')}` };
        }
        return { response: '⚠️ Database not connected. Cannot retrieve invoice summary.' };
      }

      return { response: '⚠️ Unknown finance command. Try: `GENERATE INVOICE:`, `RECORD PAYMENT:`, or `INVOICE SUMMARY`' };

    } catch (err) {
      logger.error('[FINANCE] Error:', err.message);
      return { response: `❌ Finance error: ${err.message}` };
    }
  }
};
