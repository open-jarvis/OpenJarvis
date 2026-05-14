const path = require('path');
const logger = require('../helpers/logger');
const {
  buildStructuredStudioOutput,
  saveStudioArtifact,
  wantsArtifactWrite,
  stripWriteFlag
} = require('../helpers/software-studio');

const LAUNCH_SCHEMA = {
  type: 'object',
  required: [
    'launch_summary',
    'quality_gates',
    'env_checklist',
    'deployment_flow',
    'rollback_plan',
    'post_launch_watchlist',
    'owner_signoff'
  ],
  properties: {
    launch_summary: { type: 'string' },
    quality_gates: { type: 'array', items: { type: 'string' } },
    env_checklist: { type: 'array', items: { type: 'string' } },
    deployment_flow: { type: 'array', items: { type: 'string' } },
    rollback_plan: { type: 'array', items: { type: 'string' } },
    post_launch_watchlist: { type: 'array', items: { type: 'string' } },
    owner_signoff: { type: 'array', items: { type: 'string' } }
  }
};

function formatLaunchPlan(result, artifactPath = '') {
  const fmt = (title, items) => `*${title}*\n${items.map((item) => `• ${item}`).join('\n')}`;
  return (
    `App Launch Manager\n\n` +
    `*Launch Summary*\n${result.launch_summary}\n\n` +
    `${fmt('Quality Gates', result.quality_gates)}\n\n` +
    `${fmt('Environment Checklist', result.env_checklist)}\n\n` +
    `${fmt('Deployment Flow', result.deployment_flow)}\n\n` +
    `${fmt('Rollback Plan', result.rollback_plan)}\n\n` +
    `${fmt('Post-Launch Watchlist', result.post_launch_watchlist)}\n\n` +
    `${fmt('Owner Sign-off', result.owner_signoff)}` +
    (artifactPath ? `\n\nArtifact Pack: \`${artifactPath}\`` : '')
  );
}

module.exports = {
  id: '82-app-launch-manager',
  name: 'App Launch Manager',
  description: 'Creates launch readiness plans, deployment checklists, rollback plans, and post-launch monitoring packs.',
  triggers: ['APP LAUNCH:', 'LAUNCH CHECKLIST:', 'DEPLOYMENT PLAN:', 'GO LIVE:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_82_app_launch_manager',
      description: 'Create a launch readiness and deployment plan for an app, website, or product.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['APP LAUNCH:', 'LAUNCH CHECKLIST:', 'DEPLOYMENT PLAN:', 'GO LIVE:']
          },
          payload: {
            type: 'string',
            description: 'Describe the product or release you want to launch. Add "| write" to save a launch pack.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = stripWriteFlag(payload) || 'Create a launch readiness plan for a production app.';

      const result = await buildStructuredStudioOutput(context, {
        taskLabel: 'app-launch-manager',
        schema: LAUNCH_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Create a clean pre-launch, deployment, rollback, and post-launch management plan.'
      });

      let artifactPath = '';
      if (wantsArtifactWrite(payload)) {
        artifactPath = path.resolve(saveStudioArtifact(result.launch_summary, {
          'launch-summary.md': result.launch_summary,
          'quality-gates.md': result.quality_gates.map((item) => `- ${item}`).join('\n'),
          'env-checklist.md': result.env_checklist.map((item) => `- ${item}`).join('\n'),
          'deployment-flow.md': result.deployment_flow.map((item) => `- ${item}`).join('\n'),
          'rollback-plan.md': result.rollback_plan.map((item) => `- ${item}`).join('\n'),
          'post-launch-watchlist.md': result.post_launch_watchlist.map((item) => `- ${item}`).join('\n'),
          'owner-signoff.md': result.owner_signoff.map((item) => `- ${item}`).join('\n')
        }));
      }

      logger.info('[APP LAUNCH MANAGER] Launch plan generated');
      return { response: formatLaunchPlan(result, artifactPath) };
    } catch (error) {
      logger.error('[APP LAUNCH MANAGER] Error: ' + error.message);
      return { response: `App launch manager failed: ${error.message}` };
    }
  }
};
