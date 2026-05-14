const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredBusinessOutput } = require('../helpers/business-builder');

const AGENCY_SCHEMA = {
  type: 'object',
  required: ['agency_offer', 'market_position', 'core_services', 'packages', 'delivery_system', 'proposal_outline'],
  properties: {
    agency_offer: { type: 'string' },
    market_position: { type: 'string' },
    core_services: { type: 'array', items: { type: 'string' } },
    packages: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'price', 'best_for'],
        properties: {
          name: { type: 'string' },
          price: { type: 'string' },
          best_for: { type: 'string' }
        }
      }
    },
    delivery_system: { type: 'array', items: { type: 'string' } },
    proposal_outline: { type: 'array', items: { type: 'string' } }
  }
};

function formatAgencyOffer(result) {
  const services = result.core_services.map((item) => `• ${item}`).join('\n');
  const packages = result.packages.map((item) => `• *${item.name}* — ${item.price}\nBest for: ${item.best_for}`).join('\n\n');
  const delivery = result.delivery_system.map((item) => `• ${item}`).join('\n');
  const outline = result.proposal_outline.map((item) => `• ${item}`).join('\n');

  return (
    `🏢 *Agency Offers Engine*\n\n` +
    `*Offer*\n${result.agency_offer}\n\n` +
    `*Market Position*\n${result.market_position}\n\n` +
    `*Core Services*\n${services}\n\n` +
    `*Packages*\n${packages}\n\n` +
    `*Delivery System*\n${delivery}\n\n` +
    `*Proposal Outline*\n${outline}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '75-agency-offers',
  name: 'Agency Offers Engine',
  description: 'Builds agency-style service packages, delivery systems, and proposal structures.',
  triggers: ['AGENCY OFFER:', 'AGENCY PACKAGE:', 'CONSULTING OFFER:', 'SERVICE PROPOSAL:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_75_agency_offers',
      description: 'Package an agency or consulting offer with services, pricing, and a proposal structure.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['AGENCY OFFER:', 'AGENCY PACKAGE:', 'CONSULTING OFFER:', 'SERVICE PROPOSAL:']
          },
          payload: {
            type: 'string',
            description: 'Agency niche, target market, or consulting offer idea.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Create a high-value AI-enabled agency offer Serena can help deliver.';

      const result = await buildStructuredBusinessOutput(context, {
        taskLabel: 'agency-offers',
        schema: AGENCY_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design an agency or consulting offer with clear packages, delivery workflow, and proposal structure.'
      });

      const sync = await syncContentArtifact(context, {
        skillId: '75-agency-offers',
        title: result.agency_offer || 'agency-offer',
        type: 'agency-offer',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[AGENCY OFFERS] Offer generated');
      return { response: formatAgencyOffer(result) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[AGENCY OFFERS] Error: ' + error.message);
      return { response: `❌ Agency offers engine failed: ${error.message}` };
    }
  }
};
