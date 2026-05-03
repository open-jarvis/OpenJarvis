const logger = require('../helpers/logger');
const { buildStructuredRevenueOutput } = require('../helpers/revenue-engine');

const AFFILIATE_PRODUCT_SCHEMA = {
  type: 'object',
  required: ['catalog_summary', 'products', 'page_intro'],
  properties: {
    catalog_summary: { type: 'string' },
    products: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'audience', 'benefit', 'disclosure'],
        properties: {
          name: { type: 'string' },
          audience: { type: 'string' },
          benefit: { type: 'string' },
          disclosure: { type: 'string' }
        }
      }
    },
    page_intro: { type: 'string' }
  }
};

module.exports = {
  id: '53-affiliate',
  name: 'Affiliate Product Manager',
  description: 'Generate affiliate product shortlists, compliant copy, and product link guidance.',
  triggers: ['AFFILIATE PRODUCTS', 'PRODUCT LINKS:'],

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'trusted wellness and health-support products for the practice audience';
      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'affiliate-product-manager',
        schema: AFFILIATE_PRODUCT_SCHEMA,
        reasoningEffort: 'high',
        userPrompt:
          `Request: ${request}\n\n` +
          'Build a compliant affiliate catalog shortlist with product copy and disclosure guidance.'
      });

      const products = result.products
        .map((item) => `• *${item.name}* — ${item.audience}\nBenefit: ${item.benefit}\nDisclosure: ${item.disclosure}`)
        .join('\n\n');

      return {
        response:
          `🤝 *Affiliate Product Manager*\n\n` +
          `${result.catalog_summary}\n\n` +
          `${products}\n\n` +
          `*Page Intro*\n${result.page_intro}`
      };
    } catch (error) {
      logger.error('[AFFILIATE] Error: ' + error.message);
      return { response: `❌ Affiliate product manager error: ${error.message}` };
    }
  }
};
