const path = require('path');
const logger = require('../helpers/logger');
const {
  buildStructuredStudioOutput,
  saveStudioArtifact,
  wantsArtifactWrite,
  stripWriteFlag
} = require('../helpers/software-studio');
const { syncBuildArtifact } = require('../helpers/github-build-sync');

const FULLSTACK_SCHEMA = {
  type: 'object',
  required: [
    'product_summary',
    'target_users',
    'recommended_stack',
    'architecture',
    'modules',
    'frontend_routes',
    'api_endpoints',
    'data_model',
    'delivery_plan',
    'quality_risks'
  ],
  properties: {
    product_summary: { type: 'string' },
    target_users: { type: 'string' },
    recommended_stack: { type: 'array', items: { type: 'string' } },
    architecture: { type: 'array', items: { type: 'string' } },
    modules: { type: 'array', items: { type: 'string' } },
    frontend_routes: { type: 'array', items: { type: 'string' } },
    api_endpoints: { type: 'array', items: { type: 'string' } },
    data_model: { type: 'array', items: { type: 'string' } },
    delivery_plan: { type: 'array', items: { type: 'string' } },
    quality_risks: { type: 'array', items: { type: 'string' } }
  }
};

function formatSection(title, items) {
  return `*${title}*\n${items.map((item) => `• ${item}`).join('\n')}`;
}

function formatBuildPlan(result, artifactPath = '') {
  return (
    `Fullstack Builder\n\n` +
    `*Product Summary*\n${result.product_summary}\n\n` +
    `*Target Users*\n${result.target_users}\n\n` +
    `${formatSection('Recommended Stack', result.recommended_stack)}\n\n` +
    `${formatSection('Architecture', result.architecture)}\n\n` +
    `${formatSection('Core Modules', result.modules)}\n\n` +
    `${formatSection('Frontend Routes', result.frontend_routes)}\n\n` +
    `${formatSection('API Endpoints', result.api_endpoints)}\n\n` +
    `${formatSection('Data Model', result.data_model)}\n\n` +
    `${formatSection('Delivery Plan', result.delivery_plan)}\n\n` +
    `${formatSection('Quality Risks', result.quality_risks)}` +
    (artifactPath ? `\n\nArtifact Pack: \`${artifactPath}\`` : '')
  );
}

module.exports = {
  id: '78-fullstack-builder',
  name: 'Fullstack Builder',
  description: 'Designs production-ready website and app architecture, route maps, API plans, and build packs.',
  triggers: ['FULLSTACK BUILD:', 'APP PLAN:', 'WEBSITE BUILD:', 'SAAS BUILD:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_78_fullstack_builder',
      description: 'Create a full-stack build plan for a website, app, or SaaS product.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['FULLSTACK BUILD:', 'APP PLAN:', 'WEBSITE BUILD:', 'SAAS BUILD:']
          },
          payload: {
            type: 'string',
            description: 'Describe the app, website, or SaaS product. Add "| write" to save a build pack.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = stripWriteFlag(payload) || 'Design a premium full-stack product Serena can build.';

      const result = await buildStructuredStudioOutput(context, {
        taskLabel: 'fullstack-builder',
        schema: FULLSTACK_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design the best technical stack, architecture, routes, APIs, data model, risks, and delivery plan for this product.'
      });

      let artifactPath = '';
      if (wantsArtifactWrite(payload)) {
        artifactPath = path.resolve(saveStudioArtifact(result.product_summary, {
          'overview.md': result.product_summary,
          'target-users.md': result.target_users,
          'stack.md': result.recommended_stack.map((item) => `- ${item}`).join('\n'),
          'architecture.md': result.architecture.map((item) => `- ${item}`).join('\n'),
          'modules.md': result.modules.map((item) => `- ${item}`).join('\n'),
          'routes.md': result.frontend_routes.map((item) => `- ${item}`).join('\n'),
          'api-endpoints.md': result.api_endpoints.map((item) => `- ${item}`).join('\n'),
          'data-model.md': result.data_model.map((item) => `- ${item}`).join('\n'),
          'delivery-plan.md': result.delivery_plan.map((item) => `- ${item}`).join('\n'),
          'quality-risks.md': result.quality_risks.map((item) => `- ${item}`).join('\n')
        }));
      }

      logger.info('[FULLSTACK BUILDER] Plan generated');
      const sync = await syncBuildArtifact(context, {
        skillId: '78-fullstack-builder',
        kind: 'fullstack',
        title: result.product_summary || 'fullstack-plan',
        summary: formatBuildPlan(result, artifactPath),
        result,
        metadata: { artifactPath }
      }).catch(() => null);
      return { response: formatBuildPlan(result, artifactPath) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[FULLSTACK BUILDER] Error: ' + error.message);
      return { response: `Fullstack builder failed: ${error.message}` };
    }
  }
};
