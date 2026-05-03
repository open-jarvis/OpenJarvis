// 24-compliance-guard.js — Real-time Compliance Guard
// Lightweight HPCSA pre-check for quick content review before posting.
// For deep analysis use 25-compliance.js (FULL COMPLIANCE:).

const logger = require('../helpers/logger');

// Quick-scan patterns — flags obvious violations instantly without AI
const RED_FLAGS = [
  { pattern: /\bcure[ds]?\b/gi,           rule: 'No cure claims (HPCSA 4.1.2)' },
  { pattern: /\bguarantee[ds]?\b/gi,      rule: 'No guaranteed outcomes (HPCSA 4.1.3)' },
  { pattern: /\bmiracle\b/gi,             rule: 'No miracle claims (HPCSA 4.1.2)' },
  { pattern: /\b100%\s*effective\b/gi,    rule: 'No absolute efficacy claims (HPCSA 4.1.2)' },
  { pattern: /\btestimoni/gi,             rule: 'Patient testimonials restricted (HPCSA 4.2.1)' },
  { pattern: /\bbefore\s*[&and]*\s*after\b/gi, rule: 'Before/after images restricted (HPCSA 4.2.2)' },
  { pattern: /\bno\s*side\s*effects?\b/gi, rule: 'Cannot claim no side effects (HPCSA 4.1.4)' },
  { pattern: /\bnatural\s+cure\b/gi,      rule: 'No "natural cure" claims (HPCSA 4.1.2)' },
  { pattern: /\bbest\s+doctor\b/gi,       rule: 'No superlative comparative claims (HPCSA 4.3.1)' },
  { pattern: /\bonly\s+doctor\b/gi,       rule: 'No exclusivity claims (HPCSA 4.3.1)' }
];

module.exports = {
  id: '24-compliance-guard',
  name: 'Quick Compliance Guard',
  description: 'Fast HPCSA pre-check for content before posting. Use FULL COMPLIANCE: for deep analysis.',
  triggers: ['QUICK CHECK:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[COMPLIANCE-GUARD] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '⚖️ *Compliance Guard*\n\n' +
            'Quick pre-check for HPCSA advertising rules.\n\n' +
            'Usage: `QUICK CHECK: [your content]`\n\n' +
            'Example: `QUICK CHECK: Book now for guaranteed results and a cure to your diabetes!`\n\n' +
            'For deep analysis with corrections: `FULL COMPLIANCE: [content]`\n' +
            'For POPIA + Meta policy: `ANALYSE CONTENT: [content]`'
        };
      }

      const content = payload.trim();

      // Quick pattern scan
      const violations = [];
      for (const flag of RED_FLAGS) {
        if (flag.pattern.test(content)) {
          violations.push(`❌ ${flag.rule}`);
        }
      }

      // Check for missing disclaimer on health claims
      const hasHealthClaim   = /health|medical|treat|diagnos|symptom|condition|disease/i.test(content);
      const hasDisclaimer    = /consult|disclaimer|professional|doctor|physician/i.test(content);
      const missingDisclaimer = hasHealthClaim && !hasDisclaimer;

      if (missingDisclaimer) {
        violations.push('⚠️ Health content should include: "Consult a healthcare professional"');
      }

      if (violations.length === 0) {
        // Quick pass — still do a light AI check
        if (context.aiEngine) {
          const quickCheck = await context.aiEngine.chat(
            [{
              role: 'user',
              content:
                `Quick HPCSA compliance check. Is this South African medical advertising content compliant?\n\n` +
                `"${content.substring(0, 500)}"\n\n` +
                `Reply in exactly this format:\n` +
                `VERDICT: COMPLIANT or NEEDS REVIEW\n` +
                `REASON: One sentence\n` +
                `SUGGESTION: One improvement (if any)`
            }],
            { systemPrompt: 'HPCSA compliance expert. Be concise.', temperature: 0.1 }
          );

          logger.info('[COMPLIANCE-GUARD] Quick AI check done');
          return {
            response:
              `⚖️ *Quick Compliance Check*\n\n` +
              `✅ No obvious red flags detected.\n\n` +
              `🤖 *AI Check:*\n${quickCheck.content}\n\n` +
              `_For full analysis with corrections: \`FULL COMPLIANCE: [content]\`_`
          };
        }

        return {
          response:
            `⚖️ *Quick Compliance Check*\n\n` +
            `✅ *No obvious HPCSA violations detected.*\n\n` +
            `_Pattern check passed. For deep AI analysis: \`FULL COMPLIANCE: [content]\`_`
        };
      }

      logger.info(`[COMPLIANCE-GUARD] ${violations.length} violation(s) found`);
      return {
        response:
          `⚖️ *Compliance Check — Issues Found*\n\n` +
          `🔴 *${violations.length} violation(s) detected:*\n\n` +
          violations.join('\n') +
          `\n\n━━━━━━━━━━━━━━━━━━\n` +
          `📝 *Your content:*\n_"${content.substring(0, 200)}${content.length > 200 ? '...' : ''}"_\n\n` +
          `🔧 For corrected version: \`FULL COMPLIANCE: ${content.substring(0, 100)}\``
      };

    } catch (err) {
      logger.error('[COMPLIANCE-GUARD] Error:', err.message);
      return { response: `❌ Compliance check error: ${err.message}` };
    }
  }
};
