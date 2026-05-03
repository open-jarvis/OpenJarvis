
const logger = require('../helpers/logger');
const orchestrator = require('../helpers/vscode-build-orchestrator');
const { syncBuildArtifact } = require('../helpers/github-build-sync');

module.exports = {
  id: '83-vscode-builder',
  name: 'VS Code Builder Hybrid',
  description: 'Hybrid VS Code builder that can scaffold apps, agents, services, AI projects, and cloud-native workspaces using local execution plus MCP context.',
  triggers: [
    'BUILD APP:',
    'BUILD AGENT:',
    'BUILD BACKEND:',
    'BUILD MOBILE APP:',
    'BUILD DESKTOP APP:',
    'BUILD AI APP:',
    'BUILD CLOUD APP:',
    'ANALYZE PROJECT:',
    'PATCH WORKSPACE:',
    'RUN WORKSPACE:',
    'VSCODE BUILDER STATUS',
    'CREATE TEMPLATE:'
  ],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_83_vscode_builder',
      description: 'Scaffold and operate VS Code workspaces for apps, agents, backends, AI projects, and cloud-native services.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: [
              'BUILD APP:',
              'BUILD AGENT:',
              'BUILD BACKEND:',
              'BUILD MOBILE APP:',
              'BUILD DESKTOP APP:',
              'BUILD AI APP:',
              'BUILD CLOUD APP:',
              'ANALYZE PROJECT:',
              'PATCH WORKSPACE:',
              'RUN WORKSPACE:',
              'VSCODE BUILDER STATUS',
              'CREATE TEMPLATE:'
            ]
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },
  async execute(payload, context) {
    try {
      const trigger = String(context.triggerUsed || '').trim().toUpperCase();

      if (trigger === 'VSCODE BUILDER STATUS') {
        return { response: orchestrator.buildStatus(context) };
      }

      if (trigger === 'ANALYZE PROJECT:') {
        return { response: await orchestrator.analyzeWorkspace(payload, context) };
      }

      if (trigger === 'PATCH WORKSPACE:') {
        return { response: await orchestrator.buildPatchPlan(payload, context) };
      }

      if (trigger === 'RUN WORKSPACE:') {
        return { response: await orchestrator.runWorkspace(payload, context) };
      }

      const effectiveTrigger = trigger === 'CREATE TEMPLATE:' ? 'BUILD APP:' : trigger;
      const result = await orchestrator.buildProject(effectiveTrigger, payload, context);
      const rendered = orchestrator.formatBuildResult(result);

      const sync = await syncBuildArtifact(context, {
        skillId: '83-vscode-builder',
        title: (result && (result.projectName || result.title || result.name || 'workspace-build')) || 'workspace-build',
        summary: rendered,
        result
      }).catch(() => null);

      const response = String(rendered || '').trim() || 'VS Code builder completed, but returned no rendered output.';
      return { response: response + (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') };
    } catch (error) {
      logger.error('[VSCODE BUILDER] Error: ' + error.message);
      return { response: `VS Code builder failed: ${error.message}` };
    }
  }
};
