const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredRevenueOutput } = require('../helpers/revenue-engine');
const { createWordPressContent, isWordPressConfigured } = require('../helpers/wordpress-service');

const AFFILIATE_SCHEMA = {
  type: 'object',
  required: ['strategy', 'partner_criteria', 'offers', 'guardrails', 'next_steps', 'page_copy'],
  properties: {
    strategy: { type: 'string' },
    partner_criteria: { type: 'array', items: { type: 'string' } },
    offers: {
      type: 'array',
      items: {
        type: 'object',
        required: ['offer_name', 'audience', 'why_it_fits', 'disclosure'],
        properties: {
          offer_name: { type: 'string' },
          audience: { type: 'string' },
          why_it_fits: { type: 'string' },
          disclosure: { type: 'string' }
        }
      }
    },
    guardrails: { type: 'array', items: { type: 'string' } },
    next_steps: { type: 'array', items: { type: 'string' } },
    page_copy: { type: 'string' }
  }
};

function wantsPublish(payload) {
  return /\|\s*publish\s*$/i.test(String(payload || ''));
}

function stripPublish(payload) {
  return String(payload || '').replace(/\|\s*publish\s*$/i, '').trim();
}

function formatAffiliatePlan(result, publishedPage) {
  const criteria = result.partner_criteria.map((item) => `• ${item}`).join('\n');
  const offers = result.offers
    .map((item) => `• *${item.offer_name}* — ${item.audience}\nWhy it fits: ${item.why_it_fits}\nDisclosure: ${item.disclosure}`)
    .join('\n\n');
  const guardrails = result.guardrails.map((item) => `• ${item}`).join('\n');
  const nextSteps = result.next_steps.map((item) => `• ${item}`).join('\n');

  return (
    `🤝 *Affiliate Engine*\n\n` +
    `*Strategy*\n${result.strategy}\n\n` +
    `*Partner Criteria*\n${criteria}\n\n` +
    `*Recommended Offers*\n${offers}\n\n` +
    `*Compliance Guardrails*\n${guardrails}\n\n` +
    `*Next Steps*\n${nextSteps}` +
    (publishedPage ? `\n\n🌐 *WordPress Draft:* ${publishedPage.link}` : '')
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '72-affiliate-engine',
  name: 'Affiliate Engine',
  description: 'Builds compliant affiliate and partner revenue plans, pages, and offer shortlists.',
  triggers: ['AFFILIATE ENGINE:', 'PARTNER OFFERS:', 'AFFILIATE PLAN:', 'AFFILIATE PAGE:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_72_affiliate_engine',
      description: 'Design a compliant affiliate partner plan and optional WordPress page for the practice.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['AFFILIATE ENGINE:', 'PARTNER OFFERS:', 'AFFILIATE PLAN:', 'AFFILIATE PAGE:']
          },
          payload: {
            type: 'string',
            description: 'Affiliate category, audience, or partner strategy. Add "| publish" to create a WordPress page draft.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request =
        stripPublish(payload) ||
        'Create the best compliant affiliate revenue plan for drpiet.co.za with trusted wellness and health-support offers.';

      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'affiliate-engine',
        reasoningEffort: 'high',
        schema: AFFILIATE_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Recommend affiliate or partner offers that fit a health and wellness practice without harming trust or compliance.'
      });

      let publishedPage = null;
      if ((context.triggerUsed === 'AFFILIATE PAGE:' || wantsPublish(payload)) && isWordPressConfigured()) {
        publishedPage = await createWordPressContent('pages', {
          title: process.env.WORDPRESS_AFFILIATE_PAGE_TITLE || 'Recommended Resources',
          content: result.page_copy,
          status: process.env.WORDPRESS_DEFAULT_PAGE_STATUS || 'draft',
          slug: process.env.WORDPRESS_AFFILIATE_PAGE_SLUG || 'recommended-resources'
        });
      }

      const sync = await syncContentArtifact(context, {
        skillId: '72-affiliate-engine',
        title: (result.offers && result.offers[0] && result.offers[0].offer_name) || 'affiliate-plan',
        type: 'affiliate-plan',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[AFFILIATE ENGINE] Affiliate plan generated');
      return { response: formatAffiliatePlan(result, publishedPage) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[AFFILIATE ENGINE] Error: ' + error.message);
      return { response: `❌ Affiliate engine failed: ${error.message}` };
    }
  }
};
