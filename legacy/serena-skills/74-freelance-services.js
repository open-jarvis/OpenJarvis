const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredBusinessOutput } = require('../helpers/business-builder');

const SERVICE_SCHEMA = {
  type: 'object',
  required: ['service_name', 'positioning', 'ideal_client', 'deliverables', 'pricing', 'sales_assets', 'next_steps'],
  properties: {
    service_name: { type: 'string' },
    positioning: { type: 'string' },
    ideal_client: { type: 'string' },
    deliverables: { type: 'array', items: { type: 'string' } },
    pricing: {
      type: 'array',
      items: {
        type: 'object',
        required: ['tier', 'price', 'includes'],
        properties: {
          tier: { type: 'string' },
          price: { type: 'string' },
          includes: { type: 'string' }
        }
      }
    },
    sales_assets: { type: 'array', items: { type: 'string' } },
    next_steps: { type: 'array', items: { type: 'string' } }
  }
};

function formatServicePack(result) {
  const deliverables = result.deliverables.map((item) => `• ${item}`).join('\n');
  const pricing = result.pricing.map((item) => `• *${item.tier}* — ${item.price}\nIncludes: ${item.includes}`).join('\n\n');
  const assets = result.sales_assets.map((item) => `• ${item}`).join('\n');
  const nextSteps = result.next_steps.map((item) => `• ${item}`).join('\n');

  return (
    `🧰 *Freelance Services Engine*\n\n` +
    `*Offer*\n${result.service_name}\n\n` +
    `*Positioning*\n${result.positioning}\n\n` +
    `*Ideal Client*\n${result.ideal_client}\n\n` +
    `*Deliverables*\n${deliverables}\n\n` +
    `*Pricing Tiers*\n${pricing}\n\n` +
    `*Sales Assets Needed*\n${assets}\n\n` +
    `*Next Steps*\n${nextSteps}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '74-freelance-services',
  name: 'Freelance Services Engine',
  description: 'Packages freelance and professional services into sellable offers, pricing, and sales assets.',
  triggers: ['FREELANCE SERVICE:', 'SERVICE PACKAGE:', 'REMOTE OFFER:', 'CLIENT SERVICE:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_74_freelance_services',
      description: 'Create a freelance or client service offer with positioning, pricing, and sales assets.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['FREELANCE SERVICE:', 'SERVICE PACKAGE:', 'REMOTE OFFER:', 'CLIENT SERVICE:']
          },
          payload: {
            type: 'string',
            description: 'Service type, audience, market, or delivery model to package.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Package a high-value remote service offer that Serena can help deliver.';

      const result = await buildStructuredBusinessOutput(context, {
        taskLabel: 'freelance-services',
        schema: SERVICE_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design a premium service offer with scope, pricing, and supporting sales assets.'
      });

      const sync = await syncContentArtifact(context, {
        skillId: '74-freelance-services',
        title: result.service_name || 'freelance-offer',
        type: 'freelance-offer',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[FREELANCE SERVICES] Offer generated');
      return { response: formatServicePack(result) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[FREELANCE SERVICES] Error: ' + error.message);
      return { response: `❌ Freelance services engine failed: ${error.message}` };
    }
  }
};
