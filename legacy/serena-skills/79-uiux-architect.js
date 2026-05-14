const logger = require('../helpers/logger');
const { buildStructuredStudioOutput } = require('../helpers/software-studio');

const UIUX_SCHEMA = {
  type: 'object',
  required: ['experience_direction', 'user_flow', 'screen_system', 'design_language', 'conversion_elements', 'ui_notes'],
  properties: {
    experience_direction: { type: 'string' },
    user_flow: { type: 'array', items: { type: 'string' } },
    screen_system: { type: 'array', items: { type: 'string' } },
    design_language: { type: 'array', items: { type: 'string' } },
    conversion_elements: { type: 'array', items: { type: 'string' } },
    ui_notes: { type: 'array', items: { type: 'string' } }
  }
};

function formatUiUx(result) {
  const flow = result.user_flow.map((item) => `• ${item}`).join('\n');
  const screens = result.screen_system.map((item) => `• ${item}`).join('\n');
  const language = result.design_language.map((item) => `• ${item}`).join('\n');
  const conversion = result.conversion_elements.map((item) => `• ${item}`).join('\n');
  const notes = result.ui_notes.map((item) => `• ${item}`).join('\n');

  return (
    `🎨 *UI/UX Architect*\n\n` +
    `*Experience Direction*\n${result.experience_direction}\n\n` +
    `*User Flow*\n${flow}\n\n` +
    `*Screen System*\n${screens}\n\n` +
    `*Design Language*\n${language}\n\n` +
    `*Conversion Elements*\n${conversion}\n\n` +
    `*UI Notes*\n${notes}`
  );
}

module.exports = {
  id: '79-uiux-architect',
  name: 'UI/UX Architect',
  description: 'Designs product UX flows, screen systems, visual direction, and conversion-aware interfaces.',
  triggers: ['UIUX ARCHITECT:', 'LANDING PAGE UX:', 'APP UX:', 'DESIGN SYSTEM:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_79_uiux_architect',
      description: 'Create a UI/UX system, user flow, and design direction for a product or landing page.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['UIUX ARCHITECT:', 'LANDING PAGE UX:', 'APP UX:', 'DESIGN SYSTEM:']
          },
          payload: {
            type: 'string',
            description: 'Describe the product, landing page, or app experience to design.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = String(payload || '').trim() || 'Design a premium product experience and interface system.';

      const result = await buildStructuredStudioOutput(context, {
        taskLabel: 'uiux-architect',
        schema: UIUX_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design the user flow, screen system, design language, and conversion elements for this experience.'
      });

      logger.info('[UIUX ARCHITECT] Design system generated');
      return { response: formatUiUx(result) };
    } catch (error) {
      logger.error('[UIUX ARCHITECT] Error: ' + error.message);
      return { response: `❌ UI/UX architect failed: ${error.message}` };
    }
  }
};
