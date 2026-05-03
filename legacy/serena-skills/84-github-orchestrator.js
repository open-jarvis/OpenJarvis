
const logger = require('../helpers/logger');
const { saveArtifactSet, formatSyncStatus } = require('../helpers/github-artifact-manager');

function repoDefaults() {
  return {
    owner: String(process.env.GITHUB_OWNER || '').trim(),
    repo: String(process.env.GITHUB_REPO || '').trim(),
    branch: String(process.env.GITHUB_DEFAULT_BRANCH || 'main').trim()
  };
}

module.exports = {
  id: '84-github-orchestrator',
  name: 'GitHub Platform Orchestrator',
  description: 'Shared GitHub platform layer for saving Serena artifacts, content packs, WordPress source files, and build outputs.',
  triggers: ['GITHUB PLATFORM STATUS', 'GITHUB SAVE ARTIFACT:', 'GITHUB REPO MAP'],

  async execute(payload, context) {
    try {
      const trigger = String(context.triggerUsed || '').trim().toUpperCase();
      const defaults = repoDefaults();

      if (trigger === 'GITHUB PLATFORM STATUS') {
        return {
          response: [
            'GitHub platform status',
            '',
            `Owner: ${defaults.owner || 'not set'}`,
            `Repo: ${defaults.repo || 'not set'}`,
            `Branch: ${defaults.branch || 'main'}`,
            `Token present: ${process.env.GITHUB_TOKEN ? 'yes' : 'no'}`,
            `MCP client present: ${context.mcpClient ? 'yes' : 'no'}`,
            '',
            'This platform layer is used by builder, WordPress, and selected creation skills.'
          ].join('\n')
        };
      }

      if (trigger === 'GITHUB REPO MAP') {
        return {
          response: [
            'GitHub repo map',
            '',
            '/apps',
            '/agents',
            '/wordpress/{site}/posts',
            '/wordpress/{site}/pages',
            '/content/blog',
            '/content/newsletters',
            '/content/ebooks',
            '/content/video-scripts',
            '/content/podcasts',
            '/content/social',
            '/content/email-funnels',
            '/content/canva-briefs',
            '/audits/revenue',
            '/audits/cro',
            '/offers/digital-products',
            '/offers/affiliate',
            '/offers/freelance',
            '/offers/agency',
            '/offers/knowledge-business',
            '/build-packs/fullstack',
            '/build-packs/workspaces',
            '/media/manifests'
          ].join('\n')
        };
      }

      const parts = String(payload || '').split('|').map((p) => p.trim()).filter(Boolean);
      const title = parts[0] || 'Manual Serena artifact';
      const body = parts.slice(1).join('\n\n') || title;

      const sync = await saveArtifactSet(context, {
        skillId: '84-github-orchestrator',
        title,
        basePath: 'artifacts/manual',
        files: [
          {
            path: `artifacts/manual/${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}/content.md`,
            content: body
          }
        ]
      });

      return { response: formatSyncStatus(sync, 'GitHub manual artifact save') };
    } catch (error) {
      logger.error('[GITHUB PLATFORM] Error: ' + error.message);
      return { response: `GitHub platform error: ${error.message}` };
    }
  }
};
