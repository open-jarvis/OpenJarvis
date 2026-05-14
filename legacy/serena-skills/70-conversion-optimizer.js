const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredRevenueOutput, fetchSiteRevenueSnapshot } = require('../helpers/revenue-engine');

const CRO_SCHEMA = {
  type: 'object',
  required: ['summary', 'score', 'leaks', 'cta_rewrites', 'recommended_test'],
  properties: {
    summary: { type: 'string' },
    score: { type: 'string' },
    leaks: {
      type: 'array',
      items: {
        type: 'object',
        required: ['issue', 'impact', 'fix'],
        properties: {
          issue: { type: 'string' },
          impact: { type: 'string' },
          fix: { type: 'string' }
        }
      }
    },
    cta_rewrites: { type: 'array', items: { type: 'string' } },
    recommended_test: { type: 'string' }
  }
};

function formatCroAudit(result, url) {
  const leaks = result.leaks
    .map((item, index) => `${index + 1}. *${item.issue}* — ${item.impact}\nFix: ${item.fix}`)
    .join('\n\n');
  const rewrites = result.cta_rewrites.map((item) => `• ${item}`).join('\n');

  return (
    `🎯 *Conversion Optimizer*\n\n` +
    `${url ? `🌐 *Page:* ${url}\n` : ''}` +
    `📊 *Conversion Score:* ${result.score}\n\n` +
    `*Summary*\n${result.summary}\n\n` +
    `*Leak Points*\n${leaks}\n\n` +
    `*CTA Rewrites*\n${rewrites}\n\n` +
    `*Recommended Test*\n${result.recommended_test}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '70-conversion-optimizer',
  name: 'Conversion Optimizer',
  description: 'Audits conversion leaks, improves CTAs, and produces funnel fixes for high-intent pages.',
  triggers: ['CRO AUDIT:', 'CONVERSION FIX:', 'CTA PLAN:', 'FUNNEL FIX:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_70_conversion_optimizer',
      description: 'Audit a page or offer for conversion leaks and recommend CRO fixes and CTAs.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['CRO AUDIT:', 'CONVERSION FIX:', 'CTA PLAN:', 'FUNNEL FIX:']
          },
          payload: {
            type: 'string',
            description: 'URL or description of the page, offer, funnel, or CTA problem.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim();
      if (!request) {
        return {
          response:
            '⚠️ Usage examples:\n' +
            '`CRO AUDIT: https://drpiet.co.za`\n' +
            '`CONVERSION FIX: homepage hero section for metabolic consultations`\n' +
            '`CTA PLAN: membership page`\n' +
            '`FUNNEL FIX: lead magnet thank-you page and booking handoff`'
        };
      }

      const looksLikeUrl = /^https?:\/\//i.test(request);
      let siteSnapshot = null;

      if (looksLikeUrl) {
        siteSnapshot = await fetchSiteRevenueSnapshot(request);
      }

      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'conversion-optimizer',
        reasoningEffort: 'high',
        schema: CRO_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          `${siteSnapshot ? `Page snapshot:\n${JSON.stringify(siteSnapshot, null, 2)}\n\n` : ''}` +
          'Find the highest-impact conversion leaks, rewrite the best CTAs, and recommend the single best test to run next.'
      });

      const sync = await syncContentArtifact(context, {
        skillId: '70-conversion-optimizer',
        title: request || 'cro-audit',
        type: 'cro-audit',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[CRO] Conversion analysis generated');
      return { response: formatCroAudit(result, looksLikeUrl ? request : '') + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[CRO] Error: ' + error.message);
      return { response: `❌ Conversion optimizer failed: ${error.message}` };
    }
  }
};
