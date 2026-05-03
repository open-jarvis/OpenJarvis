const logger = require('../helpers/logger');
const { buildStructuredBusinessOutput } = require('../helpers/business-builder');

const ECOMMERCE_SCHEMA = {
  type: 'object',
  required: ['store_model', 'customer', 'offer_stack', 'catalog_plan', 'ops_stack', 'launch_checklist'],
  properties: {
    store_model: { type: 'string' },
    customer: { type: 'string' },
    offer_stack: { type: 'array', items: { type: 'string' } },
    catalog_plan: { type: 'array', items: { type: 'string' } },
    ops_stack: { type: 'array', items: { type: 'string' } },
    launch_checklist: { type: 'array', items: { type: 'string' } }
  }
};

function formatEcommerceOps(result) {
  const offerStack = result.offer_stack.map((item) => `• ${item}`).join('\n');
  const catalog = result.catalog_plan.map((item) => `• ${item}`).join('\n');
  const ops = result.ops_stack.map((item) => `• ${item}`).join('\n');
  const checklist = result.launch_checklist.map((item) => `• ${item}`).join('\n');

  return (
    `🛒 *E-commerce Operations Engine*\n\n` +
    `*Store Model*\n${result.store_model}\n\n` +
    `*Customer*\n${result.customer}\n\n` +
    `*Offer Stack*\n${offerStack}\n\n` +
    `*Catalog Plan*\n${catalog}\n\n` +
    `*Operations Stack*\n${ops}\n\n` +
    `*Launch Checklist*\n${checklist}`
  );
}

module.exports = {
  id: '77-ecommerce-operations',
  name: 'E-commerce Operations Engine',
  description: 'Designs ecommerce business models, catalogs, launch stacks, and operating checklists.',
  triggers: ['ECOMMERCE OPS:', 'STORE PLAN:', 'PRODUCT OPS:', 'SHOP STRATEGY:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_77_ecommerce_operations',
      description: 'Create an ecommerce operating plan with offer stack, catalog, and launch checklist.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['ECOMMERCE OPS:', 'STORE PLAN:', 'PRODUCT OPS:', 'SHOP STRATEGY:']
          },
          payload: {
            type: 'string',
            description: 'Store concept, niche, product idea, or ecommerce operating challenge.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Create the best ecommerce operating plan Serena can help execute.';

      const result = await buildStructuredBusinessOutput(context, {
        taskLabel: 'ecommerce-operations',
        schema: ECOMMERCE_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design an ecommerce operation with a clear offer stack, catalog, ops stack, and launch checklist.'
      });

      logger.info('[ECOMMERCE OPS] Plan generated');
      return { response: formatEcommerceOps(result) };
    } catch (error) {
      logger.error('[ECOMMERCE OPS] Error: ' + error.message);
      return { response: `❌ E-commerce operations engine failed: ${error.message}` };
    }
  }
};
