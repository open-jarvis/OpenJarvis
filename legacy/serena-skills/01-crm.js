// 01-crm.js — Patient CRM (Healthcare-Compliant)
// Manages patient profiles in local SQLite via the db helper.
// DEFERRED: HubSpot sync, bulk CSV import (see 56-CrmSync.js)

const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

const safetyRule =
  'This skill manages patient records only. It does not diagnose conditions or ' +
  'recommend treatments. Consult a physician for medical advice.';

module.exports = {
  id: '01-crm',
  name: 'CRM — Patient Command Centre',
  description: 'Add, update, and retrieve patient profiles stored in local SQLite.',
  triggers: ['ADD PATIENT:', 'UPDATE PATIENT:', 'GET PATIENT:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_01_crm',
      description: 'Create, update, or retrieve patient CRM records.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['ADD PATIENT:', 'UPDATE PATIENT:', 'GET PATIENT:']
          },
          payload: {
            type: 'string'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      // ── ADD PATIENT ──────────────────────────────────────────
      if (context.triggerUsed === 'ADD PATIENT:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `ADD PATIENT: Name | email@example.com | +27821234567 | 1980-01-01 | Hypertension | Amlodipine`\n' +
              'Fields: Name | Email | Phone | DOB | Conditions (pipe-separated) | Medications (pipe-separated)'
          };
        }

        const profile = await generateStructuredOutput(context, {
          logLabel: 'crm-add-patient',
          reasoningEffort: 'medium',
          systemPrompt:
            'Extract a patient CRM record from the user request. Keep it factual and conservative.',
          userPrompt:
            `User request: ${payload}\n\n` +
            'Return JSON with name, email, phone, dob, conditions, medications.',
          schema: {
            type: 'object',
            required: ['name', 'email', 'phone', 'conditions', 'medications'],
            properties: {
              name: { type: 'string' },
              email: { type: 'string' },
              phone: { type: 'string' },
              dob: { type: 'string' },
              conditions: { type: 'array', items: { type: 'string' } },
              medications: { type: 'array', items: { type: 'string' } }
            }
          }
        });

        profile.createdAt = new Date().toISOString();
        profile.lastUpdated = new Date().toISOString();

        // Persist via db helper if available
        if (context.db) {
          await context.db.run(
            `INSERT OR REPLACE INTO patients (name, email, phone, dob, conditions, medications, createdAt, lastUpdated)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
            [
              profile.name, profile.email, profile.phone, profile.dob,
              JSON.stringify(profile.conditions), JSON.stringify(profile.medications),
              profile.createdAt, profile.lastUpdated
            ]
          );
        }

        logger.info(`[CRM] Patient added: ${profile.name}`);
        return {
          response:
            `✅ *Patient profile created*\n\n` +
            `👤 *Name:* ${profile.name}\n` +
            `📧 *Email:* ${profile.email}\n` +
            `📱 *Phone:* ${profile.phone}\n` +
            `🩺 *Conditions:* ${profile.conditions.join(', ') || 'None recorded'}\n` +
            `💊 *Medications:* ${profile.medications.join(', ') || 'None recorded'}\n\n` +
            `_${safetyRule}_`
        };
      }

      // ── UPDATE PATIENT ───────────────────────────────────────
      if (context.triggerUsed === 'UPDATE PATIENT:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '⚠️ Usage: `UPDATE PATIENT: email@example.com | field: value`\n' +
              'Example: `UPDATE PATIENT: john@example.com | phone: +27831234567`'
          };
        }

        const updates = await generateStructuredOutput(context, {
          logLabel: 'crm-update-patient',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a patient identifier and requested update fields from the user request.',
          userPrompt:
            `User request: ${payload}\n\n` +
            'Return JSON with identifier and updates object.',
          schema: {
            type: 'object',
            required: ['identifier', 'updates'],
            properties: {
              identifier: { type: 'string' },
              updates: {
                type: 'object',
                properties: {
                  name: { type: 'string' },
                  phone: { type: 'string' },
                  dob: { type: 'string' },
                  conditions: { type: 'string' },
                  medications: { type: 'string' },
                  email: { type: 'string' }
                }
              }
            }
          }
        });

        if (!updates.identifier || Object.keys(updates.updates || {}).length === 0) {
          return { response: '⚠️ Provide patient email and at least one field to update.' };
        }

        updates.updates.lastUpdated = new Date().toISOString();

        if (context.db) {
          const setClause = Object.keys(updates.updates).map(k => `${k} = ?`).join(', ');
          await context.db.run(
            `UPDATE patients SET ${setClause} WHERE email = ?`,
            [...Object.values(updates.updates), updates.identifier]
          );
        }

        logger.info(`[CRM] Patient updated: ${updates.identifier}`);
        return {
          response:
            `✅ *Patient record updated*\n\n` +
            `🔍 *Identifier:* ${updates.identifier}\n` +
            `📝 *Fields updated:* ${Object.keys(updates.updates).filter(k => k !== 'lastUpdated').join(', ')}\n\n` +
            `_${safetyRule}_`
        };
      }

      // ── GET PATIENT ──────────────────────────────────────────
      if (context.triggerUsed === 'GET PATIENT:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `GET PATIENT: email@example.com`' };
        }

        if (context.db) {
          const patient = await context.db.get(
            'SELECT * FROM patients WHERE email = ? OR name LIKE ?',
            [payload.trim(), `%${payload.trim()}%`]
          );

          if (!patient) {
            return { response: `❌ No patient found matching: _${payload.trim()}_` };
          }

          const conditions = JSON.parse(patient.conditions || '[]');
          const medications = JSON.parse(patient.medications || '[]');

          return {
            response:
              `👤 *Patient Record*\n\n` +
              `*Name:* ${patient.name}\n` +
              `*Email:* ${patient.email}\n` +
              `*Phone:* ${patient.phone}\n` +
              `*DOB:* ${patient.dob || 'Not recorded'}\n` +
              `*Conditions:* ${conditions.join(', ') || 'None'}\n` +
              `*Medications:* ${medications.join(', ') || 'None'}\n` +
              `*Last updated:* ${patient.lastUpdated}\n\n` +
              `_${safetyRule}_`
          };
        }

        return { response: '⚠️ Database not available. Contact your system administrator.' };
      }

      return { response: '⚠️ Unknown CRM command.' };

    } catch (err) {
      logger.error('[CRM] Error:', err.message);
      return { response: `❌ CRM error: ${err.message}` };
    }
  }
};
