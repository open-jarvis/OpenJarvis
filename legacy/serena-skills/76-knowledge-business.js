const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredBusinessOutput } = require('../helpers/business-builder');

const KNOWLEDGE_SCHEMA = {
  type: 'object',
  required: ['business_model', 'audience', 'core_offer', 'content_ladder', 'monetization_path', 'launch_plan'],
  properties: {
    business_model: { type: 'string' },
    audience: { type: 'string' },
    core_offer: { type: 'string' },
    content_ladder: { type: 'array', items: { type: 'string' } },
    monetization_path: { type: 'array', items: { type: 'string' } },
    launch_plan: { type: 'array', items: { type: 'string' } }
  }
};

function formatKnowledgeBusiness(result) {
  const ladder = result.content_ladder.map((item) => `• ${item}`).join('\n');
  const monetization = result.monetization_path.map((item) => `• ${item}`).join('\n');
  const launch = result.launch_plan.map((item) => `• ${item}`).join('\n');

  return (
    `📚 *Knowledge Business Engine*\n\n` +
    `*Business Model*\n${result.business_model}\n\n` +
    `*Audience*\n${result.audience}\n\n` +
    `*Core Offer*\n${result.core_offer}\n\n` +
    `*Content Ladder*\n${ladder}\n\n` +
    `*Monetization Path*\n${monetization}\n\n` +
    `*Launch Plan*\n${launch}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '76-knowledge-business',
  name: 'Knowledge Business Engine',
  description: 'Builds courses, newsletters, memberships, and knowledge-product business models.',
  triggers: ['KNOWLEDGE BUSINESS:', 'COURSE PLAN:', 'NEWSLETTER BUSINESS:', 'MEMBERSHIP MODEL:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_76_knowledge_business',
      description: 'Create a knowledge-product or membership business model with a monetization and launch plan.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['KNOWLEDGE BUSINESS:', 'COURSE PLAN:', 'NEWSLETTER BUSINESS:', 'MEMBERSHIP MODEL:']
          },
          payload: {
            type: 'string',
            description: 'Topic, audience, or knowledge-business idea to package.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Create a scalable knowledge business Serena can help run and market.';

      const result = await buildStructuredBusinessOutput(context, {
        taskLabel: 'knowledge-business',
        schema: KNOWLEDGE_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design a knowledge business model with a clear content ladder, monetization path, and launch plan.'
      });

      const sync = await syncContentArtifact(context, {
        skillId: '76-knowledge-business',
        title: result.business_model || 'knowledge-business',
        type: 'knowledge-business',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[KNOWLEDGE BUSINESS] Plan generated');
      return { response: formatKnowledgeBusiness(result) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[KNOWLEDGE BUSINESS] Error: ' + error.message);
      return { response: `❌ Knowledge business engine failed: ${error.message}` };
    }
  }
};
