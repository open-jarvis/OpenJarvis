const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredRevenueOutput, fetchSiteRevenueSnapshot } = require('../helpers/revenue-engine');

const AUDIT_SCHEMA = {
  type: 'object',
  required: ['summary', 'score', 'missing_money_pages', 'journey_gaps', 'roadmap'],
  properties: {
    summary: { type: 'string' },
    score: { type: 'string' },
    missing_money_pages: { type: 'array', items: { type: 'string' } },
    journey_gaps: { type: 'array', items: { type: 'string' } },
    roadmap: {
      type: 'array',
      items: {
        type: 'object',
        required: ['phase', 'action', 'expected_outcome'],
        properties: {
          phase: { type: 'string' },
          action: { type: 'string' },
          expected_outcome: { type: 'string' }
        }
      }
    }
  }
};

function formatAudit(url, result) {
  const missingPages = result.missing_money_pages.map((item) => `• ${item}`).join('\n');
  const gaps = result.journey_gaps.map((item) => `• ${item}`).join('\n');
  const roadmap = result.roadmap
    .map((item) => `• *${item.phase}* — ${item.action}\nExpected outcome: ${item.expected_outcome}`)
    .join('\n\n');

  return (
    `🧾 *Website Revenue Audit*\n\n` +
    `🌐 *URL:* ${url}\n` +
    `📊 *Revenue Readiness Score:* ${result.score}\n\n` +
    `*Summary*\n${result.summary}\n\n` +
    `*Missing Money Pages*\n${missingPages}\n\n` +
    `*Journey Gaps*\n${gaps}\n\n` +
    `*Roadmap*\n${roadmap}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '73-website-revenue-audit',
  name: 'Website Revenue Audit',
  description: 'Audits a site for monetization readiness, missing pages, and revenue journey gaps.',
  triggers: ['WEBSITE REVENUE AUDIT', 'REVENUE AUDIT:', 'SITE MONETIZATION:', 'MONETIZATION AUDIT:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_73_website_revenue_audit',
      description: 'Audit a website or page for monetization readiness and revenue opportunities.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['WEBSITE REVENUE AUDIT', 'REVENUE AUDIT:', 'SITE MONETIZATION:', 'MONETIZATION AUDIT:']
          },
          payload: {
            type: 'string',
            description: 'A site URL or short description. Defaults to the main practice website if omitted.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const url = String(payload || '').trim() || process.env.WORDPRESS_URL || 'https://drpiet.co.za';
      const snapshot = await fetchSiteRevenueSnapshot(url);

      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'website-revenue-audit',
        reasoningEffort: 'high',
        schema: AUDIT_SCHEMA,
        userPrompt:
          `URL: ${url}\n\n` +
          `Snapshot:\n${JSON.stringify(snapshot, null, 2)}\n\n` +
          'Audit this website for monetization readiness, trust, lead capture, memberships, digital products, affiliate opportunities, and revenue page gaps.'
      });

      const sync = await syncContentArtifact(context, {
        skillId: '73-website-revenue-audit',
        title: url || 'website-revenue-audit',
        type: 'website-revenue-audit',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[WEBSITE REVENUE AUDIT] Audit complete');
      return { response: formatAudit(url, result) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[WEBSITE REVENUE AUDIT] Error: ' + error.message);
      return { response: `❌ Website revenue audit failed: ${error.message}` };
    }
  }
};
