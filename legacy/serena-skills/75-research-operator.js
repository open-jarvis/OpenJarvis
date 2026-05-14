const logger = require('../helpers/logger');

let operator = null;
function getOperator() {
  if (operator) return operator;
  try {
    const loaded = require('../helpers/research-orchestrator');
    if (
      loaded &&
      typeof loaded.extractPage === 'function' &&
      typeof loaded.researchQuestion === 'function' &&
      typeof loaded.getResearchStatus === 'function'
    ) {
      operator = loaded;
      return operator;
    }
  } catch (error) {
    logger.error('[RESEARCH] Could not load helper research-orchestrator: ' + error.message);
  }
  return null;
}

function cleanText(value) {
  return String(value || '').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim();
}

function formatResearchErrorResponse(error, api) {
  if (api && typeof api.formatOperatorFacingError === 'function') {
    return `Web research error: ${api.formatOperatorFacingError(error)}`;
  }
  return `Web research error: ${String(error?.message || error || 'Unknown research error')}`;
}

module.exports = {
  id: '75-research-operator',
  name: 'Live Research Operator',
  description: 'Search the web, inspect websites, extract content, compare sources, and return grounded research summaries.',
  triggers: [
    'RESEARCH:',
    'RESEARCH PAGE:',
    'RESEARCH COMPARE:',
    'RESEARCH STATUS',
    'SEARCH STATUS',
    'SEARXNG STATUS'
  ],

  async execute(payload, context) {
    try {
      if (!context.mcpClient) {
        return { response: 'Research operator unavailable: MCP client is not active.' };
      }

      const api = getOperator();
      if (!api) {
        return { response: 'Web research error: helper research orchestrator is not available.' };
      }

      if (context.triggerUsed === 'RESEARCH STATUS' || context.triggerUsed === 'SEARCH STATUS' || context.triggerUsed === 'SEARXNG STATUS') {
        const status = await api.getResearchStatus(context);
        return { response: api.formatResearchStatus(status) };
      }

      if (context.triggerUsed === 'RESEARCH PAGE:') {
        const page = await api.extractPage(payload, context);
        return {
          response: [
            'Research page extraction',
            '',
            `URL: ${cleanText(page.url)}`,
            `Title: ${cleanText(page.title || 'unknown')}`,
            '',
            (page.text || '').slice(0, 3200) || 'No readable text extracted.'
          ].join('\n')
        };
      }

      const result = await api.researchQuestion(payload, context);
      return { response: api.formatResearchResult(result) };
    } catch (error) {
      logger.error('[RESEARCH] Error: ' + error.message);
      const api = getOperator();
      return { response: formatResearchErrorResponse(error, api) };
    }
  }
};
