const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredRevenueOutput } = require('../helpers/revenue-engine');
const { createWordPressContent, isWordPressConfigured } = require('../helpers/wordpress-service');

const PRODUCT_SCHEMA = {
  type: 'object',
  required: ['product_name', 'format', 'ideal_customer', 'promise', 'price', 'contents', 'funnel', 'page_copy'],
  properties: {
    product_name: { type: 'string' },
    format: { type: 'string' },
    ideal_customer: { type: 'string' },
    promise: { type: 'string' },
    price: { type: 'string' },
    contents: { type: 'array', items: { type: 'string' } },
    funnel: { type: 'array', items: { type: 'string' } },
    page_copy: { type: 'string' }
  }
};

function shouldPublish(payload) {
  return /\|\s*publish\s*$/i.test(String(payload || ''));
}

function cleanPayload(payload) {
  return String(payload || '').replace(/\|\s*publish\s*$/i, '').trim();
}

function formatProductPlan(result, publishedPage) {
  const contents = result.contents.map((item) => `• ${item}`).join('\n');
  const funnel = result.funnel.map((item) => `• ${item}`).join('\n');

  return (
    `📦 *Digital Product Engine*\n\n` +
    `*Product*\n${result.product_name}\n\n` +
    `*Format*\n${result.format}\n\n` +
    `*Ideal Customer*\n${result.ideal_customer}\n\n` +
    `*Core Promise*\n${result.promise}\n\n` +
    `*Suggested Price*\n${result.price}\n\n` +
    `*What Goes Inside*\n${contents}\n\n` +
    `*Launch Funnel*\n${funnel}` +
    (publishedPage ? `\n\n🌐 *WordPress Draft:* ${publishedPage.link}` : '')
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '71-digital-products',
  name: 'Digital Products Engine',
  description: 'Designs paid health products, launch funnels, and optional WordPress product landing pages.',
  triggers: ['DIGITAL PRODUCT:', 'PRODUCT LAUNCH:', 'PRODUCT CATALOG', 'PRODUCT PAGE:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_71_digital_products',
      description: 'Create digital product concepts, launch plans, and product pages for drpiet.co.za.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['DIGITAL PRODUCT:', 'PRODUCT LAUNCH:', 'PRODUCT CATALOG', 'PRODUCT PAGE:']
          },
          payload: {
            type: 'string',
            description: 'Product idea, audience, or monetization angle. Add "| publish" to create a WordPress page draft.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request =
        cleanPayload(payload) ||
        'Create the next best paid digital health product for Dr Piet Muller that can be sold from drpiet.co.za.';

      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'digital-products',
        reasoningEffort: 'high',
        schema: PRODUCT_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design a digital product that is useful, trustworthy, and commercially strong for this practice.'
      });

      let publishedPage = null;
      if ((context.triggerUsed === 'PRODUCT PAGE:' || shouldPublish(payload)) && isWordPressConfigured()) {
        publishedPage = await createWordPressContent('pages', {
          title: result.product_name,
          content: result.page_copy,
          status: process.env.WORDPRESS_DEFAULT_PAGE_STATUS || 'draft',
          slug: result.product_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
        });
      }

      const sync = await syncContentArtifact(context, {
        skillId: '71-digital-products',
        title: result.product_name || 'digital-product',
        type: 'digital-product',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[DIGITAL PRODUCTS] Product plan generated');
      return { response: formatProductPlan(result, publishedPage) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[DIGITAL PRODUCTS] Error: ' + error.message);
      return { response: `❌ Digital product build failed: ${error.message}` };
    }
  }
};
