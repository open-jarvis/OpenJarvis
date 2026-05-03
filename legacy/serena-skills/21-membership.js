// 21-membership.js — Membership Plan Manager
// Manages patient membership plans locally in SQLite.
// WooCommerce Subscriptions sync deferred — core logic is live.

const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

const PLANS = {
  basic: {
    name:     'Basic Wellness Plan',
    price:    399,
    features: ['Monthly health check-in (15 min)', '10% discount on consultations', 'Monthly health newsletter', 'Secure messaging via Telegram']
  },
  standard: {
    name:     'Standard Care Plan',
    price:    799,
    features: ['Bi-monthly consultation (30 min)', 'Quarterly blood pressure & BMI screening', '15% discount on all services', 'Priority booking', 'Monthly newsletter + personalised tips']
  },
  premium: {
    name:     'Premium Health Partnership',
    price:    1499,
    features: ['Monthly consultation (45 min)', 'Full quarterly health screening', 'Annual comprehensive blood panel', '20% discount on all services', 'Priority emergency access', 'Personalised wellness roadmap', 'Family add-on available']
  }
};

module.exports = {
  id: '21-membership',
  name: 'Membership Plan Manager',
  description: 'Manage patient care plan memberships — enrol, view, and list members.',
  triggers: ['CREATE MEMBERSHIP:', 'MEMBERSHIP PLANS', 'ENROL MEMBER:', 'MEMBER STATUS:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_21_membership',
      description: 'Manage membership plans, enrolments, and membership status.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['CREATE MEMBERSHIP:', 'MEMBERSHIP PLANS', 'ENROL MEMBER:', 'MEMBER STATUS:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      logger.info(`[MEMBERSHIP] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      // ── MEMBERSHIP PLANS ─────────────────────────────────────────
      if (context.triggerUsed === 'MEMBERSHIP PLANS') {
        const planLines = Object.entries(PLANS).map(([key, plan]) => {
          return (
            `*${plan.name}* — R${plan.price}/month\n` +
            plan.features.map(f => `  • ${f}`).join('\n')
          );
        }).join('\n\n');

        return {
          response:
            `💳 *Dr Piet Membership Plans*\n\n` +
            `━━━━━━━━━━━━━━━━━━\n\n` +
            planLines +
            `\n\n━━━━━━━━━━━━━━━━━━\n` +
            `To enrol a patient: \`ENROL MEMBER: Patient Email | basic/standard/premium\`\n` +
            `To check status: \`MEMBER STATUS: patient@email.com\`\n\n` +
            `💡 Generate payment link: \`PAYMENT LINK: Patient Name | ${PLANS.standard.price} | Standard Care Plan\``
        };
      }

      // ── ENROL MEMBER ─────────────────────────────────────────────
      if (context.triggerUsed === 'ENROL MEMBER:') {
        if (!payload || !payload.includes('|')) {
          return {
            response:
              '💳 *Enrol Member*\n\n' +
              'Usage: `ENROL MEMBER: email@patient.com | basic/standard/premium`\n\n' +
              'View plans first: `MEMBERSHIP PLANS`'
          };
        }

        const parsed = await generateStructuredOutput(context, {
          logLabel: 'membership-enrol',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a membership enrolment request.',
          userPrompt: `User request: ${payload}\n\nReturn JSON with email and planKey.`,
          schema: {
            type: 'object',
            required: ['email', 'planKey'],
            properties: {
              email: { type: 'string' },
              planKey: { type: 'string' }
            }
          }
        });
        const email = parsed.email.trim().toLowerCase();
        const planKey = parsed.planKey.trim().toLowerCase();
        const plan = PLANS[planKey];

        if (!plan) {
          return { response: `⚠️ Unknown plan: "${planKey}". Choose: basic, standard, or premium.` };
        }

        const startDate  = new Date().toISOString();
        const renewalDate = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
        const membershipId = `MEM-${Date.now()}`;

        if (context.db) {
          // Check if patient exists
          const patient = await context.db.get('SELECT * FROM patients WHERE email = ?', [email]);
          if (!patient) {
            return { response: `❌ Patient not found: ${email}\n\nAdd them first: \`ADD PATIENT: Name | ${email} | phone\`` };
          }

          // Store membership in knowledge table
          await context.db.run(
            `INSERT OR REPLACE INTO knowledge (key, value, createdAt) VALUES (?, ?, ?)`,
            [
              `membership:${email}`,
              JSON.stringify({ membershipId, planKey, planName: plan.name, price: plan.price, startDate, renewalDate, status: 'active' }),
              startDate
            ]
          );
        }

        logger.info(`[MEMBERSHIP] Enrolled: ${email} on ${planKey}`);
        return {
          response:
            `✅ *Membership Created*\n\n` +
            `📧 *Patient:* ${email}\n` +
            `💳 *Plan:* ${plan.name}\n` +
            `💰 *Monthly:* R${plan.price}\n` +
            `📅 *Start:* ${startDate.split('T')[0]}\n` +
            `🔄 *Next renewal:* ${renewalDate}\n` +
            `🔑 *ID:* ${membershipId}\n\n` +
            `💡 Generate payment: \`PAYMENT LINK: Patient | ${plan.price} | ${plan.name}\``
        };
      }

      // ── MEMBER STATUS ─────────────────────────────────────────────
      if (context.triggerUsed === 'MEMBER STATUS:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `MEMBER STATUS: patient@email.com`' };
        }

        const email = payload.trim().toLowerCase();

        if (!context.db) {
          return { response: '⚠️ Database not connected.' };
        }

        const record = await context.db.get(
          `SELECT value FROM knowledge WHERE key = ?`,
          [`membership:${email}`]
        );

        if (!record) {
          return {
            response:
              `❌ No membership found for: ${email}\n\n` +
              `View plans: \`MEMBERSHIP PLANS\`\n` +
              `Enrol: \`ENROL MEMBER: ${email} | standard\``
          };
        }

        const m = JSON.parse(record.value);
        const plan = PLANS[m.planKey] || {};

        return {
          response:
            `💳 *Membership Status*\n\n` +
            `📧 *Patient:* ${email}\n` +
            `📋 *Plan:* ${m.planName}\n` +
            `💰 *Monthly:* R${m.price}\n` +
            `📅 *Started:* ${m.startDate.split('T')[0]}\n` +
            `🔄 *Renewal:* ${m.renewalDate}\n` +
            `✅ *Status:* ${m.status.toUpperCase()}\n` +
            `🔑 *ID:* ${m.membershipId}\n\n` +
            `*Included:*\n${(plan.features || []).map(f => `• ${f}`).join('\n')}`
        };
      }

      // ── CREATE MEMBERSHIP (alias) ──────────────────────────────────
      if (context.triggerUsed === 'CREATE MEMBERSHIP:') {
        return {
          response:
            '💳 *Create Membership*\n\n' +
            'Use: `ENROL MEMBER: email | plan`\n\n' +
            'View plans: `MEMBERSHIP PLANS`'
        };
      }

      return { response: '⚠️ Usage: `MEMBERSHIP PLANS`, `ENROL MEMBER:`, `MEMBER STATUS:`' };

    } catch (err) {
      logger.error('[MEMBERSHIP] Error:', err.message);
      return { response: `❌ Membership error: ${err.message}` };
    }
  }
};
