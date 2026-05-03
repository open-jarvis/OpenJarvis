// 25-compliance.js — HPCSA & POPIA Compliance Analyser
// Uses AI to check content against South African medical advertising rules,
// HPCSA guidelines, POPIA data rules, and Meta advertising policies.

const logger = require('../helpers/logger');

const HPCSA_RULES = `
HPCSA ADVERTISING RULES (South Africa):
- No testimonials or endorsements from patients
- No before/after treatment photos
- No guaranteed outcomes or cure claims
- No comparative claims against other practitioners
- No pricing that creates a false impression of value
- Educational content is allowed if clearly educational
- Must include "Consult a healthcare professional" disclaimer
- Cannot claim to treat specific diseases in advertising
- Academic credentials must be accurate and verifiable
- No misleading health claims (e.g. "cure", "miracle", "guaranteed")

POPIA COMPLIANCE RULES:
- Patient data must not be shared without explicit consent
- No identifiable patient information in public content
- Data collection must have a stated purpose
- Patients have the right to access and delete their data
- Cannot retain data longer than necessary
- Must have a privacy policy

META/SOCIAL MEDIA HEALTH ADVERTISING:
- Health conditions cannot be targeted in ads
- Before/after images restricted
- Must not imply personal health outcomes
- Supplements/medical devices need disclaimers
`;

module.exports = {
  id: '25-compliance',
  name: 'HPCSA & POPIA Compliance Analyser',
  description: 'Check content for HPCSA, POPIA, and social media compliance before publishing.',
  triggers: ['COMPLIANCE CHECK:', 'HPCSA CHECK:', 'ANALYSE CONTENT:', 'FULL COMPLIANCE:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[COMPLIANCE] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '⚖️ *Compliance Analyser*\n\n' +
            'Paste content to check against:\n' +
            '• HPCSA advertising guidelines\n' +
            '• POPIA patient data rules\n' +
            '• Meta/social media health policies\n\n' +
            'Usage: `COMPLIANCE CHECK: [paste your content here]`\n\n' +
            'Example: `COMPLIANCE CHECK: Dr Piet cured my diabetes in 3 weeks! Book now for guaranteed results.`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const content = payload.trim().slice(0, 4000);

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `You are a South African healthcare compliance expert. Analyse this content against the rules below.\n\n` +
            `RULES:\n${HPCSA_RULES}\n\n` +
            `CONTENT TO ANALYSE:\n"${content}"\n\n` +
            `Provide:\n` +
            `OVERALL VERDICT: ✅ COMPLIANT / ⚠️ NEEDS CHANGES / ❌ NON-COMPLIANT\n\n` +
            `ISSUES FOUND: (list each violation with rule reference)\n\n` +
            `RISK LEVEL: LOW / MEDIUM / HIGH / CRITICAL\n\n` +
            `CORRECTED VERSION: Rewrite the content to be fully compliant while keeping the intent.\n\n` +
            `MISSING DISCLAIMERS: Any disclaimers that must be added.\n\n` +
            `Be specific, practical, and reference exact rules. If content is already compliant, say so clearly.`
        }],
        {
          systemPrompt: 'You are a South African healthcare regulatory compliance expert specialising in HPCSA guidelines, POPIA, and digital health advertising rules. Be thorough and precise.',
          temperature: 0.2
        }
      );

      logger.info('[COMPLIANCE] Analysis complete');
      return {
        response:
          '⚖️ *Compliance Analysis Report*\n\n' +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '_This analysis is AI-assisted. For formal legal compliance, consult an HPCSA-registered practitioner or healthcare attorney._'
      };

    } catch (err) {
      logger.error('[COMPLIANCE] Error:', err.message);
      return { response: `❌ Compliance check error: ${err.message}` };
    }
  }
};
