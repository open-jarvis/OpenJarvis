const logger = require('../helpers/logger');
const packageJson = require('../../package.json');
const { buildStructuredStudioOutput } = require('../helpers/software-studio');

const DEPENDENCY_SCHEMA = {
  type: 'object',
  required: ['summary', 'existing_packages', 'recommended_packages', 'approval_notes', 'risk_notes'],
  properties: {
    summary: { type: 'string' },
    existing_packages: { type: 'array', items: { type: 'string' } },
    recommended_packages: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'purpose', 'install_only_if'],
        properties: {
          name: { type: 'string' },
          purpose: { type: 'string' },
          install_only_if: { type: 'string' }
        }
      }
    },
    approval_notes: { type: 'array', items: { type: 'string' } },
    risk_notes: { type: 'array', items: { type: 'string' } }
  }
};

function formatDependencyPlan(result) {
  const existing = result.existing_packages.map((item) => `• ${item}`).join('\n');
  const recommended = result.recommended_packages
    .map((item) => `• *${item.name}* — ${item.purpose}\nInstall only if: ${item.install_only_if}`)
    .join('\n\n');
  const approval = result.approval_notes.map((item) => `• ${item}`).join('\n');
  const risks = result.risk_notes.map((item) => `• ${item}`).join('\n');

  return (
    `📦 *Dependency Manager*\n\n` +
    `*Summary*\n${result.summary}\n\n` +
    `*Existing Stack To Reuse*\n${existing}\n\n` +
    `*Recommended Packages*\n${recommended}\n\n` +
    `*Approval Notes*\n${approval}\n\n` +
    `*Risk Notes*\n${risks}`
  );
}

module.exports = {
  id: '80-dependency-manager',
  name: 'Dependency Manager',
  description: 'Reviews project stack, identifies package gaps, and prepares owner-safe dependency plans.',
  triggers: ['DEPENDENCY PLAN:', 'STACK CHECK:', 'PACKAGE GAP:', 'INSTALL REVIEW:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_80_dependency_manager',
      description: 'Review dependencies for a project and propose what should or should not be installed.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['DEPENDENCY PLAN:', 'STACK CHECK:', 'PACKAGE GAP:', 'INSTALL REVIEW:']
          },
          payload: {
            type: 'string',
            description: 'Describe the project, feature, or stack you want to review.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Review the package needs for a modern production web app.';
      const currentPackages = Object.keys(packageJson.dependencies || {});

      const result = await buildStructuredStudioOutput(context, {
        taskLabel: 'dependency-manager',
        schema: DEPENDENCY_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          `Currently installed dependencies:\n${currentPackages.join(', ')}\n\n` +
          'Recommend only justified packages, prefer the existing stack, and call out what should stay approval-only.'
      });

      logger.info('[DEPENDENCY MANAGER] Dependency plan generated');
      return { response: formatDependencyPlan(result) };
    } catch (error) {
      logger.error('[DEPENDENCY MANAGER] Error: ' + error.message);
      return { response: `❌ Dependency manager failed: ${error.message}` };
    }
  }
};
