const logger = require('../helpers/logger');
const { syncContentArtifact } = require('../helpers/github-content-sync');
const { buildStructuredRevenueOutput } = require('../helpers/revenue-engine');

const PLAN_SCHEMA = {
  type: 'object',
  required: ['summary', 'primary_goal', 'top_priorities', 'quick_wins', 'offers', 'kpis'],
  properties: {
    summary: { type: 'string' },
    primary_goal: { type: 'string' },
    top_priorities: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'why', 'owner', 'timeline'],
        properties: {
          title: { type: 'string' },
          why: { type: 'string' },
          owner: { type: 'string' },
          timeline: { type: 'string' }
        }
      }
    },
    quick_wins: { type: 'array', items: { type: 'string' } },
    offers: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'type', 'next_step'],
        properties: {
          name: { type: 'string' },
          type: { type: 'string' },
          next_step: { type: 'string' }
        }
      }
    },
    kpis: { type: 'array', items: { type: 'string' } }
  }
};

function formatPlan(result) {
  const priorities = result.top_priorities
    .map((item, index) => `${index + 1}. *${item.title}* - ${item.why} (${item.owner}; ${item.timeline})`)
    .join('\n');
  const quickWins = result.quick_wins.map((item) => `- ${item}`).join('\n');
  const offers = result.offers.map((item) => `- *${item.name}* (${item.type}) - ${item.next_step}`).join('\n');
  const kpis = result.kpis.map((item) => `- ${item}`).join('\n');

  return (
    `*Serena Monetization Plan*\n\n` +
    `*Primary Goal*\n${result.primary_goal}\n\n` +
    `*Executive Summary*\n${result.summary}\n\n` +
    `*Top Priorities*\n${priorities}\n\n` +
    `*Quick Wins*\n${quickWins}\n\n` +
    `*Revenue Offers To Push*\n${offers}\n\n` +
    `*KPIs To Track*\n${kpis}`
  );
}

function formatOutputSync(result) {
  return JSON.stringify(result, null, 2);
}

module.exports = {
  id: '69-monetization-orchestrator',
  name: 'Monetization Orchestrator',
  description: 'Builds monetization plans, revenue priorities, and growth actions for drpiet.co.za.',
  triggers: ['MONETIZATION PLAN:', 'REVENUE PLAN:', 'MONETIZATION STATUS', 'REVENUE ACTIONS'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_69_monetization_orchestrator',
      description: 'Create a monetization strategy, revenue action list, or revenue status plan for the practice.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['MONETIZATION PLAN:', 'REVENUE PLAN:', 'MONETIZATION STATUS', 'REVENUE ACTIONS']
          },
          payload: {
            type: 'string',
            description: 'Business goal, current bottleneck, campaign idea, or area to monetise.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request =
        String(payload || '').trim() ||
        'Create the best next-step monetization plan for drpiet.co.za across bookings, memberships, digital products, affiliate revenue, and corporate wellness.';

      const result = await buildStructuredRevenueOutput(context, {
        taskLabel: 'monetization-orchestrator',
        reasoningEffort: 'high',
        schema: PLAN_SCHEMA,
        userPrompt:
          `Task: ${request}\n\n` +
          `Return a practical monetization plan for the business with clear priorities, offers, and KPIs.`
      });

      const sync = await syncContentArtifact(context, {
        skillId: '69-monetization-orchestrator',
        title: result.primary_goal || 'monetization-plan',
        type: 'monetization-plan',
        summary: request,
        content: formatOutputSync(result),
        metadata: { trigger: context.triggerUsed || '' }
      }).catch(() => null);

      logger.info('[MONETIZATION] Plan generated');
      return { response: formatPlan(result) + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[MONETIZATION] Error: ' + error.message);

      try {
        const fallback = await context.aiEngine.chat(
          [{ role: 'user', content: payload || 'Build a monetization plan focused on memberships and corporate wellness for Dr Piet in South Africa.' }],
          {
            systemPrompt:
              `${context.soulFile}\n\n` +
              `You are Serena's monetization strategist.\n` +
              `Return a practical markdown plan with sections:\n` +
              `1) Primary goal\n2) 7-day action plan\n3) Membership offer stack\n4) Corporate wellness offer stack\n5) KPIs and dashboard\n6) Risks and mitigations.\n` +
              `Avoid medical claims. Stay HPCSA/POPIA-safe.`,
            reasoningEffort: 'medium',
            maxTokens: 1400,
            task: 'monetization-fallback'
          }
        );

        const content = String(fallback.content || '').trim();
        if (content) {
          return {
            response:
              `*Serena Monetization Plan (Resilient Mode)*\n\n` +
              `${content}`
          };
        }
      } catch (fallbackError) {
        logger.error('[MONETIZATION] Fallback error: ' + fallbackError.message);
      }

      return {
        response:
          `Monetization plan failed: ${error.message}\n\n` +
          `Try:\n` +
          `MONETIZATION PLAN: memberships + corporate wellness for this week`
      };
    }
  }
};
