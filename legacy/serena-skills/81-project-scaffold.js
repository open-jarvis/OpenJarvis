const path = require('path');
const logger = require('../helpers/logger');
const { buildStructuredStudioOutput, saveStudioArtifact } = require('../helpers/software-studio');

const SCAFFOLD_SCHEMA = {
  type: 'object',
  required: ['project_name', 'stack', 'folder_structure', 'key_files', 'build_steps', 'readme'],
  properties: {
    project_name: { type: 'string' },
    stack: { type: 'array', items: { type: 'string' } },
    folder_structure: { type: 'array', items: { type: 'string' } },
    key_files: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'purpose'],
        properties: {
          name: { type: 'string' },
          purpose: { type: 'string' }
        }
      }
    },
    build_steps: { type: 'array', items: { type: 'string' } },
    readme: { type: 'string' }
  }
};

function wantsWrite(payload) {
  return /\|\s*write\s*$/i.test(String(payload || ''));
}

function cleanPayload(payload) {
  return String(payload || '').replace(/\|\s*write\s*$/i, '').trim();
}

function formatScaffold(result, scaffoldPath) {
  const stack = result.stack.map((item) => `• ${item}`).join('\n');
  const folders = result.folder_structure.map((item) => `• ${item}`).join('\n');
  const files = result.key_files.map((item) => `• *${item.name}* — ${item.purpose}`).join('\n');
  const steps = result.build_steps.map((item) => `• ${item}`).join('\n');

  return (
    `🏗️ *Project Scaffold*\n\n` +
    `*Project*\n${result.project_name}\n\n` +
    `*Stack*\n${stack}\n\n` +
    `*Folder Structure*\n${folders}\n\n` +
    `*Key Files*\n${files}\n\n` +
    `*Build Steps*\n${steps}` +
    (scaffoldPath ? `\n\n📁 *Scaffold Pack:* \`${scaffoldPath}\`` : '')
  );
}

module.exports = {
  id: '81-project-scaffold',
  name: 'Project Scaffold',
  description: 'Creates project blueprints and can write scaffold artifact packs for apps and websites.',
  triggers: ['PROJECT SCAFFOLD:', 'SCAFFOLD APP:', 'SCAFFOLD SITE:', 'STACK BLUEPRINT:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_81_project_scaffold',
      description: 'Create a project scaffold plan and optionally write a scaffold artifact pack.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['PROJECT SCAFFOLD:', 'SCAFFOLD APP:', 'SCAFFOLD SITE:', 'STACK BLUEPRINT:']
          },
          payload: {
            type: 'string',
            description: 'Describe the app/site to scaffold. Add "| write" to generate scaffold artifact files under outputs/studio.'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      const request = cleanPayload(payload) || 'Create a premium scaffold for a production website or app.';

      const result = await buildStructuredStudioOutput(context, {
        taskLabel: 'project-scaffold',
        schema: SCAFFOLD_SCHEMA,
        userPrompt:
          `Task trigger: ${context.triggerUsed}\n` +
          `Request: ${request}\n\n` +
          'Design a scaffold with folder structure, key files, and implementation steps.'
      });

      let scaffoldPath = null;
      if (wantsWrite(payload)) {
        scaffoldPath = saveStudioArtifact(result.project_name, {
          'README.md': result.readme,
          'stack.md': result.stack.map((item) => `- ${item}`).join('\n'),
          'folders.md': result.folder_structure.map((item) => `- ${item}`).join('\n'),
          'files.md': result.key_files.map((item) => `- ${item.name}: ${item.purpose}`).join('\n'),
          'build-steps.md': result.build_steps.map((item) => `- ${item}`).join('\n')
        });
      }

      logger.info('[PROJECT SCAFFOLD] Scaffold generated');
      return { response: formatScaffold(result, scaffoldPath ? path.resolve(scaffoldPath) : '') };
    } catch (error) {
      logger.error('[PROJECT SCAFFOLD] Error: ' + error.message);
      return { response: `❌ Project scaffold failed: ${error.message}` };
    }
  }
};
