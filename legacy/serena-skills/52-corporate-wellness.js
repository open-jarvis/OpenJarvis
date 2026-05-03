// 52-corporate-wellness.js — Corporate Wellness Programs
// Generates proposals, talk outlines, and B2B lead content.
// CRM capture via context.db (01-crm pattern).

const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

module.exports = {
  id: '52-corporate-wellness',
  name: 'Corporate Wellness Programs',
  description: 'Generate corporate wellness proposals, talk outlines, and B2B packages for Dr Piet.',
  triggers: ['WELLNESS PROGRAM:', 'B2B LEAD:', 'CORPORATE PROPOSAL:', 'WELLNESS TALK:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_52_corporate_wellness',
      description: 'Generate corporate wellness proposals and capture B2B leads.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['WELLNESS PROGRAM:', 'B2B LEAD:', 'CORPORATE PROPOSAL:', 'WELLNESS TALK:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      logger.info(`[WELLNESS] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🏢 *Corporate Wellness Programs*\n\n' +
            'Commands:\n' +
            '• `WELLNESS PROGRAM: Company Name | industry | employees` — full program proposal\n' +
            '• `WELLNESS TALK: topic | duration | audience` — talk outline\n' +
            '• `B2B LEAD: Company | contact | notes` — log corporate lead\n' +
            '• `CORPORATE PROPOSAL: Company Name` — full PDF-ready proposal\n\n' +
            'Examples:\n' +
            '• `WELLNESS PROGRAM: Discovery Health | insurance | 500`\n' +
            '• `WELLNESS TALK: stress management | 60 minutes | HR professionals`\n' +
            '• `B2B LEAD: Absa Bank | Sarah Jones | interested in quarterly screenings`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts    = payload.split('|').map(p => p.trim());

      // ── B2B LEAD CAPTURE ──────────────────────────────────────────
      if (context.triggerUsed === 'B2B LEAD:') {
        const parsed = await generateStructuredOutput(context, {
          logLabel: 'wellness-b2b-lead',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a corporate lead capture request.',
          userPrompt: `User request: ${payload}\n\nReturn JSON with company, contact, notes.`,
          schema: {
            type: 'object',
            required: ['company'],
            properties: {
              company: { type: 'string' },
              contact: { type: 'string' },
              notes: { type: 'string' }
            }
          }
        });
        const company = parsed.company;
        const contact = parsed.contact || '';
        const notes = parsed.notes || '';

        if (context.db) {
          try {
            await context.db.run(
              `INSERT OR REPLACE INTO patients (name, email, phone, conditions, createdAt, lastUpdated)
               VALUES (?, ?, ?, ?, ?, ?)`,
              [
                `[B2B] ${company}`,
                contact.includes('@') ? contact : '',
                contact.includes('@') ? '' : contact,
                JSON.stringify(['corporate-wellness', notes]),
                new Date().toISOString(),
                new Date().toISOString()
              ]
            );
          } catch (dbErr) {
            logger.warn('[WELLNESS] DB save failed: ' + dbErr.message);
          }
        }

        logger.info(`[WELLNESS] B2B lead logged: ${company}`);
        return {
          response:
            `✅ *Corporate Lead Logged*\n\n` +
            `🏢 *Company:* ${company}\n` +
            `👤 *Contact:* ${contact || 'Not provided'}\n` +
            `📝 *Notes:* ${notes || 'None'}\n\n` +
            `💡 Next: \`CORPORATE PROPOSAL: ${company}\` to generate a full proposal`
        };
      }

      // ── WELLNESS TALK OUTLINE ─────────────────────────────────────
      if (context.triggerUsed === 'WELLNESS TALK:') {
        const topic    = parts[0];
        const duration = parts[1] || '60 minutes';
        const audience = parts[2] || 'corporate employees';

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a complete corporate wellness talk outline for Dr Piet Muller.\n\n` +
              `Topic: "${topic}"\n` +
              `Duration: ${duration}\n` +
              `Audience: ${audience}\n\n` +
              `Provide:\n` +
              `🎤 TALK TITLE: (engaging, professional)\n` +
              `🎯 LEARNING OUTCOMES: 3 things attendees will take away\n\n` +
              `TALK STRUCTURE:\n` +
              `[0-5 min] OPENING: Ice-breaker or shocking stat\n` +
              `[5-20 min] SECTION 1: The problem (why this matters to them)\n` +
              `[20-40 min] SECTION 2: The solution (practical, actionable steps)\n` +
              `[40-50 min] SECTION 3: Implementation (how to start Monday)\n` +
              `[50-60 min] Q&A + CLOSE\n\n` +
              `SPEAKER NOTES: Key points and stories for each section\n` +
              `HANDOUT SUMMARY: One-page takeaway for attendees\n` +
              `FOLLOW-UP OFFER: How to engage further with Dr Piet\n\n` +
              `South African corporate context. HPCSA-compliant. Engaging and practical.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[WELLNESS] Talk outline: ${topic.substring(0,50)}`);
        return {
          response:
            `🎤 *Wellness Talk Outline*\n📌 _${topic}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Create slides: \`VIDEO SCRIPT: ${topic} | linkedin | 90s\``
        };
      }

      // ── FULL WELLNESS PROGRAM / CORPORATE PROPOSAL ───────────────
      const company   = parts[0];
      const industry  = parts[1] || 'corporate';
      const employees = parts[2] || '100+';

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Create a full corporate wellness program proposal for Dr Piet Muller to present to:\n\n` +
            `Company: ${company}\n` +
            `Industry: ${industry}\n` +
            `Employees: ${employees}\n\n` +
            `Proposal sections:\n` +
            `1. EXECUTIVE SUMMARY (problem + solution + ROI)\n` +
            `2. DR PIET'S CREDENTIALS & APPROACH\n` +
            `3. WELLNESS PROGRAM OPTIONS:\n` +
            `   - Basic: Monthly wellness talk (pricing)\n` +
            `   - Standard: Quarterly health screenings + talks (pricing)\n` +
            `   - Premium: On-site clinic days + executive health checks (pricing)\n` +
            `4. WHAT'S INCLUDED (deliverables per tier)\n` +
            `5. ROI FOR THE COMPANY (absenteeism, productivity stats)\n` +
            `6. SOUTH AFRICAN COMPLIANCE (OHS Act, POPIA)\n` +
            `7. TIMELINE & IMPLEMENTATION\n` +
            `8. INVESTMENT SUMMARY (placeholder pricing)\n` +
            `9. NEXT STEPS & CTA\n\n` +
            `Tone: Professional, data-driven, B2B. South African corporate context.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.5 }
      );

      logger.info(`[WELLNESS] Proposal generated for: ${company}`);
      return {
        response:
          `🏢 *Corporate Wellness Proposal*\n📌 _${company}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          result.content.substring(0, 3500) +
          (result.content.length > 3500 ? '\n\n_[Proposal continues — save to Drive for full version]_' : '') +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          `💡 Log lead: \`B2B LEAD: ${company} | contact@${company.toLowerCase().replace(/\s/g,'')}.co.za\``
      };

    } catch (err) {
      logger.error('[WELLNESS] Error:', err.message);
      return { response: `❌ Corporate wellness error: ${err.message}` };
    }
  }
};
